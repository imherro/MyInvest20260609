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
python -m uvicorn invest_system.web.app:app --app-dir src
```

Open:

```text
http://127.0.0.1:8000/
http://127.0.0.1:8000/system/status
http://127.0.0.1:8000/timeline/replay
http://127.0.0.1:8000/dashboard
```

## API

- `GET /`
- `GET /market/latest`
- `GET /research/latest`
- `GET /target-pool/latest`
- `GET /decision/latest`
- `GET /portfolio/state`
- `GET /timeline/replay`
- `GET /system/dashboard_state`
- `GET /system/status`

API responses are JSON. Read-only dashboard pages are view-layer HTML. FastAPI HTML docs are disabled.

Read-only view endpoints:

- `GET /dashboard`
- `GET /overview`
- `GET /portfolio/view`
- `GET /research/view`
- `GET /report/view`

View endpoints never write data and do not expose trading controls.

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

P1 read-only dashboard pages include:

- overview
- portfolio
- research
- report preview

The shared JSON state is available at `GET /system/dashboard_state`. Pages render from SQLite and JSON state only, do not write to the database, and do not include trade controls.

## Documentation

See `docs/SYSTEM_FINAL_CONTRACT.md` for the final runtime, schema, API, replay, and validation contract.
