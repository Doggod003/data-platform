"""Shared disk-cache freshness check for integrations that fetch slow-moving data."""

from datetime import datetime, timedelta
from pathlib import Path


def is_stale(cache_path: Path, max_age_days: int, reference: datetime) -> bool:
    """True if cache_path is missing or older than max_age_days before reference."""
    if not cache_path.exists():
        return True
    mtime = datetime.fromtimestamp(cache_path.stat().st_mtime, tz=reference.tzinfo)
    return reference - mtime > timedelta(days=max_age_days)
