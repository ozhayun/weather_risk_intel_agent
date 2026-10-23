"""Tool executors: validated arguments in, typed Result out. Pure over an in-memory context."""

from dataclasses import dataclass
from typing import Literal

from app.domain.hubs import Hub, HubRegistry, Region
from app.domain.metrics import (
    STAT_METRICS,
    Aggregation,
    DailyWeather,
    StatMetric,
    count_days,
    filter_period,
)
from app.domain.results import (
    CompareResult,
    ExplainResult,
    PremiseCheck,
    RankResult,
    RankRow,
    ScopeResult,
    StatResult,
)
from app.domain.scoring import Hazard, HubScore, Label, ScoreBook, ScoringConfig, label_for

Period = Literal["last_year", "full_window"] | int
WEATHER_SOURCE = "Open-Meteo Historical (ERA5 reanalysis, ~10 km grid)"
FLAG_CAVEATS = {
    "single_source": "Hurricane exposure uses FEMA NRI only (5 years of daily data can't show it).",
    "low_coverage": "Some daily weather values are missing for this hub.",
    "nri_missing": "FEMA NRI data is missing for this hub.",
}


@dataclass
class QueryContext:
    registry: HubRegistry
    book: ScoreBook
    daily: dict[str, list[DailyWeather]]
    cfg: ScoringConfig

    @property
    def window_label(self) -> str:
        return f"{self.cfg.window_start[:4]}–{self.cfg.window_end[:4]}"


def _scope(ctx: QueryContext, reason, message: str, unknown: list[str] | None = None):
    names = [h.name for h in ctx.registry.all()]
    return ScopeResult(
        reason=reason,
        unknown=unknown or [],
        supported_hubs=names,
        message=f"{message} I cover these {len(names)} hubs: {', '.join(names)}.",
    )


def _resolve(ctx: QueryContext, mentions: list[str]) -> tuple[list[Hub], ScopeResult | None]:
    resolved = [(m, ctx.registry.resolve(m)) for m in mentions]
    unknown = [m for m, hub in resolved if hub is None]
    if unknown:
        msg = f"I only know our hub locations, and {', '.join(unknown)} is not one of them."
        return [], _scope(ctx, "unknown_hub", msg, unknown)
    hubs = list({hub.hub_id: hub for _, hub in resolved}.values())  # dedupe, keep order
    return hubs, None


def _caveats(ctx: QueryContext, scores: list[HubScore], hazards: list[Hazard]) -> list[str]:
    caveats = [
        f"Based on {ctx.window_label} history; past exposure does not predict next year.",
        "FEMA NRI baselines are county-level, not facility-level.",
    ]
    for s in scores:
        for hz in hazards:
            for flag in s.hazards[hz].flags:
                text = FLAG_CAVEATS.get(flag)
                if flag == "sources_disagree":
                    text = f"{s.name} {hz}: recent observations and the NRI baseline disagree."
                if text and text not in caveats:
                    caveats.append(text)
    return caveats


def _drivers(score: HubScore) -> list[Hazard]:
    ordered = sorted(score.hazards.values(), key=lambda h: (-h.contribution, h.hazard))
    return [h.hazard for h in ordered[:2]]


def rank_hubs(
    ctx: QueryContext,
    hazard: Hazard | Literal["overall"] = "overall",
    region: Region | None = None,
    hubs: list[str] | None = None,
    top_n: int | None = None,
) -> RankResult | ScopeResult:
    named, scope = _resolve(ctx, hubs or [])
    if scope:
        return scope
    pool = named or ctx.registry.all()
    ids = [h.hub_id for h in pool if region is None or h.region == region]
    key = None if hazard == "overall" else hazard
    ranked = ctx.book.ranked(key, hub_ids=ids)[: top_n or None]
    rows = []
    for position, s in enumerate(ranked, start=1):
        value = s.composite if key is None else s.hazards[key].score
        rows.append(
            RankRow(
                rank=position,
                hub_id=s.hub_id,
                name=s.name,
                region=s.region,
                score=value,
                label=label_for(value, ctx.cfg.labels),
                top_drivers=_drivers(s),
                hazard_detail=None if key is None else s.hazards[key],
                flags=s.flags,
            )
        )
    in_scope = list(ctx.cfg.hazards) if key is None else [key]
    return RankResult(
        hazard=hazard, region=region, rows=rows, caveats=_caveats(ctx, ranked, in_scope)
    )


def compare_hubs(
    ctx: QueryContext, hubs: list[str], hazards: list[Hazard] | None = None
) -> CompareResult | ScopeResult:
    resolved, scope = _resolve(ctx, hubs)
    if scope:
        return scope
    if len(resolved) < 2:
        return _scope(ctx, "too_few_hubs", "A comparison needs at least two different hubs.")
    scores = [ctx.book.hubs[h.hub_id] for h in resolved]
    chosen = list(dict.fromkeys(hazards or ctx.cfg.hazards))
    leaders, gaps = {}, {}
    for key in [*chosen, "overall"]:
        values = {
            s.hub_id: s.composite if key == "overall" else s.hazards[key].score for s in scores
        }
        leaders[key] = max(values, key=lambda hub_id: (values[hub_id], hub_id))
        gaps[key] = max(values.values()) - min(values.values())
    return CompareResult(
        hazards=chosen,
        hubs=scores,
        leaders=leaders,
        gaps=gaps,
        caveats=_caveats(ctx, scores, chosen),
    )


def _period_bounds(ctx: QueryContext, period: Period) -> tuple[str, str, str, float] | None:
    """(start, end, label, years) or None when outside the dataset window."""
    first, last = int(ctx.cfg.window_start[:4]), int(ctx.cfg.window_end[:4])
    if period == "full_window":
        return ctx.cfg.window_start, ctx.cfg.window_end, ctx.window_label, ctx.cfg.years
    year = last if period == "last_year" else period
    if not first <= year <= last:
        return None
    return f"{year}-01-01", f"{year}-12-31", str(year), 1.0


def get_weather_stat(
    ctx: QueryContext, hub: str, metric: StatMetric, aggregation: Aggregation, period: Period
) -> StatResult | ScopeResult:
    resolved, scope = _resolve(ctx, [hub])
    if scope:
        return scope
    bounds = _period_bounds(ctx, period)
    if bounds is None:
        return _scope(
            ctx,
            "period_out_of_range",
            f"I only have weather data for {ctx.window_label}, not {period}.",
        )
    start, end, label, years = bounds
    days = filter_period(ctx.daily.get(resolved[0].hub_id, []), start, end)
    cond = STAT_METRICS[metric]
    matched, with_data = count_days(days, cond)
    value = {
        "count": float(matched),
        "pct_of_days": 100.0 * matched / with_data if with_data else 0.0,
        "per_year_avg": matched / years,
    }[aggregation]
    caveats = ["Reanalysis data: snowfall and gusts are modeled at ~10 km, not station-measured."]
    if with_data < len(days) or not days:
        caveats.append(f"Only {with_data} of {len(days)} days have data for this metric.")
    return StatResult(
        hub_id=resolved[0].hub_id,
        hub_name=resolved[0].name,
        metric=metric,
        condition=cond.describe(),
        aggregation=aggregation,
        period_label=label,
        value=round(value, 2),
        days_total=len(days),
        days_with_data=with_data,
        source=WEATHER_SOURCE,
        caveats=caveats,
    )


def explain_hub(
    ctx: QueryContext, hub: str, asserted_level: Label | None = None
) -> ExplainResult | ScopeResult:
    resolved, scope = _resolve(ctx, [hub])
    if scope:
        return scope
    score = ctx.book.hubs[resolved[0].hub_id]
    check = None
    if asserted_level is not None:
        check = PremiseCheck(
            asserted=asserted_level, actual=score.label, holds=asserted_level == score.label
        )
    return ExplainResult(
        hub=score,
        total_hubs=len(ctx.book.hubs),
        premise_check=check,
        caveats=_caveats(ctx, [score], list(ctx.cfg.hazards)),
    )
