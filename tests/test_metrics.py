import pytest

from app.domain.metrics import (
    STAT_METRICS,
    Condition,
    DailyWeather,
    annual_rate,
    count_days,
    coverage,
    filter_period,
)


def day(date="2025-01-01", snow=None, tmin=None):
    return DailyWeather(date, snow, None, None, tmin, None, None)


def test_count_days_ignores_nulls():
    days = [day(snow=2.0), day(snow=None), day(snow=0.0)]
    assert count_days(days, Condition("snowfall_cm", ">=", 1.0)) == (1, 2)


def test_condition_le_operator_is_inclusive():
    cond = Condition("tmin_c", "<=", -18.0)
    assert cond.matches(day(tmin=-18.0)) is True
    assert cond.matches(day(tmin=-17.9)) is False
    assert cond.matches(day(tmin=None)) is None


def test_annual_rate():
    days = [day(snow=5.0)] * 10
    assert annual_rate(days, Condition("snowfall_cm", ">=", 1.0), years=5) == 2.0


def test_coverage():
    days = [day(snow=1.0), day(snow=None), day(snow=0.0)]
    assert coverage(days, "snowfall_cm", expected_days=4) == 0.5


def test_coverage_zero_expected_days():
    assert coverage([], "snowfall_cm", expected_days=0) == 0.0


def test_snow_day_threshold_is_trace():
    assert STAT_METRICS["snow_day"] == Condition("snowfall_cm", ">=", 0.1)


def test_stat_catalog_has_nine_metrics():
    assert len(STAT_METRICS) == 9


def test_filter_period_inclusive():
    days = [day("2024-12-31"), day("2025-01-01"), day("2025-12-31"), day("2026-01-01")]
    kept = filter_period(days, "2025-01-01", "2025-12-31")
    assert [d.date for d in kept] == ["2025-01-01", "2025-12-31"]


def test_condition_rejects_unknown_field():
    with pytest.raises(ValueError):
        Condition("rain", ">=", 1.0)
