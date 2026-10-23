"""SQLite access: schema, writes (ingest only) and reads (app startup)."""

import sqlite3
from pathlib import Path

from app.domain.metrics import DailyWeather

SCHEMA = """
CREATE TABLE IF NOT EXISTS daily_weather (
    hub_id          TEXT NOT NULL,
    date            TEXT NOT NULL,
    snowfall_cm     REAL,
    precip_mm       REAL,
    tmax_c          REAL,
    tmin_c          REAL,
    apparent_tmax_c REAL,
    gust_max_kmh    REAL,
    PRIMARY KEY (hub_id, date)
);
CREATE TABLE IF NOT EXISTS nri_hazard (
    hub_id        TEXT NOT NULL,
    county_fips   TEXT NOT NULL,
    hazard_code   TEXT NOT NULL,
    afreq         REAL,
    national_pctl REAL NOT NULL,
    PRIMARY KEY (hub_id, hazard_code)
);
CREATE TABLE IF NOT EXISTS dataset_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

_DAILY_COLS = "date, snowfall_cm, precip_mm, tmax_c, tmin_c, apparent_tmax_c, gust_max_kmh"


def connect(path: Path | str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.executescript(SCHEMA)
    return conn


def insert_daily(conn: sqlite3.Connection, hub_id: str, days: list[DailyWeather]) -> None:
    rows = [(hub_id, *vars(d).values()) for d in days]
    with conn:
        conn.executemany(
            "INSERT OR REPLACE INTO daily_weather VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )


def insert_nri(conn: sqlite3.Connection, rows: list[dict]) -> None:
    with conn:
        conn.executemany(
            "INSERT OR REPLACE INTO nri_hazard VALUES "
            "(:hub_id, :county_fips, :hazard_code, :afreq, :national_pctl)",
            rows,
        )


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    with conn:
        conn.execute("INSERT OR REPLACE INTO dataset_meta VALUES (?, ?)", (key, value))


def load_daily(conn: sqlite3.Connection) -> dict[str, list[DailyWeather]]:
    out: dict[str, list[DailyWeather]] = {}
    query = f"SELECT hub_id, {_DAILY_COLS} FROM daily_weather ORDER BY hub_id, date"
    for hub_id, *values in conn.execute(query):
        out.setdefault(hub_id, []).append(DailyWeather(*values))
    return out


def load_nri(conn: sqlite3.Connection) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for hub_id, code, pctl in conn.execute(
        "SELECT hub_id, hazard_code, national_pctl FROM nri_hazard"
    ):
        out.setdefault(hub_id, {})[code] = pctl
    return out


def load_meta(conn: sqlite3.Connection) -> dict[str, str]:
    return dict(conn.execute("SELECT key, value FROM dataset_meta"))
