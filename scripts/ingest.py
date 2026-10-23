"""Fetch 2021–2025 daily weather per hub from Open-Meteo and load everything into SQLite.

Run once; data/weather.db is committed. Usage: python -m scripts.ingest
"""

import csv
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import httpx

from app.config import get_settings, load_scoring_config
from app.data.db import connect, insert_daily, insert_nri, set_meta
from app.domain.hubs import Hub, HubRegistry
from app.domain.metrics import DailyWeather
from scripts.build_nri_subset import NRI_URL
from scripts.build_nri_subset import OUT_PATH as NRI_CSV

OPEN_METEO_URL = "https://archive-api.open-meteo.com/v1/archive"
DAILY_VARS = (
    "snowfall_sum,precipitation_sum,temperature_2m_max,temperature_2m_min,"
    "apparent_temperature_max,wind_gusts_10m_max"
)
BACKOFF_S = (10, 20, 40, 80)
PAUSE_BETWEEN_HUBS_S = 3


def parse_daily(payload: dict) -> list[DailyWeather]:
    if "daily" not in payload:
        raise ValueError(f"Open-Meteo error: {payload.get('reason', payload)}")
    d = payload["daily"]
    columns = [d[v] for v in DAILY_VARS.split(",")]
    return [DailyWeather(day, *values) for day, *values in zip(d["time"], *columns, strict=True)]


def fetch_daily(
    client: httpx.Client,
    hub: Hub,
    start: str,
    end: str,
    sleep: Callable[[float], None] = time.sleep,
) -> dict:
    params = {
        "latitude": hub.lat,
        "longitude": hub.lon,
        "start_date": start,
        "end_date": end,
        "daily": DAILY_VARS,
        "timezone": "auto",
    }
    for attempt in range(len(BACKOFF_S) + 1):
        response = client.get(OPEN_METEO_URL, params=params, timeout=60)
        retryable = response.status_code == 429 or response.status_code >= 500
        if not retryable or attempt == len(BACKOFF_S):
            return response.raise_for_status().json()
        sleep(BACKOFF_S[attempt])
    raise AssertionError("unreachable")


def load_nri_csv(path: Path) -> list[dict]:
    with path.open() as f:
        return [
            {**r, "afreq": float(r["afreq"] or 0), "national_pctl": float(r["national_pctl"])}
            for r in csv.DictReader(f)
        ]


def main() -> None:
    settings, cfg = get_settings(), load_scoring_config()
    start, end = cfg.window_start, cfg.window_end
    conn = connect(settings.db_path)
    with httpx.Client() as client:
        for hub in HubRegistry.from_json(settings.hubs_path).all():
            days = parse_daily(fetch_daily(client, hub, start, end))
            insert_daily(conn, hub.hub_id, days)
            print(f"{hub.hub_id}: {len(days)} days")
            time.sleep(PAUSE_BETWEEN_HUBS_S)
    insert_nri(conn, load_nri_csv(NRI_CSV))
    meta = {
        "window_start": start,
        "window_end": end,
        "open_meteo_url": OPEN_METEO_URL,
        "nri_url": NRI_URL,
        "ingested_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    for key, value in meta.items():
        set_meta(conn, key, value)
    conn.close()


if __name__ == "__main__":
    main()
