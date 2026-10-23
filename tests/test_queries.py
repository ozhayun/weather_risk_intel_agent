import pytest

from app.domain.queries import compare_hubs, explain_hub, get_weather_stat, rank_hubs


def test_rank_region_filters_and_sorts(ctx):
    r = rank_hubs(ctx, hazard="winter", region="midwest")
    assert r.kind == "rank"
    assert [row.hub_id for row in r.rows] == ["a", "b"]
    assert r.rows[0].score >= r.rows[1].score
    assert r.rows[0].hazard_detail.observed_days_per_year["snow_days"] > 0


def test_rank_overall_uses_composite_and_drivers(ctx):
    r = rank_hubs(ctx)
    assert [row.rank for row in r.rows] == [1, 2, 3]
    assert r.rows[0].score == pytest.approx(ctx.book.hubs["a"].composite)
    assert len(r.rows[0].top_drivers) == 2
    assert r.rows[0].hazard_detail is None


def test_rank_top_n(ctx):
    assert len(rank_hubs(ctx, top_n=1).rows) == 1
    assert len(rank_hubs(ctx, top_n=50).rows) == 3


def test_rank_named_hubs_with_unknown_is_scope(ctx):
    r = rank_hubs(ctx, hubs=["Alpha", "Atlantis"])
    assert r.kind == "scope" and r.unknown == ["Atlantis"]


def test_rank_named_hubs_subset(ctx):
    assert [row.hub_id for row in rank_hubs(ctx, hubs=["gamma", "beta"]).rows] == ["b", "c"]


def test_rank_caveats_always_mention_window(ctx):
    assert any("2025" in c for c in rank_hubs(ctx).caveats)


def test_rank_by_hazard_only_reports_that_hazards_flags(ctx):
    caveats = " ".join(rank_hubs(ctx, hazard="winter").caveats)
    assert "NRI only" not in caveats  # single_source belongs to hurricane


def test_compare_two_hubs_leaders_and_gaps(ctx):
    r = compare_hubs(ctx, ["Alpha", "Beta"], ["winter", "hurricane"])
    assert r.kind == "compare"
    assert r.leaders["winter"] == "a" and r.leaders["overall"] == "a"
    a, b = ctx.book.hubs["a"], ctx.book.hubs["b"]
    assert r.gaps["hurricane"] == pytest.approx(
        abs(a.hazards["hurricane"].score - b.hazards["hurricane"].score)
    )


def test_compare_defaults_to_all_hazards(ctx):
    assert compare_hubs(ctx, ["a", "b"]).hazards == ["winter", "hurricane"]


def test_compare_with_unknown_hub_is_scope(ctx):
    r = compare_hubs(ctx, ["Alpha", "Tokyo"])
    assert r.kind == "scope" and r.reason == "unknown_hub"
    assert r.unknown == ["Tokyo"]
    assert "Tokyo" in r.message and "Alpha" in r.message


def test_compare_single_hub_is_scope(ctx):
    assert compare_hubs(ctx, ["Alpha"]).reason == "too_few_hubs"


def test_compare_duplicate_hub_is_scope(ctx):
    assert compare_hubs(ctx, ["Alpha", "alpha town"]).reason == "too_few_hubs"


def test_stat_pct_of_days(ctx):
    r = get_weather_stat(ctx, "Alpha", "snow_day", "pct_of_days", 2025)
    assert r.kind == "stat"
    assert r.value == 20.0 and r.matched_days == 2
    assert r.days_in_period == 10 and r.days_with_data == 10
    assert r.condition == "snowfall_cm >= 0.1"


def test_stat_count_and_per_year(ctx):
    assert get_weather_stat(ctx, "a", "snow_day", "count", "full_window").value == 2
    assert get_weather_stat(ctx, "a", "snow_day", "per_year_avg", 2025).value == 2


def test_stat_last_year_maps_to_window_end_year(ctx):
    r = get_weather_stat(ctx, "a", "snow_day", "count", "last_year")
    assert r.period_label == "2025"


@pytest.mark.parametrize("year", [2019, 2024, 2026])
def test_stat_year_out_of_range(ctx, year):
    r = get_weather_stat(ctx, "a", "snow_day", "count", year)
    assert r.kind == "scope" and r.reason == "period_out_of_range"


def test_stat_unknown_hub(ctx):
    assert get_weather_stat(ctx, "Boston", "snow_day", "count", 2025).reason == "unknown_hub"


def test_explain_premise_check(ctx):
    r = explain_hub(ctx, "Beta", asserted_level="high")
    assert r.kind == "explain"
    assert r.premise_check.holds is False and r.premise_check.actual == "medium"
    assert r.total_hubs == 3


def test_explain_premise_holds(ctx):
    assert explain_hub(ctx, "Alpha", asserted_level="high").premise_check.holds is True


def test_explain_without_premise(ctx):
    assert explain_hub(ctx, "c").premise_check is None


def test_explain_unknown_hub(ctx):
    assert explain_hub(ctx, "Springfield").kind == "scope"


def test_rank_non_positive_top_n_returns_all(ctx):
    assert len(rank_hubs(ctx, top_n=-1).rows) == 3


def test_hazard_ranking_rows_have_no_composite_label(ctx):
    assert all(row.label is None for row in rank_hubs(ctx, hazard="winter").rows)
    assert all(row.label is not None for row in rank_hubs(ctx).rows)


def test_rank_lowest_sorts_ascending(ctx):
    r = rank_hubs(ctx, order="lowest")
    assert r.order == "lowest"
    assert [row.hub_id for row in r.rows] == ["c", "b", "a"]
    assert [row.rank for row in r.rows] == [1, 2, 3]  # position in this (ascending) list


def test_rank_lowest_with_hazard_region_and_top_n(ctx):
    r = rank_hubs(ctx, hazard="winter", region="midwest", top_n=1, order="lowest")
    assert [row.hub_id for row in r.rows] == ["b"]


def test_rank_default_order_is_highest(ctx):
    assert rank_hubs(ctx).order == "highest"


def test_period_scope_message_offers_the_window_not_the_hub_list(ctx):
    r = get_weather_stat(ctx, "Alpha", "snow_day", "count", 2018)
    assert "2025" in r.message and "not 2018" in r.message
    assert "Gamma" not in r.message  # hub list only belongs to unknown-hub messages


def test_unknown_hub_scope_message_still_lists_hubs(ctx):
    assert "Gamma" in get_weather_stat(ctx, "Boston", "snow_day", "count", 2025).message


def test_hazard_premise_is_judged_by_that_hazards_rank(ctx):
    # Gamma: lowest winter score of 3 hubs → rank 3/3 → "low" for winter
    r = explain_hub(ctx, "Gamma", asserted_level="high", hazard="winter")
    assert r.premise_check.hazard == "winter"
    assert r.premise_check.holds is False and r.premise_check.actual == "low"
    assert (r.premise_check.rank, r.premise_check.total) == (3, 3)
    assert r.focus_hazard == "winter"


def test_hazard_premise_holds_for_top_ranked_hub(ctx):
    check = explain_hub(ctx, "Alpha", asserted_level="high", hazard="winter").premise_check
    assert check.holds is True and check.rank == 1


def test_overall_premise_still_uses_composite_label(ctx):
    check = explain_hub(ctx, "Beta", asserted_level="high").premise_check
    assert check.hazard is None and check.actual == "medium" and check.rank == 2
