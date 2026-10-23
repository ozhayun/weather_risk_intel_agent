# Weather Risk Intelligence Agent

An AI agent that helps logistics analysts decide which distribution hubs to prioritize for weather-resilience investment. It ranks, compares and explains weather-disruption exposure for **15 real US hubs**, using 5 years of daily weather (Open-Meteo, 2021–2025) and FEMA's National Risk Index.

- **Deterministic scoring.** The LLM never produces a number or a ranking. It turns the question into a JSON-schema-validated `QueryPlan`; code computes the result; the LLM explains it, and a validator rejects numbers in the answer and caveats that don't match the result (a soft check: integers within ±0.5 and small counts 0–20 pass).
- **Chat UI** (Streamlit) → **API** (FastAPI) → **agent pipeline** → **SQLite** static dataset.
- **Eval set:** 25 cases, plus 12 prompt-injection and follow-up tests. **37/37 on `gpt-4o-mini`.**

## Quickstart

Requires [uv](https://docs.astral.sh/uv/) and an OpenAI API key (or Anthropic, or a local Ollama).

```bash
uv sync
cp .env.example .env          # then set OPENAI_API_KEY=...
uv run uvicorn app.api.main:app --reload     # API on http://localhost:8000 (docs at /docs)
uv run streamlit run ui/app.py               # chat UI on http://localhost:8501 (second terminal)
```

The dataset is committed (`data/weather.db`, `data/nri_hubs.csv`), so nothing is fetched at runtime except the LLM call.

**Switch LLM provider** by editing one line in `.env`, no code change:
`LLM_MODEL=openai/gpt-4o-mini` | `anthropic/claude-sonnet-5-5` | `ollama/llama3.2`

### Try asking

- Which hubs in the Midwest are most exposed to winter disruption? → then *"And for flood?"*
- Which hub has the lowest overall risk? / What are the safest Midwest hubs for winter?
- Compare Miami and Houston in terms of hurricane and flood exposure.
- What percentage of days in Denver last year had snowfall?
- Why is the Dallas hub's weather disruption risk high? → then *"What about Chicago?"*
- Why is Seattle's risk so high? (false premise, which the agent corrects: Seattle is *low*)
- How risky is Boston? / Will it snow tomorrow? (out of scope, handled explicitly)

Each answer has a **"How I got this"** panel showing the plan the LLM produced and the deterministic result it explained.

## How it works

```
Streamlit ──HTTP──▶ FastAPI /chat ──▶ interpret (LLM → QueryPlan, schema-validated)
                                     ──▶ execute   (pure Python: rank / compare / stat / explain)
                                     ──▶ narrate   (LLM → Answer, every number checked against the result)
```

| Layer | Path | Role |
|---|---|---|
| Domain | `app/domain/` | Hub registry, metrics, **scoring**, tool executors. Pure, no I/O. |
| Data | `app/data/db.py` | SQLite schema and reads |
| Agent | `app/agent/` | `QueryPlan` and `Answer` schemas, Instructor LLM client, prompts, pipeline, session memory |
| API | `app/api/` | `POST /chat`, plus `GET /hubs`, `/hubs/{hub}`, `/rankings`, `/health` (no LLM) |
| UI | `ui/app.py` | Chat; talks to the API only |
| Offline | `scripts/` | Build the NRI subset, ingest Open-Meteo, print the score report, export the session |

**Scoring** (full spec: [`docs/02-scoring-model.md`](docs/02-scoring-model.md)):
- Each hazard (winter, hurricane, flood, heat, severe storms) gets a 0–100 score blending two sources:
  - observed 2021–2025 day counts, scaled against fixed caps
  - the hub county's national percentile in FEMA NRI for how often the hazard occurs
- The composite is a weighted sum (hurricane 0.25, flood 0.25, winter 0.20, severe storms 0.20, heat 0.10), labelled low (< 35), medium (35–55) or high (≥ 55).
- Contributions add up exactly to the composite, so "why is X high" is answered from the breakdown.
- All weights and thresholds live in [`config/scoring.toml`](config/scoring.toml).

**AI boundary** (full spec: [`docs/01-requirements.md`](docs/01-requirements.md) §6):
- **The LLM:** classifies intent, extracts parameters, resolves follow-ups, writes the answer.
- **Code:** resolves hub names (only the 15 hubs; unknown cities get a scope message), validates years, computes every number, checks the user's premise, attaches uncertainty flags.

**Data storage:** SQLite, a single committed file of about 2.7 MB with 27,390 daily rows.
- Built into Python, no extra service to run.
- Supports SQL for the raw stats.
- The demo runs offline.
- Scores are computed in memory at startup from the data plus `scoring.toml`.
- Hubs are configuration in `data/hubs.json`.

## Tests and evaluation

```bash
uv run pytest              # 209 unit, pipeline, API, UI and security tests; no network, no LLM
uv run pytest -m eval -v   # 37 real-LLM tests: 25 eval cases + 12 security/follow-up (needs a key)
uv run pytest -m security  # just the prompt-injection and follow-up tests
```

The eval set (`tests/eval/cases.json`) covers:
- the 4 assignment questions
- follow-ups
- aliases ("KC", "St Louis")
- a non-hub city, mixed valid and invalid hubs, a year outside 2021–2025, "this year", a ranking restricted to one year
- a forecast request, an ROI question, a false premise

Each case checks:
- the plan (tool and arguments)
- the deterministic outcome (expected top hub, premise check)
- that every number in the answer comes from the result

Latest result: **18/18, stable over 3 runs** on `openai/gpt-4o-mini`. The eval caught real bugs, now fixed: a hub mention written as "Chicago (Wheeling), IL" wasn't recognised, and a literal example year in the prompt anchored "this year" to 2023.

## Prompt-injection safety

User text is treated as untrusted data. Defences are layered, so no single one has to hold:

| Layer | What it does |
|---|---|
| Fencing | Every user message, including history, is wrapped in `<user_input>…</user_input>`. Tags the user types are stripped first, so the fence can't be closed early. |
| Instructions | Both system prompts state that fenced text is untrusted and never overrides the instructions (no role changes, prompt reveals, or invented numbers). |
| Schema | The interpreter can only emit one of five typed tools. The narrator's numbers must match the computed result (grounding validator). |
| Output guards | Any reply, caveat or follow-up that repeats lines of the instructions is replaced with a refusal. Clarifying questions are capped at 500 characters. City names a user typed are stripped of markup and shortened before being echoed. |
| Follow-ups | The narrator may only suggest answerable forms: another hazard, another real hub, "why is X's risk {level}?", or a day statistic for 2021–2025. A deterministic filter drops seasons, forecasts, trends, ROI, costs and out-of-window years. |

`tests/test_security.py` covers the deterministic layers. `tests/eval/test_security.py` runs 9 attacks against the real LLM:
- prompt reveal and translation
- forged closing tag
- an admin "policy" hijacking a valid question
- "reply only HACKED"
- secret exfiltration
- injection inside a hub name
- a fake score in the question
- role-play

Each attack asserts that nothing leaks, no forbidden output appears, the plan and ranking are unchanged, and the answer is still grounded. A separate test feeds every suggested follow-up back to the agent and requires a real answer.

Ablation check: with these protections removed, the follow-up tests fail (reproducing the "other seasons" bug) and the "HACKED" attack succeeds.

## Assumptions, uncertainty and scope

- **Hubs:** 15 real FedEx facilities, used as a stand-in for "our" network (14 from FedEx Ground's hub list, plus the FedEx Express Miami gateway). Weather is taken at the hub city's coordinates; NRI at the county containing it.
- **Window:** 2021–2025 (static). "Last year" means 2025.
- **History ≠ future:** this ranks *exposure*, not the probability of next year's losses. There is no cost modelling (no financial data).
- **Hurricanes:** 5 years of data is too short to measure them, so hurricane exposure comes from FEMA NRI alone (flagged `single_source`).
- **Open-Meteo is reanalysis data** (~10 km grid). Snowfall and wind gusts are modeled, not measured at stations.
- **NRI is county-level.** Large counties blur conditions at the site; for example, King County includes the Cascades. When the two sources differ by 50 or more points, the hazard is flagged `sources_disagree`.
- **Heat:** NRI defines heat waves *relative to local climate*, while the observed metric counts absolute ≥ 35 °C days. That's why heat disagreements are common.
- **Out of scope:** forecasts, ROI, non-hub locations, years outside 2021–2025, and rankings for a single year (scores cover the whole window; per-year stats work for one hub). The agent says so instead of guessing.
- **Deferred:** score-change alerts (bonus), deployment, voice input.

## Documentation

| Doc | Contents |
|---|---|
| [`docs/01-requirements.md`](docs/01-requirements.md) | Business context, hub list, query types, deterministic vs. AI boundary |
| [`docs/02-scoring-model.md`](docs/02-scoring-model.md) | Exact scoring formula, calibration table, uncertainty flags |
| [`docs/03-architecture.md`](docs/03-architecture.md) | **Design doc**: components, data flow, DB schema, API, agent tools, repo structure, storage choice |
| [`docs/04-implementation-plan.md`](docs/04-implementation-plan.md) | The step-by-step test-first plan this was built from |
| [`docs/session/`](docs/session/) | Full Claude Code session: requirements, design, plan and implementation |
| [`CLAUDE.md`](CLAUDE.md) | Architecture rules, coding standards, git workflow |

### Rebuilding the dataset (optional)

```bash
uv run python -m scripts.build_nri_subset   # FEMA NRI → data/nri_hubs.csv
uv run python -m scripts.ingest             # Open-Meteo → data/weather.db (~1 min, throttled)
uv run python -m scripts.score_report       # print the scorebook
```
