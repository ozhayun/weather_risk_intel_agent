"""JSON-schema contract between the LLM and the code (docs/03-architecture.md §4)."""

import re
from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import BaseModel, Field, ValidationInfo, model_validator

from app.domain.hubs import Region
from app.domain.metrics import Aggregation, StatMetric
from app.domain.scoring import Hazard, Label

# Any year is accepted here so the domain can answer "only 2021–2025" instead of the
# schema rejecting it and the LLM retrying into a generic failure.
Period = Literal["last_year", "full_window"] | int


class RankQuery(BaseModel):
    """Rank hubs by one hazard or overall risk, optionally within a region or named hubs."""

    tool: Literal["rank_hubs"]
    hazard: Hazard | Literal["overall"] = "overall"
    region: Region | None = None
    hubs: list[str] = Field(default=[], description="City names exactly as the user wrote them")
    top_n: Annotated[int, Field(ge=1)] | None = None
    order: Literal["highest", "lowest"] = Field(
        default="highest", description="'lowest' for safest / least exposed hubs"
    )


class CompareQuery(BaseModel):
    """Compare two or more hubs side by side."""

    tool: Literal["compare_hubs"]
    hubs: list[str] = Field(min_length=2, description="City names exactly as the user wrote them")
    hazards: list[Hazard] = Field(default=[], description="Empty means all hazards")


class StatQuery(BaseModel):
    """A raw historical weather statistic for one hub."""

    tool: Literal["get_weather_stat"]
    hub: str
    metric: StatMetric
    aggregation: Aggregation
    period: Period = Field(description="'last_year', 'full_window', or a calendar year")


class ExplainQuery(BaseModel):
    """Explain one hub's risk score and its drivers."""

    tool: Literal["explain_hub"]
    hub: str
    hazard: Hazard | None = Field(
        default=None, description="Set when the question is about one hazard of this hub"
    )
    asserted_level: Label | None = Field(
        default=None, description="Risk level the user's question assumes, e.g. 'why is X high'"
    )


class Clarify(BaseModel):
    """Ask the user a question instead of running a tool."""

    tool: Literal["clarify"]
    question: str = Field(max_length=500)
    reason: Literal["ambiguous", "out_of_scope", "unsupported", "hazard_count"]


Action = RankQuery | CompareQuery | StatQuery | ExplainQuery | Clarify


class QueryPlan(BaseModel):
    action: Annotated[Action, Field(discriminator="tool")]

    @model_validator(mode="before")
    @classmethod
    def _wrap_bare_action(cls, data):
        """The model sometimes returns the tool call without the `action` wrapper."""
        if isinstance(data, dict) and "tool" in data and "action" not in data:
            return {"action": data}
        return data


_NUMBER = re.compile(r"(?<![\w.])-?\d[\d,]*(?:\.\d+)?")
_ALWAYS_ALLOWED = set(range(0, 21)) | set(range(2021, 2026))
# ponytail: small-int allowance can mask an invented small score; tighten if evals show it


def _numbers(text: str) -> list[float]:
    return [float(m.replace(",", "")) for m in _NUMBER.findall(text)]


def _is_grounded(n: float, allowed: list[float]) -> bool:
    if n in _ALWAYS_ALLOWED:
        return True
    tolerance = (0.5 if n.is_integer() else 0.05) + 1e-9  # float slack at x.x5 rounding
    return any(abs(n - v) <= tolerance for v in allowed)


class Answer(BaseModel):
    text: str = Field(description="Markdown answer, at most ~200 words")
    caveats: list[str] = []
    suggested_followups: list[str] = Field(default=[], max_length=3)

    @model_validator(mode="after")
    def _numbers_come_from_result(self, info: ValidationInfo) -> "Answer":
        result = (info.context or {}).get("result")
        if result is None:
            return self
        allowed = _numbers(result.model_dump_json())
        written = " ".join([self.text, *self.caveats])
        ungrounded = [n for n in _numbers(written) if not _is_grounded(n, allowed)]
        if ungrounded:
            raise ValueError(
                f"ungrounded numbers: {ungrounded}. Use only numbers present in the result."
            )
        return self


@dataclass
class Turn:
    message: str
    plan_json: str | None  # None for clarify turns (their reason/JSON made the model repeat them)
    reply: str = ""  # what the user saw, so "yes" / "why?" have context
    summary: str = ""  # deterministic gist of the result (e.g. top hubs)
