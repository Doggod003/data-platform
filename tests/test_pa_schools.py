"""Tests for the PA schools integration — parsing, caching, no real network calls."""

import io
import zipfile
from unittest.mock import Mock, patch

import pandas as pd
import pytest
import requests

from data_platform.integrations.pa_schools import (
    fetch_private_schools,
    fetch_school_districts,
    get_private_schools,
    get_school_districts,
)

CCD_PAYLOAD = {
    "count": 3,
    "results": [
        {
            "lea_name": "Dauphin County Technical School",
            "county_name": "Dauphin County",
            "agency_type": 9,
            "number_of_schools": 1,
            "enrollment": 450,
        },
        {
            "lea_name": "Central Dauphin School District",
            "county_name": "Dauphin County",
            "agency_type": 1,
            "number_of_schools": 12,
            "enrollment": 10500,
        },
        {
            "lea_name": "Erie City School District",
            "county_name": "Erie County",
            "agency_type": 1,
            "number_of_schools": 18,
            "enrollment": 11800,
        },
    ],
}


def _pss_zip_bytes(csv_text: str, csv_name: str = "pss2122_pu.csv") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(csv_name, csv_text.encode("latin-1"))
    return buf.getvalue()


PSS_CSV = (
    "PSTABB,PCNTNM,PINST,NUMSTUDS\n"
    "PA,DAUPHIN,ST JOSEPH SCHOOL,210\n"
    "PA,ERIE,HOLY FAMILY ACADEMY,\n"  # blank enrollment (NCES suppresses small counts)
    "NY,ALBANY,SOME NY SCHOOL,300\n"
)


@patch("data_platform.integrations.pa_schools.requests.get")
def test_fetch_school_districts_parses_and_renames(mock_get):
    mock_get.return_value = Mock(json=Mock(return_value=CCD_PAYLOAD))
    result = fetch_school_districts(year=2024, state_fips="42")
    assert list(result.columns) == [
        "district",
        "county",
        "agency_type",
        "number_of_schools",
        "enrollment",
    ]
    assert len(result) == 3
    assert set(result["county"]) == {"Dauphin County", "Erie County"}


@patch("data_platform.integrations.pa_schools.requests.get")
def test_fetch_school_districts_raises_on_non_json(mock_get):
    bad_response = Mock(text="<html>not json</html>", url="http://example.test")
    bad_response.json.side_effect = requests.exceptions.JSONDecodeError(
        "Expecting value", "<html>", 0
    )
    mock_get.return_value = bad_response
    with pytest.raises(RuntimeError, match="did not return JSON"):
        fetch_school_districts()


@patch("data_platform.integrations.pa_schools.requests.get")
def test_fetch_school_districts_raises_on_missing_results_key(mock_get):
    mock_get.return_value = Mock(json=Mock(return_value={"unexpected": "shape"}))
    with pytest.raises(RuntimeError, match="results"):
        fetch_school_districts()


@patch("data_platform.integrations.pa_schools.requests.get")
def test_fetch_school_districts_raises_on_empty_results(mock_get):
    mock_get.return_value = Mock(json=Mock(return_value={"results": []}))
    with pytest.raises(RuntimeError, match="zero districts"):
        fetch_school_districts()


@patch("data_platform.integrations.pa_schools.requests.get")
def test_fetch_private_schools_filters_state_and_normalizes_county(mock_get):
    mock_get.return_value = Mock(content=_pss_zip_bytes(PSS_CSV))
    result = fetch_private_schools(state_abbr="PA")
    assert list(result.columns) == ["school", "county", "enrollment"]
    assert len(result) == 2  # NY row excluded
    assert set(result["county"]) == {"Dauphin County", "Erie County"}


@patch("data_platform.integrations.pa_schools.requests.get")
def test_fetch_private_schools_coerces_blank_enrollment_to_nan(mock_get):
    mock_get.return_value = Mock(content=_pss_zip_bytes(PSS_CSV))
    result = fetch_private_schools(state_abbr="PA")
    erie = result[result["county"] == "Erie County"].iloc[0]
    assert pd.isna(erie["enrollment"])


@patch("data_platform.integrations.pa_schools.requests.get")
def test_fetch_private_schools_raises_on_bad_zip(mock_get):
    mock_get.return_value = Mock(content=b"not a zip file")
    with pytest.raises(RuntimeError, match="not a valid zip"):
        fetch_private_schools()


@patch("data_platform.integrations.pa_schools.requests.get")
def test_fetch_private_schools_raises_when_zip_has_no_csv(mock_get):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("readme.txt", b"no csv in here")
    mock_get.return_value = Mock(content=buf.getvalue())
    with pytest.raises(RuntimeError, match="No CSV found"):
        fetch_private_schools()


@patch("data_platform.integrations.pa_schools.requests.get")
def test_fetch_private_schools_raises_on_unexpected_layout(mock_get):
    csv_text = "SOME_OTHER_COLUMN,FOO\nbar,baz\n"
    mock_get.return_value = Mock(content=_pss_zip_bytes(csv_text))
    with pytest.raises(RuntimeError, match="missing the expected PSTABB column"):
        fetch_private_schools()


@patch("data_platform.integrations.pa_schools.requests.get")
def test_fetch_private_schools_raises_when_state_has_no_rows(mock_get):
    csv_text = "PSTABB,PCNTNM,PINST,NUMSTUDS\nNY,ALBANY,SOME NY SCHOOL,300\n"
    mock_get.return_value = Mock(content=_pss_zip_bytes(csv_text))
    with pytest.raises(RuntimeError, match="No PA rows"):
        fetch_private_schools(state_abbr="PA")


@patch("data_platform.integrations.pa_schools.fetch_school_districts")
def test_get_school_districts_fetches_and_caches_when_missing(mock_fetch, tmp_path):
    mock_fetch.return_value = pd.DataFrame(CCD_PAYLOAD["results"]).rename(
        columns={"lea_name": "district", "county_name": "county"}
    )[["district", "county", "agency_type", "number_of_schools", "enrollment"]]
    cache_path = tmp_path / "districts.csv"

    result = get_school_districts(cache_path=cache_path)

    mock_fetch.assert_called_once()
    assert cache_path.exists()
    assert len(result) == 3


@patch("data_platform.integrations.pa_schools.fetch_school_districts")
def test_get_school_districts_uses_cache_when_fresh(mock_fetch, tmp_path):
    cache_path = tmp_path / "districts.csv"
    pd.DataFrame(CCD_PAYLOAD["results"]).to_csv(cache_path, index=False)

    result = get_school_districts(cache_path=cache_path)

    mock_fetch.assert_not_called()
    assert len(result) == 3


@patch("data_platform.integrations.pa_schools.fetch_private_schools")
def test_get_private_schools_fetches_and_caches_when_missing(mock_fetch, tmp_path):
    mock_fetch.return_value = pd.DataFrame(
        [{"school": "St Joseph School", "county": "Dauphin County", "enrollment": 210}]
    )
    cache_path = tmp_path / "private.csv"

    result = get_private_schools(cache_path=cache_path)

    mock_fetch.assert_called_once()
    assert cache_path.exists()
    assert len(result) == 1


@patch("data_platform.integrations.pa_schools.fetch_private_schools")
def test_get_private_schools_uses_cache_when_fresh(mock_fetch, tmp_path):
    cache_path = tmp_path / "private.csv"
    pd.DataFrame(
        [{"school": "St Joseph School", "county": "Dauphin County", "enrollment": 210}]
    ).to_csv(cache_path, index=False)

    result = get_private_schools(cache_path=cache_path)

    mock_fetch.assert_not_called()
    assert len(result) == 1
