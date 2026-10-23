from app.data.db import connect, insert_daily, insert_nri, load_daily, load_meta, load_nri, set_meta
from app.domain.metrics import DailyWeather

DAYS = [
    DailyWeather("2025-01-02", 3.0, 1.0, 2.0, -5.0, -1.0, 30.0),
    DailyWeather("2025-01-01", None, 0.0, 1.0, -8.0, -4.0, 20.0),
]


def test_roundtrip_in_memory():
    conn = connect(":memory:")
    insert_daily(conn, "denver", DAYS)
    insert_nri(
        conn,
        [
            {
                "hub_id": "denver",
                "county_fips": "08031",
                "hazard_code": "WNTW",
                "afreq": 1.5,
                "national_pctl": 70.0,
            }
        ],
    )
    set_meta(conn, "window_end", "2025-12-31")
    assert load_daily(conn)["denver"] == sorted(DAYS, key=lambda d: d.date)
    assert load_nri(conn) == {"denver": {"WNTW": 70.0}}
    assert load_meta(conn)["window_end"] == "2025-12-31"


def test_insert_daily_is_idempotent():
    conn = connect(":memory:")
    insert_daily(conn, "denver", DAYS)
    insert_daily(conn, "denver", DAYS)
    assert len(load_daily(conn)["denver"]) == 2


def test_connect_is_reentrant(tmp_path):
    path = tmp_path / "w.db"
    connect(path).close()
    conn = connect(path)  # schema uses IF NOT EXISTS
    assert load_daily(conn) == {}
