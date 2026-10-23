"""Synthetic 3-hub context: a (midwest, high), b (midwest, medium), c (south, low)."""

import pytest

from app.domain.hubs import Hub, HubRegistry
from app.domain.metrics import DailyWeather
from app.domain.queries import QueryContext
from app.domain.scoring import ScoringConfig, build_scorebook

SNOW = {"name": "snow_days", "field": "snowfall_cm", "op": ">=", "threshold": 1.0, "cap": 30.0}
CONFIG = {
    "version": "test",
    "window_start": "2025-01-01",
    "window_end": "2025-01-10",
    "labels": {"medium": 35.0, "high": 55.0},
    "flags": {"disagree_threshold": 50.0, "min_coverage": 0.98},
    "hazards": {
        "winter": {
            "weight": 0.5,
            "alpha": 0.6,
            "nri": ["WNTW"],
            "nri_agg": "mean",
            "metrics": [SNOW],
        },
        "hurricane": {"weight": 0.5, "alpha": 0.0, "nri": ["HRCN"], "nri_agg": "mean"},
    },
}


def days(n_snow: int) -> list[DailyWeather]:
    return [
        DailyWeather(f"2025-01-{i + 1:02d}", 5.0 if i < n_snow else 0.0, 1.0, 0, -5, 0, 10)
        for i in range(10)
    ]


@pytest.fixture
def ctx() -> QueryContext:
    hubs = [
        Hub("a", "Alpha", "IL", "midwest", 0, 0, "1", "x", ("alpha town",)),
        Hub("b", "Beta", "MN", "midwest", 0, 0, "2", "x"),
        Hub("c", "Gamma", "TX", "south", 0, 0, "3", "x"),
    ]
    daily = {"a": days(2), "b": days(0), "c": days(0)}
    nri = {
        "a": {"WNTW": 80.0, "HRCN": 90.0},  # winter 92, hurricane 90 → R 91 high
        "b": {"WNTW": 50.0, "HRCN": 60.0},  # winter 20, hurricane 60 → R 40 medium
        "c": {"WNTW": 10.0, "HRCN": 10.0},  # winter 4,  hurricane 10 → R 7 low
    }
    cfg = ScoringConfig.model_validate(CONFIG)
    registry = HubRegistry(hubs)
    return QueryContext(registry, build_scorebook(hubs, daily, nri, cfg), daily, cfg)
