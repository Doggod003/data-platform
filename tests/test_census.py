"""Tests for the Census ACS integration — parsing, caching, no real network calls."""

from unittest.mock import Mock, patch

import pandas as pd
import pytest
import requests

from data_platform.integrations.census import (
    fetch_county_demographics,
    get_demographics,
    parse_demographics,
)

# The Census API's actual failure mode for a missing/invalid key: HTTP 200
# with an HTML body, not a JSON error — response.json() raises on this.
MISSING_KEY_HTML = "<html><head><title>Missing Key</title></head><body>...</body></html>"

SAMPLE_PAYLOAD = [
    [
        "NAME",
        "B01003_001E",
        "B19013_001E",
        "B01002_001E",
        "B25003_002E",
        "B25003_001E",
        "state",
        "county",
    ],
    ["Dauphin County, Pennsylvania", "270000", "65000", "38.5", "70000", "110000", "42", "043"],
    ["Cumberland County, Pennsylvania", "260000", "72000", "40.1", "75000", "100000", "42", "041"],
]


def test_parse_demographics_shapes_and_names():
    result = parse_demographics(SAMPLE_PAYLOAD)
    assert list(result.columns) == [
        "county",
        "population",
        "median_income",
        "median_age",
        "owner_occupancy_pct",
    ]
    assert set(result["county"]) == {"Dauphin County", "Cumberland County"}


def test_parse_demographics_computes_owner_occupancy_pct():
    result = parse_demographics(SAMPLE_PAYLOAD)
    dauphin = result[result["county"] == "Dauphin County"].iloc[0]
    cumberland = result[result["county"] == "Cumberland County"].iloc[0]
    assert dauphin["owner_occupancy_pct"] == 63.6  # 70000 / 110000 * 100
    assert cumberland["owner_occupancy_pct"] == 75.0  # 75000 / 100000 * 100


def test_parse_demographics_numeric_dtypes():
    result = parse_demographics(SAMPLE_PAYLOAD)
    assert pd.api.types.is_numeric_dtype(result["population"])
    assert pd.api.types.is_numeric_dtype(result["median_income"])
    assert pd.api.types.is_numeric_dtype(result["median_age"])


@patch("data_platform.integrations.census.settings")
@patch("data_platform.integrations.census.requests.get")
def test_fetch_county_demographics_calls_api_without_key(mock_get, mock_settings):
    mock_settings.census_api_key = None
    mock_get.return_value = Mock(json=Mock(return_value=SAMPLE_PAYLOAD))
    result = fetch_county_demographics(state_fips="42")
    assert len(result) == 2
    _, kwargs = mock_get.call_args
    assert kwargs["params"]["in"] == "state:42"
    assert "key" not in kwargs["params"]


@patch("data_platform.integrations.census.settings")
@patch("data_platform.integrations.census.requests.get")
def test_fetch_county_demographics_includes_api_key_when_set(mock_get, mock_settings):
    mock_settings.census_api_key = "test-key-123"
    mock_get.return_value = Mock(json=Mock(return_value=SAMPLE_PAYLOAD))
    fetch_county_demographics(state_fips="42")
    _, kwargs = mock_get.call_args
    assert kwargs["params"]["key"] == "test-key-123"


@patch("data_platform.integrations.census.requests.get")
def test_fetch_county_demographics_raises_clear_error_on_missing_key_page(mock_get):
    bad_response = Mock(text=MISSING_KEY_HTML)
    bad_response.json.side_effect = requests.exceptions.JSONDecodeError(
        "Expecting value", MISSING_KEY_HTML, 0
    )
    mock_get.return_value = bad_response

    with pytest.raises(RuntimeError, match="CENSUS_API_KEY"):
        fetch_county_demographics(state_fips="42")


@patch("data_platform.integrations.census.fetch_county_demographics")
def test_get_demographics_fetches_and_caches_when_missing(mock_fetch, tmp_path):
    mock_fetch.return_value = parse_demographics(SAMPLE_PAYLOAD)
    cache_path = tmp_path / "census_pa.csv"

    result = get_demographics(cache_path=cache_path)

    mock_fetch.assert_called_once()
    assert cache_path.exists()
    assert len(result) == 2


@patch("data_platform.integrations.census.fetch_county_demographics")
def test_get_demographics_uses_cache_when_fresh(mock_fetch, tmp_path):
    cache_path = tmp_path / "census_pa.csv"
    parse_demographics(SAMPLE_PAYLOAD).to_csv(cache_path, index=False)

    result = get_demographics(cache_path=cache_path)

    mock_fetch.assert_not_called()
    assert len(result) == 2
