"""Deterministic scoring model — docs/02-scoring-model.md §2–5. Pure: no I/O."""

from datetime import date
from statistics import mean
from typing import Literal

from pydantic import BaseModel, model_validator

from app.domain.hubs import Hub, Region
from app.domain.metrics import (
    Condition,
    DailyWeather,
    WeatherField,
    annual_rate,
    coverage,
    filter_period,
)

Hazard = Literal["winter", "hurricane", "flood", "heat", "severe_storms"]
Label = Literal["low", "medium", "high"]


class MetricConfig(BaseModel):
    name: str
    field: WeatherField
    op: Literal[">=", "<="]
    threshold: float
    cap: float

    @property
    def condition(self) -> Condition:
        return Condition(self.field, self.op, self.threshold)


class HazardConfig(BaseModel):
    weight: float
    alpha: float
    nri: list[str]
    nri_agg: Literal["mean", "max"]
    metrics: list[MetricConfig] = []

    @model_validator(mode="after")
    def _observed_needs_metrics(self) -> "HazardConfig":
        if self.alpha > 0 and not self.metrics:
            raise ValueError("alpha > 0 requires at least one metric")
        return self


class ScoringConfig(BaseModel):
    version: str
    window_start: str
    window_end: str
    labels: dict[str, float]
    flags: dict[str, float]
    hazards: dict[Hazard, HazardConfig]

    @model_validator(mode="after")
    def _weights_sum_to_one(self) -> "ScoringConfig":
        if abs(sum(h.weight for h in self.hazards.values()) - 1.0) > 1e-6:
            raise ValueError("hazard weights must sum to 1")
        return self

    @property
    def expected_days(self) -> int:
        return (
            date.fromisoformat(self.window_end) - date.fromisoformat(self.window_start)
        ).days + 1

    @property
    def years(self) -> float:
        return round(self.expected_days / 365.25, 2)


class HazardScore(BaseModel):
    hazard: Hazard
    score: float
    observed_score: float | None  # 0–100 index from 2021–2025 data (None: NRI only)
    nri_score: float  # 0–100, aggregated FEMA NRI national percentiles
    weight: float
    alpha: float
    contribution: float
    observed_days_per_year: dict[str, float]  # metric name → average days per year
    nri_percentiles: dict[str, float]  # NRI hazard code → national percentile
    flags: list[str]


class HubScore(BaseModel):
    hub_id: str
    name: str
    region: Region
    composite: float
    label: Label
    peak_hazard: Hazard
    overall_rank: int  # 1 = highest composite among all hubs
    hazards: dict[Hazard, HazardScore]
    flags: list[str]


class ScoreBook(BaseModel):
    version: str
    hubs: dict[str, HubScore]

    def ranked(
        self,
        hazard: Hazard | None = None,
        hub_ids: list[str] | None = None,
        lowest_first: bool = False,
    ) -> list[HubScore]:
        pool = [h for h in self.hubs.values() if hub_ids is None or h.hub_id in hub_ids]

        def value(h: HubScore) -> float:
            return h.hazards[hazard].score if hazard else h.composite

        sign = 1 if lowest_first else -1  # ties always break by hub_id ascending
        return sorted(pool, key=lambda h: (sign * value(h), h.hub_id))


def label_for(score: float, labels: dict[str, float]) -> Label:
    if score >= labels["high"]:
        return "high"
    return "medium" if score >= labels["medium"] else "low"


def _observed(days: list[DailyWeather], cfg: HazardConfig, years: float) -> tuple[float, dict]:
    rates = {m.name: annual_rate(days, m.condition, years) for m in cfg.metrics}
    caps = {m.name: m.cap for m in cfg.metrics}
    return mean(100.0 * min(rates[n] / caps[n], 1.0) for n in rates), rates


def score_hazard(
    hazard: Hazard,
    days: list[DailyWeather],
    pctls: dict[str, float],
    cfg: HazardConfig,
    years: float,
    flags_cfg: dict[str, float],
    expected_days: int,
) -> HazardScore:
    nri_values = [pctls.get(code, 0.0) for code in cfg.nri]
    nri = max(nri_values) if cfg.nri_agg == "max" else mean(nri_values)
    flags = [] if any(code in pctls for code in cfg.nri) else ["nri_missing"]
    obs, rates = (None, {}) if cfg.alpha == 0 else _observed(days, cfg, years)
    if obs is None:
        score = nri
        flags.append("single_source")
    else:
        score = cfg.alpha * obs + (1 - cfg.alpha) * nri
        if abs(obs - nri) >= flags_cfg["disagree_threshold"]:
            flags.append("sources_disagree")
    fields: set[WeatherField] = {m.field for m in cfg.metrics}
    if any(coverage(days, f, expected_days) < flags_cfg["min_coverage"] for f in fields):
        flags.append("low_coverage")
    return HazardScore(
        hazard=hazard,
        score=score,
        observed_score=obs,
        nri_score=nri,
        weight=cfg.weight,
        alpha=cfg.alpha,
        contribution=cfg.weight * score,
        observed_days_per_year=rates,
        nri_percentiles={code: pctls.get(code, 0.0) for code in cfg.nri},
        flags=flags,
    )


def _score_hub(hub: Hub, days: list[DailyWeather], pctls: dict, cfg: ScoringConfig) -> HubScore:
    in_window = filter_period(days, cfg.window_start, cfg.window_end)
    hazards = {
        name: score_hazard(name, in_window, pctls, hcfg, cfg.years, cfg.flags, cfg.expected_days)
        for name, hcfg in cfg.hazards.items()
    }
    composite = sum(h.contribution for h in hazards.values())
    flags = sorted({f for h in hazards.values() for f in h.flags} | {"county_level"})
    return HubScore(
        hub_id=hub.hub_id,
        name=hub.name,
        region=hub.region,
        composite=composite,
        label=label_for(composite, cfg.labels),
        peak_hazard=max(hazards.values(), key=lambda h: h.score).hazard,
        overall_rank=0,
        hazards=hazards,
        flags=flags,
    )


def build_scorebook(
    hubs: list[Hub],
    daily: dict[str, list[DailyWeather]],
    nri: dict[str, dict[str, float]],
    cfg: ScoringConfig,
) -> ScoreBook:
    scores = {
        h.hub_id: _score_hub(h, daily.get(h.hub_id, []), nri.get(h.hub_id, {}), cfg) for h in hubs
    }
    book = ScoreBook(version=cfg.version, hubs=scores)
    for position, hub_score in enumerate(book.ranked(), start=1):
        hub_score.overall_rank = position
    return book
