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
- Read-only HTML dashboard views
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
- `schemas/market_data_bundle.schema.json`
- `schemas/report_manifest.schema.json`
- `schemas/risk_state.schema.json`
- `schemas/comparison_state.schema.json`
- `schemas/macro_state.schema.json`
- `schemas/model_consensus.schema.json`
- `schemas/entry_home_state.schema.json`

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

Read-only market data:

- `scripts/collect_market_data.py`

Validation:

- `scripts/system_self_check.py`
- `scripts/check_ratio_only.py`
- `scripts/check_research_first_gate.py`
- `scripts/check_cross_file_allocation_consistency.py`
- `scripts/project_check.py`
- `scripts/run_full_system_check.py`

P0c research generation:

- `scripts/generate_p0c_research.py`

P0b-real data collection:

- `scripts/collect_market_data.py`

Report generation:

- `scripts/generate_report.py`

## API Contract

Start the API:

```powershell
python -m uvicorn invest_system.web.app:app --app-dir src --host 127.0.0.1 --port 8008
```

Read-only JSON endpoints:

- `GET /`
- `GET /home`
- `GET /entry/home_state`
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

`/system/status` accepts optional `as_of=YYYY-MM-DD`.

HTML docs are intentionally disabled.

Read-only view endpoints:

- `GET /dashboard`
- `GET /overview`
- `GET /portfolio/view`
- `GET /research/view`
- `GET /report/view`

View endpoints are presentation only. They must not write to SQLite, change replay, expose trading controls, or display account IDs, amounts, shares, order IDs, fill IDs, trade amounts, or profit amounts.

## Replay Rule

`as_of=YYYY-MM-DD` replays by `basis_date`.

Full timestamps replay by `created_at`.

The replay chain must remain traceable:

```text
event_log -> market/research/target_pool -> decision -> portfolio
```

## P0c Research Contract

P0c research is stored in `research_snapshot` and must not change replay, event log, or shadow execution behavior.

Supported modules:

- `etf_valuation`
- `stock_valuation`
- `theme_research`
- `leader_ranking`
- `review_score`

Every P0c module must pass the generic research schema and its module-specific payload schema.

## Read-Only Data Adapter Contract

The P0b-real adapter layer supports:

- `tushare`
- `baostock`
- `yfinance`
- `fred`
- `mock`

All adapter results are normalized to `market_data_bundle.schema.json`. The bundle is then converted into the existing `market_snapshot` schema and appended through the same repository method as every other market snapshot.

Adapter rules:

- read-only external access only
- no write-back to external APIs
- no broker order or execution path
- no `event_log` schema change
- mock fallback remains available for offline replay and tests
- live-source failures are recorded in `data_gaps`

P0c research may consume the adapter bundle as price input while continuing to store outputs in `research_snapshot`.

## Report Derivation Contract

Reports are derived artifacts. JSON snapshots and SQLite remain the source of truth.

Supported report formats:

- Markdown
- HTML
- minimal PDF

Report generation rules:

- stdout must be a JSON manifest validated by `report_manifest.schema.json`
- report files are written under caller-selected output directories, defaulting to `temp/reports`
- reports may read `research_snapshot`, `decision_record`, `portfolio_snapshot`, `market_snapshot`, and replay state
- reports must not be parsed back into the database
- reports must not change replay, shadow execution, or `event_log`
- reports must remain ratio-only and must not include account IDs, amounts, shares, orders, fills, or local absolute paths

## Web Dashboard Contract

The P1 dashboard reads from SQLite and JSON state only.

Dashboard JSON:

- `GET /system/dashboard_state`

Dashboard views:

- `/dashboard`
- `/overview`
- `/portfolio/view`
- `/research/view`
- `/report/view`

Dashboard rules:

- read-only presentation only
- no database writes
- no trading forms or order controls
- no replay, shadow engine, or `event_log` changes
- no sensitive account, amount, share, order, fill, or local absolute path exposure

## Entry Layer Contract

The P1 entry layer is a read-only user guidance layer above the existing analytical system.

Entry APIs:

- `GET /home`
- `GET /entry/home_state`

Entry input sources:

- `/system/dashboard_state`
- `/risk/state`
- `/macro/state`
- `/comparison/state`
- `/portfolio/state`
- `/research/latest`

Entry output includes:

- market status card
- main theme card
- portfolio summary card
- risk snapshot card
- `next_action`
- `navigation_plan`

Entry rules:

- JSON output only
- read-only computation only
- no SQLite writes
- no trading or execution output
- no replay, shadow engine, risk engine, comparison system, macro system, or `event_log` changes
- schema validation through `entry_home_state.schema.json`
- `next_action` may point only to existing read-only JSON endpoints

## Risk Monitoring Contract

The P1 risk layer computes risk state from existing JSON snapshots only.

Risk APIs:

- `GET /risk/state`
- `GET /risk/history`

Risk output includes:

- `overall_risk_score`
- `exposure_warning`
- `concentration_risk`
- `deviation_from_research`
- `shadow_vs_market_gap`
- structured warnings

Risk rules:

- read-only computation only
- no SQLite writes
- no trading or execution output
- no replay, shadow engine, or `event_log` changes
- schema validation through `risk_state.schema.json`
- dashboard may display risk summary but must not expose sensitive data

## Comparison Analysis Contract

The P2 comparison layer computes read-only real-proxy, shadow, and benchmark comparisons from existing snapshots.

Comparison APIs:

- `GET /comparison/state`
- `GET /comparison/history`

Comparison output includes:

- return comparison
- drawdown comparison
- exposure comparison
- deviation analysis
- performance attribution
- ratio-only NAV curve points

Comparison rules:

- read-only computation only
- no SQLite writes
- no trading or execution output
- no replay, shadow engine, risk engine, or `event_log` changes
- schema validation through `comparison_state.schema.json`
- `real_proxy` must be clearly marked when detailed QMT ratio weights are unavailable

## Macro And Model Analysis Contract

The P2 macro layer computes read-only macro, model-consensus, and factor-decomposition JSON from existing snapshots.

Macro APIs:

- `GET /macro/state`
- `GET /macro/history`
- `GET /model/consensus`

Macro output includes:

- liquidity index
- rate pressure
- inflation regime
- risk cycle state
- multi-model consensus
- disagreement score
- calibrated confidence
- alpha factor decomposition
- signal contribution breakdown

Macro rules:

- read-only computation only
- no SQLite writes
- no trading or execution output
- no replay, shadow engine, comparison system, risk engine, or `event_log` changes
- schema validation through `macro_state.schema.json` and `model_consensus.schema.json`
- model consensus is explanatory analysis only and not an order instruction

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
