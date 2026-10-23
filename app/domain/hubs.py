"""Hub registry: the closed set of locations the agent may talk about."""

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

Region = Literal["midwest", "south", "west", "northeast"]
STATE_NAMES = {
    "IL": "Illinois",
    "IN": "Indiana",
    "MI": "Michigan",
    "MN": "Minnesota",
    "MO": "Missouri",
    "KS": "Kansas",
    "FL": "Florida",
    "TX": "Texas",
    "GA": "Georgia",
    "TN": "Tennessee",
    "CO": "Colorado",
    "AZ": "Arizona",
    "WA": "Washington",
    "NJ": "New Jersey",
}


@dataclass(frozen=True)
class Hub:
    hub_id: str
    name: str
    state: str
    region: Region
    lat: float
    lon: float
    county_fips: str
    source_id: str
    aliases: tuple[str, ...] = ()

    @property
    def city(self) -> str:
        return self.name.split(" (")[0]


def normalize(mention: str) -> str:
    """Canonical lookup key. Exact match only: a wrong hub is worse than a clarifying question."""
    text = mention.lower().replace("_", " ")
    text = re.sub(r"[.,()]", " ", text)
    text = re.sub(r"'s\b|'", "", text)
    words = text.split()
    if words and words[0] == "the":
        words = words[1:]
    if words and words[-1] == "hub":
        words = words[:-1]
    return " ".join("saint" if w == "st" else w for w in words)


class HubRegistry:
    def __init__(self, hubs: list[Hub]):
        self._hubs = hubs
        self._by_id = {h.hub_id: h for h in hubs}
        self._index: dict[str, Hub] = {}
        for hub in hubs:
            for key in {hub.hub_id, hub.name, hub.city, *hub.aliases}:
                self._index[normalize(key)] = hub
                for state in (hub.state, STATE_NAMES.get(hub.state, hub.state)):
                    self._index[normalize(f"{key} {state}")] = hub  # "Name, ST" / "Name, State"

    @classmethod
    def from_json(cls, path: Path) -> "HubRegistry":
        rows = json.loads(Path(path).read_text())
        return cls([Hub(**{**r, "aliases": tuple(r.get("aliases", []))}) for r in rows])

    def all(self) -> list[Hub]:
        return list(self._hubs)

    def get(self, hub_id: str) -> Hub | None:
        return self._by_id.get(hub_id)

    def by_region(self, region: Region) -> list[Hub]:
        return [h for h in self._hubs if h.region == region]

    def resolve(self, mention: str) -> Hub | None:
        key = normalize(mention)
        return self._index.get(key) if key else None
