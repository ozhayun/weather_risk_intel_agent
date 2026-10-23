"""End-to-end evaluation against the real LLM. Run: uv run pytest -m eval -v"""

import json
from pathlib import Path

import pytest

from app.agent.llm import InstructorLLM
from app.agent.pipeline import NARRATE_FAILED, Agent
from app.agent.schemas import Answer
from app.api.main import load_context
from app.config import get_settings

CASES = json.loads((Path(__file__).parent / "cases.json").read_text())
pytestmark = pytest.mark.eval


@pytest.fixture(scope="module")
def real_ctx():
    return load_context(get_settings())


@pytest.fixture(scope="module")
def llm():
    try:
        return InstructorLLM(get_settings().llm_model)
    except Exception as exc:  # no key configured
        pytest.skip(f"LLM unavailable: {exc}")


def plan_hub_ids(action, ctx) -> set[str]:
    mentions = getattr(action, "hubs", None) or [getattr(action, "hub", None)]
    resolved = [ctx.registry.resolve(m) for m in mentions if m]
    return {h.hub_id for h in resolved if h}


def check_plan(action, exp: dict, ctx) -> None:
    if "tool" in exp:
        assert action.tool == exp["tool"]
    for key in ("hazard", "region", "metric", "aggregation", "top_n", "asserted_level"):
        if key in exp:
            assert getattr(action, key) == exp[key], key
    if "period" in exp:
        assert action.period in exp["period"]
    if "hubs" in exp:
        assert plan_hub_ids(action, ctx) == set(exp["hubs"])
    if "hazards_include" in exp:
        assert set(exp["hazards_include"]) <= set(action.hazards or ctx.cfg.hazards)


def check_result(out, exp: dict, ctx) -> None:
    result = out.result
    if exp.get("scope_or_clarify"):
        assert out.plan.action.tool == "clarify" or result.kind == "scope"
        return
    if "top_hub" in exp:
        assert result.rows[0].hub_id == exp["top_hub"]
    if "premise_holds" in exp:
        assert result.premise_check is not None
        assert result.premise_check.holds is exp["premise_holds"]
    if result is not None and result.kind != "scope":
        assert out.answer.text != NARRATE_FAILED
        Answer.model_validate(out.answer.model_dump(), context={"result": result})


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_eval_case(case, real_ctx, llm):
    agent = Agent(llm, real_ctx)
    for turn in case["turns"]:
        out = agent.run(case["id"], turn)
    exp = case["expect"]
    assert out.plan is not None, out.answer.text
    check_plan(out.plan.action, exp, real_ctx)
    check_result(out, exp, real_ctx)
    if "answer_contains" in exp:
        assert exp["answer_contains"] in out.answer.text
