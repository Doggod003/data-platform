"""PA school data: public district directory (NCES CCD) + private schools (NCES PSS).

Public district enrollment and school counts come from the Urban Institute's
Education Data Portal (educationdata.urban.org), a free, no-key REST API that
republishes NCES's Common Core of Data (CCD) in clean, year-parameterized
JSON — including county names already in our "X County" format, so no
district-to-county crosswalk is needed. It's a third-party aggregator of the
federal data rather than nces.ed.gov directly, but it's a well-established,
actively maintained, versioned public API.

Private schools come straight from NCES's own Private School Survey (PSS)
bulk CSV download, published every two years.

Both are cached to disk like census.py and re-fetched only when stale
(90 days), and both fail loudly rather than silently accept an unexpected
response.
"""

import io
import logging
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import requests

from data_platform.utils.caching import is_stale

logger = logging.getLogger(__name__)

CCD_URL_TMPL = "https://educationdata.urban.org/api/v1/school-districts/ccd/directory/{year}/"
PSS_URL_TMPL = "https://nces.ed.gov/surveys/pss/zip/pss{survey}_pu_csv.zip"

REGULAR_DISTRICT_AGENCY_TYPE = 1  # NCES agency_type code for a "regular" local school district

DEFAULT_CCD_YEAR = 2024
DEFAULT_PSS_SURVEY = "2122"  # 2021-22 school year, the latest available at time of writing

DEFAULT_DISTRICTS_CACHE_PATH = Path("data/processed/pa_school_districts.csv")
DEFAULT_PRIVATE_CACHE_PATH = Path("data/processed/pa_private_schools.csv")
CACHE_MAX_AGE_DAYS = 90


def fetch_school_districts(year: int = DEFAULT_CCD_YEAR, state_fips: str = "42") -> pd.DataFrame:
    """Pull the CCD district directory (enrollment, school counts) for a state/year.

    Output columns: district, county, agency_type, number_of_schools, enrollment
    """
    url = CCD_URL_TMPL.format(year=year)
    logger.info("Downloading CCD school district directory for %s, FIPS %s", year, state_fips)
    response = requests.get(url, params={"fips": state_fips}, timeout=30)
    response.raise_for_status()
    try:
        payload = response.json()
    except requests.exceptions.JSONDecodeError as exc:
        raise RuntimeError(
            "Education Data Portal API did not return JSON for the CCD district "
            f"directory — the endpoint may have changed or is down. URL: {response.url}. "
            f"Response body started with: {response.text[:200]!r}"
        ) from exc
    if "results" not in payload:
        raise RuntimeError(
            "Education Data Portal API response is missing the expected 'results' key "
            f"— its schema may have changed. Payload keys: {list(payload.keys())}"
        )
    districts = pd.DataFrame(payload["results"])
    if districts.empty:
        raise RuntimeError(f"CCD directory returned zero districts for FIPS {state_fips}, {year}.")
    return districts.rename(columns={"lea_name": "district", "county_name": "county"})[
        ["district", "county", "agency_type", "number_of_schools", "enrollment"]
    ]


def fetch_private_schools(survey: str = DEFAULT_PSS_SURVEY, state_abbr: str = "PA") -> pd.DataFrame:
    """Pull the NCES PSS private school directory for a biennial survey (e.g. '2122').

    Output columns: school, county, enrollment
    """
    url = PSS_URL_TMPL.format(survey=survey)
    logger.info("Downloading NCES PSS private school data for survey %s", survey)
    response = requests.get(url, timeout=60)
    response.raise_for_status()
    try:
        archive = zipfile.ZipFile(io.BytesIO(response.content))
    except zipfile.BadZipFile as exc:
        raise RuntimeError(
            f"NCES PSS download at {url} was not a valid zip file — the file may have "
            f"moved or survey code {survey!r} may be wrong. "
            f"First bytes: {response.content[:20]!r}"
        ) from exc
    csv_name = next((n for n in archive.namelist() if n.lower().endswith(".csv")), None)
    if csv_name is None:
        raise RuntimeError(f"No CSV found inside NCES PSS zip at {url}: {archive.namelist()}")

    with archive.open(csv_name) as f:
        raw = pd.read_csv(io.TextIOWrapper(f, encoding="latin-1"), low_memory=False)
    if "PSTABB" not in raw.columns:
        raise RuntimeError(
            f"NCES PSS file {csv_name} is missing the expected PSTABB column — its "
            f"layout may have changed. Columns seen: {list(raw.columns)[:10]}..."
        )

    private = raw[raw["PSTABB"] == state_abbr].copy()
    if private.empty:
        raise RuntimeError(f"No {state_abbr} rows found in NCES PSS survey {survey} data.")
    private["county"] = private["PCNTNM"].str.title() + " County"
    private["enrollment"] = pd.to_numeric(private["NUMSTUDS"], errors="coerce")
    return private.rename(columns={"PINST": "school"})[["school", "county", "enrollment"]]


def get_school_districts(
    year: int = DEFAULT_CCD_YEAR,
    state_fips: str = "42",
    cache_path: Path = DEFAULT_DISTRICTS_CACHE_PATH,
    max_age_days: int = CACHE_MAX_AGE_DAYS,
) -> pd.DataFrame:
    """Return cached district directory if fresh, else fetch, cache, and return."""
    if not is_stale(cache_path, max_age_days, datetime.now(UTC)):
        logger.info("Using cached school districts: %s", cache_path)
        return pd.read_csv(cache_path)

    districts = fetch_school_districts(year, state_fips)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    districts.to_csv(cache_path, index=False)
    logger.info("Cached school districts: %s (%d rows)", cache_path, len(districts))
    return districts


def get_private_schools(
    survey: str = DEFAULT_PSS_SURVEY,
    state_abbr: str = "PA",
    cache_path: Path = DEFAULT_PRIVATE_CACHE_PATH,
    max_age_days: int = CACHE_MAX_AGE_DAYS,
) -> pd.DataFrame:
    """Return cached private school directory if fresh, else fetch, cache, and return."""
    if not is_stale(cache_path, max_age_days, datetime.now(UTC)):
        logger.info("Using cached private schools: %s", cache_path)
        return pd.read_csv(cache_path)

    private = fetch_private_schools(survey, state_abbr)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    private.to_csv(cache_path, index=False)
    logger.info("Cached private schools: %s (%d rows)", cache_path, len(private))
    return private
