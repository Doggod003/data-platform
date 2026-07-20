"""Tests for reporting: forensic tests + dashboard rendering."""

from datetime import date

import pandas as pd

from data_platform.reporting.dashboard import build_dashboard
from data_platform.reporting.forensic import run_forensic_tests


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
            },
            # clean, unremarkable county
            {
                "region": "Erie County",
                "latest_date": date(2026, 6, 30),
                "latest_zhvi": 228459,
                "yoy_pct": 6.0,
                "growth_5yr_pct": 40.2,
                "yoy_rank": 10,
            },
            # small base + double-digit YoY
            {
                "region": "Elk County",
                "latest_date": date(2026, 6, 30),
                "latest_zhvi": 50000,
                "yoy_pct": 12.0,
                "growth_5yr_pct": 15.0,
                "yoy_rank": 1,
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
    out = build_dashboard(sample_summary(), sample_monthly(), tmp_path / "dash.html")
    assert out.exists()
    content = out.read_text(encoding="utf-8")
    assert "PA Housing Market Tracker" in content
    assert "Forest County" in content
    assert "<script" in content
