"""Tests for matplotlib chart exports."""

from data_platform.reporting.charts import (
    consistency_scatter,
    flagged_trends,
    top_movers,
    write_charts,
)
from data_platform.reporting.forensic import run_forensic_tests
from tests.test_reporting import sample_monthly, sample_summary

MIN_PNG_BYTES = 5_000


def test_top_movers_writes_png(tmp_path):
    tested = run_forensic_tests(sample_summary())
    out = top_movers(tested, tmp_path / "top_movers.png")
    assert out.exists()
    assert out.stat().st_size > MIN_PNG_BYTES


def test_consistency_scatter_writes_png(tmp_path):
    tested = run_forensic_tests(sample_summary())
    out = consistency_scatter(tested, tmp_path / "scatter.png")
    assert out.exists()
    assert out.stat().st_size > MIN_PNG_BYTES


def test_flagged_trends_writes_png(tmp_path):
    tested = run_forensic_tests(sample_summary())
    out = flagged_trends(tested, sample_monthly(), tmp_path / "trends.png")
    assert out.exists()
    assert out.stat().st_size > MIN_PNG_BYTES


def test_flagged_trends_handles_no_flags(tmp_path):
    tested = run_forensic_tests(sample_summary())
    tested["flag_severity"] = "none"
    out = flagged_trends(tested, sample_monthly(), tmp_path / "trends.png")
    assert out.exists()
    assert out.stat().st_size > 0


def test_write_charts_writes_all_three(tmp_path):
    paths = write_charts(sample_summary(), sample_monthly(), tmp_path)
    assert len(paths) == 3
    for path in paths:
        assert path.exists()
        assert path.stat().st_size > MIN_PNG_BYTES
