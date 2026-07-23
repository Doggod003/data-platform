"""PA county amenities from OpenStreetMap, via the Overpass API.

Counts (and names, for the county detail page) of parks, golf courses,
playgrounds, and sports pitches by sport, queried per county boundary using
Overpass's area-chaining (state -> county, both matched by admin_level, which
correctly covers Philadelphia's consolidated city-county too — verified
directly against the API before writing this).

Overpass is a shared, rate-limited public service, so queries run
sequentially with a courtesy delay between counties, and a bounded retry with
exponential backoff (honoring Retry-After when Overpass sends one) on the
transient 429/502/503/504s the public instance returns when busy or
rate-limiting us, and on network-level failures (timeouts, connection
errors) — all observed firsthand while developing this. If the primary
instance (overpass-api.de) still won't serve a county after exhausting
retries, we try the community mirror (overpass.kumi.systems) before giving
up — GitHub Actions runner IPs have been observed getting throttled by the
primary instance even when a Codespace IP is served fine. A User-Agent
header is required — Overpass's frontend returns HTTP 406 without one.

Unlike Zillow/Census/schools, amenities are non-critical: get_amenities()
degrades gracefully through fresh cache -> live fetch -> stale cache ->
committed seed snapshot (data/seeds/osm_amenities_seed.csv) rather than
hard-failing the whole pipeline, since a bad Overpass day (or a fresh CI
runner with no cache yet) shouldn't block the housing data everything else
depends on. Every tier returns a fetched_date column so callers can show
users how current the data is.
"""

import logging
import time
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import requests

from data_platform.pipelines.regions import COUNTY_REGION
from data_platform.utils.caching import is_stale

logger = logging.getLogger(__name__)

OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
HEADERS = {"User-Agent": "data-platform/1.0 (PA housing market pipeline)", "Accept": "*/*"}

STATE_ISO = "US-PA"
CATEGORIES = ["park", "golf_course", "pitch", "playground"]

DEFAULT_CACHE_PATH = Path("data/processed/pa_osm_amenities.csv")
DEFAULT_SEED_PATH = Path("data/seeds/osm_amenities_seed.csv")
CACHE_MAX_AGE_DAYS = 90
REQUEST_DELAY_SECONDS = 2.0  # courtesy delay between sequential per-county queries
RETRYABLE_STATUS_CODES = (429, 502, 503, 504)
MAX_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 5.0  # base for exponential backoff: 5s, 10s, 20s, ...


def _build_query(county: str, state_iso: str = STATE_ISO) -> str:
    clauses = "\n  ".join(
        f'node["leisure"="{cat}"](area.cty);\n  way["leisure"="{cat}"](area.cty);'
        for cat in CATEGORIES
    )
    return (
        f"[out:json][timeout:60];\n"
        f'area["ISO3166-2"="{state_iso}"]["admin_level"="4"]->.state;\n'
        f'area["name"="{county}"]["admin_level"="6"](area.state)->.cty;\n'
        f"(\n  {clauses}\n);\n"
        f"out tags;"
    )


def _parse_elements(elements: list[dict], county: str) -> pd.DataFrame:
    rows = [
        {
            "county": county,
            "category": tags["leisure"],
            "sport": tags.get("sport") if tags["leisure"] == "pitch" else None,
            "name": tags.get("name"),
        }
        for el in elements
        for tags in [el.get("tags", {})]
        if tags.get("leisure") in CATEGORIES
    ]
    return pd.DataFrame(rows, columns=["county", "category", "sport", "name"])


def _retry_wait_seconds(response: requests.Response, attempt: int) -> float:
    """Honor Retry-After if Overpass sends one, else exponential backoff."""
    retry_after = response.headers.get("Retry-After")
    if retry_after is not None:
        try:
            return float(retry_after)
        except ValueError:
            pass  # fall through to backoff if header isn't a plain number
    return RETRY_BACKOFF_SECONDS * (2 ** (attempt - 1))


def fetch_county_amenities(county: str, state_iso: str = STATE_ISO) -> pd.DataFrame:
    """Query Overpass for one county's parks/golf courses/pitches/playgrounds.

    Tries each URL in OVERPASS_URLS in turn (primary instance, then the
    community mirror), giving each up to MAX_ATTEMPTS with exponential
    backoff before moving on.

    Output columns: county, category, sport (pitches only, else None), name (nullable)
    """
    query = _build_query(county, state_iso)
    last_error = None
    for url in OVERPASS_URLS:
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                response = requests.post(url, data={"data": query}, headers=HEADERS, timeout=90)
            except requests.exceptions.RequestException as exc:
                wait = RETRY_BACKOFF_SECONDS * (2 ** (attempt - 1))
                logger.warning(
                    "Overpass at %s raised %s for %s (attempt %d/%d) — waiting %.0fs",
                    url,
                    type(exc).__name__,
                    county,
                    attempt,
                    MAX_ATTEMPTS,
                    wait,
                )
                last_error = exc
                time.sleep(wait)
                continue

            if response.status_code in RETRYABLE_STATUS_CODES:
                wait = _retry_wait_seconds(response, attempt)
                logger.warning(
                    "Overpass at %s returned %s for %s (attempt %d/%d) — waiting %.0fs",
                    url,
                    response.status_code,
                    county,
                    attempt,
                    MAX_ATTEMPTS,
                    wait,
                )
                last_error = response.status_code
                time.sleep(wait)
                continue

            response.raise_for_status()
            try:
                payload = response.json()
            except requests.exceptions.JSONDecodeError as exc:
                raise RuntimeError(
                    f"Overpass did not return JSON for {county} — response body started with: "
                    f"{response.text[:200]!r}"
                ) from exc
            if "elements" not in payload:
                raise RuntimeError(
                    f"Overpass response for {county} is missing the expected 'elements' key. "
                    f"Payload keys: {list(payload.keys())}"
                )
            logger.info("Fetched %s from %s", county, url)
            return _parse_elements(payload["elements"], county)

    raise RuntimeError(
        f"Overpass kept failing for {county} ({last_error}) on every instance tried "
        f"({', '.join(OVERPASS_URLS)}) after {MAX_ATTEMPTS} attempts each."
    )


def fetch_all_counties_amenities(
    counties: list[str] | None = None,
    delay_seconds: float = REQUEST_DELAY_SECONDS,
) -> pd.DataFrame:
    """Sequentially query every county with a courtesy delay, then concatenate."""
    counties = counties if counties is not None else sorted(COUNTY_REGION.keys())
    frames = []
    for i, county in enumerate(counties):
        frames.append(fetch_county_amenities(county))
        if i < len(counties) - 1:
            time.sleep(delay_seconds)
    return pd.concat(frames, ignore_index=True)


def _vintage(path: Path, df: pd.DataFrame) -> str:
    """Best available 'as of' date for a cache/seed file.

    Prefers the file's own fetched_date column — git checkout doesn't
    preserve original mtimes, so a committed seed's mtime would just be
    whenever it was last checked out, not when it was fetched.
    """
    if "fetched_date" in df.columns and len(df):
        return str(df["fetched_date"].iloc[0])
    return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).date().isoformat()


def get_amenities(
    counties: list[str] | None = None,
    cache_path: Path = DEFAULT_CACHE_PATH,
    max_age_days: int = CACHE_MAX_AGE_DAYS,
    delay_seconds: float = REQUEST_DELAY_SECONDS,
    seed_path: Path = DEFAULT_SEED_PATH,
) -> pd.DataFrame:
    """Amenities degrade gracefully rather than hard-failing: fresh cache -> live
    fetch (primary then mirror) -> stale cache -> committed seed snapshot ->
    only then raise. Every path returns a fetched_date column.
    """
    if not is_stale(cache_path, max_age_days, datetime.now(UTC)):
        cached = pd.read_csv(cache_path)
        logger.info(
            "Using cached amenities (as of %s): %s", _vintage(cache_path, cached), cache_path
        )
        return cached

    try:
        amenities = fetch_all_counties_amenities(counties, delay_seconds)
        amenities["fetched_date"] = datetime.now(UTC).date().isoformat()
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        amenities.to_csv(cache_path, index=False)
        logger.info("Fetched and cached amenities: %s (%d rows)", cache_path, len(amenities))
        return amenities
    except Exception as exc:
        logger.warning("Live Overpass fetch failed for all counties/instances: %s", exc)

    if cache_path.exists():
        stale = pd.read_csv(cache_path)
        vintage = _vintage(cache_path, stale)
        logger.warning(
            "Falling back to STALE cached amenities (as of %s, past the %d-day freshness "
            "window): %s",
            vintage,
            max_age_days,
            cache_path,
        )
        return stale

    if seed_path.exists():
        seed = pd.read_csv(seed_path)
        vintage = _vintage(seed_path, seed)
        logger.warning(
            "No live Overpass data and no local cache; falling back to the committed seed "
            "snapshot (as of %s): %s",
            vintage,
            seed_path,
        )
        return seed

    raise RuntimeError(
        f"Could not obtain OSM amenities: live fetch failed, no cache at {cache_path}, "
        f"and no seed at {seed_path}."
    )
