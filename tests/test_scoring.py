import pytest
from pydantic import ValidationError

from app.config import load_scoring_config
from app.domain.hubs import Hub
from app.domain.metrics import DailyWeather
from app.domain.scoring import (
    HazardConfig,
    ScoringConfig,
    build_scorebook,
    label_for,
    score_hazard,
)

LABELS = {"medium": 35.0, "high": 55.0}
FLAGS = {"disagree_threshold": 40.0, "min_coverage": 0.98}


def snow_cfg(alpha=0.6, cap=30.0, nri=("WNTW",), agg="mean", weight=0.5):
    return HazardConfig.model_validate(
        {
            "weight": weight,
            "alpha": alpha,
            "nri": list(nri),
            "nri_agg": agg,
            "metrics": []
            if alpha == 0
            else [
                {
                    "name": "snow_days",
                    "field": "snowfall_cm",
                    "op": ">=",
                    "threshold": 1.0,
                    "cap": cap,
                }
            ],
        }
    )


def days_with_snow(n_snow, total=10, start_year=2025):
    return [
        DailyWeather(f"{start_year}-01-{i + 1:02d}", 5.0 if i < n_snow else 0.0, 0, 0, 0, 0, 0)
        for i in range(total)
    ]


def score(cfg, days, pctls, years=1.0, expected=10):
    return score_hazard("winter", days, pctls, cfg, years, FLAGS, expected)


def test_metric_score_caps_at_100():
    h = score(snow_cfg(cap=3.0), days_with_snow(6), {"WNTW": 0.0})
    assert h.observed_score == 100.0
    assert h.observed_days_per_year == {"snow_days": 6.0}


def test_hazard_blend():
    h = score(snow_cfg(alpha=0.6, cap=10.0), days_with_snow(5), {"WNTW": 80.0})
    assert h.observed_score == 50.0
    assert h.score == pytest.approx(0.6 * 50 + 0.4 * 80)
    assert h.contribution == pytest.approx(0.5 * h.score)


def test_flood_uses_max_nri():
    cfg = snow_cfg(nri=("IFLD", "CFLD"), agg="max")
    assert score(cfg, days_with_snow(0), {"IFLD": 98.0, "CFLD": 0.0}).nri_score == 98.0


def test_mean_nri_treats_missing_code_as_zero():
    cfg = snow_cfg(nri=("WNTW", "ISTM"))
    assert score(cfg, days_with_snow(0), {"WNTW": 60.0}).nri_score == 30.0


def test_alpha_zero_single_source():
    h = score(snow_cfg(alpha=0.0, nri=("HRCN",)), days_with_snow(10), {"HRCN": 91.0})
    assert h.observed_score is None
    assert h.score == 91.0
    assert "single_source" in h.flags


def test_sources_disagree_flag():
    h = score(snow_cfg(cap=200.0), days_with_snow(10), {"WNTW": 96.0})  # obs 5
    assert "sources_disagree" in h.flags


def test_low_coverage_flag():
    days = days_with_snow(2)[:5]  # 5 of 10 expected days present
    assert "low_coverage" in score(snow_cfg(), days, {"WNTW": 1.0}).flags


def test_nri_missing_flag():
    assert "nri_missing" in score(snow_cfg(), days_with_snow(1), {}).flags


@pytest.mark.parametrize(
    "r,label", [(0.0, "low"), (34.99, "low"), (35.0, "medium"), (54.99, "medium"), (55.0, "high")]
)
def test_label_bands(r, label):
    assert label_for(r, LABELS) == label


def make_config(**over):
    raw = {
        "version": "t",
        "window_start": "2025-01-01",
        "window_end": "2025-01-10",
        "labels": LABELS,
        "flags": FLAGS,
        "hazards": {
            "winter": snow_cfg(weight=0.5).model_dump(),
            "hurricane": snow_cfg(alpha=0.0, nri=("HRCN",), weight=0.5).model_dump(),
        },
    }
    return ScoringConfig.model_validate({**raw, **over})


def hub(hub_id, region="midwest"):
    return Hub(hub_id, hub_id.title(), "XX", region, 0, 0, "00000", "x")


def test_config_weights_must_sum_to_one():
    bad = make_config().model_dump()
    bad["hazards"]["winter"]["weight"] = 0.9
    with pytest.raises(ValidationError, match="sum to 1"):
        ScoringConfig.model_validate(bad)


def test_config_observed_hazard_needs_metrics():
    with pytest.raises(ValidationError):
        HazardConfig.model_validate({"weight": 1, "alpha": 0.5, "nri": ["X"], "nri_agg": "mean"})


def test_config_years():
    assert load_scoring_config().years == 5.0
    assert load_scoring_config().expected_days == 1826


def test_contributions_sum_to_composite():
    book = build_scorebook(
        [hub("a")], {"a": days_with_snow(3)}, {"a": {"WNTW": 50.0, "HRCN": 90.0}}, make_config()
    )
    h = book.hubs["a"]
    assert sum(x.contribution for x in h.hazards.values()) == pytest.approx(h.composite)
    assert h.peak_hazard == "hurricane"
    assert h.overall_rank == 1
    assert "county_level" in h.flags and "single_source" in h.flags


def test_scorebook_ignores_days_outside_window():
    days = days_with_snow(3) + days_with_snow(10, start_year=2024)
    book_a = build_scorebook([hub("a")], {"a": days}, {"a": {}}, make_config())
    book_b = build_scorebook([hub("a")], {"a": days_with_snow(3)}, {"a": {}}, make_config())
    assert book_a.hubs["a"].composite == book_b.hubs["a"].composite


def test_hub_without_daily_data_is_flagged_not_crashing():
    book = build_scorebook([hub("a")], {}, {"a": {"WNTW": 50.0}}, make_config())
    assert "low_coverage" in book.hubs["a"].flags


def test_ranked_tie_breaks_by_hub_id():
    nri = {"WNTW": 50.0, "HRCN": 50.0}
    book = build_scorebook(
        [hub("b"), hub("a"), hub("c")],
        {k: days_with_snow(0) for k in "abc"},
        {"a": nri, "b": nri, "c": {"WNTW": 90.0, "HRCN": 90.0}},
        make_config(),
    )
    assert [h.hub_id for h in book.ranked()] == ["c", "a", "b"]
    assert [h.overall_rank for h in book.ranked()] == [1, 2, 3]
    assert [h.hub_id for h in book.ranked("winter", hub_ids=["a", "b"])] == ["a", "b"]


def test_real_config_loads():
    cfg = load_scoring_config()
    assert cfg.hazards["flood"].nri_agg == "max"
    assert set(cfg.hazards) == {"winter", "hurricane", "flood", "heat", "severe_storms"}
