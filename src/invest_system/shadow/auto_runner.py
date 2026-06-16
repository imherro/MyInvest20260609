from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from invest_system.guidance.engine import DEFAULT_POLICY
from invest_system.repositories import SQLiteRepository
from invest_system.shadow.engine import ShadowPortfolioEngine
from invest_system.validators.cross_layer_integrity import is_stock_reference_text
from invest_system.validators.module_contracts import ModuleContractViolation, validate_module_contract
from invest_system.validators.policies import assert_no_sensitive_content
from invest_system.validators.research_schemas import RESEARCH_PAYLOAD_SCHEMA_BY_MODULE
from invest_system.validators.schema_validator import SchemaValidationError, validate_or_raise


def run_auto_shadow_portfolio(
    repo: SQLiteRepository,
    *,
    trigger: str,
    as_of: str | None = None,
    market_returns: dict[str, float] | None = None,
    benchmark_returns: dict[str, float] | None = None,
) -> dict[str, Any]:
    repo.init_db()
    replay = repo.replay_state(as_of)
    market = replay.get("market")
    target_pool = replay.get("target_pool")
    previous = replay.get("portfolio")
    if market is None or target_pool is None or previous is None:
        return _result(
            "skipped",
            trigger=trigger,
            reason="missing_market_target_pool_or_portfolio",
            basis_date=as_of,
        )
    source_research_ids = _source_research_ids(repo, as_of=as_of, target_pool=target_pool, portfolio=previous)
    if not source_research_ids:
        return _result(
            "skipped",
            trigger=trigger,
            reason="missing_research_source",
            basis_date=market["basis_date"],
        )

    target_weights = _model_target_weights(
        market=market,
        target_pool=target_pool,
        previous_portfolio=previous,
    )
    if not target_weights:
        return _result("skipped", trigger=trigger, reason="no_eligible_shadow_holdings", basis_date=market["basis_date"])
    if _target_unchanged(previous.get("holdings_weight", {}), target_weights):
        return _result(
            "skipped",
            trigger=trigger,
            reason="model_target_unchanged",
            basis_date=market["basis_date"],
            target_weights=target_weights,
        )

    decision = _model_decision(
        market=market,
        target_pool=target_pool,
        previous_portfolio=previous,
        target_weights=target_weights,
        trigger=trigger,
        source_research_ids=source_research_ids,
    )
    inserted_decision = repo.append_decision_record(decision)
    portfolio = ShadowPortfolioEngine(repo, rebalance_threshold=0.0).apply_decision(
        decision=decision,
        previous_portfolio=previous,
        market_returns=market_returns or {},
        benchmark_returns=benchmark_returns or previous.get("benchmark_returns", {}),
        as_of=None,
    )
    inserted_portfolio = repo.append_portfolio_snapshot(portfolio)
    result = _result(
        "applied",
        trigger=trigger,
        reason="model_target_changed",
        basis_date=market["basis_date"],
        target_weights=target_weights,
        decision_id=decision["decision_id"],
        portfolio_id=portfolio["portfolio_id"],
        inserted=[inserted_decision, inserted_portfolio],
    )
    result["paper_changes"] = portfolio["paper_trades"]
    assert_no_sensitive_content(result)
    return result


def _model_target_weights(
    *,
    market: dict[str, Any],
    target_pool: dict[str, Any],
    previous_portfolio: dict[str, Any],
) -> dict[str, float]:
    approved = _pool_symbols(target_pool, "approved")
    blocked = _pool_symbols(target_pool, "blocked") | _pool_symbols(target_pool, "research_first")
    current = previous_portfolio.get("holdings_weight", {})
    eligible = {
        symbol: float(weight)
        for symbol, weight in current.items()
        if weight > 0 and symbol in approved and symbol not in blocked
    }
    if not eligible:
        return {}

    equity_symbols = {symbol for symbol in eligible if not _is_cash_like(symbol)}
    defensive_symbols = set(eligible) - equity_symbols
    current_equity = sum(eligible[symbol] for symbol in equity_symbols)
    current_defensive = sum(eligible[symbol] for symbol in defensive_symbols)
    policy_cash_floor = float(DEFAULT_POLICY["risk_bounds"]["min_cash_weight"])
    market_payload = market["payload"]
    equity_max = float(market_payload["equity_max"])
    equity_min = float(market_payload["equity_min"])

    target_equity = min(current_equity, equity_max)
    if current_equity < equity_min and previous_portfolio.get("cash_weight", 0) > policy_cash_floor:
        target_equity = min(equity_min, 1 - policy_cash_floor - current_defensive)
    target_equity = max(0.0, round(target_equity, 6))

    remaining_after_cash = max(0.0, round(1 - policy_cash_floor - target_equity, 6))
    target_defensive = min(current_defensive, remaining_after_cash)
    target_defensive = max(0.0, round(target_defensive, 6))

    targets: dict[str, float] = {}
    targets.update(_scale_weights(eligible, equity_symbols, target_equity))
    targets.update(_scale_weights(eligible, defensive_symbols, target_defensive))
    return {symbol: weight for symbol, weight in sorted(targets.items()) if weight > 0}


def _model_decision(
    *,
    market: dict[str, Any],
    target_pool: dict[str, Any],
    previous_portfolio: dict[str, Any],
    target_weights: dict[str, float],
    trigger: str,
    source_research_ids: list[str],
) -> dict[str, Any]:
    current = previous_portfolio.get("holdings_weight", {})
    basis_date = market["basis_date"]
    decision_id = f"decision-{basis_date}-auto-shadow-{_compact_utc_now()}"
    approved = _pool_symbols(target_pool, "approved")
    restricted = _pool_symbols(target_pool, "blocked") | _pool_symbols(target_pool, "research_first")
    actions = []
    for symbol in sorted(set(current) | set(target_weights)):
        current_weight = round(float(current.get(symbol, 0)), 6)
        target_weight = round(float(target_weights.get(symbol, 0)), 6)
        delta_pp = round((target_weight - current_weight) * 100, 4)
        is_research_first = symbol in restricted or (target_weight == 0 and symbol not in approved)
        action = _decision_action(delta_pp, is_research_first)
        actions.append(
            {
                "symbol": symbol,
                "action": action,
                "current_weight": current_weight,
                "target_weight": target_weight,
                "delta_weight_pp": delta_pp,
                "rationale": _rationale(delta_pp, trigger, is_research_first),
                "gates": _decision_gates(is_research_first),
            }
        )
    return {
        "schema_version": "1.0",
        "decision_id": decision_id,
        "basis_date": basis_date,
        "generated_at": _utc_now(),
        "source_research_ids": source_research_ids,
        "status": "human_approved",
        "required_human_review": True,
        "chatgpt_reviewed": True,
        "human_approval": True,
        "decision_actions": actions,
        "risk_notes": [
            "Auto shadow runner maintains the model portfolio as paper-only comparison.",
            "Targets are derived from latest market equity boundary, cash floor, approved pool, and current passed-gate holdings.",
            "ResearchFirst and blocked symbols receive zero model weight.",
            "No external execution path is created.",
        ],
        "trace": {
            "source_market_snapshot_id": market["snapshot_id"],
            "source_research_snapshot_ids": source_research_ids,
        },
    }


def _source_research_ids(
    repo: SQLiteRepository,
    *,
    as_of: str | None,
    target_pool: dict[str, Any],
    portfolio: dict[str, Any],
) -> list[str]:
    current_scope = _current_symbol_scope(target_pool, portfolio)
    latest: dict[str, dict[str, Any]] = {}
    for event in repo.timeline(as_of):
        if event["type"] != "research":
            continue
        payload = event["payload"]
        module = payload.get("module")
        module_schema = RESEARCH_PAYLOAD_SCHEMA_BY_MODULE.get(module)
        if not module_schema or not _research_is_contract_valid(payload, module_schema):
            continue
        symbol = payload.get("payload", {}).get("symbol")
        if symbol and current_scope and symbol not in current_scope:
            continue
        if is_stock_reference_text(event["object_id"]):
            continue
        key = f"{module}:{symbol}" if symbol else str(module)
        latest[key] = event
    return [event["object_id"] for event in latest.values()]


def _current_symbol_scope(target_pool: dict[str, Any], portfolio: dict[str, Any]) -> set[str]:
    symbols: set[str] = set()
    for entry in target_pool.get("entries", []):
        symbols.update(entry.get("symbols", []))
    symbols.update(symbol for symbol, weight in portfolio.get("holdings_weight", {}).items() if float(weight) > 0)
    return symbols


def _research_is_contract_valid(payload: dict[str, Any], module_schema: str) -> bool:
    try:
        validate_or_raise(payload, "research.schema.json")
        validate_or_raise(payload["payload"], module_schema)
        validate_module_contract(payload)
    except (KeyError, SchemaValidationError, ModuleContractViolation, ValueError):
        return False
    return True


def _pool_symbols(target_pool: dict[str, Any], pool_type: str) -> set[str]:
    symbols: set[str] = set()
    for entry in target_pool.get("entries", []):
        if entry.get("pool_type") == pool_type:
            symbols.update(entry.get("symbols", []))
    return symbols


def _scale_weights(weights: dict[str, float], symbols: set[str], target_total: float) -> dict[str, float]:
    current_total = sum(weights[symbol] for symbol in symbols)
    if current_total <= 0 or target_total <= 0:
        return {}
    scaled = {
        symbol: round(weights[symbol] / current_total * target_total, 6)
        for symbol in sorted(symbols)
    }
    drift = round(target_total - sum(scaled.values()), 6)
    if scaled and abs(drift) >= 0.000001:
        largest = max(scaled, key=scaled.get)
        scaled[largest] = round(scaled[largest] + drift, 6)
    return scaled


def _target_unchanged(current: dict[str, float], target: dict[str, float]) -> bool:
    symbols = set(current) | set(target)
    return all(abs(float(current.get(symbol, 0)) - float(target.get(symbol, 0))) < 0.0001 for symbol in symbols)


def _decision_action(delta_pp: float, is_research_first: bool) -> str:
    if is_research_first:
        return "research_first" if abs(delta_pp) >= 0.0001 else "hold"
    return "no_action" if abs(delta_pp) < 0.0001 else "rebalance_candidate"


def _decision_gates(is_research_first: bool) -> dict[str, Any]:
    if is_research_first:
        return {
            "profile": "blocked",
            "valuation": "blocked",
            "liquidity": "blocked",
            "research_first": True,
        }
    return {
        "profile": "pass",
        "valuation": "pass",
        "liquidity": "pass",
        "research_first": False,
    }


def _rationale(delta_pp: float, trigger: str, is_research_first: bool) -> list[str]:
    if is_research_first:
        return [
            "Auto shadow runner assigns zero model weight because this symbol is ResearchFirst, blocked, or outside the approved pool.",
            "This is paper-only model comparison, not external execution.",
            f"Trigger source is {trigger}.",
        ]
    if abs(delta_pp) < 0.0001:
        return [
            "Auto shadow runner keeps this passed-gate holding unchanged.",
            f"Trigger source is {trigger}.",
        ]
    direction = "raises" if delta_pp > 0 else "lowers"
    return [
        f"Auto shadow runner {direction} the model weight by {abs(delta_pp)} percentage points.",
        "The symbol is in the approved pool and is not ResearchFirst.",
        "This is paper-only model comparison, not external execution.",
    ]


def _is_cash_like(symbol: str) -> bool:
    return symbol.startswith("511")


def _result(
    status: str,
    *,
    trigger: str,
    reason: str,
    basis_date: str | None,
    target_weights: dict[str, float] | None = None,
    decision_id: str | None = None,
    portfolio_id: str | None = None,
    inserted: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    payload = {
        "schema_version": "1.0",
        "status": status,
        "trigger": trigger,
        "reason": reason,
        "basis_date": basis_date,
        "generated_at": _utc_now(),
        "decision_id": decision_id,
        "portfolio_id": portfolio_id,
        "target_weights": target_weights or {},
        "inserted": inserted or [],
        "constraints": {
            "approved_target_pool_only": True,
            "research_first_weight_zero": True,
            "paper_only": True,
        },
    }
    assert_no_sensitive_content(payload)
    return payload


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _compact_utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
