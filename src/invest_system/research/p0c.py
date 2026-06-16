from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from invest_system.repositories import SQLiteRepository
from invest_system.validators.cross_layer_integrity import validate_cross_layer_integrity
from invest_system.validators.module_contracts import validate_module_contract
from invest_system.validators.schema_validator import validate_or_raise


DEFAULT_PRICE_DATA = {
    "etfs": {
        "510300.SH": {
            "price": 3.82,
            "fair_value_mid": 4.05,
            "tracking_target": "CSI300",
            "volatility": 0.18,
        }
    },
    "stocks": {
        "002920.SZ": {
            "price": 28.6,
            "fair_value_mid": 31.0,
            "method": "three_factor_relative_valuation",
            "volatility": 0.28,
        }
    },
    "themes": [
        {
            "theme_id": "broad_market_recovery",
            "theme_name": "宽基修复主线",
            "sector": "broad_market",
            "return_signal": 0.62,
            "breadth_signal": 0.58,
            "liquidity_signal": 0.55,
            "leading_indicators": ["index breadth", "turnover resilience", "risk appetite"],
        }
    ],
}


def generate_p0c_research(
    repo: SQLiteRepository,
    basis_date: str,
    price_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    repo.init_db()
    data = price_data or DEFAULT_PRICE_DATA
    market = repo.latest_market(basis_date) or repo.latest_market()
    decision = repo.latest_decision(basis_date) or repo.latest_decision()
    portfolio = repo.latest_portfolio(basis_date) or repo.latest_portfolio()
    fact_pack_id = f"p0c-fact-pack-{basis_date}"
    market_id = market["snapshot_id"] if market else "market-unavailable"

    snapshots = [
        _etf_valuation_snapshot(basis_date, fact_pack_id, market_id, data),
        _stock_valuation_snapshot(basis_date, fact_pack_id, market_id, data),
        _theme_research_snapshot(basis_date, fact_pack_id, market_id, data),
        _review_score_snapshot(basis_date, fact_pack_id, market_id, decision, portfolio),
    ]

    inserted = []
    for snapshot, payload_schema in snapshots:
        validate_or_raise(snapshot["payload"], payload_schema)
        validate_or_raise(snapshot, "research.schema.json")
        validate_module_contract(snapshot)
        validate_cross_layer_integrity(snapshot)
        inserted.append(repo.append_research_snapshot(snapshot))
    return {"status": "ok", "inserted": inserted}


def _etf_valuation_snapshot(
    basis_date: str, fact_pack_id: str, market_id: str, data: dict[str, Any]
) -> tuple[dict[str, Any], str]:
    symbol, raw = next(iter(data["etfs"].items()))
    payload = _valuation_payload(
        symbol=symbol,
        price=raw["price"],
        fair_value_mid=raw["fair_value_mid"],
        method="tracking_target_relative_band",
        volatility=raw["volatility"],
    )
    payload["tracking_target"] = raw["tracking_target"]
    snapshot = _research_snapshot(
        basis_date=basis_date,
        module="etf_valuation",
        snapshot_id=f"etf-valuation-{basis_date}-{symbol}",
        fact_pack_id=fact_pack_id,
        market_id=market_id,
        summary=f"ETF valuation for {symbol} remains JSON-only and review-gated.",
        key_facts=[f"{symbol} observed level is compared with a ratio-only fair-value band."],
        reasoning=["Deviation from fair value determines score and risk flag."],
        risks=["Tracking error or delayed holdings disclosure can weaken the valuation signal."],
        payload=payload,
    )
    return snapshot, "etf_valuation_payload.schema.json"


def _stock_valuation_snapshot(
    basis_date: str, fact_pack_id: str, market_id: str, data: dict[str, Any]
) -> tuple[dict[str, Any], str]:
    symbol, raw = next(iter(data["stocks"].items()))
    payload, blocked_reasons = _stock_payload(symbol, raw)
    snapshot = _research_snapshot(
        basis_date=basis_date,
        module="stock_valuation",
        snapshot_id=f"stock-valuation-{basis_date}-{symbol}",
        fact_pack_id=fact_pack_id,
        market_id=market_id,
        summary=_stock_summary(symbol, blocked_reasons),
        key_facts=_stock_key_facts(blocked_reasons),
        reasoning=["Stock research fails closed when profile, valuation, or liquidity evidence is incomplete."],
        risks=["Single-name news and liquidity shocks can invalidate the score."],
        payload=payload,
        status="blocked" if blocked_reasons else "json_validated",
        actionability="research_first" if blocked_reasons else "observe",
    )
    return snapshot, "stock_valuation_payload.schema.json"


def _theme_research_snapshot(
    basis_date: str, fact_pack_id: str, market_id: str, data: dict[str, Any]
) -> tuple[dict[str, Any], str]:
    theme = data["themes"][0]
    strength_score = round(
        (theme["return_signal"] * 0.4 + theme["breadth_signal"] * 0.35 + theme["liquidity_signal"] * 0.25) * 100,
        4,
    )
    payload = {
        "theme_id": theme["theme_id"],
        "theme_name": theme["theme_name"],
        "sector": theme["sector"],
        "theme_state": _theme_state(strength_score),
        "signal_type": _theme_signal_types(theme),
        "leading_indicators": theme["leading_indicators"],
        "strength_score": strength_score,
    }
    snapshot = _research_snapshot(
        basis_date=basis_date,
        module="theme_research",
        snapshot_id=f"theme-research-{basis_date}-{theme['theme_id']}",
        fact_pack_id=fact_pack_id,
        market_id=market_id,
        summary=f"Theme {theme['theme_name']} is in {payload['theme_state']} state.",
        key_facts=[
            f"Theme state is {payload['theme_state']}.",
            f"Sector is {theme['sector']}.",
        ],
        reasoning=["Theme state is the decision-facing output; strength_score is non-decision context only."],
        risks=["Theme evidence is fixture-based until live data adapters are connected."],
        payload=payload,
    )
    return snapshot, "theme_research_payload.schema.json"


def _review_score_snapshot(
    basis_date: str,
    fact_pack_id: str,
    market_id: str,
    decision: dict[str, Any] | None,
    portfolio: dict[str, Any] | None,
) -> tuple[dict[str, Any], str]:
    portfolio_id = portfolio["portfolio_id"] if portfolio else "portfolio-unavailable"
    decision_id = decision["decision_id"] if decision else "decision-unavailable"
    pnl_ratio = portfolio.get("pnl_ratio", 0) if portfolio else 0
    turnover = portfolio.get("turnover", 0) if portfolio else 0
    decision_quality = 85 if decision and decision.get("human_approval") else 50
    risk_adjusted_proxy = round((pnl_ratio * 100) - (turnover * 10), 4)
    total_score = round(max(0, min(100, decision_quality * 0.65 + (50 + risk_adjusted_proxy) * 0.35)), 4)
    payload = {
        "total_score": total_score,
        "risk_adjusted_return_proxy": risk_adjusted_proxy,
        "decision_quality": decision_quality,
        "portfolio_trace": {
            "source_decision_id": decision_id,
            "portfolio_id": portfolio_id,
            "market_snapshot_id": market_id,
        },
        "score_reasons": [
            "Decision quality rewards reviewed and approved decisions.",
            "Risk-adjusted proxy penalizes turnover and reflects ratio-only PnL.",
        ],
    }
    snapshot = _research_snapshot(
        basis_date=basis_date,
        module="review_score",
        snapshot_id=f"review-score-{basis_date}",
        fact_pack_id=fact_pack_id,
        market_id=market_id,
        summary="Review score is derived from decision, portfolio, and market trace IDs.",
        key_facts=[f"Portfolio trace is {portfolio_id}.", f"Decision trace is {decision_id}."],
        reasoning=["The score is a review metric, not a trading instruction."],
        risks=["Review score is a proxy until richer benchmark data is connected."],
        payload=payload,
    )
    return snapshot, "review_score_payload.schema.json"


def _valuation_payload(
    *,
    symbol: str,
    price: float,
    fair_value_mid: float,
    method: str,
    volatility: float,
) -> dict[str, Any]:
    deviation = round((price - fair_value_mid) / fair_value_mid, 6)
    observed_to_fair_value_ratio = round(price / fair_value_mid, 6)
    valuation_score = round(max(0, min(100, 50 - deviation * 220)), 4)
    risk_flag = "high" if volatility >= 0.3 or abs(deviation) >= 0.18 else "medium" if volatility >= 0.2 else "low"
    rating = "Undervalued" if deviation <= -0.08 else "Overvalued" if deviation >= 0.08 else "Fair"
    return {
        "symbol": symbol,
        "valuation_score": valuation_score,
        "fair_value_band_pct": {"low": -0.08, "mid": 0, "high": 0.08},
        "observed_to_fair_value_ratio": observed_to_fair_value_ratio,
        "deviation": deviation,
        "risk_flag": risk_flag,
        "confidence": round(max(0.35, min(0.85, 0.82 - volatility * 0.5)), 4),
        "method": method,
        "rating": rating,
    }


def _stock_payload(symbol: str, raw: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    profile_gate = raw.get("profile_gate", "missing")
    liquidity_gate = raw.get("liquidity_gate", "missing")
    deviation = round((raw["price"] - raw["fair_value_mid"]) / raw["fair_value_mid"], 6)
    valuation_gate = raw.get("valuation_gate") or ("fail" if abs(deviation) >= 0.18 else "pass")
    risk_score = round(min(100, max(0, abs(deviation) * 220 + float(raw["volatility"]) * 100)), 4)
    gates = {
        "profile": profile_gate,
        "valuation": valuation_gate,
        "liquidity": liquidity_gate,
    }
    blocked = [
        name
        for name, value in gates.items()
        if value in {"missing", "blocked", "fail"}
    ]
    payload = {
        "symbol": symbol,
        "valuation_state": "blocked" if valuation_gate in {"missing", "blocked"} else valuation_gate,
        "research_first_status": "BLOCKED" if blocked else "PASSED",
        "risk_score": risk_score,
        "signal_type": ["valuation", "liquidity", "structural"],
        "gates": gates,
        "reason": (
            ["RESEARCH_FIRST_GATE", *[f"{name}_gate_{gates[name]}" for name in blocked]]
            if blocked
            else ["profile, valuation, and liquidity gates pass"]
        ),
    }
    return payload, blocked


def _stock_summary(symbol: str, blocked_reasons: list[str]) -> str:
    if blocked_reasons:
        return f"{symbol} is BLOCKED by RESEARCH_FIRST_GATE because required stock gates are incomplete."
    return f"{symbol} stock research passes profile, valuation, and liquidity gates."


def _stock_key_facts(blocked_reasons: list[str]) -> list[str]:
    if blocked_reasons:
        return [f"RESEARCH_FIRST_GATE blocks stock completion: {', '.join(blocked_reasons)}."]
    return ["Profile, valuation, and liquidity gates all pass."]


def _research_snapshot(
    *,
    basis_date: str,
    module: str,
    snapshot_id: str,
    fact_pack_id: str,
    market_id: str,
    summary: str,
    key_facts: list[str],
    reasoning: list[str],
    risks: list[str],
    payload: dict[str, Any],
    status: str = "json_validated",
    actionability: str = "observe",
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "snapshot_id": snapshot_id,
        "basis_date": basis_date,
        "generated_at": _utc_now(),
        "module": module,
        "data_sources": ["fixture:p0c_research_inputs"],
        "data_gaps": ["live_data_adapter_not_connected"],
        "conflicts": [],
        "executive_summary": summary,
        "key_facts": key_facts,
        "reasoning": reasoning,
        "risks": risks,
        "conclusion_strength": "medium",
        "actionability": actionability,
        "confidence": payload.get("confidence", 0.7) if isinstance(payload.get("confidence"), (int, float)) else 0.7,
        "invalidation_conditions": ["Source signal update invalidates current score."],
        "next_review_date": basis_date,
        "must_not_do": ["Do not treat research output as real broker execution."],
        "required_human_review": True,
        "status": status,
        "trace": {"fact_pack_id": fact_pack_id, "source_market_snapshot_id": market_id},
        "payload": payload,
    }


def _theme_state(score: float) -> str:
    if score < 35:
        return "exhausted"
    if score < 50:
        return "weakening"
    if score < 65:
        return "emerging"
    if score < 80:
        return "strengthening"
    return "dominant"


def _theme_signal_types(theme: dict[str, Any]) -> list[str]:
    signals = ["momentum", "liquidity", "structural"]
    if theme.get("valuation_signal") is not None:
        signals.append("valuation")
    if theme.get("risk_event_signal"):
        signals.append("risk_event")
    return signals


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
