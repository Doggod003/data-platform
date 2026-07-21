"""Tests for the shared disk-cache freshness check."""

from datetime import UTC, datetime, timedelta

from data_platform.utils.caching import is_stale


def test_is_stale_missing_file(tmp_path):
    assert is_stale(tmp_path / "missing.csv", 90, datetime.now(UTC)) is True


def test_is_stale_fresh_file(tmp_path):
    cache = tmp_path / "cache.csv"
    cache.write_text("county\n")
    assert is_stale(cache, 90, datetime.now(UTC)) is False


def test_is_stale_old_file(tmp_path):
    cache = tmp_path / "cache.csv"
    cache.write_text("county\n")
    reference = datetime.now(UTC) + timedelta(days=100)
    assert is_stale(cache, 90, reference) is True
