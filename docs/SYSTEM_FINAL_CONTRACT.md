# MyInvest Final System Contract

## Scope

MyInvest is a local A-share investment research, decision record, and shadow replay system. It is not an automatic trading system.

The delivered MVP supports:

- JSON-first research and decision snapshots
- Append-only SQLite history
- Target pool persistence
- Shadow portfolio paper simulation
- Multi-day replay by `basis_date`
- JSON-only read APIs
- JSON-only CLI validation and append workflows

## Hard Boundaries

The system must not:

- create real broker orders
- send data to QMT or any broker
- output account IDs, total assets, position amounts, share counts, order IDs, fill IDs, trade amounts, or profit amounts
- overwrite or delete historical records
- treat Markdown, HTML, or PDF as a source of truth

Allowed outputs are JSON records containing ratios, weights, percentage-point deltas, gate status, risk notes, trace IDs, and replay state.

## Runtime Contract

Use Python 3.14 or a compatible Python 3 runtime with dependencies from `requirements.txt`.

Initialize a local database:

```powershell
python scripts/init_db.py --db temp/system.sqlite
```

Seed a multi-day replay fixture:

```powershell
python scripts/seed_multiday_demo.py --db temp/system.sqlite
```

Run the system self-check:

```powershell
python scripts/system_self_check.py --db temp/system.sqlite --as-of 2026-06-14
```

Run the full smoke check:

```powershell
python scripts/run_full_system_check.py
```

## SQLite Data Model

Append-only snapshot tables:

- `market_snapshot`
- `research_snapshot`
- `target_pool_snapshot`
- `decision_record`
- `portfolio_snapshot`

Event table:

- `event_log`

Every snapshot append writes a matching event. QMT mock imports write `market_event` entries and, when successful, a `target_pool_snapshot`.

All key tables have triggers that block `UPDATE` and `DELETE`.

## JSON Schemas

Schema files:

- `schemas/market_snapshot.schema.json`
- `schemas/research.schema.json`
- `schemas/target_pool.schema.json`
- `schemas/decision.schema.json`
- `schemas/portfolio.schema.json`

Repository append methods validate schema and policy before writing.

## CLI Entrypoints

Database and fixtures:

- `scripts/init_db.py`
- `scripts/seed_demo.py`
- `scripts/seed_multiday_demo.py`

External JSON append:

- `scripts/append_research_snapshot.py`
- `scripts/append_decision.py`

QMT mock import:

- `scripts/import_qmt_positions.py`

Validation:

- `scripts/system_self_check.py`
- `scripts/check_ratio_only.py`
- `scripts/check_research_first_gate.py`
- `scripts/check_cross_file_allocation_consistency.py`
- `scripts/project_check.py`
- `scripts/run_full_system_check.py`

## API Contract

Start the API:

```powershell
python -m uvicorn invest_system.web.app:app --app-dir src
```

Read-only JSON endpoints:

- `GET /`
- `GET /market/latest`
- `GET /research/latest`
- `GET /target-pool/latest`
- `GET /decision/latest`
- `GET /portfolio/state`
- `GET /timeline/replay`
- `GET /system/status`

`/system/status` accepts optional `as_of=YYYY-MM-DD`.

HTML docs are intentionally disabled.

## Replay Rule

`as_of=YYYY-MM-DD` replays by `basis_date`.

Full timestamps replay by `created_at`.

The replay chain must remain traceable:

```text
event_log -> market/research/target_pool -> decision -> portfolio
```

## Final Verification

Required release checks:

```powershell
python -m pytest -W error
python -m compileall -q src scripts
python scripts/run_full_system_check.py
```

The smoke check must return JSON with:

- `status: passed`
- all self-checks passed
- all migrated policy checks passed
- API endpoint checks passed
- replay confidence score equal to `1.0`

