"""Tests for the PA county->region mapping and region-level aggregates."""

import pandas as pd

from data_platform.pipelines.regions import (
    COUNTY_REGION,
    REGIONS,
    add_region,
    regional_monthly,
    regional_summary,
)

# The 67 counties Zillow's PA ZHVI data actually contains (RegionName values),
# captured from the live dataset — guards against typos/omissions in the mapping.
ZILLOW_PA_COUNTIES = {
    "Adams County",
    "Allegheny County",
    "Armstrong County",
    "Beaver County",
    "Bedford County",
    "Berks County",
    "Blair County",
    "Bradford County",
    "Bucks County",
    "Butler County",
    "Cambria County",
    "Cameron County",
    "Carbon County",
    "Centre County",
    "Chester County",
    "Clarion County",
    "Clearfield County",
    "Clinton County",
    "Columbia County",
    "Crawford County",
    "Cumberland County",
    "Dauphin County",
    "Delaware County",
    "Elk County",
    "Erie County",
    "Fayette County",
    "Forest County",
    "Franklin County",
    "Fulton County",
    "Greene County",
    "Huntingdon County",
    "Indiana County",
    "Jefferson County",
    "Juniata County",
    "Lackawanna County",
    "Lancaster County",
    "Lawrence County",
    "Lebanon County",
    "Lehigh County",
    "Luzerne County",
    "Lycoming County",
    "McKean County",
    "Mercer County",
    "Mifflin County",
    "Monroe County",
    "Montgomery County",
    "Montour County",
    "Northampton County",
    "Northumberland County",
    "Perry County",
    "Philadelphia County",
    "Pike County",
    "Potter County",
    "Schuylkill County",
    "Snyder County",
    "Somerset County",
    "Sullivan County",
    "Susquehanna County",
    "Tioga County",
    "Union County",
    "Venango County",
    "Warren County",
    "Washington County",
    "Wayne County",
    "Westmoreland County",
    "Wyoming County",
    "York County",
}


def test_county_region_covers_every_pa_county_exactly_once():
    assert set(COUNTY_REGION.keys()) == ZILLOW_PA_COUNTIES
    assert len(COUNTY_REGION) == len(ZILLOW_PA_COUNTIES) == 67


def test_regions_has_nine_named_regions():
    assert len(REGIONS) == 9
    assert REGIONS == sorted(REGIONS)


def test_add_region_maps_known_counties():
    df = pd.DataFrame({"region": ["Philadelphia County", "Allegheny County", "Erie County"]})
    result = add_region(df)
    assert list(result["pa_region"]) == ["Philadelphia", "Pittsburgh", "PA Wilds / Northwest"]


def test_add_region_respects_custom_county_col():
    df = pd.DataFrame({"county": ["Lehigh County"]})
    result = add_region(df, county_col="county")
    assert result["pa_region"].iloc[0] == "Lehigh Valley"


def sample_tested_summary() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "region": "Philadelphia County",
                "pa_region": "Philadelphia",
                "latest_zhvi": 250000,
                "yoy_pct": 8.0,
                "affordability_ratio": 4.0,
                "flag_severity": "red",
            },
            {
                "region": "Bucks County",
                "pa_region": "Philadelphia",
                "latest_zhvi": 350000,
                "yoy_pct": 4.0,
                "affordability_ratio": 3.0,
                "flag_severity": "none",
            },
            {
                "region": "Erie County",
                "pa_region": "PA Wilds / Northwest",
                "latest_zhvi": 150000,
                "yoy_pct": 2.0,
                "affordability_ratio": 2.5,
                "flag_severity": "none",
            },
        ]
    )


def test_regional_summary_aggregates_per_region():
    result = regional_summary(sample_tested_summary())
    philly = result[result["pa_region"] == "Philadelphia"].iloc[0]
    assert philly["county_count"] == 2
    assert philly["median_zhvi"] == 300000  # median(250000, 350000)
    assert philly["avg_yoy_pct"] == 6.0  # mean(8.0, 4.0)
    assert philly["avg_affordability_ratio"] == 3.5  # mean(4.0, 3.0)
    assert philly["flagged_count"] == 1


def test_regional_summary_flagged_count_zero_when_clean():
    result = regional_summary(sample_tested_summary())
    wilds = result[result["pa_region"] == "PA Wilds / Northwest"].iloc[0]
    assert wilds["flagged_count"] == 0


def sample_monthly_with_region() -> pd.DataFrame:
    dates = pd.date_range("2024-01-31", "2024-06-30", freq="ME")
    rows = []
    for region, pa_region, start in [
        ("Philadelphia County", "Philadelphia", 250000),
        ("Bucks County", "Philadelphia", 350000),
        ("Erie County", "PA Wilds / Northwest", 150000),
    ]:
        for i, d in enumerate(dates):
            rows.append(
                {"region": region, "pa_region": pa_region, "date": d, "zhvi": start + i * 100}
            )
    return pd.DataFrame(rows)


def test_regional_monthly_averages_across_counties_in_region():
    result = regional_monthly(sample_monthly_with_region())
    philly_q1 = result[
        (result["pa_region"] == "Philadelphia") & (result["quarter"] == pd.Timestamp("2024-01-01"))
    ].iloc[0]
    # Jan/Feb/Mar mean of Philadelphia (250000..) and Bucks (350000..) at i=0,1,2
    expected = ((250000 + 350000) + (250100 + 350100) + (250200 + 350200)) / 6
    assert philly_q1["zhvi"] == round(expected)


def test_regional_monthly_has_no_county_column():
    result = regional_monthly(sample_monthly_with_region())
    assert list(result.columns) == ["pa_region", "quarter", "zhvi"]
