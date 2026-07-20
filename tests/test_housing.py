"""Tests for the housing pipeline — pure transforms only, no network calls."""

import pandas as pd

from data_platform.pipelines.housing import filter_state, summarize, to_long


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
