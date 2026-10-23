"""Build data/nri_hubs.csv from FEMA's National Risk Index (run rarely, output is committed).

Fetches only STCOFIPS + annualized-frequency columns for ALL counties (national percentiles
need the whole country), then keeps the 15 hub counties. Usage: python -m scripts.build_nri_subset
"""

import csv
from collections.abc import Iterable
from pathlib import Path

import httpx

from app.config import get_settings
from app.domain.hubs import Hub, HubRegistry

NRI_URL = (
    "https://services.arcgis.com/XG15cJAlne2vxtgt/arcgis/rest/services/"
    "National_Risk_Index_Counties/FeatureServer/0/query"
)
NRI_CODES = ("WNTW", "ISTM", "CWAV", "HRCN", "IFLD", "CFLD", "HWAV", "TRND", "HAIL", "SWND")
OUT_PATH = Path("data/nri_hubs.csv")
FIELDS = ["hub_id", "county_fips", "hazard_code", "afreq", "national_pctl"]


def national_percentile(all_values: Iterable[float | None], value: float | None) -> float:
    """Share of counties strictly below `value` (no data = zero frequency)."""
    values = [v or 0.0 for v in all_values]
    target = value or 0.0
    return 100.0 * sum(v < target for v in values) / len(values)


def fetch_counties(client: httpx.Client) -> list[dict]:
    out_fields = ",".join(["STCOFIPS", *(f"{c}_AFREQ" for c in NRI_CODES)])
    rows: list[dict] = []
    while True:
        params = {
            "where": "1=1",
            "outFields": out_fields,
            "returnGeometry": "false",
            "f": "json",
            "resultOffset": len(rows),
            "resultRecordCount": 2000,
        }
        data = client.get(NRI_URL, params=params, timeout=60).raise_for_status().json()
        rows += [f["attributes"] for f in data["features"]]
        if not data.get("exceededTransferLimit"):
            return rows


def build_rows(
    hubs: list[Hub], counties: list[dict], codes: Iterable[str] = NRI_CODES
) -> list[dict]:
    by_fips = {c["STCOFIPS"]: c for c in counties}
    rows = []
    for hub in hubs:
        if hub.county_fips not in by_fips:
            raise KeyError(f"county {hub.county_fips} ({hub.hub_id}) not in NRI data")
        county = by_fips[hub.county_fips]
        for code in codes:
            afreq = county[f"{code}_AFREQ"]
            pctl = national_percentile((c[f"{code}_AFREQ"] for c in counties), afreq)
            rows.append(
                {
                    "hub_id": hub.hub_id,
                    "county_fips": hub.county_fips,
                    "hazard_code": code,
                    "afreq": afreq,
                    "national_pctl": round(pctl, 2),
                }
            )
    return rows


def main() -> None:
    hubs = HubRegistry.from_json(get_settings().hubs_path).all()
    with httpx.Client() as client:
        counties = fetch_counties(client)
    print(f"fetched {len(counties)} counties")
    rows = build_rows(hubs, counties)
    with OUT_PATH.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {len(rows)} rows to {OUT_PATH}")


if __name__ == "__main__":
    main()
