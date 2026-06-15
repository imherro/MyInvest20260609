from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from invest_system.repositories import SQLiteRepository
from invest_system.validators.policies import assert_no_sensitive_content
from invest_system.validators.schema_validator import validate_or_raise


def compute_macro_state(repo: SQLiteRepository, as_of: str | None = None) -> dict[str, Any]:
    repo.init_db()
    replay = repo.replay_state(as_of)
    timeline = repo.timeline(as_of)
    market = replay.get("market")
    portfolio = replay.get("portfolio")
    research_items = _latest_research_by_module(timeline)
    if not any([market, portfolio, research_items]):
        state = _empty_macro_state(as_of)
        validate_or_raise(state, "macro_state.schema.json")
        return state

    macro_snapshot = _macro_snapshot(market, portfolio, as_of)
    consensus = _consensus_body(macro_snapshot, market, portfolio, research_items)
    factor_decomposition = _factor_decomposition(macro_snapshot, market, portfolio)
    state = {
        "schema_version": "1.0",
        "status": "ok",
        "as_of": as_of,
        "generated_at": _utc_now(),
        "source_ids": _source_ids(market, portfolio, research_items),
        "macro_snapshot": macro_snapshot,
        "model_consensus": consensus,
        "alpha_factor_decomposition": factor_decomposition,
    }
    assert_no_sensitive_content(state)
    validate_or_raise(state, "macro_state.schema.json")
    return state


def compute_macro_history(repo: SQLiteRepository) -> dict[str, Any]:
    repo.init_db()
    basis_dates = sorted(
        {
            event["basis_date"]
            for event in repo.timeline()
            if event["type"] in {"market", "research", "portfolio"}
        }
    )
    items = [
        {
            "as_of": state["as_of"],
            "liquidity_index": state["macro_snapshot"]["liquidity_index"],
            "rate_pressure": state["macro_snapshot"]["rate_pressure"],
            "inflation_regime": state["macro_snapshot"]["inflation_regime"],
            "risk_cycle_state": state["macro_snapshot"]["risk_cycle_state"],
            "consensus_score": state["model_consensus"]["consensus_score"],
            "disagreement_score": state["model_consensus"]["disagreement_score"],
        }
        for state in (compute_macro_state(repo, basis_date) for basis_date in basis_dates)
    ]
    result = {"status": "ok", "data": {"items": items}}
    assert_no_sensitive_content(result)
    return result


def compute_model_consensus(repo: SQLiteRepository, as_of: str | None = None) -> dict[str, Any]:
    repo.init_db()
    macro_state = compute_macro_state(repo, as_of)
    consensus = {
        "schema_version": "1.0",
        "status": macro_state["status"],
        "as_of": as_of,
        "generated_at": _utc_now(),
        "source_ids": macro_state["source_ids"],
        **macro_state["model_consensus"],
    }
    assert_no_sensitive_content(consensus)
    validate_or_raise(consensus, "model_consensus.schema.json")
    return consensus


def _empty_macro_state(as_of: str | None) -> dict[str, Any]:
    macro_snapshot = {
        "macro_snapshot_id": "macro-derived-empty",
        "basis_date": as_of,
        "liquidity_index": 0,
        "rate_pressure": 0,
        "inflation_regime": "neutral",
        "risk_cycle_state": "balanced",
        "data_gaps": ["No replay state is available for macro analysis."],
        "conflicts": [],
        "signals": [],
    }
    return {
        "schema_version": "1.0",
        "status": "empty",
        "as_of": as_of,
        "generated_at": _utc_now(),
        "source_ids": {"market_snapshot_id": None, "portfolio_id": None, "research_snapshot_ids": []},
        "macro_snapshot": macro_snapshot,
        "model_consensus": _empty_consensus_body(),
        "alpha_factor_decomposition": {
            "factors": [],
            "signal_contribution": [],
            "explanatory_notes": [],
        },
    }


def _latest_research_by_module(timeline: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest_by_module: dict[str, dict[str, Any]] = {}
    for event in timeline:
        if event["type"] == "research":
            payload = event["payload"]
            latest_by_module[payload.get("module", "unknown")] = payload
    return list(latest_by_module.values())


def _source_ids(
    market: dict[str, Any] | None,
    portfolio: dict[str, Any] | None,
    research_items: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "market_snapshot_id": market.get("snapshot_id") if market else None,
        "portfolio_id": portfolio.get("portfolio_id") if portfolio else None,
        "research_snapshot_ids": [item["snapshot_id"] for item in research_items],
    }


def _macro_snapshot(
    market: dict[str, Any] | None,
    portfolio: dict[str, Any] | None,
    as_of: str | None,
) -> dict[str, Any]:
    market_payload = market.get("payload") if market else {}
    market_score = float(market_payload.get("market_score", 50))
    crowding = float(market_payload.get("crowding_penalty", 0))
    confidence = float(market.get("confidence", 0.5)) if market else 0.5
    cash_weight = float(portfolio.get("cash_weight", 0)) if portfolio else 0
    liquidity_index = _bounded(
        0.2 + confidence * 0.3 + (1 - crowding / 100) * 0.3 + cash_weight * 0.2,
        0,
        1,
    )
    rate_pressure = _bounded(_risk_level_pressure(market) + crowding / 200, 0, 1)
    macro_snapshot = {
        "macro_snapshot_id": f"macro-derived-{_basis_date(market, portfolio, as_of) or 'latest'}",
        "basis_date": _basis_date(market, portfolio, as_of),
        "liquidity_index": round(liquidity_index, 6),
        "rate_pressure": round(rate_pressure, 6),
        "inflation_regime": _inflation_regime(rate_pressure),
        "risk_cycle_state": _risk_cycle_state(liquidity_index, rate_pressure, market_score),
        "data_gaps": _data_gaps(market),
        "conflicts": _conflicts(market),
        "signals": [
            {"name": "market_score", "value": round(market_score / 100, 6), "source": "market_snapshot"},
            {"name": "liquidity_index", "value": round(liquidity_index, 6), "source": "derived_macro"},
            {"name": "rate_pressure", "value": round(rate_pressure, 6), "source": "derived_macro"},
            {"name": "cash_buffer", "value": round(cash_weight, 6), "source": "portfolio_snapshot"},
        ],
    }
    return macro_snapshot


def _consensus_body(
    macro_snapshot: dict[str, Any],
    market: dict[str, Any] | None,
    portfolio: dict[str, Any] | None,
    research_items: list[dict[str, Any]],
) -> dict[str, Any]:
    liquidity = macro_snapshot["liquidity_index"]
    rate_pressure = macro_snapshot["rate_pressure"]
    macro_score = _bounded((liquidity * 70) + ((1 - rate_pressure) * 30), 0, 100)
    market_score = float(market["payload"]["market_score"]) if market else 50
    portfolio_score = _portfolio_alignment_score(market, portfolio)
    research_score = _research_confidence_score(research_items)
    models = [
        _model("macro_cycle", macro_score, _average([liquidity, 1 - rate_pressure]), [
            f"Liquidity index is {round(liquidity, 4)}.",
            f"Rate pressure is {round(rate_pressure, 4)}.",
        ]),
        _model("market_position", market_score, float(market.get("confidence", 0.5)) if market else 0.5, [
            f"Market score is {round(market_score, 4)}.",
            f"Risk cycle state is {macro_snapshot['risk_cycle_state']}.",
        ]),
        _model("portfolio_alignment", portfolio_score, 0.7 if portfolio else 0.35, [
            "Portfolio alignment uses ratio-only equity exposure versus market target midpoint.",
        ]),
        _model("research_quality", research_score, _research_confidence(research_items), [
            f"Research snapshot count is {len(research_items)}.",
        ]),
    ]
    scores = [item["score"] for item in models]
    confidences = [item["confidence"] for item in models]
    consensus_score = round(_average(scores), 4)
    disagreement_score = round((max(scores) - min(scores)) / 100 if scores else 0, 6)
    calibrated_confidence = round(_bounded(_average(confidences) * (1 - disagreement_score * 0.5), 0, 1), 6)
    return {
        "models": models,
        "consensus_score": consensus_score,
        "consensus_state": _consensus_state(consensus_score),
        "disagreement_score": disagreement_score,
        "calibrated_confidence": calibrated_confidence,
        "notes": [
            "Consensus is a read-only analysis output and is not a trading instruction.",
            "Model scores are derived from existing JSON snapshots only.",
        ],
    }


def _empty_consensus_body() -> dict[str, Any]:
    return {
        "models": [],
        "consensus_score": 0,
        "consensus_state": "neutral",
        "disagreement_score": 0,
        "calibrated_confidence": 0,
        "notes": [],
    }


def _factor_decomposition(
    macro_snapshot: dict[str, Any],
    market: dict[str, Any] | None,
    portfolio: dict[str, Any] | None,
) -> dict[str, Any]:
    market_score = float(market["payload"]["market_score"]) if market else 50
    equity_alignment = _portfolio_alignment_factor(market, portfolio)
    benchmark_gap = _benchmark_gap_factor(portfolio)
    factors = [
        _factor("macro_liquidity", (macro_snapshot["liquidity_index"] - 0.5) * 2, "macro_snapshot"),
        _factor("rate_pressure", (0.5 - macro_snapshot["rate_pressure"]) * 2, "macro_snapshot"),
        _factor("market_momentum", (market_score / 100 - 0.5) * 2, "market_snapshot"),
        _factor("portfolio_alignment", equity_alignment, "portfolio_snapshot"),
        _factor("shadow_alpha_proxy", benchmark_gap, "portfolio_snapshot"),
    ]
    signal_contribution = [
        {"signal": item["factor"], "weight": round(1 / len(factors), 6), "value": item["contribution_score"]}
        for item in factors
    ]
    return {
        "factors": factors,
        "signal_contribution": signal_contribution,
        "explanatory_notes": [
            "Alpha decomposition is a ratio-only explanatory proxy.",
            "No factor output changes the shadow portfolio or real holdings.",
        ],
    }


def _model(model_id: str, score: float, confidence: float, evidence: list[str]) -> dict[str, Any]:
    bounded_score = round(_bounded(score, 0, 100), 4)
    return {
        "model_id": model_id,
        "score": bounded_score,
        "stance": _consensus_state(bounded_score),
        "confidence": round(_bounded(confidence, 0, 1), 6),
        "evidence": evidence,
    }


def _factor(factor: str, contribution_score: float, source: str) -> dict[str, Any]:
    bounded_score = round(_bounded(contribution_score, -1, 1), 6)
    return {
        "factor": factor,
        "contribution_score": bounded_score,
        "direction": _direction(bounded_score),
        "source": source,
    }


def _portfolio_alignment_score(market: dict[str, Any] | None, portfolio: dict[str, Any] | None) -> float:
    if not market or not portfolio:
        return 50
    target_mid = _market_target_mid(market)
    equity_weight = _equity_weight(portfolio)
    return round(_bounded(100 - abs(equity_weight - target_mid) * 250, 0, 100), 4)


def _portfolio_alignment_factor(market: dict[str, Any] | None, portfolio: dict[str, Any] | None) -> float:
    if not market or not portfolio:
        return 0
    target_mid = _market_target_mid(market)
    equity_weight = _equity_weight(portfolio)
    return round(_bounded(1 - abs(equity_weight - target_mid) * 5, -1, 1), 6)


def _benchmark_gap_factor(portfolio: dict[str, Any] | None) -> float:
    if not portfolio:
        return 0
    benchmarks = portfolio.get("benchmark_returns", {})
    benchmark_return = _average(list(benchmarks.values())) if benchmarks else 0
    return round(_bounded((portfolio["pnl_ratio"] - benchmark_return) * 25, -1, 1), 6)


def _research_confidence_score(research_items: list[dict[str, Any]]) -> float:
    if not research_items:
        return 50
    return round(_research_confidence(research_items) * 100, 4)


def _research_confidence(research_items: list[dict[str, Any]]) -> float:
    if not research_items:
        return 0.35
    return _average([float(item["confidence"]) for item in research_items])


def _risk_level_pressure(market: dict[str, Any] | None) -> float:
    if not market:
        return 0.5
    risk_level = market["payload"]["risk_level"]
    if risk_level == "high":
        return 0.65
    if risk_level == "medium":
        return 0.45
    return 0.25


def _inflation_regime(rate_pressure: float) -> str:
    if rate_pressure >= 0.65:
        return "elevated"
    if rate_pressure >= 0.35:
        return "neutral"
    return "benign"


def _risk_cycle_state(liquidity_index: float, rate_pressure: float, market_score: float) -> str:
    if rate_pressure >= 0.7 or market_score <= 35:
        return "risk_off"
    if liquidity_index >= 0.6 and market_score >= 55:
        return "risk_on"
    return "balanced"


def _consensus_state(score: float) -> str:
    if score >= 60:
        return "risk_on"
    if score >= 40:
        return "neutral"
    return "risk_off"


def _direction(score: float) -> str:
    if score > 0.05:
        return "positive"
    if score < -0.05:
        return "negative"
    return "neutral"


def _basis_date(
    market: dict[str, Any] | None,
    portfolio: dict[str, Any] | None,
    as_of: str | None,
) -> str | None:
    if as_of and len(as_of) == 10:
        return as_of
    if portfolio:
        return portfolio["basis_date"]
    if market:
        return market["basis_date"]
    return as_of


def _data_gaps(market: dict[str, Any] | None) -> list[str]:
    if not market:
        return ["No market snapshot is available for macro overlay."]
    return list(market.get("data_gaps", []))


def _conflicts(market: dict[str, Any] | None) -> list[str]:
    if not market:
        return []
    return list(market.get("conflicts", []))


def _market_target_mid(market: dict[str, Any]) -> float:
    payload = market["payload"]
    return round((payload["equity_min"] + payload["equity_max"]) / 2, 6)


def _equity_weight(portfolio: dict[str, Any]) -> float:
    return round(sum(weight for symbol, weight in portfolio["holdings_weight"].items() if _is_equity_symbol(symbol)), 6)


def _is_equity_symbol(symbol: str) -> bool:
    return not symbol.startswith("511")


def _average(values: list[float]) -> float:
    if not values:
        return 0
    return sum(values) / len(values)


def _bounded(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
