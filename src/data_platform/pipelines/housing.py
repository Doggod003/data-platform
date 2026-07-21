"""PA Housing Market pipeline.

Extract:   Zillow ZHVI county-level home values (public CSV) + Census ACS
           county demographics + PA school districts/private schools
           (all cached, re-fetched every 90 days)
Transform: filter to Pennsylvania, reshape to tidy long format, compute
           latest value, year-over-year change, and 5-year growth per county;
           join demographics and derive affordability_ratio; join per-county
           school aggregates; tag each county with its PA tourism region
Load:      write Power BI-ready CSVs to reports/

Run with:  python -m data_platform.pipelines.housing
"""

import logging
from pathlib import Path

import pandas as pd

from data_platform.integrations.census import get_demographics
from data_platform.integrations.pa_schools import (
    REGULAR_DISTRICT_AGENCY_TYPE,
    get_private_schools,
    get_school_districts,
)
from data_platform.integrations.zillow import fetch_zhvi
from data_platform.pipelines.regions import add_region
from data_platform.reporting.charts import write_charts
from data_platform.reporting.dashboard import build_dashboard
from data_platform.reporting.powerbi_export import write_powerbi_exports

logger = logging.getLogger(__name__)

REPORTS_DIR = Path("reports")

# Zillow wide files have metadata columns first, then one column per month.
ID_COLS = ["RegionID", "RegionName", "StateName"]


def filter_state(raw: pd.DataFrame, state: str = "PA") -> pd.DataFrame:
    """Keep only rows for the given state."""
    return raw[raw["StateName"] == state].copy()


def to_long(wide: pd.DataFrame) -> pd.DataFrame:
    """Reshape wide (one column per month) to tidy long format.

    Output columns: region, state, date, zhvi
    """
    date_cols = [c for c in wide.columns if c[:2] in {"19", "20"}]
    long_df = wide.melt(
        id_vars=[c for c in ID_COLS if c in wide.columns],
        value_vars=date_cols,
        var_name="date",
        value_name="zhvi",
    )
    long_df["date"] = pd.to_datetime(long_df["date"])
    long_df = long_df.rename(columns={"RegionName": "region", "StateName": "state"})
    return long_df.dropna(subset=["zhvi"]).sort_values(["region", "date"])


def summarize(long_df: pd.DataFrame) -> pd.DataFrame:
    """One row per region: latest value, YoY change, 5-year growth, rank."""
    rows = []
    for region, grp in long_df.groupby("region"):
        grp = grp.sort_values("date")
        latest = grp.iloc[-1]
        latest_date = latest["date"]

        def value_near(years_back: int, g=grp, ref=latest_date):
            target = ref - pd.DateOffset(years=years_back)
            candidates = g[g["date"] <= target]
            return candidates.iloc[-1]["zhvi"] if len(candidates) else None

        yr1, yr5 = value_near(1), value_near(5)
        rows.append(
            {
                "region": region,
                "latest_date": latest_date.date(),
                "latest_zhvi": round(latest["zhvi"]),
                "yoy_pct": round((latest["zhvi"] / yr1 - 1) * 100, 1) if yr1 else None,
                "growth_5yr_pct": round((latest["zhvi"] / yr5 - 1) * 100, 1) if yr5 else None,
            }
        )
    summary = pd.DataFrame(rows).sort_values("yoy_pct", ascending=False)
    summary["yoy_rank"] = range(1, len(summary) + 1)
    return summary


def enrich_with_demographics(summary: pd.DataFrame, demographics: pd.DataFrame) -> pd.DataFrame:
    """Left-join Census demographics onto the summary; add affordability_ratio."""
    merged = summary.merge(demographics, left_on="region", right_on="county", how="left").drop(
        columns="county"
    )
    merged["affordability_ratio"] = round(merged["latest_zhvi"] / merged["median_income"], 2)
    return merged


def aggregate_schools(districts: pd.DataFrame, private: pd.DataFrame) -> pd.DataFrame:
    """One row per county: district_count (regular districts only), total_enrollment
    (all public LEAs — charter/CTC students are still county residents), and
    private_school_count.
    """
    regular = districts[districts["agency_type"] == REGULAR_DISTRICT_AGENCY_TYPE]
    district_count = regular.groupby("county").size().rename("district_count")
    total_enrollment = districts.groupby("county")["enrollment"].sum(min_count=1)
    total_enrollment = total_enrollment.rename("total_enrollment")
    private_school_count = private.groupby("county").size().rename("private_school_count")

    combined = pd.concat([district_count, total_enrollment, private_school_count], axis=1)
    combined = combined.fillna(0).reset_index().rename(columns={"index": "county"})
    for col in ["district_count", "total_enrollment", "private_school_count"]:
        combined[col] = combined[col].astype(int)
    return combined


def enrich_with_schools(summary: pd.DataFrame, school_aggregates: pd.DataFrame) -> pd.DataFrame:
    """Left-join per-county school aggregates onto the summary."""
    return summary.merge(school_aggregates, left_on="region", right_on="county", how="left").drop(
        columns="county"
    )


def load(long_df: pd.DataFrame, summary: pd.DataFrame, districts: pd.DataFrame) -> None:
    REPORTS_DIR.mkdir(exist_ok=True)
    long_path = REPORTS_DIR / "pa_housing_monthly.csv"
    summary_path = REPORTS_DIR / "pa_housing_summary.csv"
    schools_path = REPORTS_DIR / "pa_schools.csv"
    long_df.to_csv(long_path, index=False)
    summary.to_csv(summary_path, index=False)
    districts.to_csv(schools_path, index=False)
    logger.info(
        "Wrote %s (%d rows) and %s (%d rows)", long_path, len(long_df), summary_path, len(summary)
    )
    logger.info("Wrote %s (%d rows)", schools_path, len(districts))
    dashboard_path = build_dashboard(summary, long_df, REPORTS_DIR / "pa_housing_dashboard.html")
    logger.info("Wrote %s", dashboard_path)
    write_powerbi_exports(summary, long_df, REPORTS_DIR / "powerbi")
    write_charts(summary, long_df, REPORTS_DIR / "charts")


def run(state: str = "PA") -> pd.DataFrame:
    raw = fetch_zhvi("county")
    long_df = to_long(filter_state(raw, state))
    summary = summarize(long_df)
    summary = enrich_with_demographics(summary, get_demographics())

    districts = get_school_districts()
    private = get_private_schools()
    summary = enrich_with_schools(summary, aggregate_schools(districts, private))

    summary = add_region(summary)
    long_df = add_region(long_df)
    districts = add_region(districts, county_col="county")
    load(long_df, summary, districts)
    return summary


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    )
    result = run()
    print(result.head(15).to_string(index=False))
