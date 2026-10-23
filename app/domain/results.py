"""Typed results of the deterministic tools — the only facts the LLM may narrate."""

from typing import Literal

from pydantic import BaseModel

from app.domain.hubs import Region
from app.domain.metrics import Aggregation, StatMetric
from app.domain.scoring import Hazard, HazardScore, HubScore, Label


class RankRow(BaseModel):
    rank: int
    hub_id: str
    name: str
    region: Region
    score: float
    label: Label  # composite bands applied to `score`
    top_drivers: list[Hazard]
    hazard_detail: HazardScore | None  # set when ranking by a single hazard
    flags: list[str]


class RankResult(BaseModel):
    kind: Literal["rank"] = "rank"
    hazard: Hazard | Literal["overall"]
    region: Region | None
    rows: list[RankRow]
    caveats: list[str]


class CompareResult(BaseModel):
    kind: Literal["compare"] = "compare"
    hazards: list[Hazard]
    hubs: list[HubScore]
    leaders: dict[str, str]  # hazard or "overall" → hub_id
    gaps: dict[str, float]  # hazard or "overall" → |max − min|
    caveats: list[str]


class StatResult(BaseModel):
    kind: Literal["stat"] = "stat"
    hub_id: str
    hub_name: str
    metric: StatMetric
    condition: str
    aggregation: Aggregation
    period_label: str
    value: float  # pct_of_days is a percentage 0–100
    matched_days: int  # days meeting the condition
    days_in_period: int
    days_with_data: int
    source: str
    caveats: list[str]


class PremiseCheck(BaseModel):
    asserted: Label
    actual: Label
    holds: bool


class ExplainResult(BaseModel):
    kind: Literal["explain"] = "explain"
    hub: HubScore
    total_hubs: int
    premise_check: PremiseCheck | None
    caveats: list[str]


class ScopeResult(BaseModel):
    kind: Literal["scope"] = "scope"
    reason: Literal["unknown_hub", "period_out_of_range", "too_few_hubs"]
    unknown: list[str]
    message: str
    supported_hubs: list[str]
    caveats: list[str] = []


Result = RankResult | CompareResult | StatResult | ExplainResult | ScopeResult
