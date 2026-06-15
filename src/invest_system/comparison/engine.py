from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from invest_system.repositories import SQLiteRepository
from invest_system.validators.policies import assert_no_sensitive_content
from invest_system.validators.schema_validator import validate_or_raise


def compute_comparison_state(repo: SQLiteRepository, as_of: str | None = None) -> dict[str, Any]:
    repo.init_db()
    replay = repo.replay_state(as_of)
    portfolio = replay.get("portfolio")
    target_pool = replay.get("target_pool")
    if portfolio is None:
        state = _empty_state(as_of)
        validate_or_raise(state, "comparison_state.schema.json")
        return state

    real_weights, real_source_id, real_source_note = _real_proxy_weights(target_pool, portfolio)
    shadow_weights = portfolio["holdings_weight"]
    allocation_overlap = _allocation_overlap(real_weights, shadow_weights)
    shadow_return = portfolio["pnl_ratio"]
    benchmark_return = _average_benchmark_return(portfolio)
    real_proxy_return = round(shadow_return * allocation_overlap + benchmark_return * (1 - allocation_overlap), 6)
    shadow_drawdown = portfolio["drawdown"]
    benchmark_drawdown = min(0, round(benchmark_return, 6))
    real_proxy_drawdown = min(0, round(real_proxy_return, 6))
    real_equity = _equity_weight(real_weights)
    shadow_equity = _equity_weight(shadow_weights)
    curve = _comparison_curve(repo)
    state = {
        "schema_version": "1.0",
        "status": "ok",
        "as_of": as_of,
        "generated_at": _utc_now(),
        "source_ids": {
            "real_proxy_source_id": real_source_id,
            "shadow_portfolio_id": portfolio["portfolio_id"],
            "benchmark_ids": sorted(portfolio.get("benchmark_returns", {}).keys()),
        },
        "return_comparison": {
            "real_proxy_return": real_proxy_return,
            "shadow_return": shadow_return,
            "benchmark_return": benchmark_return,
            "shadow_minus_benchmark": round(shadow_return - benchmark_return, 6),
            "real_proxy_minus_shadow": round(real_proxy_return - shadow_return, 6),
        },
        "drawdown_comparison": {
            "real_proxy_drawdown": real_proxy_drawdown,
            "shadow_drawdown": shadow_drawdown,
            "benchmark_drawdown": benchmark_drawdown,
        },
        "exposure_comparison": {
            "real_proxy_equity_weight": real_equity,
            "shadow_equity_weight": shadow_equity,
            "benchmark_equity_weight": 1,
            "active_exposure_pp": round((shadow_equity - real_equity) * 100, 4),
        },
        "deviation_analysis": {
            "tracking_gap_pp": round(abs(shadow_return - benchmark_return) * 100, 4),
            "allocation_overlap": allocation_overlap,
            "notes": [
                real_source_note,
                "Comparison is read-only and does not alter the shadow portfolio.",
            ],
        },
        "attribution": {
            "performance_attribution": _performance_attribution(shadow_return, benchmark_return, real_proxy_return),
            "source_of_return": _source_of_return(shadow_weights, portfolio),
            "risk_contribution": _risk_contribution(shadow_weights),
        },
        "curve": curve,
    }
    assert_no_sensitive_content(state)
    validate_or_raise(state, "comparison_state.schema.json")
    return state


def compute_comparison_history(repo: SQLiteRepository) -> dict[str, Any]:
    repo.init_db()
    basis_dates = sorted(
        {
            event["basis_date"]
            for event in repo.timeline()
            if event["type"] == "portfolio"
        }
    )
    items = [
        {
            "as_of": state["as_of"],
            "shadow_return": state["return_comparison"]["shadow_return"],
            "benchmark_return": state["return_comparison"]["benchmark_return"],
            "tracking_gap_pp": state["deviation_analysis"]["tracking_gap_pp"],
            "allocation_overlap": state["deviation_analysis"]["allocation_overlap"],
        }
        for state in (compute_comparison_state(repo, basis_date) for basis_date in basis_dates)
    ]
    result = {"status": "ok", "data": {"items": items}}
    assert_no_sensitive_content(result)
    return result


def _empty_state(as_of: str | None) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "status": "empty",
        "as_of": as_of,
        "generated_at": _utc_now(),
        "source_ids": {"real_proxy_source_id": None, "shadow_portfolio_id": None, "benchmark_ids": []},
        "return_comparison": {
            "real_proxy_return": 0,
            "shadow_return": 0,
            "benchmark_return": 0,
            "shadow_minus_benchmark": 0,
            "real_proxy_minus_shadow": 0,
        },
        "drawdown_comparison": {
            "real_proxy_drawdown": 0,
            "shadow_drawdown": 0,
            "benchmark_drawdown": 0,
        },
        "exposure_comparison": {
            "real_proxy_equity_weight": 0,
            "shadow_equity_weight": 0,
            "benchmark_equity_weight": 1,
            "active_exposure_pp": 0,
        },
        "deviation_analysis": {
            "tracking_gap_pp": 0,
            "allocation_overlap": 0,
            "notes": ["No portfolio replay state is available."],
        },
        "attribution": {
            "performance_attribution": [],
            "source_of_return": [],
            "risk_contribution": [],
        },
        "curve": [],
    }


def _real_proxy_weights(
    target_pool: dict[str, Any] | None,
    portfolio: dict[str, Any],
) -> tuple[dict[str, float], str | None, str]:
    if target_pool:
        approved = _symbols_for_pool(target_pool, "approved")
        if approved:
            weight = round(1 / len(approved), 6)
            return (
                {symbol: weight for symbol in approved},
                target_pool["target_pool_id"],
                "Real proxy uses approved QMT/target-pool symbols as equal-weight ratio input.",
            )
    holdings = portfolio["holdings_weight"]
    total = sum(holdings.values()) or 1
    return (
        {symbol: round(weight / total, 6) for symbol, weight in holdings.items()},
        portfolio["portfolio_id"],
        "Real proxy falls back to normalized shadow weights because no QMT ratio source is available.",
    )


def _symbols_for_pool(target_pool: dict[str, Any], pool_type: str) -> list[str]:
    for entry in target_pool["entries"]:
        if entry["pool_type"] == pool_type:
            return entry["symbols"]
    return []


def _allocation_overlap(left: dict[str, float], right: dict[str, float]) -> float:
    symbols = set(left) | set(right)
    if not symbols:
        return 0
    return round(sum(min(left.get(symbol, 0), right.get(symbol, 0)) for symbol in symbols), 6)


def _average_benchmark_return(portfolio: dict[str, Any]) -> float:
    values = list(portfolio.get("benchmark_returns", {}).values())
    if not values:
        return 0
    return round(sum(values) / len(values), 6)


def _equity_weight(weights: dict[str, float]) -> float:
    return round(sum(weight for symbol, weight in weights.items() if _is_equity_symbol(symbol)), 6)


def _comparison_curve(repo: SQLiteRepository) -> list[dict[str, Any]]:
    curve: list[dict[str, Any]] = []
    real_nav = 100.0
    benchmark_nav = 100.0
    previous_shadow_nav = 100.0
    for event in repo.timeline():
        if event["type"] != "portfolio":
            continue
        portfolio = event["payload"]
        shadow_nav = portfolio["nav_index"]
        shadow_return = 0 if not curve else shadow_nav / previous_shadow_nav - 1
        benchmark_return = _average_benchmark_return(portfolio)
        overlap = _allocation_overlap(portfolio["holdings_weight"], portfolio["holdings_weight"])
        real_return = shadow_return * overlap + benchmark_return * (1 - overlap)
        real_nav = round(real_nav * (1 + real_return), 6)
        benchmark_nav = round(benchmark_nav * (1 + benchmark_return), 6)
        previous_shadow_nav = shadow_nav
        curve.append(
            {
                "as_of": portfolio["basis_date"],
                "real_proxy_nav": real_nav,
                "shadow_nav": shadow_nav,
                "benchmark_nav": benchmark_nav,
            }
        )
    return curve


def _performance_attribution(shadow_return: float, benchmark_return: float, real_proxy_return: float) -> list[str]:
    return [
        f"Shadow minus benchmark return is {round((shadow_return - benchmark_return) * 100, 4)} pp.",
        f"Real proxy minus shadow return is {round((real_proxy_return - shadow_return) * 100, 4)} pp.",
    ]


def _source_of_return(weights: dict[str, float], portfolio: dict[str, Any]) -> list[str]:
    pnl_ratio = portfolio["pnl_ratio"]
    if not weights:
        return ["No holding weights are available for source-of-return attribution."]
    return [
        f"{symbol} contributes through weight {round(weight * 100, 4)}% under portfolio pnl ratio {round(pnl_ratio * 100, 4)}%."
        for symbol, weight in sorted(weights.items())
    ]


def _risk_contribution(weights: dict[str, float]) -> list[str]:
    if not weights:
        return ["No holding weights are available for risk contribution."]
    total_weight = sum(weights.values()) or 1
    return [
        f"{symbol} risk contribution proxy is {round(weight / total_weight * 100, 4)}%."
        for symbol, weight in sorted(weights.items())
    ]


def _is_equity_symbol(symbol: str) -> bool:
    return not symbol.startswith("511")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
