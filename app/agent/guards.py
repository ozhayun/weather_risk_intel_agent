"""Deterministic output guards: prompt-leak detection and follow-up filtering."""

import re

from app.agent.prompts import INTERPRET_RULES, NARRATE_RULES, SECURITY_RULES

REFUSAL = "I can only help with weather-risk questions about our 15 hubs."
_MIN_LEAK_LINE = 40  # distinctive prompt lines; short lines like "Rules:" are too generic


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


_PROMPT_LINES = [
    _norm(line.lstrip("- "))
    for rules in (INTERPRET_RULES, NARRATE_RULES, SECURITY_RULES)
    for line in rules.splitlines()
    if len(line.strip()) >= _MIN_LEAK_LINE
]


def leaks_instructions(text: str) -> bool:
    normalized = _norm(text)
    return any(line in normalized for line in _PROMPT_LINES)


# Topics the tools cannot answer. Plain keyword match: false drops only lose a suggestion.
_UNANSWERABLE = re.compile(
    r"\b(seasons?|spring|summer|autumn|forecasts?|tomorrow|next (week|month|year)|future|"
    r"predict\w*|trends?|roi|return on|costs?|prices?|budget|invest\w*|insurance|dollars?)\b|\$",
    re.IGNORECASE,
)
# Hurricanes, floods and storms come from static FEMA NRI: there are no daily counts to ask for.
_HAZARD_COUNT = re.compile(
    r"\b(hurricanes?|flood(s|ing)?|(severe[- ])?storms?|tornado(es|s)?|hail)\s+"
    r"(days?|events?|counts?)\b|\bhow many (hurricanes|floods|storms|tornado(es|s)?)\b|"
    r"\bdays\b.*\b(had|with)\s+(flooding|hurricanes?|tornado(es|s)?|hail)\b",
    re.IGNORECASE,
)
_YEAR = re.compile(r"\b(19|20)\d{2}\b")


def asks_hazard_event_count(text: str) -> bool:
    """'How many flood/storm/hurricane days…': data the daily weather does not have."""
    return bool(_HAZARD_COUNT.search(text))


def filter_followups(
    followups: list[str], first_year: int = 2021, last_year: int = 2025
) -> list[str]:
    def answerable(q: str) -> bool:
        years = [int(m.group()) for m in _YEAR.finditer(q)]
        in_window = all(first_year <= y <= last_year for y in years)
        return in_window and not _UNANSWERABLE.search(q) and not _HAZARD_COUNT.search(q)

    return [q for q in followups if answerable(q)]
