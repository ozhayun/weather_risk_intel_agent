import pytest
from pydantic import ValidationError

from app.agent.schemas import Answer, CompareQuery, QueryPlan, RankQuery, StatQuery
from app.domain.results import StatResult


def plan(action: dict) -> QueryPlan:
    return QueryPlan.model_validate({"action": action})


def test_plan_discriminates_by_tool():
    assert isinstance(
        plan({"tool": "compare_hubs", "hubs": ["Miami", "Houston"]}).action, CompareQuery
    )
    assert isinstance(plan({"tool": "rank_hubs"}).action, RankQuery)


def test_compare_requires_two_hubs():
    with pytest.raises(ValidationError):
        plan({"tool": "compare_hubs", "hubs": ["Miami"]})


def test_unknown_tool_rejected():
    with pytest.raises(ValidationError):
        plan({"tool": "delete_hub", "hub": "Miami"})


def test_unknown_hazard_rejected():
    with pytest.raises(ValidationError):
        plan({"tool": "rank_hubs", "hazard": "earthquake"})


def test_stat_period_accepts_out_of_window_year_for_domain_to_scope():
    a = plan(
        {
            "tool": "get_weather_stat",
            "hub": "Denver",
            "metric": "snow_day",
            "aggregation": "count",
            "period": 2019,
        }
    ).action
    assert isinstance(a, StatQuery) and a.period == 2019


def test_top_n_must_be_positive():
    with pytest.raises(ValidationError):
        plan({"tool": "rank_hubs", "top_n": 0})


def stat_result(value=60.63) -> StatResult:
    return StatResult(
        hub_id="dallas",
        hub_name="Dallas",
        metric="snow_day",
        condition="snowfall_cm >= 0.1",
        aggregation="pct_of_days",
        period_label="2025",
        value=value,
        days_total=365,
        days_with_data=365,
        source="Open-Meteo",
        caveats=["~10 km grid"],
    )


def grounded(text: str, result=None) -> Answer:
    return Answer.model_validate({"text": text}, context={"result": result or stat_result()})


def test_grounding_accepts_rounded_value():
    grounded("Dallas scores 60.6 (about 61) over 365 days.")


def test_grounding_rejects_invented_score():
    with pytest.raises(ValidationError, match="87.3"):
        grounded("Dallas scores 87.3.")


def test_grounding_allows_years_and_small_ints():
    grounded("Over 5 years, 2021–2025 and 2021-2025, the top 3 hubs.")


def test_grounding_accepts_numbers_from_result_strings():
    grounded("Days with snowfall >= 0.1 cm on a ~10 km grid: 60.63%.")


def test_grounding_handles_thousands_separator():
    result = stat_result(value=27390)
    grounded("That is 27,390 days.", result)
    with pytest.raises(ValidationError):
        grounded("That is 28,390 days.", result)


def test_grounding_rejects_invented_negative():
    with pytest.raises(ValidationError):
        grounded("Temperatures fell to -40 degrees.")


def test_no_context_skips_grounding():
    assert Answer.model_validate({"text": "Scores 87.3"}).text == "Scores 87.3"


def test_followups_capped_at_three():
    with pytest.raises(ValidationError):
        Answer(text="x", suggested_followups=["a", "b", "c", "d"])
