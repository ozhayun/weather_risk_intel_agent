# Weather Risk Intelligence Agent

AI agent that ranks, compares and explains weather-disruption exposure for 15 US logistics hubs.
Read `docs/01-requirements.md` (scope, query types, AI boundary) and `docs/02-scoring-model.md` (formula) before changing behavior.

## Stack

| Concern | Choice |
|---|---|
| Language / env | Python 3.12+, `uv` (deps + venv), `ruff` (lint + format) |
| Backend API | FastAPI + Pydantic v2 |
| Chat UI | Streamlit, talks to the API over HTTP only |
| LLM | `instructor.from_provider(LLM_MODEL)`: `openai/…`, `anthropic/…`, `ollama/…` set in `.env`, no code change |
| Storage | SQLite (stdlib `sqlite3`), single file under `data/` |
| Data | Open-Meteo Historical (daily, 2021–2025) + FEMA NRI static subset `data/nri_hubs.csv` |
| Tests / eval | `pytest` (unit tests + eval set) |

## Architecture rules (non-negotiable)

1. **The LLM never produces numbers, scores or rankings.** It turns language into a `QueryPlan` and turns a `Result` back into an `Answer`. All math lives in `domain/`.
2. **Pipeline, not an open-ended agent loop:** `interpret (LLM) → validate + execute (code) → narrate (LLM)`.
3. **Every LLM call has a Pydantic `response_model`** with `max_retries` set. Schemas live in one module, and plans are validated before any code runs.
4. **Dependency direction:** `api → agent → domain ← data`. `domain/` is pure: no I/O, no HTTP, no LLM, no SQL. `data/` owns all external I/O (APIs, SQLite).
5. **Runtime never calls FEMA**, and serving `/chat` never calls Open-Meteo. Ingest scripts fill SQLite, and the app only reads it.
6. **Config, not constants:** weights, caps and thresholds live in `config/scoring.toml` with a `version`. Hubs live in `data/hubs.json`. Secrets and the model name live in `.env` (never committed; keep `.env.example` current).
7. **Hub-only scope:** entities are resolved against the hub registry in code. Unknown locations become a scope message, never a guess.
8. **Uncertainty is data:** coverage and source-disagreement flags are computed in `domain/` and passed to the LLM, never invented by it.

## Coding standards

- **SOLID, applied pragmatically:**
  - One responsibility per module.
  - Depend on small `Protocol`s only where a second implementation is real (for example, the LLM client is faked in tests).
  - No interface that has only one implementation.
- **Lean files:** aim for under ~200 lines per module and under ~30 lines per function. Split by responsibility, not by line count.
- **Typed everywhere:** full type hints; Pydantic models at boundaries, dataclasses or plain types inside.
- **Pure functions** for metrics and scoring: same input, same output, easy to unit-test.
- **Errors:**
  - Validate at trust boundaries: user input, LLM output, external APIs.
  - Fail loudly in ingest, degrade gracefully in chat with a clarifying message.
  - Never swallow exceptions silently.
- **Naming:** `snake_case` functions and modules, `PascalCase` classes, `UPPER_SNAKE` constants. Units go in names (`gust_kmh`, `snow_cm`).
- **Style:**
  - Comments explain *why*, not *what*.
  - No dead code, no speculative abstractions, no scaffolding "for later".
  - Prefer the stdlib and already-installed dependencies before adding a new one.
- **Tests:**
  - Every scoring/metric function gets a unit test.
  - Tests never hit the network or a real LLM (use a fake client).
  - The eval set (`tests/eval/`) runs the real pipeline and is opt-in (`pytest -m eval`).

## Commands

```bash
uv sync                                    # install
uv run python -m scripts.build_nri_subset  # rebuild data/nri_hubs.csv (rarely)
uv run python -m scripts.ingest             # fetch Open-Meteo → SQLite (scores are computed at API startup)
uv run python -m scripts.score_report       # print the scorebook
uv run uvicorn app.api.main:app --reload   # API on :8000 (docs at /docs)
uv run streamlit run ui/app.py             # chat UI
uv run pytest                              # unit tests
uv run pytest -m eval                      # eval set (needs LLM key)
uv run ruff check . && uv run ruff format .
```

## Git workflow

- **`main` is always runnable.** Work on short-lived branches named `<type>/<short-kebab-desc>`, for example `feat/scoring-engine` or `fix/hub-alias-resolution`.
- **Conventional Commits:** `<type>(<scope>): <imperative summary>`, 72 characters max.
  - types: `feat`, `fix`, `refactor`, `test`, `docs`, `chore`, `build`
  - scopes: `domain`, `data`, `agent`, `api`, `ui`, `eval`, `config`, `docs`
- **Small commits:** one logical change each, and each one passes `ruff` and `pytest`.
- **Commit after every completed task.** Never leave finished work uncommitted.
- **Merge:** push, open a PR with `gh pr create`, merge with a merge commit (not squash) so the small-commit history stays visible.
- **Never commit:** `.env`, API keys, `.venv/`, caches. The SQLite demo file *is* committed on purpose, so the live demo works offline.
