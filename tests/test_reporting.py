"""Tests for reporting: forensic tests + dashboard rendering."""

from datetime import date

import pandas as pd

from data_platform.reporting.dashboard import build_dashboard, slugify
from data_platform.reporting.forensic import run_forensic_tests
from data_platform.reporting.powerbi_export import (
    add_momentum,
    build_monthly_quarterly,
    build_summary_enriched,
    write_powerbi_exports,
)


def sample_summary() -> pd.DataFrame:
    return pd.DataFrame(
        [
            # trend reversal: negative 5yr, strong positive YoY
            {
                "region": "Forest County",
                "latest_date": date(2026, 6, 30),
                "latest_zhvi": 138625,
                "yoy_pct": 11.8,
                "growth_5yr_pct": -0.5,
                "yoy_rank": 2,
                "population": 7181,
                "median_income": 48000,
                "median_age": 51.2,
                "owner_occupancy_pct": 79.5,
                "affordability_ratio": 2.89,
                "district_count": 1,
                "total_enrollment": 1200,
                "private_school_count": 1,
                "park_count": 3,
                "golf_course_count": 0,
                "pitch_count": 1,
                "playground_count": 2,
                "pitch_baseball_count": 1,
                "pitch_soccer_count": 0,
                "pitch_rugby_count": 0,
                "pitch_basketball_count": 0,
                "pitch_tennis_count": 0,
                "total_amenities": 6,
            },
            # clean, unremarkable county
            {
                "region": "Erie County",
                "latest_date": date(2026, 6, 30),
                "latest_zhvi": 228459,
                "yoy_pct": 6.0,
                "growth_5yr_pct": 40.2,
                "yoy_rank": 10,
                "population": 270876,
                "median_income": 61000,
                "median_age": 40.6,
                "owner_occupancy_pct": 66.8,
                "affordability_ratio": 3.75,
                "district_count": 3,
                "total_enrollment": 15000,
                "private_school_count": 8,
                "park_count": 10,
                "golf_course_count": 2,
                "pitch_count": 5,
                "playground_count": 4,
                "pitch_baseball_count": 2,
                "pitch_soccer_count": 2,
                "pitch_rugby_count": 0,
                "pitch_basketball_count": 0,
                "pitch_tennis_count": 1,
                "total_amenities": 21,
            },
            # small base + double-digit YoY
            {
                "region": "Elk County",
                "latest_date": date(2026, 6, 30),
                "latest_zhvi": 50000,
                "yoy_pct": 12.0,
                "growth_5yr_pct": 15.0,
                "yoy_rank": 1,
                "population": 29365,
                "median_income": 52000,
                "median_age": 45.9,
                "owner_occupancy_pct": 74.3,
                "affordability_ratio": 0.96,
                "district_count": 1,
                "total_enrollment": 1800,
                "private_school_count": 0,
                "park_count": 1,
                "golf_course_count": 0,
                "pitch_count": 0,
                "playground_count": 1,
                "pitch_baseball_count": 0,
                "pitch_soccer_count": 0,
                "pitch_rugby_count": 0,
                "pitch_basketball_count": 0,
                "pitch_tennis_count": 0,
                "total_amenities": 2,
            },
        ]
    )


def sample_monthly() -> pd.DataFrame:
    dates = pd.date_range("2016-01-31", "2026-06-30", freq="ME")
    rows = []
    for region, start in [
        ("Forest County", 138000),
        ("Erie County", 160000),
        ("Elk County", 44000),
    ]:
        for i, d in enumerate(dates):
            rows.append({"region": region, "date": d, "zhvi": start + i * 50})
    return pd.DataFrame(rows)


def sample_amenities() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"county": "Forest County", "category": "park", "sport": None, "name": "Forest Park"},
            {
                "county": "Forest County",
                "category": "pitch",
                "sport": "baseball",
                "name": "Forest Diamond",
            },
            {
                "county": "Erie County",
                "category": "golf_course",
                "sport": None,
                "name": "Erie Golf Club",
            },
        ]
    )


def test_trend_reversal_flagged_red():
    result = run_forensic_tests(sample_summary())
    forest = result[result["region"] == "Forest County"].iloc[0]
    assert forest["flag_severity"] == "red"
    assert forest["flag_test"] == "Trend reversal"


def test_clean_county_not_flagged():
    result = run_forensic_tests(sample_summary())
    erie = result[result["region"] == "Erie County"].iloc[0]
    assert erie["flag_severity"] == "none"


def test_small_base_flagged_amber():
    result = run_forensic_tests(sample_summary())
    elk = result[result["region"] == "Elk County"].iloc[0]
    assert elk["flag_severity"] == "amber"
    assert elk["flag_test"] == "Small-base distortion"


def test_implied_prior_growth_computed():
    result = run_forensic_tests(sample_summary())
    assert "implied_prior4yr" in result.columns
    assert result["implied_prior4yr"].notna().all()


def test_build_dashboard_writes_html(tmp_path):
    out = build_dashboard(
        sample_summary(), sample_monthly(), sample_amenities(), tmp_path / "dash.html"
    )
    assert out.exists()
    content = out.read_text(encoding="utf-8")
    assert "PA Housing Market Tracker" in content
    assert "Forest County" in content
    assert "<script" in content
    assert "pa_housing_summary.csv" in content
    assert "pa_housing_monthly.csv" in content
    assert 'class="county-link"' in content
    assert 'id="top-mover-chip"' in content
    assert 'id="trend-card"' in content


def test_build_dashboard_has_three_views_and_router(tmp_path):
    out = build_dashboard(
        sample_summary(), sample_monthly(), sample_amenities(), tmp_path / "dash.html"
    )
    content = out.read_text(encoding="utf-8")
    assert 'id="view-overview"' in content
    assert 'id="view-regions"' in content
    assert 'id="view-county"' in content
    assert 'data-route="overview"' in content
    assert 'data-route="regions"' in content
    assert 'data-route="county"' in content
    assert "hashchange" in content
    assert "function route()" in content


def test_build_dashboard_renders_a_county_section(tmp_path):
    out = build_dashboard(
        sample_summary(), sample_monthly(), sample_amenities(), tmp_path / "dash.html"
    )
    content = out.read_text(encoding="utf-8")
    # Forest County's slug must be embedded so #county/forest-county is reachable
    assert "forest-county" in content
    assert "avg_yoy_pct" in content  # proves the REGIONAL blob is embedded too


def test_build_dashboard_has_living_here_section(tmp_path):
    out = build_dashboard(
        sample_summary(), sample_monthly(), sample_amenities(), tmp_path / "dash.html"
    )
    content = out.read_text(encoding="utf-8")
    assert "Living Here" in content
    assert 'class="amenity-group"' in content
    assert "amenities_per_10k" in content  # Regions view card stat


def test_build_dashboard_embeds_amenity_names(tmp_path):
    out = build_dashboard(
        sample_summary(), sample_monthly(), sample_amenities(), tmp_path / "dash.html"
    )
    content = out.read_text(encoding="utf-8")
    # the raw amenity names must be embedded so the expandable list can show them
    assert "Forest Park" in content
    assert "Forest Diamond" in content


def test_slugify_lowercases_and_hyphenates_spaces():
    assert slugify("Forest County") == "forest-county"


def test_slugify_handles_mixed_case_and_symbols():
    assert slugify("PA Wilds / Northwest") == "pa-wilds-northwest"


def test_slugify_collapses_repeated_separators():
    assert slugify("  Multiple   Spaces  ") == "multiple-spaces"


def test_momentum_labels_cooling_steady_hot():
    df = pd.DataFrame({"yoy_pct": [-2.0, 0.0, 4.9, 5.0]})
    result = add_momentum(df)
    assert list(result["momentum"]) == ["Cooling", "Steady", "Steady", "Hot"]


def test_summary_enriched_has_momentum_and_forensic_columns():
    result = build_summary_enriched(sample_summary())
    forest = result[result["region"] == "Forest County"].iloc[0]
    assert forest["momentum"] == "Hot"
    assert forest["flag_severity"] == "red"
    assert "implied_prior4yr" in result.columns


def test_monthly_quarterly_aggregates_per_region():
    result = build_monthly_quarterly(sample_monthly())
    assert list(result.columns) == ["region", "quarter", "zhvi"]
    assert len(result) < len(sample_monthly())
    forest_q1_2016 = result[
        (result["region"] == "Forest County") & (result["quarter"] == pd.Timestamp("2016-01-01"))
    ].iloc[0]
    assert forest_q1_2016["zhvi"] == 138050  # mean of Jan/Feb/Mar zhvi (138000, 138050, 138100)


def test_write_powerbi_exports_writes_csvs(tmp_path):
    enriched_path, quarterly_path = write_powerbi_exports(
        sample_summary(), sample_monthly(), tmp_path / "powerbi"
    )
    assert enriched_path.exists()
    assert quarterly_path.exists()

    enriched = pd.read_csv(enriched_path)
    assert "momentum" in enriched.columns
    assert "flag_severity" in enriched.columns

    quarterly = pd.read_csv(quarterly_path)
    assert "Forest County" in quarterly["region"].values
