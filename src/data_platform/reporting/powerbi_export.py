"""Power BI-optimized exports for the PA Housing Market Tracker.

Power BI reads reports/powerbi/*.csv directly via Get Data > CSV. Forensic
flags and quarterly aggregation are computed once here in Python so Power
Query doesn't need to reimplement that logic — this stays the single source
of truth.
"""

import logging
from pathlib import Path

import pandas as pd

from data_platform.reporting.forensic import run_forensic_tests

logger = logging.getLogger(__name__)

HOT_YOY = 5.0  # >= this YoY% is "Hot"; [0, HOT_YOY) is "Steady"; < 0 is "Cooling"


def add_momentum(summary: pd.DataFrame) -> pd.DataFrame:
    """Add a Momentum column: Hot (>=5% YoY), Steady (0-5%), Cooling (<0%)."""
    df = summary.copy()
    bins = [-float("inf"), 0, HOT_YOY, float("inf")]
    labels = ["Cooling", "Steady", "Hot"]
    df["momentum"] = pd.cut(df["yoy_pct"], bins=bins, labels=labels, right=False).astype(str)
    return df


def build_summary_enriched(summary: pd.DataFrame) -> pd.DataFrame:
    """Summary + forensic flag columns + momentum, ready for Power BI."""
    return add_momentum(run_forensic_tests(summary))


def build_monthly_quarterly(monthly: pd.DataFrame) -> pd.DataFrame:
    """Monthly zhvi pre-aggregated to quarterly means per region (flat, tabular)."""
    df = monthly.copy()
    df["date"] = pd.to_datetime(df["date"])
    df["quarter"] = df["date"].dt.to_period("Q").dt.to_timestamp()
    quarterly = (
        df.groupby(["region", "quarter"], as_index=False)["zhvi"]
        .mean()
        .sort_values(["region", "quarter"])
    )
    quarterly["zhvi"] = quarterly["zhvi"].round()
    return quarterly


def write_powerbi_exports(
    summary: pd.DataFrame,
    monthly: pd.DataFrame,
    out_dir: Path = Path("reports/powerbi"),
) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    enriched_path = out_dir / "summary_enriched.csv"
    quarterly_path = out_dir / "monthly_quarterly.csv"
    build_summary_enriched(summary).to_csv(enriched_path, index=False)
    build_monthly_quarterly(monthly).to_csv(quarterly_path, index=False)
    logger.info("Wrote %s and %s", enriched_path, quarterly_path)
    return enriched_path, quarterly_path
