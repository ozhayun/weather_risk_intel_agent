"""Daily weather records and pure metric functions over them."""

from dataclasses import dataclass
from typing import Literal, get_args

WeatherField = Literal[
    "snowfall_cm", "precip_mm", "tmax_c", "tmin_c", "apparent_tmax_c", "gust_max_kmh"
]
StatMetric = Literal[
    "snow_day",
    "heavy_snow_day",
    "freezing_day",
    "extreme_cold_day",
    "rain_day",
    "heavy_rain_day",
    "hot_day",
    "dangerous_heat_day",
    "high_wind_day",
]
Aggregation = Literal["count", "pct_of_days", "per_year_avg"]


@dataclass(frozen=True)
class DailyWeather:
    date: str  # ISO yyyy-mm-dd, hub local time
    snowfall_cm: float | None
    precip_mm: float | None
    tmax_c: float | None
    tmin_c: float | None
    apparent_tmax_c: float | None
    gust_max_kmh: float | None


@dataclass(frozen=True)
class Condition:
    field: WeatherField
    op: Literal[">=", "<="]
    threshold: float

    def __post_init__(self) -> None:
        if self.field not in get_args(WeatherField) or self.op not in (">=", "<="):
            raise ValueError(f"invalid condition: {self}")

    def matches(self, day: DailyWeather) -> bool | None:
        value = getattr(day, self.field)
        if value is None:
            return None
        return value >= self.threshold if self.op == ">=" else value <= self.threshold

    def describe(self) -> str:
        return f"{self.field} {self.op} {self.threshold:g}"


# Q3 catalog — docs/02-scoring-model.md §6. snow_day counts any measurable snow (≥ 0.1 cm).
STAT_METRICS: dict[StatMetric, Condition] = {
    "snow_day": Condition("snowfall_cm", ">=", 0.1),
    "heavy_snow_day": Condition("snowfall_cm", ">=", 10.0),
    "freezing_day": Condition("tmin_c", "<=", 0.0),
    "extreme_cold_day": Condition("tmin_c", "<=", -18.0),
    "rain_day": Condition("precip_mm", ">=", 1.0),
    "heavy_rain_day": Condition("precip_mm", ">=", 25.0),
    "hot_day": Condition("tmax_c", ">=", 35.0),
    "dangerous_heat_day": Condition("apparent_tmax_c", ">=", 40.0),
    "high_wind_day": Condition("gust_max_kmh", ">=", 75.0),
}


def count_days(days: list[DailyWeather], cond: Condition) -> tuple[int, int]:
    """(matching days, days with data) — null values are excluded from both."""
    results = [cond.matches(d) for d in days]
    with_data = [r for r in results if r is not None]
    return sum(with_data), len(with_data)


def annual_rate(days: list[DailyWeather], cond: Condition, years: float) -> float:
    return count_days(days, cond)[0] / years


def coverage(days: list[DailyWeather], field: WeatherField, expected_days: int) -> float:
    if expected_days <= 0:
        return 0.0
    return sum(getattr(d, field) is not None for d in days) / expected_days


def filter_period(days: list[DailyWeather], start: str, end: str) -> list[DailyWeather]:
    return [d for d in days if start <= d.date <= end]
