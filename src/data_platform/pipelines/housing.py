"""PA Housing Market pipeline.

Extract:   Zillow ZHVI county-level home values (public CSV)
Transform: filter to Pennsylvania, reshape to tidy long format, compute
           latest value, year-over-year change, and 5-year growth per county
Load:      write Power BI-ready CSVs to reports/

Run with:  python -m data_platform.pipelines.housing
"""

import logging
from pathlib import Path

import pandas as pd

from data_platform.integrations.zillow import fetch_zhvi
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


def load(long_df: pd.DataFrame, summary: pd.DataFrame) -> None:
    REPORTS_DIR.mkdir(exist_ok=True)
    long_path = REPORTS_DIR / "pa_housing_monthly.csv"
    summary_path = REPORTS_DIR / "pa_housing_summary.csv"
    long_df.to_csv(long_path, index=False)
    summary.to_csv(summary_path, index=False)
    logger.info(
        "Wrote %s (%d rows) and %s (%d rows)", long_path, len(long_df), summary_path, len(summary)
    )
    dashboard_path = build_dashboard(summary, long_df, REPORTS_DIR / "pa_housing_dashboard.html")
    logger.info("Wrote %s", dashboard_path)
    write_powerbi_exports(summary, long_df, REPORTS_DIR / "powerbi")
    write_charts(summary, long_df, REPORTS_DIR / "charts")


def run(state: str = "PA") -> pd.DataFrame:
    raw = fetch_zhvi("county")
    long_df = to_long(filter_state(raw, state))
    summary = summarize(long_df)
    load(long_df, summary)
    return summary


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    )
    result = run()
    print(result.head(15).to_string(index=False))
