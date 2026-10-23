from pathlib import Path

import pytest

from app.domain.hubs import HubRegistry

REG = HubRegistry.from_json(Path("data/hubs.json"))


@pytest.mark.parametrize(
    "mention,hub_id",
    [
        ("chicago", "chicago"),
        ("Wheeling", "chicago"),
        ("  DALLAS ", "dallas"),
        ("St Louis", "st_louis"),
        ("saint louis", "st_louis"),
        ("St. Louis", "st_louis"),
        ("KC", "kansas_city"),
        ("Chicago hub", "chicago"),
        ("the Dallas hub", "dallas"),
        ("Dallas-Fort Worth", "dallas"),
        ("Dallas, TX", "dallas"),
        ("Dallas's", "dallas"),
        ("the Dallas hub's", "dallas"),
        ("st_louis", "st_louis"),
        ("Chicago (Wheeling)", "chicago"),
    ],
)
def test_resolve_variants(mention, hub_id):
    hub = REG.resolve(mention)
    assert hub is not None and hub.hub_id == hub_id


@pytest.mark.parametrize("mention", ["Tokyo", "Springfield", "", "   ", "Fort Worth", "hub"])
def test_resolve_unknown_returns_none(mention):
    assert REG.resolve(mention) is None


def test_by_region_midwest():
    assert len(REG.by_region("midwest")) == 6


def test_all_and_get():
    assert len(REG.all()) == 15
    assert REG.get("miami").state == "FL"
    assert REG.get("tokyo") is None
