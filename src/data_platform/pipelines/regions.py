"""PA county to tourism-region mapping and region-level aggregates.

Nine regions, adapted from the standard PA tourism regions (visitPA.com) so
they're recognizable to PA-based agents and clients. Every one of the 67
counties in Zillow's PA data must map to exactly one region — completeness
against the full county list is verified in tests.
"""

import pandas as pd

COUNTY_REGION: dict[str, str] = {
    # Philadelphia region
    "Philadelphia County": "Philadelphia",
    "Bucks County": "Philadelphia",
    "Montgomery County": "Philadelphia",
    "Delaware County": "Philadelphia",
    "Chester County": "Philadelphia",
    # Lehigh Valley
    "Lehigh County": "Lehigh Valley",
    "Northampton County": "Lehigh Valley",
    # Poconos
    "Monroe County": "Poconos",
    "Pike County": "Poconos",
    "Wayne County": "Poconos",
    "Carbon County": "Poconos",
    # PA Dutch Country
    "Lancaster County": "PA Dutch Country",
    "Berks County": "PA Dutch Country",
    "Lebanon County": "PA Dutch Country",
    "Schuylkill County": "PA Dutch Country",
    "York County": "PA Dutch Country",
    "Adams County": "PA Dutch Country",
    # Susquehanna
    "Lackawanna County": "Susquehanna",
    "Luzerne County": "Susquehanna",
    "Wyoming County": "Susquehanna",
    "Susquehanna County": "Susquehanna",
    "Bradford County": "Susquehanna",
    "Sullivan County": "Susquehanna",
    "Columbia County": "Susquehanna",
    "Montour County": "Susquehanna",
    "Northumberland County": "Susquehanna",
    "Snyder County": "Susquehanna",
    "Union County": "Susquehanna",
    # Central PA
    "Dauphin County": "Central PA",
    "Cumberland County": "Central PA",
    "Perry County": "Central PA",
    "Franklin County": "Central PA",
    "Fulton County": "Central PA",
    "Centre County": "Central PA",
    "Mifflin County": "Central PA",
    "Juniata County": "Central PA",
    "Huntingdon County": "Central PA",
    # Pittsburgh region
    "Allegheny County": "Pittsburgh",
    "Butler County": "Pittsburgh",
    "Beaver County": "Pittsburgh",
    "Washington County": "Pittsburgh",
    "Armstrong County": "Pittsburgh",
    "Lawrence County": "Pittsburgh",
    # Laurel Highlands
    "Westmoreland County": "Laurel Highlands",
    "Fayette County": "Laurel Highlands",
    "Somerset County": "Laurel Highlands",
    "Greene County": "Laurel Highlands",
    "Indiana County": "Laurel Highlands",
    "Bedford County": "Laurel Highlands",
    "Cambria County": "Laurel Highlands",
    "Blair County": "Laurel Highlands",
    # PA Wilds / Northwest
    "Erie County": "PA Wilds / Northwest",
    "Crawford County": "PA Wilds / Northwest",
    "Mercer County": "PA Wilds / Northwest",
    "Venango County": "PA Wilds / Northwest",
    "Warren County": "PA Wilds / Northwest",
    "Forest County": "PA Wilds / Northwest",
    "Clarion County": "PA Wilds / Northwest",
    "Jefferson County": "PA Wilds / Northwest",
    "Elk County": "PA Wilds / Northwest",
    "McKean County": "PA Wilds / Northwest",
    "Cameron County": "PA Wilds / Northwest",
    "Potter County": "PA Wilds / Northwest",
    "Tioga County": "PA Wilds / Northwest",
    "Clinton County": "PA Wilds / Northwest",
    "Clearfield County": "PA Wilds / Northwest",
    "Lycoming County": "PA Wilds / Northwest",
}

REGIONS: list[str] = sorted(set(COUNTY_REGION.values()))


def add_region(df: pd.DataFrame, county_col: str = "region") -> pd.DataFrame:
    """Add a pa_region column by mapping county_col through COUNTY_REGION."""
    out = df.copy()
    out["pa_region"] = out[county_col].map(COUNTY_REGION)
    return out


def regional_summary(tested_summary: pd.DataFrame) -> pd.DataFrame:
    """One row per region: county count, median value, avg YoY, avg affordability,
    flagged count, and amenities per 10k residents.

    Expects a summary that already carries pa_region (via add_region),
    flag_severity (via forensic.run_forensic_tests), and population/
    total_amenities (via housing.enrich_with_demographics/enrich_with_amenities).
    amenities_per_10k is region-wide total_amenities / total population, not an
    average of each county's own ratio — that would let a tiny county's ratio
    count as much as Philadelphia's.
    """
    grouped = tested_summary.groupby("pa_region")
    out = grouped.agg(
        county_count=("region", "count"),
        median_zhvi=("latest_zhvi", "median"),
        avg_yoy_pct=("yoy_pct", "mean"),
        avg_affordability_ratio=("affordability_ratio", "mean"),
        flagged_count=("flag_severity", lambda s: int((s != "none").sum())),
        total_amenities=("total_amenities", "sum"),
        total_population=("population", "sum"),
    ).reset_index()
    out["median_zhvi"] = out["median_zhvi"].round(0)
    out["avg_yoy_pct"] = out["avg_yoy_pct"].round(1)
    out["avg_affordability_ratio"] = out["avg_affordability_ratio"].round(2)
    out["amenities_per_10k"] = round(out["total_amenities"] / out["total_population"] * 10000, 1)
    out = out.drop(columns=["total_amenities", "total_population"])
    return out.sort_values("pa_region").reset_index(drop=True)


def regional_monthly(monthly_with_region: pd.DataFrame) -> pd.DataFrame:
    """Quarterly mean zhvi per region (mean across the region's counties).

    Expects monthly data that already carries pa_region (via add_region).
    """
    df = monthly_with_region.copy()
    df["date"] = pd.to_datetime(df["date"])
    df["quarter"] = df["date"].dt.to_period("Q").dt.to_timestamp()
    out = df.groupby(["pa_region", "quarter"], as_index=False)["zhvi"].mean()
    out["zhvi"] = out["zhvi"].round()
    return out.sort_values(["pa_region", "quarter"]).reset_index(drop=True)
