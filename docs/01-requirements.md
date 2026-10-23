# 01 — Requirements & Scope

_Weather Risk Intelligence Agent · status: implemented · 2026-10-23_

## 1. Business context

- **User:** analysts at a US logistics company with regional distribution hubs.
- **Decision supported:** once a year, choose a handful of hubs for resilience-upgrade investment.
- **Implication:** the core signal is **structural, historical exposure** (multi-year), not short-term forecasts.
  Live data only matters for the (bonus) alert.

## 2. Assumptions

| Topic | Decision |
|---|---|
| Hub network | 15 real hubs from the FedEx network (see §3). Used as a realistic stand-in for "our" company. |
| Scoring window | Last **5 full calendar years: 2021–2025**. |
| "Last year" | Previous calendar year = **2025**. |
| Hub location | Coordinates of the hub's named city (not the exact facility address). |
| Regions | US Census Bureau regions (Midwest, South, West, Northeast). |
| "Exposure" | Historical frequency / severity of hazards near the hub. No $ cost modelling (no financial data). |
| Rare hazards | 5 years is too short to characterise hurricanes (and partly floods). These need a **long-term baseline** source in addition to the 5-year observations. |

## 3. Hub registry (15 hubs)

Source: FedEx Ground (Economy) hub list ([Shiptheory, correct as of Mar 2024](https://support.shiptheory.com/support/solutions/articles/24000090200-fedex-fedex-ground-economy-formally-smart-post-hub-ids));
Miami is the FedEx Express Americas gateway hub at MIA ([FedEx newsroom](https://newsroom.fedex.com/newsroom/global/fedex-express-completes-major-expansion-at-miami-international-airport)).

| Hub | State | Region | Source ID | Aliases |
|---|---|---|---|---|
| Chicago (Wheeling) | IL | Midwest | WHIL 5602 | Chicago, Wheeling |
| Indianapolis | IN | Midwest | ININ 5465 | Indy |
| Detroit | MI | Midwest | DTMI 5481 | |
| Minneapolis | MN | Midwest | MPMN 5552 | Twin Cities |
| St. Louis | MO | Midwest | STMO 5631 | Saint Louis |
| Kansas City | KS | Midwest | KCKS 5648 | KC |
| Miami | FL | South | FedEx Express MIA | |
| Houston | TX | South | HOTX 5771 | |
| Dallas | TX | South | DLTX 5751 | DFW |
| Atlanta | GA | South | ATGA 5303 | |
| Memphis | TN | South | METN 5379 | |
| Denver | CO | West | DNCO 5802 | |
| Phoenix | AZ | West | PHAZ 5854 | |
| Seattle | WA | West | SEWA 5983 | |
| Newark | NJ | Northeast | NENJ 5095 | |

Midwest has 6 hubs (enough for regional ranking); the other hubs add contrast: hurricane coast, heat, mountain snow, mild baseline.

## 4. Hazards (5)

| Hazard | Covers |
|---|---|
| Winter | snow, ice, extreme cold |
| Hurricane | tropical storms / hurricanes |
| Flood | heavy rain, riverine and coastal flooding |
| Heat | extreme heat days / heat waves |
| Severe storms | tornado, hail, damaging wind |

Each hazard gets a sub-score from 0 to 100. A weighted composite gives the overall **disruption risk score** and a label (low / medium / high).

## 5. Query types

| # | Type | Example | Output |
|---|---|---|---|
| Q1 | **Rank / filter** | "Which Midwest hubs are most exposed to winter disruption?" | Ordered hubs + scores + top drivers |
| Q2 | **Compare** | "Compare Miami and Houston on hurricane and flood" | Side-by-side per-hazard scores, gaps, leader per hazard |
| Q3 | **Raw historical stat** | "What % of days in Denver last year had snowfall?" | Value + metric definition + source + data coverage (days) |
| Q4 | **Explain** | "Why is Dallas's risk high?" / "Why is Miami high-risk for winter?" | Component contributions, main drivers, rank. **Corrects false premises** (overall, or per hazard by rank). |
| Q5 | **Follow-up** | "What about Chicago?" / "And flood?" / "Why?" / "yes" | Resolved against conversation context (previous plan, result summary, reply), then handled as Q1–Q4 |
| Q6 | **Clarify / out of scope** | "Springfield?", "Will it snow tomorrow?", "What's the ROI?", "How many flood days…?" | A clarifying question ending in one concrete offer, or a statement of what is supported |

Rankings also support **lowest / safest** ("Which hub has the lowest risk?") by sorting ascending.

**Location scope:** the agent answers **only about the 15 hub cities**. For any other city it says it only knows the hub locations and lists them. Nice-to-have: name the nearest hub.

**Time scope:** stats for years 2021–2025. Forecasts and future predictions are out of scope.

## 6. Deterministic vs AI boundary

**Rule: the LLM never produces a number or a ranking.**

### Deterministic (code)
- Hub registry, aliases, region mapping
- Entity validation: the LLM's extracted hub names must resolve against the registry, or the agent asks to clarify
- Data fetching, caching, coverage checks
- Metric computation (e.g. % snow days, heavy-rain days, heat days)
- Scoring: normalize → hazard sub-scores → weighted composite → label (weights in one config)
- Ranking, comparison, filtering
- Explanation data: component contributions, rank, percentile
- Uncertainty data: coverage and confidence flags, caveats
- Schema validation of all LLM output (retry or clarify on failure)
- Alerting (bonus, deferred): recompute → diff against the last stored score → alert on threshold crossing

### AI (LLM)
- Classify the intent (Q1–Q6) and extract parameters → **JSON-schema-validated query plan**
- Resolve follow-ups from conversation context
- Detect ambiguous or out-of-scope requests and write the clarification / refusal
- Write the answer from the deterministic result data, including drivers and caveats

### Guardrails
- Schema in both directions: the LLM's plan is validated before any code runs, and the result data is the only source for the answer.
- **Grounding:** a validator checks every number in the answer and caveats against the result data, and the eval re-checks it.
- **Premise check:** explain queries check the user's premise against the computed label, or against the hazard rank when the premise names a hazard. Code writes the rejection line.
- **Hazard-day counts:** flood, storm and hurricane day counts are refused in code. Those hazards come from the static FEMA NRI baseline; the daily data has only snow, rain, heat, cold and wind.
- **Prompt injection:** user text is fenced in `<user_input>` and declared untrusted; a leak guard and a follow-up filter run on all LLM output.

## 7. Requirements traceability (audited against `ASSIGNMENT.pdf`)

| Assignment requirement | Status | Where |
|---|---|---|
| Answer the 4 example questions | ✅ | eval cases `midwest_winter`, `compare_miami_houston`, `denver_snow`, `dallas_why` |
| Public APIs for weather and hazard data | ✅ | Open-Meteo Historical + FEMA NRI, fetched by `scripts/` into a committed static dataset |
| Rank or compare hubs by a defined KPI | ✅ | `docs/02-scoring-model.md`; `rank_hubs` / `compare_hubs` (incl. lowest / safest) |
| Explain reasoning clearly | ✅ | `explain_hub`: contributions, observed days/yr, NRI percentiles, rank, caveats; "How I got this" panel |
| Conversational follow-ups | ✅ | session memory (PLAN + RESULT + REPLY); eval: follow-ups, "why?", "yes"/"no" |
| Deterministic scoring/ranking (not only LLM) | ✅ | `app/domain/` (pure); the LLM never produces numbers (grounding validator) |
| Chat interface | ✅ | Streamlit `ui/app.py` |
| Voice (bonus) | ❌ deferred | not implemented |
| Alert when a hub's risk score changes (bonus) | ❌ deferred | design only: 02 §7 / 03 §10 |
| Agent exposed through an API the chat uses | ✅ | FastAPI `app/api/`; the UI talks HTTP only |
| JSON schema between LLM and code | ✅ | `QueryPlan` / `Answer` Pydantic models via Instructor, with retries |
| Small evaluation set and a way to run it | ✅ | `tests/eval/` (32 cases + 12 security), `uv run pytest -m eval` |
| Assumptions, uncertainty, scoping | ✅ | §2, §5, 02 §5 flags and §8 limitations, caveats in every answer, README |
| **Deliverable:** source code + run instructions | ✅ | README quickstart (verified from a clean clone) |
| **Deliverable:** deploy to a URL (preferred, not mandatory) | ❌ not done | runs locally |
| **Deliverable:** design doc: architecture, repo structure, storage | ✅ | `docs/03-architecture.md` (+ `architecture.svg`) §2, §5, §8 |
| **Deliverable:** full AI session (mandatory) | ✅ | `docs/session/claude-code-session.md`; re-export at the very end |

Not done from this doc's own scope: §5's "nice-to-have: name the nearest hub" for non-hub cities.
