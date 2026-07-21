"""Census ACS 5-year API client for county-level demographics.

Free public API — an optional CENSUS_API_KEY (config.settings) raises the
rate limit but isn't required. Demographics move slowly, so results are
cached to disk and only re-fetched when the cache is missing or stale.
Docs: https://www.census.gov/data/developers/data-sets/acs-5year.html
"""

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import requests

from data_platform.config import settings

logger = logging.getLogger(__name__)

ACS_URL = "https://api.census.gov/data/2023/acs/acs5"

# Census variable code -> our column name
VARIABLES = {
    "B01003_001E": "population",
    "B19013_001E": "median_income",
    "B01002_001E": "median_age",
    "B25003_002E": "owner_occupied",
    "B25003_001E": "total_occupied",
}

DEFAULT_CACHE_PATH = Path("data/processed/census_pa.csv")
CACHE_MAX_AGE_DAYS = 90


def parse_demographics(payload: list[list[str]]) -> pd.DataFrame:
    """Turn the Census API's [header, *rows] JSON payload into a tidy DataFrame.

    Output columns: county, population, median_income, median_age, owner_occupancy_pct
    """
    header, *rows = payload
    raw = pd.DataFrame(rows, columns=header).rename(columns=VARIABLES)
    raw["county"] = raw["NAME"].str.split(",").str[0].str.strip()

    for col in VARIABLES.values():
        raw[col] = pd.to_numeric(raw[col])

    raw["owner_occupancy_pct"] = round(raw["owner_occupied"] / raw["total_occupied"] * 100, 1)

    return raw[["county", "population", "median_income", "median_age", "owner_occupancy_pct"]]


def fetch_county_demographics(state_fips: str = "42") -> pd.DataFrame:
    """Pull ACS 5-year county demographics for the given state FIPS code (42 = PA)."""
    params = {
        "get": "NAME," + ",".join(VARIABLES),
        "for": "county:*",
        "in": f"state:{state_fips}",
    }
    if settings.census_api_key:
        params["key"] = settings.census_api_key

    logger.info("Downloading ACS demographics for state FIPS %s", state_fips)
    response = requests.get(ACS_URL, params=params, timeout=30)
    response.raise_for_status()
    return parse_demographics(response.json())


def _is_stale(cache_path: Path, max_age_days: int, reference: datetime) -> bool:
    """True if cache_path is missing or older than max_age_days before reference."""
    if not cache_path.exists():
        return True
    mtime = datetime.fromtimestamp(cache_path.stat().st_mtime, tz=UTC)
    return reference - mtime > timedelta(days=max_age_days)


def get_demographics(
    state_fips: str = "42",
    cache_path: Path = DEFAULT_CACHE_PATH,
    max_age_days: int = CACHE_MAX_AGE_DAYS,
) -> pd.DataFrame:
    """Return cached demographics if fresh, else fetch, cache, and return."""
    if not _is_stale(cache_path, max_age_days, datetime.now(UTC)):
        logger.info("Using cached demographics: %s", cache_path)
        return pd.read_csv(cache_path)

    demographics = fetch_county_demographics(state_fips)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    demographics.to_csv(cache_path, index=False)
    logger.info("Cached demographics: %s (%d rows)", cache_path, len(demographics))
    return demographics
