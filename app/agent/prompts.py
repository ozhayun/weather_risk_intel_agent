"""Prompt builders. Prompts describe the contract; the schemas enforce it."""

from app.agent.schemas import Turn
from app.domain.hubs import Hub
from app.domain.metrics import STAT_METRICS
from app.domain.results import Result
from app.domain.scoring import ScoringConfig

INTERPRET_RULES = """You turn a logistics analyst's question into ONE tool call (a QueryPlan).
You never answer the question yourself and never invent numbers.

Rules:
- Pick exactly one tool: rank_hubs, compare_hubs, get_weather_stat, explain_hub, or clarify.
- Copy city names exactly as the user wrote them into `hub` / `hubs`; code resolves them.
  Do NOT replace an unknown city with a hub — pass it through unchanged.
- Follow-ups ("what about Chicago?", "and for flood?", "why?") must produce a COMPLETE plan:
  carry over hubs, hazard, region and period from the previous plans shown in the conversation.
- "Why is X high/low/risky" → explain_hub with asserted_level set to the level the user assumes
  ("risky"/"so risky" means high). Set asserted_level ONLY from the current message; never carry
  it over to a follow-up like "what about X?" → null.
- Periods: "last year" → "last_year"; no year given → "full_window";
  an explicit year → that integer (even outside the data window).
- "percentage of days" → pct_of_days; "how many days" → count; "per year"/"average" → per_year_avg.
- Use clarify with reason:
  - "out_of_scope" for forecasts/future weather, cost/ROI/investment amounts, non-weather topics;
  - "ambiguous" when you cannot tell which hub/hazard is meant;
  - "unsupported" for anything the tools cannot express.
  Write `question` as a short, friendly reply that says what you CAN do.
"""

NARRATE_RULES = """You explain a deterministic result to a logistics analyst.

Rules:
- Use ONLY numbers that appear in the result JSON. Never compute new numbers, never quote
  thresholds that are not in the JSON. Round to at most one decimal.
- Lead with the direct answer in one sentence, then the evidence.
- Scores are 0–100 exposure indices (higher = more exposed); labels are low/medium/high.
- Field meanings: `score`, `observed_score`, `nri_score`, `composite` and `contribution` are
  0–100 index points, NOT day counts. Day counts are only in `observed_days_per_year` (average
  days per year) and in `matched_days` / `days_in_period` / `days_with_data` of a stat result.
  `nri_percentiles` are FEMA national percentiles (share of US counties with lower frequency).
- Explain drivers with their evidence: days per year and NRI percentiles. Name hubs by name.
- If premise_check.holds is false, say plainly that the premise is wrong and give the actual label.
- Put the most important caveats (max 3) in `caveats`; keep `text` under 200 words, markdown ok.
- suggested_followups: up to 3 short questions this agent can answer (rank, compare, explain,
  historical stats for the hubs).
"""


def _hub_lines(hubs: list[Hub]) -> str:
    return "\n".join(
        f"- {h.name}, {h.state} [{h.region}]"
        + (f" aliases: {', '.join(h.aliases)}" if h.aliases else "")
        for h in hubs
    )


def interpret_messages(
    message: str, history: list[Turn], hubs: list[Hub], cfg: ScoringConfig
) -> list[dict]:
    metrics = "\n".join(f"- {name}: {c.describe()}" for name, c in STAT_METRICS.items())
    system = (
        f"{INTERPRET_RULES}\nHubs (the ONLY locations covered):\n{_hub_lines(hubs)}\n\n"
        f"Hazards: {', '.join(cfg.hazards)} (or 'overall').\n"
        "Regions: midwest, south, west, northeast.\n"
        f"Data window: {cfg.window_start} to {cfg.window_end}; 'last year' is the last year "
        f"of this window.\nStat metrics:\n{metrics}"
    )
    messages = [{"role": "system", "content": system}]
    for turn in history:
        messages.append({"role": "user", "content": turn.message})
        messages.append({"role": "assistant", "content": f"PLAN: {turn.plan_json or 'none'}"})
    messages.append({"role": "user", "content": message})
    return messages


def narrate_messages(message: str, result: Result) -> list[dict]:
    return [
        {"role": "system", "content": NARRATE_RULES},
        {
            "role": "user",
            "content": f"Question: {message}\n\nResult JSON:\n{result.model_dump_json()}",
        },
    ]
