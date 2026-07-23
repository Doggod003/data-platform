"""Tests for the OSM/Overpass amenities integration — parsing, retries, caching,
no real network calls."""

import os
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock, patch

import pandas as pd
import pytest
import requests

from data_platform.integrations.osm_amenities import (
    OVERPASS_URLS,
    RETRY_BACKOFF_SECONDS,
    _build_query,
    _parse_elements,
    fetch_all_counties_amenities,
    fetch_county_amenities,
    get_amenities,
)

SAMPLE_ELEMENTS = [
    {"type": "node", "id": 1, "tags": {"leisure": "park", "name": "Riverfront Park"}},
    {"type": "way", "id": 2, "tags": {"leisure": "golf_course", "name": "Colonial Golf Club"}},
    {"type": "way", "id": 3, "tags": {"leisure": "pitch", "sport": "baseball", "name": "Field 3"}},
    {"type": "node", "id": 4, "tags": {"leisure": "pitch", "sport": "soccer"}},  # no name tag
    {"type": "node", "id": 5, "tags": {"leisure": "playground"}},
    {"type": "way", "id": 6, "tags": {"leisure": "stadium", "name": "Some Stadium"}},  # excluded
]


def test_build_query_includes_county_and_all_categories():
    query = _build_query("Dauphin County")
    assert 'name"="Dauphin County"' in query
    assert 'admin_level"="6"' in query
    assert 'ISO3166-2"="US-PA"' in query
    for category in ["park", "golf_course", "pitch", "playground"]:
        assert f'"leisure"="{category}"' in query


def test_parse_elements_filters_and_captures_sport():
    result = _parse_elements(SAMPLE_ELEMENTS, "Dauphin County")
    assert len(result) == 5  # stadium excluded
    baseball = result[result["name"] == "Field 3"].iloc[0]
    assert baseball["category"] == "pitch"
    assert baseball["sport"] == "baseball"


def test_parse_elements_sport_is_none_for_non_pitch():
    result = _parse_elements(SAMPLE_ELEMENTS, "Dauphin County")
    park = result[result["name"] == "Riverfront Park"].iloc[0]
    assert pd.isna(park["sport"])


def test_parse_elements_handles_missing_name():
    result = _parse_elements(SAMPLE_ELEMENTS, "Dauphin County")
    soccer_pitch = result[(result["category"] == "pitch") & (result["sport"] == "soccer")].iloc[0]
    assert pd.isna(soccer_pitch["name"])


@patch("data_platform.integrations.osm_amenities.requests.post")
def test_fetch_county_amenities_success(mock_post):
    mock_post.return_value = Mock(
        status_code=200, json=Mock(return_value={"elements": SAMPLE_ELEMENTS})
    )
    result = fetch_county_amenities("Dauphin County")
    assert len(result) == 5
    assert set(result["county"]) == {"Dauphin County"}


@patch("data_platform.integrations.osm_amenities.time.sleep")
@patch("data_platform.integrations.osm_amenities.requests.post")
def test_fetch_county_amenities_retries_on_5xx_then_succeeds(mock_post, mock_sleep):
    busy = Mock(status_code=504, headers={})
    ok = Mock(status_code=200, json=Mock(return_value={"elements": SAMPLE_ELEMENTS}))
    mock_post.side_effect = [busy, ok]

    result = fetch_county_amenities("Dauphin County")

    assert len(result) == 5
    assert mock_post.call_count == 2
    mock_sleep.assert_called_once()


@patch("data_platform.integrations.osm_amenities.time.sleep")
@patch("data_platform.integrations.osm_amenities.requests.post")
def test_fetch_county_amenities_retries_on_429_then_succeeds(mock_post, mock_sleep):
    rate_limited = Mock(status_code=429, headers={})
    ok = Mock(status_code=200, json=Mock(return_value={"elements": SAMPLE_ELEMENTS}))
    mock_post.side_effect = [rate_limited, ok]

    result = fetch_county_amenities("Dauphin County")

    assert len(result) == 5
    assert mock_post.call_count == 2
    mock_sleep.assert_called_once()


@patch("data_platform.integrations.osm_amenities.time.sleep")
@patch("data_platform.integrations.osm_amenities.requests.post")
def test_fetch_county_amenities_backoff_grows_within_an_instance(mock_post, mock_sleep):
    busy = Mock(status_code=504, headers={})
    ok = Mock(status_code=200, json=Mock(return_value={"elements": SAMPLE_ELEMENTS}))
    # 2 failures on the primary (growing backoff), then success on attempt 3
    mock_post.side_effect = [busy, busy, ok]

    fetch_county_amenities("Dauphin County")

    waits = [call.args[0] for call in mock_sleep.call_args_list]
    assert waits == sorted(waits) and len(set(waits)) > 1  # strictly increasing, not flat


@patch("data_platform.integrations.osm_amenities.time.sleep")
@patch("data_platform.integrations.osm_amenities.requests.post")
def test_fetch_county_amenities_honors_retry_after_header(mock_post, mock_sleep):
    rate_limited = Mock(status_code=429, headers={"Retry-After": "17"})
    ok = Mock(status_code=200, json=Mock(return_value={"elements": SAMPLE_ELEMENTS}))
    mock_post.side_effect = [rate_limited, ok]

    fetch_county_amenities("Dauphin County")

    mock_sleep.assert_called_once_with(17.0)


@patch("data_platform.integrations.osm_amenities.time.sleep")
@patch("data_platform.integrations.osm_amenities.requests.post")
def test_fetch_county_amenities_falls_back_to_backoff_on_non_numeric_retry_after(
    mock_post, mock_sleep
):
    # Some servers send an HTTP-date Retry-After instead of a delta-seconds int
    rate_limited = Mock(status_code=429, headers={"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"})
    ok = Mock(status_code=200, json=Mock(return_value={"elements": SAMPLE_ELEMENTS}))
    mock_post.side_effect = [rate_limited, ok]

    fetch_county_amenities("Dauphin County")

    mock_sleep.assert_called_once_with(RETRY_BACKOFF_SECONDS)


@patch("data_platform.integrations.osm_amenities.time.sleep")
@patch("data_platform.integrations.osm_amenities.requests.post")
def test_fetch_county_amenities_falls_back_to_mirror_when_primary_exhausted(mock_post, mock_sleep):
    busy = Mock(status_code=504, headers={})
    ok = Mock(status_code=200, json=Mock(return_value={"elements": SAMPLE_ELEMENTS}))
    # 3 failures on the primary, then success on the mirror's first attempt
    mock_post.side_effect = [busy, busy, busy, ok]

    result = fetch_county_amenities("Dauphin County")

    assert len(result) == 5
    assert mock_post.call_count == 4
    called_urls = [call.args[0] for call in mock_post.call_args_list]
    assert called_urls == [OVERPASS_URLS[0]] * 3 + [OVERPASS_URLS[1]]


@patch("data_platform.integrations.osm_amenities.time.sleep")
@patch("data_platform.integrations.osm_amenities.requests.post")
def test_fetch_county_amenities_raises_after_max_attempts_on_every_instance(mock_post, mock_sleep):
    mock_post.return_value = Mock(status_code=504, headers={})
    with pytest.raises(RuntimeError, match="every instance tried"):
        fetch_county_amenities("Dauphin County")
    assert mock_post.call_count == len(OVERPASS_URLS) * 3


@patch("data_platform.integrations.osm_amenities.time.sleep")
@patch("data_platform.integrations.osm_amenities.requests.post")
def test_fetch_county_amenities_retries_on_network_exception_then_succeeds(mock_post, mock_sleep):
    ok = Mock(status_code=200, json=Mock(return_value={"elements": SAMPLE_ELEMENTS}))
    mock_post.side_effect = [requests.exceptions.ReadTimeout("timed out"), ok]

    result = fetch_county_amenities("Dauphin County")

    assert len(result) == 5
    assert mock_post.call_count == 2
    mock_sleep.assert_called_once()


@patch("data_platform.integrations.osm_amenities.time.sleep")
@patch("data_platform.integrations.osm_amenities.requests.post")
def test_fetch_county_amenities_network_exception_falls_back_to_mirror(mock_post, mock_sleep):
    ok = Mock(status_code=200, json=Mock(return_value={"elements": SAMPLE_ELEMENTS}))
    mock_post.side_effect = [
        requests.exceptions.ConnectionError("boom"),
        requests.exceptions.ConnectionError("boom"),
        requests.exceptions.ConnectionError("boom"),
        ok,
    ]

    result = fetch_county_amenities("Dauphin County")

    assert len(result) == 5
    called_urls = [call.args[0] for call in mock_post.call_args_list]
    assert called_urls == [OVERPASS_URLS[0]] * 3 + [OVERPASS_URLS[1]]


@patch("data_platform.integrations.osm_amenities.requests.post")
def test_fetch_county_amenities_raises_on_non_json(mock_post):
    bad_response = Mock(status_code=200, text="<html>not json</html>")
    bad_response.json.side_effect = requests.exceptions.JSONDecodeError(
        "Expecting value", "<html>", 0
    )
    mock_post.return_value = bad_response
    with pytest.raises(RuntimeError, match="did not return JSON"):
        fetch_county_amenities("Dauphin County")


@patch("data_platform.integrations.osm_amenities.requests.post")
def test_fetch_county_amenities_raises_on_missing_elements_key(mock_post):
    mock_post.return_value = Mock(status_code=200, json=Mock(return_value={"unexpected": "shape"}))
    with pytest.raises(RuntimeError, match="elements"):
        fetch_county_amenities("Dauphin County")


@patch("data_platform.integrations.osm_amenities.time.sleep")
@patch("data_platform.integrations.osm_amenities.fetch_county_amenities")
def test_fetch_all_counties_amenities_queries_sequentially_with_delay(mock_fetch, mock_sleep):
    mock_fetch.side_effect = lambda county, **_: pd.DataFrame(
        [{"county": county, "category": "park", "sport": None, "name": "Test Park"}]
    )
    result = fetch_all_counties_amenities(["Dauphin County", "Erie County", "Elk County"])

    assert len(result) == 3
    assert mock_fetch.call_count == 3
    assert mock_sleep.call_count == 2  # delay between, not after, the last query


@patch("data_platform.integrations.osm_amenities.fetch_all_counties_amenities")
def test_get_amenities_fetches_and_caches_when_missing(mock_fetch, tmp_path):
    mock_fetch.return_value = pd.DataFrame(
        [{"county": "Dauphin County", "category": "park", "sport": None, "name": "Riverfront Park"}]
    )
    cache_path = tmp_path / "amenities.csv"

    result = get_amenities(cache_path=cache_path, seed_path=tmp_path / "no-seed.csv")

    mock_fetch.assert_called_once()
    assert cache_path.exists()
    assert len(result) == 1
    assert "fetched_date" in result.columns
    assert "fetched_date" in pd.read_csv(cache_path).columns


@patch("data_platform.integrations.osm_amenities.fetch_all_counties_amenities")
def test_get_amenities_uses_cache_when_fresh(mock_fetch, tmp_path):
    cache_path = tmp_path / "amenities.csv"
    pd.DataFrame(
        [{"county": "Dauphin County", "category": "park", "sport": None, "name": "Riverfront Park"}]
    ).to_csv(cache_path, index=False)

    result = get_amenities(cache_path=cache_path, seed_path=tmp_path / "no-seed.csv")

    mock_fetch.assert_not_called()
    assert len(result) == 1


@patch("data_platform.integrations.osm_amenities.fetch_all_counties_amenities")
def test_get_amenities_falls_back_to_stale_cache_when_fetch_fails(mock_fetch, tmp_path):
    cache_path = tmp_path / "amenities.csv"
    pd.DataFrame(
        [
            {
                "county": "Dauphin County",
                "category": "park",
                "sport": None,
                "name": "Old Park",
                "fetched_date": "2020-01-01",
            }
        ]
    ).to_csv(cache_path, index=False)
    # backdate the file so is_stale() sees it as past the freshness window
    old_time = (datetime.now(UTC) - timedelta(days=200)).timestamp()
    os.utime(cache_path, (old_time, old_time))

    mock_fetch.side_effect = RuntimeError("Overpass is down everywhere")

    result = get_amenities(cache_path=cache_path, seed_path=tmp_path / "no-seed.csv")

    assert len(result) == 1
    assert result["name"].iloc[0] == "Old Park"


@patch("data_platform.integrations.osm_amenities.fetch_all_counties_amenities")
def test_get_amenities_falls_back_to_seed_when_no_cache_and_fetch_fails(mock_fetch, tmp_path):
    seed_path = tmp_path / "seed.csv"
    pd.DataFrame(
        [
            {
                "county": "Dauphin County",
                "category": "park",
                "sport": None,
                "name": "Seed Park",
                "fetched_date": "2026-01-15",
            }
        ]
    ).to_csv(seed_path, index=False)

    mock_fetch.side_effect = RuntimeError("Overpass is down everywhere")

    result = get_amenities(cache_path=tmp_path / "missing-cache.csv", seed_path=seed_path)

    assert len(result) == 1
    assert result["name"].iloc[0] == "Seed Park"


@patch("data_platform.integrations.osm_amenities.fetch_all_counties_amenities")
def test_get_amenities_raises_when_fetch_cache_and_seed_all_unavailable(mock_fetch, tmp_path):
    mock_fetch.side_effect = RuntimeError("Overpass is down everywhere")

    with pytest.raises(RuntimeError, match="Could not obtain OSM amenities"):
        get_amenities(
            cache_path=tmp_path / "missing-cache.csv", seed_path=tmp_path / "missing-seed.csv"
        )
