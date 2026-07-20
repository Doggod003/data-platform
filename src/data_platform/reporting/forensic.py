"""Forensic consistency tests applied to the housing summary.

Each test is a pure function over the summary DataFrame — no I/O — so the
whole exception logic is unit-testable and shows up in CI.
"""

import pandas as pd

MEDIAN_BASE_RATIO = 0.85  # "small base" = below 85% of median county value
SMALL_BASE_YOY = 10.0  # ...combined with a double-digit YoY move
ACCEL_MULTIPLE = 2.5  # YoY more than 2.5x its own 4-yr baseline
ACCEL_GAP_PTS = 4.0  # ...and at least 4pts above it


def implied_prior_growth(yoy_pct: pd.Series, growth_5yr_pct: pd.Series) -> pd.Series:
    """Back-solve total growth over years 2-5: (1+g5)/(1+g1) - 1, in percent."""
    return ((1 + growth_5yr_pct / 100) / (1 + yoy_pct / 100) - 1) * 100


def run_forensic_tests(summary: pd.DataFrame) -> pd.DataFrame:
    """Annotate the summary with consistency-test results.

    Adds columns:
      implied_prior4yr  - back-solved growth for years 2-5 (%)
      flag_severity     - 'red' | 'amber' | 'none'
      flag_test         - name of the triggered test
      flag_detail       - human-readable explanation for the exception report
    """
    df = summary.copy()
    df["implied_prior4yr"] = implied_prior_growth(df["yoy_pct"], df["growth_5yr_pct"]).round(1)
    implied_annual = df["implied_prior4yr"] / 4
    median_value = df["latest_zhvi"].median()

    df["flag_severity"] = "none"
    df["flag_test"] = ""
    df["flag_detail"] = ""

    # Test 3 (lowest precedence first): small-base distortion
    small_base = (df["latest_zhvi"] < median_value * MEDIAN_BASE_RATIO) & (
        df["yoy_pct"] >= SMALL_BASE_YOY
    )
    df.loc[small_base, ["flag_severity", "flag_test"]] = ["amber", "Small-base distortion"]
    df.loc[small_base, "flag_detail"] = df.loc[small_base].apply(
        lambda r: (
            f"Low absolute value (${r['latest_zhvi']:,.0f}) inflates percentage moves; "
            "corroborate with transaction volume before citing."
        ),
        axis=1,
    )

    # Test 2: acceleration outlier — YoY far above the county's own baseline
    accel = (
        (df["yoy_pct"] > implied_annual * ACCEL_MULTIPLE)
        & (df["yoy_pct"] - implied_annual > ACCEL_GAP_PTS)
        & (df["flag_severity"] == "none")
    )
    df.loc[accel, ["flag_severity", "flag_test"]] = ["amber", "Acceleration outlier"]
    df.loc[accel, "flag_detail"] = df.loc[accel].apply(
        lambda r: (
            f"YoY of {r['yoy_pct']}% runs {r['yoy_pct'] - r['implied_prior4yr'] / 4:.1f}pts "
            f"above its own 4-yr baseline ({r['implied_prior4yr'] / 4:.1f}%/yr). "
            "Sudden regime change — check for local drivers."
        ),
        axis=1,
    )

    # Test 1 (highest precedence): trend reversal — recent gain against negative history
    reversal = (df["growth_5yr_pct"] < 0) & (df["yoy_pct"] > 5)
    df.loc[reversal, ["flag_severity", "flag_test"]] = ["red", "Trend reversal"]
    df.loc[reversal, "flag_detail"] = df.loc[reversal].apply(
        lambda r: (
            f"5-yr growth is negative ({r['growth_5yr_pct']}%) yet YoY is +{r['yoy_pct']}%. "
            "The entire gain is recent — verify it isn't a thin-market artifact "
            "or data revision."
        ),
        axis=1,
    )

    return df
