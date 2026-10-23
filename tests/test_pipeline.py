import pytest

from app.agent.pipeline import HAZARD_COUNT, Agent
from app.agent.prompts import interpret_messages
from app.agent.schemas import Answer, QueryPlan
from tests.fakes import FakeLLM


def plan(**action) -> QueryPlan:
    return QueryPlan.model_validate({"action": action})


RANK = plan(tool="rank_hubs", hazard="winter", region="midwest")
ANSWER = Answer(text="Alpha leads.")


def text_of(messages: list[dict]) -> str:
    return "\n".join(m["content"] for m in messages)


def test_rank_flow_calls_llm_twice_and_passes_result_context(ctx):
    llm = FakeLLM([RANK, ANSWER])
    out = Agent(llm, ctx).run("s1", "Which Midwest hubs are worst in winter?")
    assert out.answer.text == "Alpha leads."
    assert out.result.kind == "rank" and out.plan == RANK
    assert len(llm.calls) == 2
    assert llm.calls[0].response_model is QueryPlan
    assert llm.calls[1].response_model is Answer
    assert llm.calls[1].context == {"result": out.result}
    assert '"hub_id":"a"' in text_of(llm.calls[1].messages)


def test_clarify_skips_execution(ctx):
    llm = FakeLLM([plan(tool="clarify", question="Which hub?", reason="ambiguous")])
    out = Agent(llm, ctx).run("s1", "how risky is it?")
    assert len(llm.calls) == 1
    assert out.answer.text == "Which hub?" and out.result is None


def test_unknown_hub_returns_scope_message_without_narration(ctx):
    llm = FakeLLM([plan(tool="explain_hub", hub="Tokyo")])
    out = Agent(llm, ctx).run("s1", "Why is Tokyo risky?")
    assert len(llm.calls) == 1
    assert out.result.kind == "scope" and "Tokyo" in out.answer.text


def test_followup_history_includes_previous_plan(ctx):
    llm = FakeLLM([RANK, ANSWER, plan(tool="rank_hubs", hazard="hurricane"), ANSWER])
    agent = Agent(llm, ctx)
    agent.run("s1", "Winter in the Midwest?")
    agent.run("s1", "And hurricanes?")
    second_interpret = text_of(llm.calls[2].messages)
    assert "Winter in the Midwest?" in second_interpret
    assert RANK.model_dump_json() in second_interpret


def test_sessions_are_isolated(ctx):
    llm = FakeLLM([RANK, ANSWER, RANK, ANSWER])
    agent = Agent(llm, ctx)
    agent.run("s1", "Winter in the Midwest?")
    agent.run("s2", "Something else")
    assert "Winter in the Midwest?" not in text_of(llm.calls[2].messages)


def test_history_is_limited(ctx):
    llm = FakeLLM([RANK, ANSWER] * 3)
    agent = Agent(llm, ctx, history_turns=1)
    for q in ("first q", "second q", "third q"):
        agent.run("s1", q)
    last = text_of(llm.calls[4].messages)
    assert "second q" in last and "first q" not in last


def test_interpret_failure_is_graceful(ctx):
    out = Agent(FakeLLM([RuntimeError("boom")]), ctx).run("s1", "???")
    assert out.plan is None and out.result is None
    assert out.answer.text.startswith("I couldn't interpret")


def test_narration_failure_keeps_result(ctx):
    out = Agent(FakeLLM([RANK, RuntimeError("grounding failed")]), ctx).run("s1", "q")
    assert out.result.kind == "rank"
    assert "couldn't phrase" in out.answer.text


def test_interpret_prompt_lists_all_hubs(ctx):
    content = text_of(interpret_messages("hi", [], ctx.registry.all(), ctx.cfg))
    assert all(h.name in content for h in ctx.registry.all())
    assert "alpha town" in content  # aliases
    assert "snow_day" in content  # stat catalog


def test_execute_failure_is_graceful(ctx, monkeypatch):
    agent = Agent(FakeLLM([RANK]), ctx)
    monkeypatch.setattr(agent, "execute", lambda plan: (_ for _ in ()).throw(KeyError("bug")))
    out = agent.run("s1", "q")
    assert out.result is None and out.plan == RANK
    assert "couldn't compute" in out.answer.text


def test_hazard_count_clarify_uses_deterministic_nri_explanation(ctx):
    llm = FakeLLM([plan(tool="clarify", question="Nope.", reason="hazard_count")])
    out = Agent(llm, ctx).run("s1", "How many hurricane days did Alpha have in 2025?")
    assert "static FEMA NRI" in out.answer.text and "Nope." not in out.answer.text
    assert "heavy-rain" in out.answer.text


def test_lowest_order_reaches_the_executor(ctx):
    llm = FakeLLM([plan(tool="rank_hubs", order="lowest"), ANSWER])
    out = Agent(llm, ctx).run("s1", "Which hub is safest?")
    assert out.result.order == "lowest" and out.result.rows[0].hub_id == "c"


def test_clarify_turns_do_not_leak_their_plan_into_history(ctx):
    clarify = plan(tool="clarify", question="No forecasts, sorry.", reason="out_of_scope")
    llm = FakeLLM([clarify, plan(tool="rank_hubs"), ANSWER])
    agent = Agent(llm, ctx)
    agent.run("s1", "Will it snow at Alpha tomorrow?")
    agent.run("s1", "How many heavy rain days did Alpha have in 2025?")
    second = text_of(llm.calls[1].messages[1:])  # conversation only, not the system rules
    assert "out_of_scope" not in second and "No forecasts, sorry." not in second
    assert "asked a clarifying question" in second


def test_hazard_count_text_only_when_message_mentions_hazard_events(ctx):
    llm = FakeLLM([plan(tool="clarify", question="Which year?", reason="hazard_count")])
    out = Agent(llm, ctx).run("s1", "How many heavy rain days did Alpha have in 2025?")
    assert "FEMA NRI" not in out.answer.text and out.answer.text == "Which year?"


@pytest.mark.parametrize(
    "message",
    [
        "How many flood days did Houston have in 2023?",
        "How many storm days did Dallas have in 2024?",
        "How many severe storm days did Kansas City have?",
        "How many hurricane days did Miami have in 2024?",
        "How many hurricanes hit Miami in 2022?",
        "What percentage of days in Houston had flooding in 2023?",
        "Count the tornado days in Dallas for 2021.",
        "How many hail events did Denver see in 2025?",
    ],
)
def test_hazard_event_counts_are_refused_before_the_llm(ctx, message):
    llm = FakeLLM([])  # any LLM call would raise IndexError
    out = Agent(llm, ctx).run("s1", message)
    assert llm.calls == []
    assert out.answer.text == HAZARD_COUNT
    assert out.plan.action.tool == "clarify" and out.plan.action.reason == "hazard_count"


@pytest.mark.parametrize(
    "message",
    [
        "How many heavy rain days did Houston have in 2023?",
        "How exposed is Houston to flood?",
        "Compare Miami and Houston on hurricane exposure.",
        "Rank the hubs by severe storms.",
    ],
)
def test_supported_questions_about_these_hazards_still_reach_the_llm(ctx, message):
    llm = FakeLLM([plan(tool="rank_hubs"), ANSWER])
    Agent(llm, ctx).run("s1", message)
    assert len(llm.calls) == 2
