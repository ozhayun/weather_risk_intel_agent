# Weather Risk Intelligence Agent — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Status: executed.** All 14 tasks are done. Later changes came from review findings and manual testing (UI polish, prompt-injection safety, follow-up and premise fixes, lowest-risk rankings); each one is a merged PR with its own tests. The current design is `docs/03-architecture.md`.

**Goal:** A local, runnable agent that ranks, compares and explains weather-disruption exposure for 15 US hubs. It has a FastAPI backend, a Streamlit chat UI, deterministic scoring and a pytest eval set.

**Architecture:**
- Offline scripts build a static dataset: Open-Meteo 2021–2025 into SQLite, plus a FEMA NRI subset CSV.
- At API startup a pure `domain/` layer computes a `ScoreBook` in memory.
- The agent is a fixed pipeline: LLM → `QueryPlan` (Pydantic discriminated union) → deterministic executor → LLM → `Answer`. A number-grounding validator checks the answer.

**Tech Stack:** Python 3.12, uv, FastAPI, Pydantic v2, pydantic-settings, Instructor (+ openai SDK), httpx, Streamlit, SQLite (stdlib), pytest, ruff.

**Spec:** `docs/01-requirements.md`, `docs/02-scoring-model.md`, `docs/03-architecture.md`, `CLAUDE.md`

## Global Constraints

- Python `>=3.12`; dependencies managed with `uv`; lint and format with `ruff`.
- `LLM_MODEL` default `openai/gpt-4o-mini`, read from `.env`. The provider is switched only through this string (`instructor.from_provider`).
- Scoring window `2021-01-01` → `2025-12-31` (5 years, 1826 days). `last_year` = `2025`.
- Dependency direction: `api → agent → domain ← data`. `app/domain/` does no I/O.
- The LLM never produces numbers or rankings. Every LLM call uses a `response_model` and `max_retries=2`.
- Weights, alphas, caps, label bands and flag thresholds live only in `config/scoring.toml` (values from `02-scoring-model.md` §3–5).
- Modules stay under ~200 lines and functions under ~30 lines. Code is fully typed.
- Tests never touch the network or a real LLM, except the `eval` marker. `pytest` defaults to `-m "not eval"`.
- Git:
  - one branch per task group (named in each group header)
  - a Conventional Commit after every task
  - push, then `gh pr create`, then `gh pr merge --merge --delete-branch`
  - every commit ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`

## Review Focus

1. **Hub mention variants** ("St Louis", "saint louis", "KC", "Chicago hub", "the Dallas hub") must resolve. Pinned in Task 2 (`test_resolve_variants`).
2. **Mixed valid and invalid hubs** ("Compare Miami and Tokyo") must return a scope message naming `Tokyo`, never silently compare a single hub. Pinned in Task 8 (`test_compare_with_unknown_hub_is_scope`).
3. **Years outside the window** (2019, or "this year" = 2026) must return a `ScopeResult`, not an error or an empty stat. Pinned in Task 8 (`test_stat_year_out_of_range`).
4. **Null daily values** must be excluded from counts and lower coverage, which raises `low_coverage` below 0.98. Pinned in Task 5 (`test_count_days_ignores_nulls`) and Task 6 (`test_low_coverage_flag`).
5. **Harmless numbers in the narration** ("5 years", "2025", "top 3") must not fail grounding; invented scores must. Pinned in Task 9 (`test_grounding_allows_years_and_small_ints`, `test_grounding_rejects_invented_score`).

---

## Group A — `feat/project-setup`

### Task 1: Project skeleton, config and hub registry data

**Files:**
- Create: `pyproject.toml`, `app/__init__.py` (and an empty `__init__.py` in `app/domain`, `app/data`, `app/agent`, `app/api`), `scripts/__init__.py`, `tests/__init__.py`
- Create: `app/config.py`, `config/scoring.toml`, `data/hubs.json`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces:
  - `Settings` (pydantic-settings, reads `.env`): `llm_model: str = "openai/gpt-4o-mini"`, `db_path: Path = Path("data/weather.db")`, `api_url: str = "http://localhost:8000"`
  - `get_settings() -> Settings` (cached)
  - `load_scoring_config(path: Path = Path("config/scoring.toml")) -> ScoringConfig`. `ScoringConfig` is defined in Task 6; until then this function returns the raw dict from `tomllib`, and Task 6 switches it to `ScoringConfig.model_validate`.

**Dependencies:**
- Runtime: `fastapi`, `uvicorn[standard]`, `pydantic>=2`, `pydantic-settings`, `instructor`, `openai`, `httpx`, `streamlit`
- Dev: `pytest`, `ruff`
- `[tool.pytest.ini_options]`: `addopts = "-m 'not eval'"`, `markers = ["eval: runs the real LLM"]`
- `[tool.ruff]`: `line-length = 100`

**`config/scoring.toml`:**
- `version = "1.0"`
- `window_start = "2021-01-01"`, `window_end = "2025-12-31"`
- `[labels] medium = 35.0, high = 55.0`
- `[flags] disagree_threshold = 40.0, min_coverage = 0.98`
- `[hazards.<name>]` for each of `winter, hurricane, flood, heat, severe_storms`, with `weight`, `alpha`, `nri = [...]`, `nri_agg = "mean" | "max"`, and `[[hazards.<name>.metrics]]` entries (`name, field, op, threshold, cap`). Values are exactly the table in `02-scoring-model.md` §3:

  | Hazard | Metrics |
  |---|---|
  | winter | `snow_days` (`snowfall_cm >= 1.0`, cap 30); `extreme_cold_days` (`tmin_c <= -18.0`, cap 30) |
  | hurricane | none (`alpha = 0.0`) |
  | flood | `heavy_rain_days` (`precip_mm >= 25`, cap 15); `very_heavy_rain_days` (`precip_mm >= 50`, cap 5) |
  | heat | `hot_days` (`tmax_c >= 35`, cap 120); `dangerous_heat_days` (`apparent_tmax_c >= 40`, cap 60) |
  | severe_storms | `high_wind_days` (`gust_max_kmh >= 75`, cap 5) |

**`data/hubs.json`:** a list of `{hub_id, name, state, region, lat, lon, county_fips, source_id, aliases}`.

| hub_id | name | state | region | lat | lon | county_fips | aliases |
|---|---|---|---|---|---|---|---|
| chicago | Chicago (Wheeling) | IL | midwest | 42.139 | -87.929 | 17031 | chicago, wheeling |
| indianapolis | Indianapolis | IN | midwest | 39.768 | -86.158 | 18097 | indy |
| detroit | Detroit | MI | midwest | 42.331 | -83.046 | 26163 | |
| minneapolis | Minneapolis | MN | midwest | 44.978 | -93.265 | 27053 | twin cities |
| st_louis | St. Louis | MO | midwest | 38.627 | -90.199 | 29510 | saint louis |
| kansas_city | Kansas City | KS | midwest | 39.114 | -94.627 | 20209 | kc |
| miami | Miami | FL | south | 25.762 | -80.192 | 12086 | |
| houston | Houston | TX | south | 29.760 | -95.370 | 48201 | |
| dallas | Dallas | TX | south | 32.777 | -96.797 | 48113 | dfw, dallas-fort worth |
| atlanta | Atlanta | GA | south | 33.749 | -84.388 | 13121 | |
| memphis | Memphis | TN | south | 35.150 | -90.049 | 47157 | |
| denver | Denver | CO | west | 39.739 | -104.990 | 08031 | |
| phoenix | Phoenix | AZ | west | 33.448 | -112.074 | 04013 | |
| seattle | Seattle | WA | west | 47.606 | -122.332 | 53033 | |
| newark | Newark | NJ | northeast | 40.736 | -74.172 | 34013 | |

`source_id` values come from `01-requirements.md` §3.

- [ ] **Step 1: Write failing tests** in `tests/test_config.py`

```python
def test_scoring_weights_sum_to_one():
    cfg = load_scoring_config()
    assert abs(sum(h["weight"] for h in cfg["hazards"].values()) - 1.0) < 1e-9

def test_hurricane_has_no_observed_component():
    assert load_scoring_config()["hazards"]["hurricane"]["alpha"] == 0.0

def test_hubs_json_has_15_hubs_6_midwest():
    hubs = json.loads(Path("data/hubs.json").read_text())
    assert len(hubs) == 15
    assert sum(h["region"] == "midwest" for h in hubs) == 6
    assert {"miami", "houston", "dallas", "denver"} <= {h["hub_id"] for h in hubs}

def test_settings_default_model(monkeypatch):
    monkeypatch.delenv("LLM_MODEL", raising=False)
    assert Settings(_env_file=None).llm_model == "openai/gpt-4o-mini"
```

- [ ] **Step 2:** `uv sync && uv run pytest tests/test_config.py -v`. Expected: FAIL (import errors).
- [ ] **Step 3:** Create the files listed above.
- [ ] **Step 4:** `uv run pytest -v && uv run ruff check .`. Expected: 4 passed, ruff clean.
- [ ] **Step 5:** Commit `chore(config): add project skeleton, scoring config and hub registry data`, then open a PR and merge.

---

## Group B — `feat/data-ingest`

### Task 2: Hub registry and name resolution

**Files:** Create `app/domain/hubs.py`. Test `tests/test_hubs.py`.

**Interfaces:**
- Produces:
  - `Region = Literal["midwest", "south", "west", "northeast"]`
  - `@dataclass(frozen=True) Hub(hub_id, name, state, region: Region, lat: float, lon: float, county_fips: str, source_id: str, aliases: tuple[str, ...])`
  - `class HubRegistry`:
    - `from_json(path: Path) -> HubRegistry` (classmethod)
    - `all() -> list[Hub]`
    - `get(hub_id: str) -> Hub | None`
    - `by_region(region: Region) -> list[Hub]`
    - `resolve(mention: str) -> Hub | None`
- **Resolution rule:**
  1. Lowercase the mention.
  2. Replace `.` and `,` with nothing.
  3. Drop a trailing `hub` and a leading `the`.
  4. Map `st`↔`saint`.
  5. Collapse whitespace.
  6. Look up an exact key among `hub_id`, `name.lower()`, the bare city (`name` before ` (`), and the aliases.

  There is no fuzzy matching: a wrong match is worse than a clarifying question.

- [ ] **Step 1: Failing tests**

```python
REG = HubRegistry.from_json(Path("data/hubs.json"))

@pytest.mark.parametrize("mention,hub_id", [
    ("chicago", "chicago"), ("Wheeling", "chicago"), ("  DALLAS ", "dallas"),
    ("St Louis", "st_louis"), ("saint louis", "st_louis"), ("St. Louis", "st_louis"),
    ("KC", "kansas_city"), ("Chicago hub", "chicago"), ("the Dallas hub", "dallas"),
])
def test_resolve_variants(mention, hub_id):
    assert REG.resolve(mention).hub_id == hub_id

@pytest.mark.parametrize("mention", ["Tokyo", "Springfield", "", "Fort Worth"])
def test_resolve_unknown_returns_none(mention):
    assert REG.resolve(mention) is None

def test_by_region_midwest():
    assert len(REG.by_region("midwest")) == 6
```

- [ ] **Step 2:** `uv run pytest tests/test_hubs.py -v`. Expected: FAIL.
- [ ] **Step 3:** Implement `app/domain/hubs.py`.
- [ ] **Step 4:** `uv run pytest tests/test_hubs.py -v`. Expected: all pass.
- [ ] **Step 5:** Commit `feat(domain): add hub registry with alias resolution`.

### Task 3: SQLite data layer

**Files:** Create `app/data/db.py`, plus `DailyWeather` in `app/domain/metrics.py` (the type only, for now). Test `tests/test_db.py`.

**Interfaces:**
- Produces, in `app/domain/metrics.py`:
  - `@dataclass(frozen=True) DailyWeather(date: str, snowfall_cm: float | None, precip_mm: float | None, tmax_c: float | None, tmin_c: float | None, apparent_tmax_c: float | None, gust_max_kmh: float | None)`
- Produces, in `app/data/db.py`:
  - `SCHEMA: str`, exactly the DDL in `03-architecture.md` §5
  - `connect(path: Path | str) -> sqlite3.Connection`, which runs `SCHEMA` (`CREATE TABLE IF NOT EXISTS`)
  - `insert_daily(conn, hub_id: str, days: list[DailyWeather]) -> None` (`INSERT OR REPLACE`)
  - `insert_nri(conn, rows: list[dict]) -> None`; row keys are `hub_id, county_fips, hazard_code, afreq, national_pctl`
  - `set_meta(conn, key: str, value: str) -> None`
  - `load_daily(conn) -> dict[str, list[DailyWeather]]`, keyed by hub_id and ordered by date
  - `load_nri(conn) -> dict[str, dict[str, float]]`, mapping hub_id → {hazard_code: national_pctl}
  - `load_meta(conn) -> dict[str, str]`

- [ ] **Step 1: Failing test** `test_roundtrip_in_memory`:
  - insert 2 `DailyWeather` rows for `"denver"` (one with `snowfall_cm=None`), 1 NRI row, 1 meta key
  - `load_daily(conn)["denver"]` equals the inserted list (order by date)
  - `load_nri(conn) == {"denver": {"WNTW": 70.0}}`
  - `load_meta(conn)["window_end"] == "2025-12-31"`
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run. Expected: PASS.
- [ ] **Step 5:** Commit `feat(data): add sqlite schema and read/write functions`.

### Task 4: Build the static dataset (NRI subset + Open-Meteo ingest)

**Files:** Create `scripts/build_nri_subset.py`, `scripts/ingest.py`, `data/nri_hubs.csv` (generated), `data/weather.db` (generated). Test `tests/test_ingest.py`.

**Interfaces:**
- Consumes: `HubRegistry` (Task 2); `connect`, `insert_daily`, `insert_nri`, `set_meta` (Task 3).
- Produces, in `scripts/build_nri_subset.py`:
  - `NRI_URL = "https://services.arcgis.com/XG15cJAlne2vxtgt/arcgis/rest/services/National_Risk_Index_Counties/FeatureServer/0/query"`
  - `NRI_CODES = ("WNTW","ISTM","CWAV","HRCN","IFLD","CFLD","HWAV","TRND","HAIL","SWND")`
  - `national_percentile(all_values: list[float], value: float) -> float`: `100 * count(v < value) / len(all_values)`; `None` is treated as 0
  - `fetch_counties() -> list[dict]`: paginates with `resultOffset` in steps of 2000, `outFields=STCOFIPS,<code>_AFREQ...`, `returnGeometry=false`
  - `build_rows(hubs: list[Hub], counties: list[dict]) -> list[dict]`
  - `main()` writes `data/nri_hubs.csv` (long format, 150 rows)
- Produces, in `scripts/ingest.py`:
  - `OPEN_METEO_URL = "https://archive-api.open-meteo.com/v1/archive"`
  - `DAILY_VARS = "snowfall_sum,precipitation_sum,temperature_2m_max,temperature_2m_min,apparent_temperature_max,wind_gusts_10m_max"`
  - `parse_daily(payload: dict) -> list[DailyWeather]`
  - `fetch_daily(client: httpx.Client, hub: Hub, start: str, end: str) -> dict`: `timezone=auto`; on HTTP 429 or 5xx, retry with backoff 10s, 20s, 40s, 80s, then raise
  - `main()`:
    1. For each hub: fetch, then sleep 3 s.
    2. `insert_daily`.
    3. Load `data/nri_hubs.csv` and call `insert_nri`.
    4. `set_meta` for `window_start`, `window_end`, `open_meteo_url`, `nri_url`, `ingested_at`.

- [ ] **Step 1: Failing tests**

```python
def test_national_percentile_strict_below():
    vals = [0, 0, 0, 5, 10]
    assert national_percentile(vals, 0) == 0.0
    assert national_percentile(vals, 5) == 60.0
    assert national_percentile(vals, 10) == 80.0

def test_parse_daily_maps_fields_and_keeps_nulls():
    payload = {"daily": {"time": ["2025-01-01"], "snowfall_sum": [None], "precipitation_sum": [2.0],
               "temperature_2m_max": [5.0], "temperature_2m_min": [-3.0],
               "apparent_temperature_max": [1.0], "wind_gusts_10m_max": [40.0]}}
    assert parse_daily(payload) == [DailyWeather("2025-01-01", None, 2.0, 5.0, -3.0, 1.0, 40.0)]
```

- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement both scripts.
- [ ] **Step 4:** `uv run pytest tests/test_ingest.py -v`. Expected: PASS.
- [ ] **Step 5:** `uv run python -m scripts.build_nri_subset`. Expected: `data/nri_hubs.csv` has 151 lines (header + 150), and Miami's `HRCN` percentile is ≥ 95.
- [ ] **Step 6:** `uv run python -m scripts.ingest` (about 2 minutes because of throttling). Then check with `sqlite3 data/weather.db "select count(*) from daily_weather"`. Expected: `27390`.
- [ ] **Step 7:** Commit `feat(data): add nri subset builder and open-meteo ingest`, then commit `build(data): add static 2021-2025 dataset`. Open a PR and merge.

---

## Group C — `feat/scoring`

### Task 5: Metrics

**Files:** Modify `app/domain/metrics.py`. Test `tests/test_metrics.py`.

**Interfaces:**
- Produces:
  - `WeatherField = Literal["snowfall_cm","precip_mm","tmax_c","tmin_c","apparent_tmax_c","gust_max_kmh"]`
  - `@dataclass(frozen=True) Condition(field: WeatherField, op: Literal[">=", "<="], threshold: float)` with `matches(day: DailyWeather) -> bool | None`, which returns `None` when the field is null
  - `count_days(days: list[DailyWeather], cond: Condition) -> tuple[int, int]`, returning `(matched, days_with_data)`
  - `annual_rate(days, cond, years: float) -> float`, equal to `matched / years`
  - `coverage(days, field: WeatherField, expected_days: int) -> float`
  - `StatMetric = Literal[...]` and `STAT_METRICS: dict[StatMetric, Condition]`. These are exactly the 9 rows of `02-scoring-model.md` §6; `snow_day` is `snowfall_cm >= 0.1`.
  - `Aggregation = Literal["count", "pct_of_days", "per_year_avg"]`
  - `filter_period(days, start: str, end: str) -> list[DailyWeather]`

- [ ] **Step 1: Failing tests**
  - `test_count_days_ignores_nulls`: 3 days with snowfall `[2.0, None, 0.0]` and `>= 1.0` → `(1, 2)`
  - `test_annual_rate`: 10 matching days over 5 years → `2.0`
  - `test_coverage`: 2 non-null out of 4 expected → `0.5`
  - `test_snow_day_threshold_is_trace`: `STAT_METRICS["snow_day"].threshold == 0.1`
  - `test_filter_period_inclusive`: both bounds are kept
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run. Expected: PASS.
- [ ] **Step 5:** Commit `feat(domain): add daily weather metrics and stat catalog`.

### Task 6: Scoring engine → ScoreBook

**Files:** Create `app/domain/scoring.py`. Modify `app/config.py` so `load_scoring_config` returns `ScoringConfig`, and update `tests/test_config.py` to use attribute access. Test `tests/test_scoring.py`.

**Interfaces:**
- Consumes: `DailyWeather`, `Condition`, `count_days`, `coverage` (Task 5); `Hub` (Task 2).
- Produces (all Pydantic models):
  - `Hazard = Literal["winter","hurricane","flood","heat","severe_storms"]`
  - `Label = Literal["low","medium","high"]`
  - `MetricConfig(name, field: WeatherField, op, threshold, cap)` with `.condition -> Condition`
  - `HazardConfig(weight, alpha, nri: list[str], nri_agg: Literal["mean","max"], metrics: list[MetricConfig] = [])`
  - `ScoringConfig(version, window_start, window_end, labels: dict[str, float], flags: dict[str, float], hazards: dict[Hazard, HazardConfig])` with `.years -> float`, which is 5.0 (`days_in_window / 365.25`, rounded to 2 decimals)
  - `HazardScore(hazard, score, obs: float | None, nri: float, weight, alpha, contribution, obs_metrics: dict[str, float], nri_pctls: dict[str, float], flags: list[str])`. `obs_metrics` maps a metric name to its rate in days per year.
  - `HubScore(hub_id, name, region, composite, label: Label, peak_hazard: Hazard, rank: int, hazards: dict[Hazard, HazardScore], flags: list[str])`. `rank` is 1 for the highest composite among all hubs.
  - `ScoreBook(version: str, hubs: dict[str, HubScore])` with `ranked(hazard: Hazard | None = None, hub_ids: list[str] | None = None) -> list[HubScore]`. It sorts descending by `hazards[hazard].score` or by `composite`; ties break by `hub_id` ascending.
  - `label_for(score: float, labels: dict[str, float]) -> Label`
  - `score_hazard(days, pctls: dict[str, float], cfg: HazardConfig, years: float, flags_cfg: dict[str, float], expected_days: int) -> HazardScore`. Its `contribution` is set to `weight * score`.
  - `build_scorebook(hubs: list[Hub], daily: dict[str, list[DailyWeather]], nri: dict[str, dict[str, float]], cfg: ScoringConfig) -> ScoreBook`
- Formula: exactly `02-scoring-model.md` §2:

  ```
  s_m = 100 · min(rate / cap, 1)
  OBS = mean(s_m)
  NRI = mean or max of pctls (missing code → 0)
  H   = α·OBS + (1−α)·NRI        # when α = 0, OBS is None and H = NRI
  R   = Σ w·H
  ```

- Flags:
  - `single_source` when α = 0
  - `sources_disagree` when α > 0 and `|OBS − NRI| ≥ flags.disagree_threshold`
  - `low_coverage` when any metric field's coverage is below `flags.min_coverage`
  - `HubScore.flags` is the sorted union of the hazard flags, plus `"county_level"` always

- [ ] **Step 1: Failing tests**, using a tiny inline `ScoringConfig` fixture (2 hazards) and synthetic days:

```python
def test_metric_score_caps_at_100():  # rate 60/yr with cap 30 → obs 100
def test_hazard_blend():               # obs 50, nri 80, alpha 0.6 → 0.6*50 + 0.4*80 == 62.0
def test_flood_uses_max_nri():         # nri_agg "max", pctls {IFLD: 98, CFLD: 0} → nri == 98
def test_alpha_zero_single_source():   # obs is None, score == nri, "single_source" in flags
def test_sources_disagree_flag():      # obs 5, nri 96, alpha 0.6 → "sources_disagree"
def test_low_coverage_flag():          # half the days null → "low_coverage"
def test_contributions_sum_to_composite():
    book = build_scorebook(...)
    h = book.hubs["a"]
    assert abs(sum(x.contribution for x in h.hazards.values()) - h.composite) < 1e-9
@pytest.mark.parametrize("r,label", [(34.99, "low"), (35.0, "medium"), (54.99, "medium"), (55.0, "high")])
def test_label_bands(r, label): ...
def test_ranked_tie_breaks_by_hub_id(): ...
def test_real_config_loads():          # load_scoring_config().hazards["flood"].nri_agg == "max"
```

- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement `app/domain/scoring.py` and update `app/config.py`.
- [ ] **Step 4:** `uv run pytest -v`. Expected: all pass.
- [ ] **Step 5:** Commit `feat(domain): add deterministic scoring engine`.

### Task 7: Calibrate on real data and freeze

**Files:** Create `scripts/score_report.py`. Modify `config/scoring.toml` (caps only, if needed) and `docs/02-scoring-model.md` §3–4 (record the final values and the real table).

**Interfaces:** Consumes `connect`, `load_daily`, `load_nri` (Task 3), `build_scorebook` (Task 6), `load_scoring_config`.

- [ ] **Step 1:** Implement `main()`. It prints one row per hub, sorted by composite: `rank, hub, composite, label, then each H_h`. It also prints every `obs_metrics` rate.
- [ ] **Step 2:** Run `uv run python -m scripts.score_report`. Check:
  - no observed metric saturates (score 100) for more than 2 hubs; if more do, raise that cap to roughly the 2nd-highest hub's rate
  - Seattle is `low`
  - at least one hub falls in each label
- [ ] **Step 3:** If any value changed, bump `version = "1.1"` and paste the final table into `02-scoring-model.md` §4.
- [ ] **Step 4:** `uv run pytest`. Expected: PASS.
- [ ] **Step 5:** Commit `chore(config): calibrate caps on real data`. Open a PR and merge.

---

## Group D — `feat/agent`

### Task 8: Result models and tool executors

**Files:** Create `app/domain/results.py` and `app/domain/queries.py`. Test `tests/test_queries.py` (synthetic `QueryContext` built in a fixture: 3 hubs, small daily lists, a ScoreBook from Task 6).

**Interfaces:**
- Consumes: `HubRegistry`, `Region` (Task 2); `STAT_METRICS`, `StatMetric`, `Aggregation`, `filter_period`, `count_days` (Task 5); `ScoreBook`, `HubScore`, `Hazard`, `Label` (Task 6).
- Produces, in `results.py` (every model has `kind: Literal[...]` and `caveats: list[str]`):
  - `RankRow(rank, hub_id, name, region, score, label, top_drivers: list[Hazard], flags)`
  - `RankResult(kind="rank", hazard: Hazard | Literal["overall"], region: Region | None, rows: list[RankRow])`
  - `CompareResult(kind="compare", hazards: list[Hazard], hubs: list[HubScore], leaders: dict[Hazard, str], gaps: dict[Hazard, float])`
  - `StatResult(kind="stat", hub_id, metric: StatMetric, condition: str, aggregation, period_label: str, value: float, days_total: int, days_with_data: int, source: str)`. `value` is a percentage from 0 to 100 for `pct_of_days`.
  - `PremiseCheck(asserted: Label, actual: Label, holds: bool)`
  - `ExplainResult(kind="explain", hub: HubScore, total_hubs: int, premise_check: PremiseCheck | None)`
  - `ScopeResult(kind="scope", reason: Literal["unknown_hub","period_out_of_range","too_few_hubs"], unknown: list[str], message: str, supported_hubs: list[str])`
  - `Result = RankResult | CompareResult | StatResult | ExplainResult | ScopeResult`
- Produces, in `queries.py`:
  - `@dataclass QueryContext(registry: HubRegistry, book: ScoreBook, daily: dict[str, list[DailyWeather]], cfg: ScoringConfig)`
  - `rank_hubs(ctx, hazard="overall", region=None, hubs: list[str] = [], top_n=None) -> RankResult | ScopeResult`
  - `compare_hubs(ctx, hubs: list[str], hazards: list[Hazard] = []) -> CompareResult | ScopeResult`. If `hazards` is empty, all 5 are used.
  - `get_weather_stat(ctx, hub: str, metric: StatMetric, aggregation: Aggregation, period: Literal["last_year","full_window"] | int) -> StatResult | ScopeResult`
  - `explain_hub(ctx, hub: str, asserted_level: Label | None = None) -> ExplainResult | ScopeResult`
- Rules:
  - Every hub mention is resolved with `registry.resolve`. **Any** unresolved mention produces `ScopeResult(reason="unknown_hub")`, and its `message` names the unknown mention(s) and lists all 15 hub names.
  - `last_year` resolves to the year of `cfg.window_end` (2025). Integer years outside 2021–2025 produce `period_out_of_range`.
  - `top_drivers` are the 2 hazards with the highest `contribution`.
  - Caveats always include the window ("2021–2025 history"). Add `"NRI is county-level"` whenever NRI feeds the result, and add one caveat per flag present.

- [ ] **Step 1: Failing tests**
  - `test_rank_region_filters_and_sorts`: only that region's hubs, scores non-increasing
  - `test_rank_top_n`
  - `test_compare_two_hubs_leaders_and_gaps`: leader is the higher `H`; gap equals the absolute difference
  - `test_compare_with_unknown_hub_is_scope`: `compare_hubs(ctx, ["Miami", "Tokyo"])` gives `kind == "scope"`, `unknown == ["Tokyo"]`, `"Tokyo"` in the message
  - `test_compare_single_hub_is_scope`: reason is `too_few_hubs`
  - `test_stat_pct_of_days`: 2 snow days out of 10 days in 2025 → `value == 20.0`, `days_total == 10`
  - `test_stat_last_year_maps_to_2025`
  - `test_stat_year_out_of_range`: `period=2019` gives `reason == "period_out_of_range"`
  - `test_explain_premise_check`: `asserted_level="high"` on a medium hub gives `holds is False` and `actual == "medium"`
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run. Expected: PASS.
- [ ] **Step 5:** Commit `feat(domain): add result models and tool executors`.

### Task 9: Agent schemas (QueryPlan + grounded Answer)

**Files:** Create `app/agent/schemas.py`. Test `tests/test_schemas.py`.

**Interfaces:**
- Consumes: `Hazard`, `Label` (Task 6); `Region` (Task 2); `StatMetric`, `Aggregation` (Task 5); `Result` (Task 8).
- Produces: `RankQuery`, `CompareQuery`, `StatQuery`, `ExplainQuery`, `Clarify` and `QueryPlan(action: <union>, discriminator="tool")`. Fields are exactly as in `03-architecture.md` §4, with `CompareQuery.hubs` declared `Field(min_length=2)`.
- Produces: `Answer(text: str, caveats: list[str] = [], suggested_followups: list[str] = Field(default=[], max_length=3))` with a `model_validator(mode="after")` that reads `info.context["result"]` when present.
- **Grounding rule:**
  - Extract numbers from `text` with the regex `-?\d+(?:\.\d+)?`, ignoring thousands separators.
  - Collect every int or float found anywhere in `result.model_dump()`.
  - A text number `n` is grounded if some result value `v` satisfies `|n − v| ≤ 0.05`, or `|n − v| ≤ 0.5` when `n` is an integer (this allows rounding).
  - Also allowed: the years 2021–2025 and the integers 0–20.
    `# ponytail: small-int allowance can mask an invented small score; tighten if evals show it`
  - An ungrounded number raises `ValueError("ungrounded numbers: [...]")`. Instructor sends that message back to the model when it retries.

- [ ] **Step 1: Failing tests**
  - `test_plan_discriminates_by_tool`: `QueryPlan.model_validate({"action": {"tool": "compare_hubs", "hubs": ["Miami", "Houston"]}})` gives an `action` that is a `CompareQuery`
  - `test_compare_requires_two_hubs`: raises `ValidationError`
  - `test_stat_period_rejects_2019`: raises `ValidationError`
  - `test_grounding_accepts_rounded_value`: result composite 60.63, text "scores 60.6 (about 61)" → OK
  - `test_grounding_rejects_invented_score`: text "scores 87.3" → `ValidationError`
  - `test_grounding_allows_years_and_small_ints`: "over 5 years, 2021–2025, top 3" → OK
  - `test_no_context_skips_grounding`
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run. Expected: PASS.
- [ ] **Step 5:** Commit `feat(agent): add query plan union and grounded answer schema`.

### Task 10: LLM client, prompts and pipeline

**Files:** Create `app/agent/llm.py`, `app/agent/prompts.py`, `app/agent/pipeline.py`, `tests/fakes.py`. Test `tests/test_pipeline.py`.

**Interfaces:**
- Consumes: the `QueryPlan` members and `Answer` (Task 9); `QueryContext` and the four executors (Task 8); `Settings` (Task 1).
- Produces, in `llm.py`:
  - `class StructuredLLM(Protocol)` with `def complete(self, response_model: type[T], messages: list[dict], context: dict | None = None) -> T`
  - `class InstructorLLM(model: str, max_retries: int = 2)`, which uses `instructor.from_provider(model)` and `client.create(response_model=..., messages=..., max_retries=..., context=context)`. Check the exact keyword in the installed Instructor version (`context` vs `validation_context`).
- Produces, in `prompts.py`:
  - `interpret_messages(message: str, history: list[Turn], hubs: list[Hub]) -> list[dict]`. The system prompt includes the hub names and aliases, the 5 hazards, the 4 regions, the stat metric catalog, the dataset window, and these rules:
    - output a plan only, never an answer
    - follow-ups must produce a **complete** plan
    - forecasts, ROI, and anything other than the hubs → `Clarify(reason="out_of_scope"|"unsupported")`
    - ambiguous → `Clarify(reason="ambiguous")`
    - capture the user's asserted level in `asserted_level`
    - pass city names exactly as the user wrote them
  - `narrate_messages(message: str, result: Result) -> list[dict]`. Rules for the model:
    - use only numbers from the result JSON
    - lead with the direct answer
    - name the top drivers
    - correct a false premise explicitly when `premise_check.holds` is false
    - mention the caveats
    - ≤ 200 words
- Produces, in `pipeline.py`:
  - `@dataclass Turn(message: str, plan_json: str | None)`
  - `@dataclass ChatOutcome(answer: Answer, plan: QueryPlan | None, result: Result | None)`
  - `class Agent(llm: StructuredLLM, ctx: QueryContext, history_turns: int = 4)` with `run(session_id: str, message: str) -> ChatOutcome` and `execute(plan: QueryPlan) -> Result`, which dispatches on `plan.action.tool`
  - Sessions are kept in `dict[str, list[Turn]]` on the Agent.
- Flow:
  - `interpret`. If it raises, return `Answer(text="I couldn't interpret that — try rephrasing, e.g. 'Rank Midwest hubs by winter risk'.")` with `plan=None`.
  - If the plan is `Clarify`, return `Answer(text=plan.question)` (one LLM call).
  - Otherwise `execute`.
    - A `ScopeResult` returns `Answer(text=result.message)` (one LLM call).
    - Any other result goes to `narrate` with `context={"result": result}`.
  - Append the turn to the session.
- `tests/fakes.py`: `FakeLLM(responses: list[BaseModel])` returns the responses in order and records the `messages` and `context` of each call in `.calls`.

- [ ] **Step 1: Failing tests** (FakeLLM plus the synthetic ctx from Task 8, moved into `tests/conftest.py`):
  - `test_rank_flow_calls_llm_twice_and_passes_result_context`
  - `test_clarify_skips_execution`: `len(llm.calls) == 1`
  - `test_unknown_hub_returns_scope_message_without_narration`: 1 call, and the answer contains "Tokyo"
  - `test_followup_history_includes_previous_plan`: in the second `run`, the interpret messages contain the first plan's JSON
  - `test_interpret_failure_is_graceful`: FakeLLM raises → `plan is None` and the text starts with "I couldn't interpret"
  - `test_interpret_prompt_lists_all_hubs`
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** `uv run pytest -v`. Expected: PASS.
- [ ] **Step 5:** Commit `feat(agent): add llm client, prompts and pipeline`. Open a PR and merge.

---

## Group E — `feat/api-ui`

### Task 11: FastAPI app

**Files:** Create `app/api/models.py` and `app/api/main.py`. Test `tests/test_api.py`.

**Interfaces:**
- Consumes: `get_settings`, `load_scoring_config`; `connect`, `load_daily`, `load_nri`, `load_meta`; `HubRegistry`, `build_scorebook`, `QueryContext`, `rank_hubs`; `Agent`, `InstructorLLM`.
- Produces, in `models.py`:
  - `ChatRequest(session_id: str | None = None, message: str = Field(min_length=1, max_length=1000))`
  - `ChatResponse(session_id: str, answer: Answer, plan: QueryPlan | None, result: Result | None)`
  - `HubSummary(hub_id, name, state, region, composite, label, peak_hazard, rank)`
- Produces, in `main.py`:
  - `load_context(settings: Settings) -> QueryContext` (also used by the eval runner)
  - `build_app(agent_factory: Callable[[QueryContext], Agent] | None = None) -> FastAPI` and `app = build_app()`
  - The lifespan loads data and builds the ScoreBook and the Agent into `app.state`. The default factory is `Agent(InstructorLLM(settings.llm_model), ctx)`.
  - Routes, per `03-architecture.md` §6:
    - `POST /chat`: a new `uuid4().hex` is assigned when `session_id` is missing
    - `GET /hubs`
    - `GET /hubs/{hub_id}`: 404 if unknown
    - `GET /rankings?hazard=&region=&top_n=`
    - `GET /health`: returns `{status: "ok", dataset: meta, llm_model, scoring_version}`

- [ ] **Step 1: Failing tests** (`TestClient(build_app(agent_factory=lambda ctx: Agent(FakeLLM([...]), ctx)))`, real `data/weather.db`):
  - `test_health_ok`
  - `test_hubs_returns_15_sorted_by_rank`
  - `test_hub_detail_404`
  - `test_rankings_midwest_winter_has_6_rows`
  - `test_chat_assigns_session_and_returns_answer`
  - `test_chat_rejects_empty_message_422`
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run. Expected: PASS.
- [ ] **Step 5:** Manual check: `uv run uvicorn app.api.main:app --reload`, open `http://localhost:8000/docs`, then `curl -s localhost:8000/rankings?hazard=winter\&region=midwest`. Expected: JSON with 6 rows.
- [ ] **Step 6:** Commit `feat(api): add fastapi endpoints`.

### Task 12: Streamlit chat UI

**Files:** Create `ui/app.py`. Verified manually; it's a thin view with no logic worth unit-testing.

**Interfaces:** Consumes the HTTP API only (`API_URL` from the environment, default `http://localhost:8000`). It must not import `app.*`.

- [ ] **Step 1:** Implement:
  - `st.session_state` holds `session_id` and `messages`.
  - `st.chat_input` sends a POST to `/chat` with `httpx` (timeout 60 s).
  - The answer is rendered with `st.chat_message`, with caveats as a caption and suggested follow-ups as buttons that resend.
  - An `st.expander("How I got this")` shows the plan JSON and the result. A `rank` or `compare` result is shown as an `st.dataframe` of hub × score; other results as JSON.
  - Sidebar: the overall ranking table from `GET /hubs`, the model name from `/health`, the 4 assignment questions as example buttons, and a "New conversation" button.
  - If the API can't be reached, show an `st.error` with the uvicorn command.
- [ ] **Step 2:** With the API running and a real `OPENAI_API_KEY`, run `uv run streamlit run ui/app.py` and ask the 4 assignment questions plus "What about Chicago?". Expected: grounded answers, with the expander showing the plan and the result.
- [ ] **Step 3:** Commit `feat(ui): add streamlit chat interface`. Open a PR and merge.

---

## Group F — `feat/eval`

### Task 13: Evaluation set

**Files:** Create `tests/eval/cases.json` and `tests/eval/test_eval.py`.

**Interfaces:** Consumes `Agent`, `InstructorLLM`, the real `QueryContext` via `load_context(settings)` (Task 11), and `ScoreBook.ranked`.

**Case format:** `{id, turns: [str], expect: {tool?, hubs?, hazard?, region?, metric?, period?, asserted_level?, result_kind?, premise_holds?, answer_contains?}}`. Assertions run against the **last** turn.

| id | turns | expect |
|---|---|---|
| midwest_winter | "Which hubs in the Midwest are most exposed to winter disruption?" | tool `rank_hubs`, hazard `winter`, region `midwest` |
| compare_miami_houston | "Compare Miami and Houston in terms of hurricane and flood exposure." | `compare_hubs`, hubs {miami, houston}, hazards ⊇ {hurricane, flood} |
| denver_snow | "What percentage of days in Denver last year had snowfall?" | `get_weather_stat`, metric `snow_day`, aggregation `pct_of_days`, period `last_year` or 2025 |
| dallas_why | "Why is the Dallas hub's weather disruption risk high?" | `explain_hub`, hub dallas, asserted_level `high` |
| followup_chicago | dallas_why, then "What about Chicago?" | `explain_hub`, hub chicago |
| followup_hazard | midwest_winter, then "And for flood?" | `rank_hubs`, hazard `flood`, region `midwest` |
| top3_overall | "Top 3 riskiest hubs overall" | `rank_hubs`, top_n 3 |
| heat_south | "Rank southern hubs by heat" | `rank_hubs`, hazard `heat`, region `south` |
| non_hub_city | "How risky is Boston?" | result_kind `scope`, or tool `clarify` |
| mixed_hubs | "Compare Miami and Tokyo" | result_kind `scope`, answer_contains "Tokyo" |
| year_out_of_range | "How many snow days did Denver have in 2019?" | result_kind `scope`, or tool `clarify` |
| forecast | "Will it snow in Denver tomorrow?" | tool `clarify` |
| roi | "What's the ROI of upgrading Miami?" | tool `clarify` |
| false_premise | "Why is Seattle's risk so high?" | `explain_hub`, premise_holds `false` |
| alias | "Is KC more exposed to severe storms than St Louis?" | `compare_hubs`, hubs {kansas_city, st_louis} |

- [ ] **Step 1:** Write `cases.json` (the table above) and `test_eval.py`:
  - `@pytest.mark.eval`, parametrized over the cases
  - a fresh `Agent` per case
  - compare hubs by **resolved** `hub_id`
  - for rank cases, also assert that the result rows equal `ctx.book.ranked(...)` (deterministic source of truth)
  - for every non-scope result, assert `Answer.model_validate(answer.model_dump(), context={"result": result})` passes (grounding)
- [ ] **Step 2:** `uv run pytest -m eval -v` with a real key. Expected: ≥ 13/15 pass. Record the pass rate and the failures in the README; fix prompts only for real misroutes.
- [ ] **Step 3:** `uv run pytest` (the default run). Expected: evals deselected, all unit tests pass.
- [ ] **Step 4:** Commit `test(eval): add evaluation set and runner`. Open a PR and merge.

---

## Group G — `docs/readme`

### Task 14: README and deliverables

**Files:** Create `README.md`. Create `docs/session/` (export of the AI session, a required deliverable).

- [ ] **Step 1:** Write `README.md` covering:
  - what the project is
  - quickstart: `uv sync`, `cp .env.example .env` (add your key), the uvicorn and streamlit commands
  - the sample questions
  - how scoring works (a 5-line summary linking to `02`)
  - the AI boundary (linking to `01` §6)
  - how to run the tests and evals, with the latest eval pass rate
  - assumptions, uncertainty and scope (from `01` §2 and `02` §8)
  - links to the docs: requirements, scoring, architecture with repo structure and data storage choice, and this plan
- [ ] **Step 2:** Export this Claude Code session transcript into `docs/session/` (mandatory deliverable).
- [ ] **Step 3:** From a clean clone, follow the README quickstart. Expected: the UI answers the 4 assignment questions.
- [ ] **Step 4:** Commit `docs: add readme and session transcript`. Open a PR and merge.
