"""Daily weather records and pure metric functions over them."""

from dataclasses import dataclass


@dataclass(frozen=True)
class DailyWeather:
    date: str  # ISO yyyy-mm-dd, hub local time
    snowfall_cm: float | None
    precip_mm: float | None
    tmax_c: float | None
    tmin_c: float | None
    apparent_tmax_c: float | None
    gust_max_kmh: float | None
