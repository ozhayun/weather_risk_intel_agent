"""interpret (LLM) → execute (deterministic) → narrate (LLM)."""

import logging
from dataclasses import dataclass

from app.agent.llm import StructuredLLM
from app.agent.prompts import interpret_messages, narrate_messages
from app.agent.schemas import (
    Answer,
    Clarify,
    CompareQuery,
    ExplainQuery,
    QueryPlan,
    RankQuery,
    StatQuery,
    Turn,
)
from app.domain.queries import (
    QueryContext,
    compare_hubs,
    explain_hub,
    get_weather_stat,
    rank_hubs,
)
from app.domain.results import Result

log = logging.getLogger(__name__)

INTERPRET_FAILED = (
    "I couldn't interpret that — try rephrasing, e.g. 'Rank Midwest hubs by winter risk'."
)
EXECUTE_FAILED = "I understood the question but couldn't compute the result. Please try rephrasing."
NARRATE_FAILED = (
    "I computed the result (see the details panel) but couldn't phrase it reliably. "
    "Try asking again."
)


@dataclass
class ChatOutcome:
    answer: Answer
    plan: QueryPlan | None
    result: Result | None


class Agent:
    # ponytail: in-memory sessions, unbounded session count; move to SQLite if this outlives a demo
    def __init__(self, llm: StructuredLLM, ctx: QueryContext, history_turns: int = 4):
        self.llm = llm
        self.ctx = ctx
        self.history_turns = history_turns
        self.sessions: dict[str, list[Turn]] = {}

    def run(self, session_id: str, message: str) -> ChatOutcome:
        history = self.sessions.setdefault(session_id, [])
        outcome = self._run(message, history[-self.history_turns :])
        plan_json = outcome.plan.model_dump_json() if outcome.plan else None
        history.append(Turn(message, plan_json))
        return outcome

    def _run(self, message: str, history: list[Turn]) -> ChatOutcome:
        hubs = self.ctx.registry.all()
        try:
            plan = self.llm.complete(
                QueryPlan, interpret_messages(message, history, hubs, self.ctx.cfg)
            )
        except Exception:
            log.exception("interpret failed")
            return ChatOutcome(Answer(text=INTERPRET_FAILED), None, None)
        if isinstance(plan.action, Clarify):
            return ChatOutcome(Answer(text=plan.action.question), plan, None)
        try:
            result = self.execute(plan)
        except Exception:
            log.exception("execute failed")
            return ChatOutcome(Answer(text=EXECUTE_FAILED), plan, None)
        if result.kind == "scope":
            return ChatOutcome(Answer(text=result.message), plan, result)
        try:
            answer = self.llm.complete(
                Answer, narrate_messages(message, result), context={"result": result}
            )
        except Exception:
            log.exception("narrate failed")
            answer = Answer(text=NARRATE_FAILED, caveats=result.caveats[:3])
        return ChatOutcome(answer, plan, result)

    def execute(self, plan: QueryPlan) -> Result:
        match plan.action:
            case RankQuery() as a:
                return rank_hubs(self.ctx, a.hazard, a.region, a.hubs, a.top_n)
            case CompareQuery() as a:
                return compare_hubs(self.ctx, a.hubs, a.hazards)
            case StatQuery() as a:
                return get_weather_stat(self.ctx, a.hub, a.metric, a.aggregation, a.period)
            case ExplainQuery() as a:
                return explain_hub(self.ctx, a.hub, a.asserted_level)
        raise ValueError(f"no executor for {plan.action.tool}")
