# MyInvest20260609

Local JSON-first investment research, decision record, and shadow portfolio replay system.

This project is not an automatic trading system. It stores auditable JSON snapshots, append-only history, and paper-only shadow portfolio replay.

## Quick Start

```powershell
python scripts/run_full_system_check.py
```

The command creates a temporary validation database, seeds a three-day replay fixture, runs self-checks, validates policy gates, and calls the JSON API handlers.

## Run API

```powershell
python -m uvicorn invest_system.web.app:app --app-dir src --host 127.0.0.1 --port 8008
```

Open:

```text
http://127.0.0.1:8008/
http://127.0.0.1:8008/app
http://127.0.0.1:8008/workflow/daily/view
http://127.0.0.1:8008/home
http://127.0.0.1:8008/home_human
http://127.0.0.1:8008/guidance/view
http://127.0.0.1:8008/research/import/view
http://127.0.0.1:8008/usability/view
http://127.0.0.1:8008/system/status
http://127.0.0.1:8008/timeline/replay
http://127.0.0.1:8008/dashboard
```

## API

- `GET /`
- `GET /home`
- `GET /entry/home_state`
- `GET /workflow/daily/state`
- `GET /guidance/state`
- `GET /usability/state`
- `POST /research/import/validate`
- `POST /research/import`
- `GET /decision/proposal`
- `GET /decision/explain`
- `GET /market/latest`
- `GET /research/latest`
- `GET /target-pool/latest`
- `GET /decision/latest`
- `GET /portfolio/state`
- `GET /timeline/replay`
- `GET /comparison/state`
- `GET /comparison/history`
- `GET /macro/state`
- `GET /macro/history`
- `GET /model/consensus`
- `GET /risk/state`
- `GET /risk/history`
- `GET /system/dashboard_state`
- `GET /system/status`

API responses are JSON. Read-only dashboard pages are view-layer HTML. FastAPI HTML docs are disabled.

Read-only view endpoints:

- `GET /app`
- `GET /home_human`
- `GET /workflow/daily/view`
- `GET /guidance/view`
- `GET /dashboard`
- `GET /overview`
- `GET /market/view`
- `GET /risk/view`
- `GET /macro/view`
- `GET /comparison/view`
- `GET /decision/view`
- `GET /portfolio/view`
- `GET /research/view`
- `GET /research/import/view`
- `GET /report/view`
- `GET /system/view`
- `GET /usability/view`

GET view endpoints do not write data and do not expose trading controls. `/research/import/view` can call the JSON import APIs after the user provides research JSON; those APIs append only to `research_snapshot` and `event_log`. `/app` is the unified natural-person browser entry with shared header, footer, feature entrances, next-step guidance, and usability checks. `/home_human` remains as a compatible human entry route and renders through the same portal shell.

## Validation

```powershell
python -m pytest -W error
python -m compileall -q src scripts
python scripts/run_full_system_check.py
```

Policy checks:

```powershell
python scripts/check_ratio_only.py --db temp/full_system_check.sqlite
python scripts/check_research_first_gate.py --db temp/full_system_check.sqlite
python scripts/check_cross_file_allocation_consistency.py --db temp/full_system_check.sqlite
python scripts/project_check.py --current-only --db temp/full_system_check.sqlite
```

Generate P0c research snapshots:

```powershell
python scripts/generate_p0c_research.py --db temp/full_system_check.sqlite --basis-date 2026-06-15
```

Collect read-only market data and append it as a market snapshot:

```powershell
python scripts/collect_market_data.py --db temp/full_system_check.sqlite --basis-date 2026-06-15 --source auto
```

Use `--allow-network` only when local credentials and optional data packages are ready. Without live access, the command records `data_gaps` and falls back to deterministic mock data.

Generate derived reports from JSON and SQLite:

```powershell
python scripts/generate_report.py --db temp/full_system_check.sqlite --as-of 2026-06-15 --format markdown --format html
```

The command writes report files under `temp/reports` by default and prints a JSON manifest to stdout. JSON and SQLite remain the source of truth.

## Data Model

Append-only tables:

- `market_snapshot`
- `research_snapshot`
- `target_pool_snapshot`
- `decision_record`
- `portfolio_snapshot`
- `event_log`

SQLite triggers block historical `UPDATE` and `DELETE`.

## Research Modules

P0c research snapshots currently include:

- ETF valuation
- stock valuation
- theme research
- leader ranking
- review score

## Data Adapters

P0b-real read-only adapters currently include:

- Tushare
- BaoStock
- yfinance
- FRED
- mock fallback

Adapter output is normalized to `market_data_bundle.schema.json` and then converted into the existing `market_snapshot` schema. The adapter layer never writes to external systems and never creates trading instructions.

## Report Renderer

P1 report generation currently supports:

- Markdown
- HTML
- minimal PDF

Reports are derived views. They are generated from `research_snapshot`, `decision_record`, `portfolio_snapshot`, and replay state, and they are never parsed back into the database.

## Web Dashboard

P1 read-only B/S portal pages include:

- unified home
- daily research workflow
- today's action boundary
- market
- risk
- macro
- comparison
- decision preview
- shadow portfolio
- research
- research JSON import
- report preview
- system status
- usability checks

The shared JSON state is available at `GET /system/dashboard_state`. Pages render from SQLite and JSON state only, do not write to the database, and do not include trade controls.
The primary browser entry is `GET /app`. All main portal pages use a shared header and footer so a non-technical user can move between modules without remembering raw API paths.

## Daily Workflow

The daily workflow answers what is missing before the system can be used for the day.

- `GET /workflow/daily/state` returns stable JSON.
- `GET /workflow/daily/view` renders the same status in the unified portal shell.

It checks:

- market snapshot
- mainline `theme_research`
- today's action boundary
- shadow portfolio replay
- report preview readiness
- decision proposal preview

The workflow is a status and guidance layer. It does not collect data, generate research, write SQLite, or create execution output.

## Research Import

Research import standardizes how externally generated research enters the system.

- `POST /research/import/validate` validates research JSON without writing.
- `POST /research/import` validates and appends a research snapshot.
- `GET /research/import/view` provides the browser page for paste, validate, and append.

The import path validates `research.schema.json`, known module payload schemas, ratio-only policy, ResearchFirst policy, and duplicate `snapshot_id`. Successful import writes append-only records to `research_snapshot` and `event_log`.

## Decision Proposal

The decision proposal layer is read-only and explanatory.

- `GET /decision/proposal` returns a structured proposal JSON.
- `GET /decision/explain` returns the explanation chain.
- `GET /decision/view` renders the same proposal in the unified portal shell.

Allowed proposal actions are:

- `observe`
- `research_first`
- `rebalance_candidate`
- `no_action`

The layer derives from existing market, research, risk, macro, portfolio, and guidance state. It does not write `decision_record`, does not mutate the shadow portfolio, does not change replay, and does not create external execution output.

## Entry Layer

P1 entry layer JSON APIs are read-only and JSON-only. They compute:

- market status card
- main theme card
- portfolio summary card
- risk snapshot card
- next action guidance
- navigation plan

Entry APIs are `GET /home` and `GET /entry/home_state`. They derive guidance from existing dashboard, risk, macro, comparison, portfolio, and research state without writing to SQLite or changing core replay behavior.

The human entry view is `GET /home_human`. It is a derived HTML presentation of the same `/home` state. It does not add analysis logic, write SQLite, change replay, or create execution output.
The B/S portal uses the same entry state and exposes it at `GET /app` with feature entrances and a recommended-use flow.

## Guidance Layer

The guidance layer is the first page to check before considering any action.

- `GET /guidance/state` returns stable JSON.
- `GET /guidance/view` renders a plain-language "today action boundary" page.
- `config/investor_policy.json` stores ratio-only risk boundaries, data freshness limits, ResearchFirst behavior, and paper-only execution policy.

The layer checks:

- personal risk boundaries
- daily data freshness
- ResearchFirst queue and gate coverage
- portfolio risk limits
- replay availability
- paper-only execution boundary

It does not place orders, write SQLite, change replay, change the shadow engine, or produce external execution instructions.

## Usability Layer

The usability layer checks whether the browser system is usable by a natural person.

- `GET /usability/state` returns stable JSON.
- `GET /usability/view` renders the same checks in the unified portal shell.

It checks the primary home, shared header, shared footer, visible feature entrances, next-step guidance, guidance boundary visibility, JSON source availability, and read-only boundary.

## Risk Monitoring

P1 risk monitoring is read-only and computes:

- overall risk score
- exposure warning
- concentration risk
- deviation from research or decision targets
- shadow-vs-market gap

Risk APIs are `GET /risk/state` and `GET /risk/history`. They compute from existing snapshots and never write to SQLite.

## Comparison Analysis

P2 comparison analysis is read-only and computes:

- real-proxy vs shadow vs benchmark return comparison
- drawdown comparison
- exposure comparison
- deviation analysis
- performance attribution

Comparison APIs are `GET /comparison/state` and `GET /comparison/history`. The real side is a ratio-only `real_proxy` derived from QMT/target-pool symbols when detailed ratio weights are not available.

## Macro And Model Analysis

P2 macro analysis is read-only and computes:

- macro overlay state with liquidity index, rate pressure, inflation regime, and risk cycle state
- multi-model consensus with disagreement score and calibrated confidence
- alpha factor decomposition with ratio-only signal contribution

Macro APIs are `GET /macro/state`, `GET /macro/history`, and `GET /model/consensus`. They derive JSON from existing snapshots and never write to SQLite.

## Documentation

See `docs/SYSTEM_FINAL_CONTRACT.md` for the final runtime, schema, API, replay, and validation contract.
