"""Tests for reporting: forensic tests + dashboard rendering."""

from datetime import date

import pandas as pd

from data_platform.reporting.dashboard import build_dashboard
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
    assert "pa_housing_summary.csv" in content
    assert "pa_housing_monthly.csv" in content
    assert 'class="region-link"' in content
    assert 'id="top-mover-chip"' in content
    assert 'id="trend-card"' in content


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
