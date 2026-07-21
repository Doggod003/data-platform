"""Tests for the housing pipeline — pure transforms only, no network calls."""

import pandas as pd

from data_platform.pipelines.housing import (
    aggregate_amenities,
    aggregate_schools,
    enrich_with_amenities,
    enrich_with_demographics,
    enrich_with_schools,
    filter_state,
    summarize,
    to_long,
)


def sample_wide() -> pd.DataFrame:
    """Fake Zillow-shaped wide frame: 2 PA counties + 1 NY county, 3 dates."""
    return pd.DataFrame(
        {
            "RegionID": [1, 2, 3],
            "RegionName": ["Dauphin County", "Cumberland County", "Erie County"],
            "StateName": ["PA", "PA", "NY"],
            "2020-06-30": [200000.0, 250000.0, 180000.0],
            "2025-06-30": [280000.0, 340000.0, 220000.0],
            "2026-06-30": [300000.0, 350000.0, 230000.0],
        }
    )


def test_filter_state_keeps_only_pa():
    result = filter_state(sample_wide(), "PA")
    assert set(result["RegionName"]) == {"Dauphin County", "Cumberland County"}


def test_to_long_shapes_correctly():
    long_df = to_long(filter_state(sample_wide(), "PA"))
    assert list(long_df.columns) == ["RegionID", "region", "state", "date", "zhvi"]
    # 2 counties x 3 dates
    assert len(long_df) == 6
    assert long_df["date"].dtype.kind == "M"  # datetime


def test_summarize_computes_yoy_and_growth():
    summary = summarize(to_long(filter_state(sample_wide(), "PA")))
    dauphin = summary[summary["region"] == "Dauphin County"].iloc[0]
    # latest 300k vs 280k one year prior = +7.1%
    assert dauphin["yoy_pct"] == 7.1
    # latest 300k vs 200k ~6 years prior (nearest <= 5y back) = +50.0%
    assert dauphin["growth_5yr_pct"] == 50.0
    assert dauphin["latest_zhvi"] == 300000


def test_summarize_ranks_by_yoy():
    summary = summarize(to_long(filter_state(sample_wide(), "PA")))
    assert summary.iloc[0]["yoy_rank"] == 1
    assert summary.iloc[0]["yoy_pct"] >= summary.iloc[-1]["yoy_pct"]


def sample_demographics() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "county": "Dauphin County",
                "population": 270000,
                "median_income": 60000,
                "median_age": 38.5,
                "owner_occupancy_pct": 63.6,
            },
            {
                "county": "Cumberland County",
                "population": 260000,
                "median_income": 70000,
                "median_age": 40.1,
                "owner_occupancy_pct": 75.0,
            },
        ]
    )


def test_enrich_with_demographics_joins_by_county():
    summary = summarize(to_long(filter_state(sample_wide(), "PA")))
    enriched = enrich_with_demographics(summary, sample_demographics())
    assert "median_income" in enriched.columns
    assert "county" not in enriched.columns
    dauphin = enriched[enriched["region"] == "Dauphin County"].iloc[0]
    assert dauphin["population"] == 270000


def test_enrich_with_demographics_computes_affordability_ratio():
    summary = summarize(to_long(filter_state(sample_wide(), "PA")))
    enriched = enrich_with_demographics(summary, sample_demographics())
    dauphin = enriched[enriched["region"] == "Dauphin County"].iloc[0]
    # latest_zhvi 300000 / median_income 60000 = 5.0
    assert dauphin["affordability_ratio"] == 5.0


def sample_districts() -> pd.DataFrame:
    return pd.DataFrame(
        [
            # Dauphin: 1 regular district + 1 CTC (agency_type=9, not a "district")
            {
                "district": "Central Dauphin School District",
                "county": "Dauphin County",
                "agency_type": 1,
                "number_of_schools": 12,
                "enrollment": 10500,
            },
            {
                "district": "Dauphin County Technical School",
                "county": "Dauphin County",
                "agency_type": 9,
                "number_of_schools": 1,
                "enrollment": 450,
            },
            # Cumberland: 1 regular district, no private schools
            {
                "district": "Cumberland Valley School District",
                "county": "Cumberland County",
                "agency_type": 1,
                "number_of_schools": 8,
                "enrollment": 7200,
            },
        ]
    )


def sample_private_schools() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"school": "St Joseph School", "county": "Dauphin County", "enrollment": 210},
            {"school": "Trinity Academy", "county": "Dauphin County", "enrollment": 150},
        ]
    )


def test_aggregate_schools_counts_only_regular_districts():
    result = aggregate_schools(sample_districts(), sample_private_schools())
    dauphin = result[result["county"] == "Dauphin County"].iloc[0]
    # 2 LEAs in Dauphin, but only the regular district (agency_type=1) counts
    assert dauphin["district_count"] == 1


def test_aggregate_schools_sums_enrollment_across_all_agency_types():
    result = aggregate_schools(sample_districts(), sample_private_schools())
    dauphin = result[result["county"] == "Dauphin County"].iloc[0]
    # 10500 (regular district) + 450 (CTC) -- CTC students still live in the county
    assert dauphin["total_enrollment"] == 10950


def test_aggregate_schools_counts_private_schools():
    result = aggregate_schools(sample_districts(), sample_private_schools())
    dauphin = result[result["county"] == "Dauphin County"].iloc[0]
    assert dauphin["private_school_count"] == 2


def test_aggregate_schools_zero_fills_county_with_no_private_schools():
    result = aggregate_schools(sample_districts(), sample_private_schools())
    cumberland = result[result["county"] == "Cumberland County"].iloc[0]
    assert cumberland["private_school_count"] == 0
    assert cumberland["district_count"] == 1
    assert cumberland["total_enrollment"] == 7200


def test_enrich_with_schools_joins_by_county():
    summary = summarize(to_long(filter_state(sample_wide(), "PA")))
    aggregates = aggregate_schools(sample_districts(), sample_private_schools())
    enriched = enrich_with_schools(summary, aggregates)
    assert "county" not in enriched.columns
    dauphin = enriched[enriched["region"] == "Dauphin County"].iloc[0]
    assert dauphin["district_count"] == 1
    assert dauphin["private_school_count"] == 2


def sample_amenities() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "county": "Dauphin County",
                "category": "park",
                "sport": None,
                "name": "Riverfront Park",
            },
            {
                "county": "Dauphin County",
                "category": "park",
                "sport": None,
                "name": "Wildwood Park",
            },
            {
                "county": "Dauphin County",
                "category": "golf_course",
                "sport": None,
                "name": "Colonial",
            },
            {
                "county": "Dauphin County",
                "category": "pitch",
                "sport": "baseball",
                "name": "Field 1",
            },
            {"county": "Dauphin County", "category": "pitch", "sport": "soccer", "name": None},
            {"county": "Dauphin County", "category": "playground", "sport": None, "name": None},
            {"county": "Cumberland County", "category": "park", "sport": None, "name": "Only Park"},
        ]
    )


def test_aggregate_amenities_counts_by_category():
    result = aggregate_amenities(sample_amenities())
    dauphin = result[result["county"] == "Dauphin County"].iloc[0]
    assert dauphin["park_count"] == 2
    assert dauphin["golf_course_count"] == 1
    assert dauphin["pitch_count"] == 2
    assert dauphin["playground_count"] == 1


def test_aggregate_amenities_counts_pitches_by_sport():
    result = aggregate_amenities(sample_amenities())
    dauphin = result[result["county"] == "Dauphin County"].iloc[0]
    assert dauphin["pitch_baseball_count"] == 1
    assert dauphin["pitch_soccer_count"] == 1
    assert dauphin["pitch_rugby_count"] == 0
    assert dauphin["pitch_basketball_count"] == 0
    assert dauphin["pitch_tennis_count"] == 0


def test_aggregate_amenities_computes_total():
    result = aggregate_amenities(sample_amenities())
    dauphin = result[result["county"] == "Dauphin County"].iloc[0]
    assert dauphin["total_amenities"] == 6


def test_aggregate_amenities_zero_fills_county_with_few_amenities():
    result = aggregate_amenities(sample_amenities())
    cumberland = result[result["county"] == "Cumberland County"].iloc[0]
    assert cumberland["park_count"] == 1
    assert cumberland["pitch_baseball_count"] == 0
    assert cumberland["total_amenities"] == 1


def test_enrich_with_amenities_joins_by_county():
    summary = summarize(to_long(filter_state(sample_wide(), "PA")))
    aggregates = aggregate_amenities(sample_amenities())
    enriched = enrich_with_amenities(summary, aggregates)
    assert "county" not in enriched.columns
    dauphin = enriched[enriched["region"] == "Dauphin County"].iloc[0]
    assert dauphin["total_amenities"] == 6
