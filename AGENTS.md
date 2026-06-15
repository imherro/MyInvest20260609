# AGENTS.md - MyInvest Project Instructions

## Project nature

MyInvest is a local A-share investment research and risk-control system. It is not an automatic trading system.

## Hard boundaries

1. ResearchFirst
   - No single-security buy/add/reduce/sell may be produced unless profile, valuation, and liquidity gates pass.
   - Cash/short-duration instruments must also pass liquidity, duration boundary, valuation, interest-rate risk, credit risk, and liquidity risk disclosure.

2. Ratio-only privacy
   - Research outputs, Web API responses, review packages, developer packages, and action plans must not contain total assets, monetary amount, market value, share count, available quantity, trade amount, profit amount, full account, local absolute paths, order records, or fill records.
   - Allowed fields include ratios, percentage points, target ranges, action types, gate status, and research blocking reasons.

3. Current-only default
   - Review and Web display default to research/latest_index.json modules.
   - Do not treat historical files outside latest_index.modules as current issues.

4. No real automatic trading
   - Do not add QMT write/trading/order placement features unless explicitly requested.
   - QMT holding import is read-only and local-only.
   - A shadow account may create paper-only simulated trades for strategy review.
   - Shadow-account holdings must be selected only from the approved target pool.
   - Shadow-account records are not broker orders and must never be sent to QMT or any broker.
   - Execution runtime must be local-only and excluded from Git, review packages, and developer packages unless explicitly requested.

5. Safety
   - .env, runtime, temp, caches, archives, databases, logs outside research, credentials, local absolute paths must not be committed or included in packages.

## Required validation

After changes, run:
- python scripts/check_ratio_only.py --path <latest_index.modules.action_plan.path>
- python scripts/check_research_first_gate.py --path <latest_index.modules.action_plan.path>
- python scripts/check_cross_file_allocation_consistency.py
- python scripts/project_check.py --current-only
- pytest if tests exist

Any ResearchFirst or ratio-only violation is a blocking failure.
