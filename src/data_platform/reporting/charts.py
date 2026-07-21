"""Matplotlib chart exports for the PA Housing Market Tracker.

Charts render from the same forensic-tested summary the dashboard uses, so
the PNGs and the HTML dashboard never disagree. The Agg backend keeps this
headless-safe (GitHub Actions has no display).
"""

import logging
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from data_platform.reporting.forensic import run_forensic_tests  # noqa: E402

logger = logging.getLogger(__name__)

DPI = 150
TOP_N = 15
MAX_TREND_PANELS = 6
TREND_YEARS = 10
SEVERITY_COLOR = {"red": "#c0392b", "amber": "#b7791f", "none": "#0e7c7b"}

plt.rcParams.update(
    {
        "font.family": "sans-serif",
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": True,
        "grid.color": "#eef0f3",
        "grid.linewidth": 0.8,
        "axes.axisbelow": True,
    }
)


def top_movers(tested: pd.DataFrame, out_path: Path) -> Path:
    """Horizontal bar chart: top N counties by YoY growth, colored by flag severity."""
    top = tested.sort_values("yoy_pct", ascending=False).head(TOP_N).iloc[::-1]
    fig, ax = plt.subplots(figsize=(8, 6))
    ax.barh(
        top["region"].str.replace(" County", ""),
        top["yoy_pct"],
        color=[SEVERITY_COLOR[s] for s in top["flag_severity"]],
    )
    ax.set_xlabel("YoY Growth %")
    ax.set_title(f"Top {TOP_N} Counties by YoY Growth — {tested['latest_date'].iloc[0]}")
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=DPI)
    plt.close(fig)
    return out_path


def consistency_scatter(tested: pd.DataFrame, out_path: Path) -> Path:
    """Scatter of YoY vs 5-yr growth, colored by flag severity; flagged counties annotated."""
    fig, ax = plt.subplots(figsize=(7, 6))
    ax.scatter(
        tested["growth_5yr_pct"],
        tested["yoy_pct"],
        c=[SEVERITY_COLOR[s] for s in tested["flag_severity"]],
        s=60,
        edgecolors="white",
        linewidths=0.5,
    )
    for _, r in tested[tested["flag_severity"] != "none"].iterrows():
        ax.annotate(
            r["region"].replace(" County", ""),
            (r["growth_5yr_pct"], r["yoy_pct"]),
            textcoords="offset points",
            xytext=(6, 4),
            fontsize=8,
        )
    ax.set_xlabel("5-Year Growth %")
    ax.set_ylabel("YoY Growth %")
    ax.set_title("Consistency Test: 1-Year vs 5-Year Growth")
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=DPI)
    plt.close(fig)
    return out_path


def flagged_trends(tested: pd.DataFrame, monthly: pd.DataFrame, out_path: Path) -> Path:
    """Small multiples of monthly ZHVI for flagged counties (max 6), last 10 years."""
    flagged = tested[tested["flag_severity"] != "none"].head(MAX_TREND_PANELS)
    recent = monthly.copy()
    recent["date"] = pd.to_datetime(recent["date"])
    cutoff = recent["date"].max() - pd.DateOffset(years=TREND_YEARS)
    recent = recent[recent["date"] >= cutoff]

    regions = list(flagged["region"])
    ncols = min(3, len(regions)) or 1
    nrows = -(-len(regions) // ncols) or 1
    fig, axes = plt.subplots(nrows, ncols, figsize=(4 * ncols, 3 * nrows), squeeze=False)
    flat_axes = axes.flat

    if not regions:
        ax = next(flat_axes)
        ax.text(0.5, 0.5, "No flagged counties", ha="center", va="center", transform=ax.transAxes)
        ax.set_xticks([])
        ax.set_yticks([])
    for region in regions:
        ax = next(flat_axes)
        series = recent[recent["region"] == region].sort_values("date")
        severity = flagged.loc[flagged["region"] == region, "flag_severity"].iloc[0]
        ax.plot(series["date"], series["zhvi"], color=SEVERITY_COLOR[severity], linewidth=2)
        ax.set_title(region.replace(" County", ""), fontsize=10)
        ax.tick_params(axis="x", labelrotation=45, labelsize=7)
        ax.tick_params(axis="y", labelsize=7)

    for ax in flat_axes:
        ax.axis("off")

    fig.suptitle(f"Flagged County Trends — {TREND_YEARS}-Year Monthly ZHVI")
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=DPI)
    plt.close(fig)
    return out_path


def write_charts(
    summary: pd.DataFrame,
    monthly: pd.DataFrame,
    out_dir: Path = Path("reports/charts"),
) -> list[Path]:
    tested = run_forensic_tests(summary)
    paths = [
        top_movers(tested, out_dir / "top_movers.png"),
        consistency_scatter(tested, out_dir / "consistency_scatter.png"),
        flagged_trends(tested, monthly, out_dir / "flagged_trends.png"),
    ]
    logger.info("Wrote %d charts to %s", len(paths), out_dir)
    return paths
