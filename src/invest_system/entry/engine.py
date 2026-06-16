from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from invest_system.comparison import compute_comparison_state
from invest_system.macro import compute_macro_state
from invest_system.repositories import SQLiteRepository
from invest_system.risk import compute_risk_state
from invest_system.validators.policies import assert_no_sensitive_content
from invest_system.validators.schema_validator import validate_or_raise


SOURCE_ENDPOINTS = [
    "/system/dashboard_state",
    "/risk/state",
    "/macro/state",
    "/comparison/state",
    "/portfolio/state",
    "/research/latest",
]


def build_home_state(repo: SQLiteRepository, as_of: str | None = None) -> dict[str, Any]:
    repo.init_db()
    replay = repo.replay_state(as_of)
    timeline = repo.timeline(as_of)
    market = replay.get("market")
    portfolio = replay.get("portfolio")
    research_items = _latest_research_by_module(timeline)
    risk = compute_risk_state(repo, as_of)
    macro = compute_macro_state(repo, as_of)
    comparison = compute_comparison_state(repo, as_of)
    cards = {
        "market_status": _market_status_card(market, macro),
        "main_theme": _main_theme_card(research_items),
        "portfolio_summary": _portfolio_summary_card(portfolio, comparison),
        "risk_snapshot": _risk_snapshot_card(risk),
    }
    next_action = _next_action(cards, macro, comparison)
    state = {
        "schema_version": "1.0",
        "status": "ok" if any([market, portfolio, research_items]) else "empty",
        "as_of": as_of,
        "generated_at": _utc_now(),
        "source_endpoints": SOURCE_ENDPOINTS,
        "cards": cards,
        "next_action": next_action,
        "navigation_plan": _navigation_plan(next_action["reason_code"]),
    }
    assert_no_sensitive_content(state)
    validate_or_raise(state, "entry_home_state.schema.json")
    return state


def _market_status_card(market: dict[str, Any] | None, macro: dict[str, Any]) -> dict[str, Any]:
    if market is None:
        return {"overall_market_state": "unavailable", "liquidity_index": 0, "risk_level": "unknown"}
    liquidity_index = 0
    if macro["status"] == "ok":
        liquidity_index = macro["macro_snapshot"]["liquidity_index"]
    payload = market["payload"]
    return {
        "overall_market_state": _overall_market_state(payload["risk_level"], payload["market_score"]),
        "liquidity_index": liquidity_index,
        "risk_level": payload["risk_level"],
    }


def _main_theme_card(research_items: list[dict[str, Any]]) -> dict[str, Any]:
    theme_item = _theme_research_item(research_items)
    if theme_item is None:
        return {
            "current_theme": None,
            "strength_score": None,
            "leading_symbols": [],
            "clarity_state": "unavailable",
        }
    payload = theme_item.get("payload", {})
    strength = payload.get("strength_score")
    return {
        "current_theme": payload.get("theme"),
        "strength_score": strength,
        "leading_symbols": payload.get("leading_symbols", []),
        "clarity_state": _theme_clarity(strength),
    }


def _portfolio_summary_card(
    portfolio: dict[str, Any] | None,
    comparison: dict[str, Any],
) -> dict[str, Any]:
    if portfolio is None:
        return {"shadow_return": 0, "benchmark_return": 0, "drawdown": 0}
    benchmark_return = 0
    if comparison["status"] == "ok":
        benchmark_return = comparison["return_comparison"]["benchmark_return"]
    return {
        "shadow_return": portfolio["pnl_ratio"],
        "benchmark_return": benchmark_return,
        "drawdown": portfolio["drawdown"],
    }


def _risk_snapshot_card(risk: dict[str, Any]) -> dict[str, Any]:
    if risk["status"] != "ok":
        return {"overall_risk_score": 0, "risk_level": "unknown", "exposure_warning": "unavailable"}
    return {
        "overall_risk_score": risk["overall_risk_score"],
        "risk_level": risk["risk_level"],
        "exposure_warning": risk["exposure_warning"],
    }


def _next_action(
    cards: dict[str, Any],
    macro: dict[str, Any],
    comparison: dict[str, Any],
) -> dict[str, Any]:
    risk = cards["risk_snapshot"]
    market = cards["market_status"]
    theme = cards["main_theme"]
    if risk["risk_level"] == "high" or risk["overall_risk_score"] >= 65:
        return _action(
            "/risk/state",
            "high_risk",
            "high",
            [
                "Risk level is high or the risk score crossed the high-risk threshold.",
                "Review risk warnings before checking portfolio changes.",
            ],
        )
    if macro["status"] == "ok" and macro["macro_snapshot"]["risk_cycle_state"] == "risk_off":
        return _action(
            "/macro/state",
            "volatile_macro",
            "high",
            [
                "Macro risk cycle is risk_off.",
                "Review macro pressure before comparing portfolio performance.",
            ],
        )
    if market["liquidity_index"] < 0.35:
        return _action(
            "/macro/state",
            "liquidity_watch",
            "medium",
            [
                "Liquidity index is below the normal operating range.",
                "Check macro state before using portfolio or comparison views.",
            ],
        )
    if theme["clarity_state"] in {"weak", "unavailable"}:
        return _action(
            "/research/latest",
            "weak_theme_clarity",
            "medium",
            [
                "Theme clarity is weak or unavailable.",
                "Review research snapshots before relying on portfolio conclusions.",
            ],
        )
    if comparison["status"] == "ok" and comparison["deviation_analysis"]["tracking_gap_pp"] >= 2:
        return _action(
            "/comparison/state",
            "tracking_gap",
            "medium",
            [
                "Shadow portfolio tracking gap is elevated.",
                "Compare shadow, real proxy, and benchmark before reviewing holdings.",
            ],
        )
    if risk["exposure_warning"] != "within_range":
        return _action(
            "/portfolio/state",
            "portfolio_exposure_review",
            "medium",
            [
                "Portfolio exposure is outside the target midpoint comfort zone.",
                "Review portfolio weights and target range before report generation.",
            ],
        )
    return _action(
        "/portfolio/state",
        "stable_market",
        "low",
        [
            "Market, macro, theme, and risk signals are stable enough for portfolio review.",
            "Start with portfolio state, then use the report preview for a full readout.",
        ],
    )


def _action(endpoint: str, reason_code: str, priority: str, reasoning: list[str]) -> dict[str, Any]:
    return {
        "recommended_next_view": endpoint,
        "recommended_endpoint": endpoint,
        "reason_code": reason_code,
        "reasoning": reasoning,
        "priority": priority,
    }


def _navigation_plan(reason_code: str) -> dict[str, Any]:
    if reason_code in {"high_risk", "portfolio_exposure_review"}:
        path_id = "high_risk"
        steps = [
            _step("Home", "/home"),
            _step("Risk", "/risk/state"),
            _step("Portfolio", "/portfolio/state"),
            _step("Comparison", "/comparison/state"),
        ]
    elif reason_code in {"volatile_macro", "liquidity_watch"}:
        path_id = "volatile_market"
        steps = [
            _step("Home", "/home"),
            _step("Macro", "/macro/state"),
            _step("Risk", "/risk/state"),
            _step("Comparison", "/comparison/state"),
        ]
    else:
        path_id = "normal_market"
        steps = [
            _step("Home", "/home"),
            _step("Market", "/market/latest"),
            _step("Research", "/research/latest"),
            _step("Portfolio", "/portfolio/state"),
            _step("Report", "/system/dashboard_state"),
        ]
    return {
        "path_id": path_id,
        "steps": steps,
        "shortcuts": [
            {"label": "Home", "endpoint": "/home"},
            {"label": "Risk", "endpoint": "/risk/state"},
            {"label": "Portfolio", "endpoint": "/portfolio/state"},
            {"label": "Research", "endpoint": "/research/latest"},
            {"label": "Report", "endpoint": "/system/dashboard_state"},
        ],
    }


def _step(label: str, endpoint: str) -> dict[str, str]:
    return {"label": label, "view": endpoint, "endpoint": endpoint}


def _theme_research_item(items: list[dict[str, Any]]) -> dict[str, Any] | None:
    for item in items:
        if item["module"] == "theme_research":
            return item
    return None


def _latest_research_by_module(timeline: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest_by_module: dict[str, dict[str, Any]] = {}
    for event in timeline:
        if event["type"] == "research":
            payload = event["payload"]
            latest_by_module[payload.get("module", "unknown")] = payload
    return list(latest_by_module.values())


def _overall_market_state(risk_level: str, market_score: float) -> str:
    if risk_level == "high" or market_score < 40:
        return "defensive"
    if market_score >= 60:
        return "constructive"
    return "balanced"


def _theme_clarity(strength: Any) -> str:
    if strength is None:
        return "unavailable"
    if strength >= 70:
        return "strong"
    if strength >= 45:
        return "medium"
    return "weak"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
