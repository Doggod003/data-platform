"""PA county amenities from OpenStreetMap, via the Overpass API.

Counts (and names, for the county detail page) of parks, golf courses,
playgrounds, and sports pitches by sport, queried per county boundary using
Overpass's area-chaining (state -> county, both matched by admin_level, which
correctly covers Philadelphia's consolidated city-county too — verified
directly against the API before writing this).

Overpass is a shared, rate-limited public service, so queries run
sequentially with a courtesy delay between counties, and a bounded retry
with exponential backoff on the transient 429/502/503/504s the public
instance returns when busy or rate-limiting us (observed firsthand while
developing this). Everything else fails loudly. A User-Agent header is
required — Overpass's frontend returns HTTP 406 without one. Results are
cached for 90 days so a full 67-county pull is rare, and if a fresh fetch
fails outright, get_amenities() falls back to whatever is cached (even if
stale) rather than taking down the whole pipeline — amenities is an
enrichment layer, not the pipeline's core output.
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

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
HEADERS = {"User-Agent": "data-platform/1.0 (PA housing market pipeline)", "Accept": "*/*"}

STATE_ISO = "US-PA"
CATEGORIES = ["park", "golf_course", "pitch", "playground"]

DEFAULT_CACHE_PATH = Path("data/processed/pa_osm_amenities.csv")
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

    Output columns: county, category, sport (pitches only, else None), name (nullable)
    """
    query = _build_query(county, state_iso)
    last_status = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        response = requests.post(OVERPASS_URL, data={"data": query}, headers=HEADERS, timeout=90)
        if response.status_code in RETRYABLE_STATUS_CODES:
            wait = _retry_wait_seconds(response, attempt)
            logger.warning(
                "Overpass returned %s for %s (attempt %d/%d) — waiting %.0fs before retry",
                response.status_code,
                county,
                attempt,
                MAX_ATTEMPTS,
                wait,
            )
            last_status = response.status_code
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
        return _parse_elements(payload["elements"], county)

    raise RuntimeError(
        f"Overpass kept returning server errors ({last_status}) for {county} after "
        f"{MAX_ATTEMPTS} attempts — the public instance may be overloaded or rate-limiting us; "
        f"try again later."
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


def get_amenities(
    counties: list[str] | None = None,
    cache_path: Path = DEFAULT_CACHE_PATH,
    max_age_days: int = CACHE_MAX_AGE_DAYS,
    delay_seconds: float = REQUEST_DELAY_SECONDS,
) -> pd.DataFrame:
    """Return cached amenities if fresh, else fetch all counties, cache, and return.

    If a fresh fetch fails after retries (e.g. Overpass is down or rate-limiting
    us hard), falls back to whatever is cached — even if stale — with a logged
    warning, rather than raising. Amenities is an enrichment layer on top of the
    core housing metrics, so a bad Overpass day shouldn't take down the whole
    monthly refresh. Only raises if there is truly no cache to fall back to.
    """
    if not is_stale(cache_path, max_age_days, datetime.now(UTC)):
        logger.info("Using cached amenities: %s", cache_path)
        return pd.read_csv(cache_path)

    try:
        amenities = fetch_all_counties_amenities(counties, delay_seconds)
    except Exception:
        if cache_path.exists():
            logger.warning(
                "Overpass fetch failed — falling back to stale cache: %s",
                cache_path,
                exc_info=True,
            )
            return pd.read_csv(cache_path)
        logger.error(
            "Overpass fetch failed and no cache exists at %s — amenities unavailable this run",
            cache_path,
        )
        raise

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    amenities.to_csv(cache_path, index=False)
    logger.info("Cached amenities: %s (%d rows)", cache_path, len(amenities))
    return amenities
