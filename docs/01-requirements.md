# 01 — Requirements & Scope

_Weather Risk Intelligence Agent · status: agreed · 2026-10-23_

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
| Q4 | **Explain** | "Why is Dallas's risk high?" | Component contributions, main drivers, rank. **Corrects false premises.** |
| Q5 | **Follow-up** | "What about Chicago?" / "And flood?" / "Why?" | Resolved against conversation context, then handled as Q1–Q4 |
| Q6 | **Clarify / out of scope** | "Springfield?", "Will it snow tomorrow?", "What's the ROI?" | A clarifying question, or a statement of what is supported |

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
- Alerting (bonus): recompute → diff against the last stored score → alert on threshold crossing

### AI (LLM)
- Classify the intent (Q1–Q6) and extract parameters → **JSON-schema-validated query plan**
- Resolve follow-ups from conversation context
- Detect ambiguous or out-of-scope requests and write the clarification / refusal
- Write the answer from the deterministic result data, including drivers and caveats

### Guardrails
- Schema in both directions: the LLM's plan is validated before any code runs, and the result data is the only source for the answer.
- Eval check: every number in the answer must appear in the result data.
- Explain queries check the user's premise against the computed label.

## 7. Requirements traceability

| Assignment requirement | Where addressed |
|---|---|
| Public weather/hazard APIs | Data layer (see architecture doc) |
| Rank/compare by defined KPI | Deterministic scoring, Q1/Q2 |
| Explain reasoning | Q4 + contribution breakdown |
| Conversational follow-ups | Q5 |
| Deterministic scoring | §6 |
| Chat interface (voice bonus) | Frontend |
| Alert on score change (bonus) | §6 alerting |
| Agent exposed via API | Backend |
| JSON schema between LLM and code | §6 guardrails |
| Eval set + runner | Eval module |
| Assumptions / uncertainty / scope | §2, §5, caveats in every answer |
