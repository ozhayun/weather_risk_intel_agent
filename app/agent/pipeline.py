"""interpret (LLM) → execute (deterministic) → narrate (LLM)."""

import logging
import re
from dataclasses import dataclass

from app.agent.guards import (
    REFUSAL,
    asks_hazard_event_count,
    filter_followups,
    leaks_instructions,
)
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
from app.domain.results import CompareResult, ExplainResult, RankResult, Result, StatResult

log = logging.getLogger(__name__)
# A premise needs a level word in THIS message; otherwise it was carried over from history.
_LEVEL_WORDS = re.compile(
    r"\b(high|higher|highest|low|lower|lowest|medium|moderate|risky|riskier|riskiest|safe|"
    r"safer|safest|dangerous|vulnerable|exposed|worst|bad)\b",
    re.IGNORECASE,
)
_HAZARD_EVENTS = re.compile(r"hurricane|flood|storm|tornado|hail", re.IGNORECASE)

INTERPRET_FAILED = (
    "I couldn't interpret that — try rephrasing, e.g. 'Rank Midwest hubs by winter risk'."
)
EXECUTE_FAILED = "I understood the question but couldn't compute the result. Please try rephrasing."
HAZARD_COUNT = (
    "I can't count hurricane, flood or severe-storm days: the daily weather data has no such "
    "events. Hurricane exposure comes from the static FEMA NRI long-term historical baseline, "
    "which I can explain or compare across hubs. For daily statistics I can count snow, "
    "extreme-cold, heavy-rain, extreme-heat and high-wind days for any hub in 2021–2025."
)
NARRATE_FAILED = (
    "I computed the result (see the details panel) but couldn't phrase it reliably. "
    "Try asking again."
)


REPLY_CHARS = 300


def summarize(result: Result | None) -> str:
    """Entities a follow-up can refer to ("why?", "the second one"), built from the result."""
    match result:
        case None:
            return ""
        case RankResult():
            top = ", ".join(f"{r.rank}. {r.name}" for r in result.rows[:5])
            return f"rank_hubs ({result.hazard}, order {result.order}): {top}"
        case CompareResult():
            return "compared: " + ", ".join(h.name for h in result.hubs)
        case ExplainResult():
            return f"explained: {result.hub.name}"
        case StatResult():
            return f"stat for {result.hub_name} ({result.metric}, {result.period_label})"
    return f"out of scope: {result.reason}"


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
        # Clarify plans stay out of history: replaying them made the model repeat refusals.
        executed = outcome.plan and not isinstance(outcome.plan.action, Clarify)
        plan_json = outcome.plan.model_dump_json() if executed else None
        reply = outcome.answer.text[:REPLY_CHARS]
        history.append(Turn(message, plan_json, reply, summarize(outcome.result)))
        return outcome

    def _run(self, message: str, history: list[Turn]) -> ChatOutcome:
        if asks_hazard_event_count(message):  # decided in code: the LLM kept offering fake stats
            refusal = Clarify(tool="clarify", question=HAZARD_COUNT, reason="hazard_count")
            return ChatOutcome(Answer(text=HAZARD_COUNT), QueryPlan(action=refusal), None)
        hubs = self.ctx.registry.all()
        try:
            plan = self.llm.complete(
                QueryPlan, interpret_messages(message, history, hubs, self.ctx.cfg)
            )
        except Exception:
            log.exception("interpret failed")
            return ChatOutcome(Answer(text=INTERPRET_FAILED), None, None)
        if (
            isinstance(plan.action, ExplainQuery)
            and plan.action.asserted_level
            and not _LEVEL_WORDS.search(message)
        ):
            action = plan.action.model_copy(update={"asserted_level": None})
            plan = plan.model_copy(update={"action": action})
        if isinstance(plan.action, Clarify):
            question = plan.action.question
            text = REFUSAL if leaks_instructions(question) else question
            if plan.action.reason == "hazard_count" and _HAZARD_EVENTS.search(message):
                text = HAZARD_COUNT  # a fact code owns, not LLM wording
            return ChatOutcome(Answer(text=text), plan, None)
        try:
            result = self.execute(plan)
        except Exception:
            log.exception("execute failed")
            return ChatOutcome(Answer(text=EXECUTE_FAILED), plan, None)
        if result.kind == "scope":
            return ChatOutcome(Answer(text=result.message), plan, result)
        try:
            messages = narrate_messages(message, result, hubs, self.ctx.window_label)
            answer = self._safe(self.llm.complete(Answer, messages, context={"result": result}))
            answer = self._with_premise(answer, result)
        except Exception:
            log.exception("narrate failed")
            answer = Answer(text=NARRATE_FAILED, caveats=result.caveats[:3])
        return ChatOutcome(answer, plan, result)

    def _safe(self, answer: Answer) -> Answer:
        """Drop prompt echoes and follow-ups the tools can't answer."""
        written = " ".join([answer.text, *answer.caveats, *answer.suggested_followups])
        if leaks_instructions(written):
            log.warning("narration echoed the instructions; replaced with refusal")
            return Answer(text=REFUSAL)
        first, last = (int(d[:4]) for d in (self.ctx.cfg.window_start, self.ctx.cfg.window_end))
        followups = filter_followups(answer.suggested_followups, first, last)
        return answer.model_copy(update={"suggested_followups": followups})

    @staticmethod
    def _with_premise(answer: Answer, result: Result) -> Answer:
        """A false premise is rejected by code, first, whatever the narration says."""
        check = getattr(result, "premise_check", None)
        if result.kind != "explain" or check is None or check.holds:
            return answer
        scope = f" for {check.hazard.replace('_', ' ')}" if check.hazard else " overall"
        lead = (
            f"**Premise check:** {result.hub.name} is not {check.asserted}-risk{scope}: "
            f"its exposure is {check.actual} (rank {check.rank} of {check.total})."
        )
        return answer.model_copy(update={"text": f"{lead}\n\n{answer.text}"})

    def execute(self, plan: QueryPlan) -> Result:
        match plan.action:
            case RankQuery() as a:
                return rank_hubs(self.ctx, a.hazard, a.region, a.hubs, a.top_n, a.order)
            case CompareQuery() as a:
                return compare_hubs(self.ctx, a.hubs, a.hazards)
            case StatQuery() as a:
                return get_weather_stat(self.ctx, a.hub, a.metric, a.aggregation, a.period)
            case ExplainQuery() as a:
                return explain_hub(self.ctx, a.hub, a.asserted_level, a.hazard)
        raise ValueError(f"no executor for {plan.action.tool}")
