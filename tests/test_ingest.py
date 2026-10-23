import httpx
import pytest

from app.domain.hubs import Hub
from app.domain.metrics import DailyWeather
from scripts.build_nri_subset import build_rows, national_percentile
from scripts.ingest import fetch_daily, parse_daily

HUB = Hub("denver", "Denver", "CO", "west", 39.7, -105.0, "08031", "x")
DAILY = {
    "time": ["2025-01-01"],
    "snowfall_sum": [None],
    "precipitation_sum": [2.0],
    "temperature_2m_max": [5.0],
    "temperature_2m_min": [-3.0],
    "apparent_temperature_max": [1.0],
    "wind_gusts_10m_max": [40.0],
}


def test_national_percentile_strict_below():
    vals = [0, 0, 0, 5, 10]
    assert national_percentile(vals, 0) == 0.0
    assert national_percentile(vals, 5) == 60.0
    assert national_percentile(vals, 10) == 80.0


def test_national_percentile_treats_none_as_zero():
    assert national_percentile([None, 0, 5, 10], None) == 0.0
    assert national_percentile([None, 0, 5, 10], 10) == 75.0


def test_build_rows_long_format():
    counties = [
        {"STCOFIPS": "08031", **{f"{c}_AFREQ": 1.0 for c in ("WNTW", "HRCN")}},
        {"STCOFIPS": "99999", **{f"{c}_AFREQ": 0.0 for c in ("WNTW", "HRCN")}},
    ]
    rows = build_rows([HUB], counties, codes=("WNTW", "HRCN"))
    assert rows == [
        {
            "hub_id": "denver",
            "county_fips": "08031",
            "hazard_code": "WNTW",
            "afreq": 1.0,
            "national_pctl": 50.0,
        },
        {
            "hub_id": "denver",
            "county_fips": "08031",
            "hazard_code": "HRCN",
            "afreq": 1.0,
            "national_pctl": 50.0,
        },
    ]


def test_build_rows_missing_county_fails_loudly():
    with pytest.raises(KeyError, match="08031"):
        build_rows([HUB], [{"STCOFIPS": "11111", "WNTW_AFREQ": 1.0}], codes=("WNTW",))


def test_parse_daily_maps_fields_and_keeps_nulls():
    assert parse_daily({"daily": DAILY}) == [
        DailyWeather("2025-01-01", None, 2.0, 5.0, -3.0, 1.0, 40.0)
    ]


def test_parse_daily_error_payload_raises():
    with pytest.raises(ValueError, match="bad coords"):
        parse_daily({"error": True, "reason": "bad coords"})


def test_fetch_daily_retries_on_429():
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(429)
        return httpx.Response(200, json={"daily": DAILY})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    payload = fetch_daily(client, HUB, "2025-01-01", "2025-01-01", sleep=lambda s: None)
    assert payload["daily"]["time"] == ["2025-01-01"]
    assert len(calls) == 2
    assert calls[0].url.params["timezone"] == "auto"


def test_fetch_daily_gives_up_after_retries():
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    with pytest.raises(httpx.HTTPStatusError):
        fetch_daily(client, HUB, "2025-01-01", "2025-01-01", sleep=lambda s: None)


def test_fetch_daily_does_not_retry_on_400():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(400, json={"error": True, "reason": "x"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(httpx.HTTPStatusError):
        fetch_daily(client, HUB, "2025-01-01", "2025-01-01", sleep=lambda s: None)
    assert len(calls) == 1
