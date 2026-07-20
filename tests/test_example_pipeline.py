from data_platform.pipelines.example import extract, transform


def test_extract_returns_rows():
    rows = extract()
    assert len(rows) > 0
    assert "id" in rows[0]


def test_transform_doubles_value():
    result = transform([{"id": 1, "value": 5}])
    assert result[0]["value_doubled"] == 10
