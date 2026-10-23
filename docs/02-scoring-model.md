# 02 — Deterministic Scoring Model

_status: agreed design, thresholds provisional until first full ingest · 2026-10-23_

All scoring is pure Python over stored data. Given the same inputs (SQLite data plus `config/scoring.toml`), the output is always the same. The LLM never computes or changes a score.

## 1. Inputs

| Source | Granularity | Window | Used for |
|---|---|---|---|
| **Open-Meteo Historical** (ERA5 reanalysis) | Daily, at the hub city's coordinates | 2021-01-01 → 2025-12-31 (5 years) | Observed component (`OBS`) and raw stats (Q3) |
| **FEMA NRI** (static subset in the repo) | County containing the hub | Long-term (NRI's own record) | Baseline component (`NRI`) |

Daily variables: `snowfall_sum` (cm), `precipitation_sum` (mm), `temperature_2m_max` / `temperature_2m_min` (°C), `apparent_temperature_max` (°C), `wind_gusts_10m_max` (km/h).

> Verified while probing: the archive's `weather_code` never contains freezing-rain (56/57/66/67) or thunderstorm (95–99) codes, so ice storms, tornadoes and hail come from NRI only.

### NRI static subset

- **Full dataset:** 3,232 counties × 467 columns. We don't download it.
- **Build script:** `scripts/build_nri_subset.py` queries FEMA's public ArcGIS FeatureServer (`National_Risk_Index_Counties`). It fetches **only** `STCOFIPS` plus the 10 `*_AFREQ` columns for **all** counties, because a national percentile needs the whole country.
- **Output:** `data/nri_hubs.csv`, 15 rows (a few KB) with the percentiles below plus source URL and retrieval date. This file is committed, so runtime never calls FEMA.

| Hub county FIPS | | |
|---|---|---|
| Chicago (Wheeling) → Cook 17031 | Indianapolis → Marion 18097 | Detroit → Wayne 26163 |
| Minneapolis → Hennepin 27053 | St. Louis → St. Louis city 29510 | Kansas City → Wyandotte 20209 |
| Miami → Miami-Dade 12086 | Houston → Harris 48201 | Dallas → Dallas 48113 |
| Atlanta → Fulton 13121 | Memphis → Shelby 47157 | Denver → Denver 08031 |
| Phoenix → Maricopa 04013 | Seattle → King 53033 | Newark → Essex 34013 |

## 2. Formula

### 2.1 Observed metric score (per hub, per metric `m`)

```
rate_m  = (# days in window meeting condition_m) / 5            # days per year
s_m     = 100 · min(rate_m / cap_m, 1)                          # 0–100
OBS_h   = mean(s_m  for m in obs_metrics(h))
```

The caps are **absolute** values, not the min/max across hubs. This has three benefits:
- Adding or removing a hub doesn't change anyone else's score.
- A score of 100 means "at or beyond the severe-exposure cap", which is easy to interpret.
- Alerts only fire when the *data* changes.

### 2.2 NRI baseline score (per hub, per NRI hazard `k`)

```
p_k   = 100 · |{counties c : AFREQ_k(c) < AFREQ_k(hub_county)}| / 3232    # national percentile
NRI_h = agg_h(p_k  for k in nri_hazards(h))
```

- **Frequency (`AFREQ`), not NRI's risk score or expected-loss score.** NRI's risk score includes social vulnerability, and its expected-loss score grows with the county's building value. Neither describes how exposed a *facility* is.
- **Strict `<` percentile.** For example, 83% of counties have zero coastal-flood frequency. With strict `<`, an inland county scores 0 for coastal flood instead of 83.

### 2.3 Hazard sub-score and composite

```
H_h = α_h · OBS_h + (1 − α_h) · NRI_h                 # 0–100
R   = Σ_h  w_h · H_h                                  # composite disruption risk, 0–100
c_h = w_h · H_h                                       # contribution; Σ c_h = R exactly
```

A weighted *mean* keeps the explanation additive: "flood contributes 21 of Dallas's 61 points." The hazard with the highest `H_h` is also returned as `peak_hazard`, so a single dominant hazard isn't hidden.

## 3. Hazard definitions (provisional values in `config/scoring.toml`)

| Hazard `h` | Weight `w_h` | `α_h` (obs share) | Observed metrics (condition → cap, days/yr) | NRI hazards → agg |
|---|---|---|---|---|
| **Winter** | 0.20 | 0.6 | snow ≥ 1 cm → 30; tmin ≤ −18 °C → 30 | WNTW, ISTM, CWAV → mean |
| **Hurricane** | 0.25 | 0.0 | — (5 years of point data can't capture it) | HRCN → single |
| **Flood** | 0.25 | 0.4 | precip ≥ 25 mm → 15; precip ≥ 50 mm → 5 | IFLD, CFLD → **max** |
| **Heat** | 0.10 | 0.6 | tmax ≥ 35 °C → 120; apparent tmax ≥ 40 °C → 60 | HWAV → single |
| **Severe storms** | 0.20 | 0.3 | gust ≥ 75 km/h → 5 | TRND, HAIL, SWND → mean |

How these were chosen:
- **Weights:** a business assumption about how long each hazard typically shuts a hub down. Hurricanes and floods can close a hub for days; heat mostly slows work rather than stopping it.
- **`α`:** how well 5 years of daily data at one point captures the hazard. Snow and heat show up well; tornadoes and hail don't show up in the data at all; flooding depends on terrain as much as rain.
- **`max` for flood:** inland and coastal flooding are alternative ways the same hub can flood, so a mean would wrongly halve an inland hub's flood score.
- **Caps:** set from a 5-year probe of the sample hubs (for example, Phoenix has 137 days/yr ≥ 35 °C, Minneapolis 26 days/yr ≤ −18 °C, Houston 4.2 days/yr ≥ 50 mm). They're tuned once after the full ingest and then **frozen**. Any change bumps `scoring.version`.

## 4. Labels

| Label | Composite `R` |
|---|---|
| low | `R < 35` |
| medium | `35 ≤ R < 55` |
| high | `R ≥ 55` |

These bands are provisional. A hand-worked estimate from the probe data gives Dallas ≈ 61 (high), Houston ≈ 62 (high), Miami ≈ 56 (high), Minneapolis ≈ 43 (medium) and Seattle ≈ 23 (low). We'll re-check after the real ingest.

Ranking for Q1 sorts by `H_h` for the requested hazard, or by `R` for overall. Ties are broken by `hub_id`.
Values are stored at full precision and rounded to 1 decimal only for display.

## 5. Uncertainty flags (computed, then passed to the LLM)

| Flag | Rule |
|---|---|
| `low_coverage` | Fewer than 98% of days in the window have a non-null value for the metric's variable |
| `sources_disagree` | `α_h > 0` and `|OBS_h − NRI_h| ≥ 40`. Example: Seattle winter, where King County includes the Cascades (NRI winter 96th percentile vs. little snow in the city) |
| `single_source` | `α_h = 0` (hurricane) |
| `county_level` | Always attached to NRI: the score describes the whole county, not the facility |

## 6. Raw stats catalog (Q3)

Q3 answers are computed directly from `daily_weather`. The LLM only *picks* a metric from this catalog (an enum in the schema).

| Metric | Condition |
|---|---|
| `snow_day` | snowfall ≥ 0.1 cm (any measurable snow; scoring uses ≥ 1 cm to drop trace amounts) |
| `heavy_snow_day` | snowfall ≥ 10 cm |
| `freezing_day` | tmin ≤ 0 °C |
| `extreme_cold_day` | tmin ≤ −18 °C |
| `rain_day` | precip ≥ 1 mm |
| `heavy_rain_day` | precip ≥ 25 mm |
| `hot_day` | tmax ≥ 35 °C |
| `dangerous_heat_day` | apparent tmax ≥ 40 °C |
| `high_wind_day` | gust ≥ 75 km/h |

- **Aggregations:** `count`, `pct_of_days`, `per_year_avg`.
- **Time ranges:** a single year (2021–2025) or the full window.
- **Every result includes:** the condition, `days_total`, `days_with_data`, and the source.
- **Probe example:** Denver 2025, `snow_day`, `pct_of_days` → **10.1%**.

## 7. Score snapshots and alerts (bonus)

- Each scoring run writes one `score_snapshots` row per hub: `run_at`, window, `scoring_version`, `R`, every `H_h`, `OBS_h`, `NRI_h`.
- An alert fires when the **label changes** or `|ΔR| ≥ 5` compared with the previous snapshot of the same hub.
- Real-world triggers: the window rolls forward (each January), NRI publishes a new release, or the scoring config version changes. The alert message names the cause.

## 8. Known limitations

- ERA5 is a ~10 km model grid. Snowfall and gusts are modeled, not measured, and gusts tend to be underestimated.
- NRI is county-level, so large counties like Maricopa and King blur conditions at the facility.
- History doesn't predict the future: this ranks *exposure*, not the probability of next year's losses.
- Weights, `α` values and caps are documented assumptions. Analysts can change them in `config/scoring.toml`.
- Open-Meteo rate-limits: a burst of 7 requests got `429` during the probe. Ingest throttles and retries, and caches everything in SQLite once.
