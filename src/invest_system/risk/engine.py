from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from invest_system.repositories import SQLiteRepository
from invest_system.validators.policies import assert_no_sensitive_content
from invest_system.validators.schema_validator import validate_or_raise


def compute_risk_state(repo: SQLiteRepository, as_of: str | None = None) -> dict[str, Any]:
    repo.init_db()
    replay = repo.replay_state(as_of)
    market = replay.get("market")
    research = replay.get("research")
    decision = replay.get("decision")
    portfolio = replay.get("portfolio")
    if not any([market, research, decision, portfolio]):
        risk_state = _empty_state(as_of)
        validate_or_raise(risk_state, "risk_state.schema.json")
        return risk_state

    equity_weight = _equity_weight(portfolio)
    market_mid = _market_target_mid(market)
    exposure_deviation_pp = 0 if market_mid is None else round((equity_weight - market_mid) * 100, 4)
    concentration_risk = _concentration_risk(portfolio)
    decision_gap = _decision_gap_pp(decision, portfolio)
    shadow_gap = _shadow_vs_market_gap_pp(portfolio)
    crowding = _crowding_penalty(market)
    warnings = _warnings(
        exposure_deviation_pp=exposure_deviation_pp,
        concentration_risk=concentration_risk,
        decision_gap=decision_gap,
        shadow_gap=shadow_gap,
        crowding=crowding,
        market=market,
        research=research,
    )
    score = _overall_score(
        exposure_deviation_pp=exposure_deviation_pp,
        concentration_risk=concentration_risk,
        decision_gap=decision_gap,
        shadow_gap=shadow_gap,
        crowding=crowding,
        warning_count=len(warnings),
    )
    risk_state = {
        "schema_version": "1.0",
        "status": "ok",
        "as_of": as_of,
        "generated_at": _utc_now(),
        "overall_risk_score": score,
        "risk_level": _risk_level(score),
        "exposure_warning": _exposure_warning(exposure_deviation_pp),
        "concentration_risk": concentration_risk,
        "deviation_from_research": decision_gap,
        "shadow_vs_market_gap": shadow_gap,
        "warnings": warnings,
        "source_ids": {
            "market_snapshot_id": market.get("snapshot_id") if market else None,
            "decision_id": decision.get("decision_id") if decision else None,
            "portfolio_id": portfolio.get("portfolio_id") if portfolio else None,
            "research_snapshot_id": research.get("snapshot_id") if research else None,
        },
    }
    assert_no_sensitive_content(risk_state)
    validate_or_raise(risk_state, "risk_state.schema.json")
    return risk_state


def compute_risk_history(repo: SQLiteRepository) -> dict[str, Any]:
    repo.init_db()
    basis_dates = sorted(
        {
            event["basis_date"]
            for event in repo.timeline()
            if event["type"] == "portfolio"
        }
    )
    items = [_history_item(compute_risk_state(repo, basis_date)) for basis_date in basis_dates]
    result = {"status": "ok", "data": {"items": items}}
    assert_no_sensitive_content(result)
    return result


def _history_item(risk_state: dict[str, Any]) -> dict[str, Any]:
    return {
        "as_of": risk_state["as_of"],
        "overall_risk_score": risk_state["overall_risk_score"],
        "risk_level": risk_state["risk_level"],
        "warning_count": len(risk_state["warnings"]),
        "portfolio_id": risk_state["source_ids"]["portfolio_id"],
    }


def _empty_state(as_of: str | None) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "status": "empty",
        "as_of": as_of,
        "generated_at": _utc_now(),
        "overall_risk_score": 0,
        "risk_level": "low",
        "exposure_warning": "no_replay_state",
        "concentration_risk": 0,
        "deviation_from_research": 0,
        "shadow_vs_market_gap": 0,
        "warnings": [],
        "source_ids": {
            "market_snapshot_id": None,
            "decision_id": None,
            "portfolio_id": None,
            "research_snapshot_id": None,
        },
    }


def _equity_weight(portfolio: dict[str, Any] | None) -> float:
    if not portfolio:
        return 0
    return round(
        sum(weight for symbol, weight in portfolio["holdings_weight"].items() if _is_equity_symbol(symbol)),
        6,
    )


def _market_target_mid(market: dict[str, Any] | None) -> float | None:
    if not market:
        return None
    payload = market["payload"]
    return round((payload["equity_min"] + payload["equity_max"]) / 2, 6)


def _concentration_risk(portfolio: dict[str, Any] | None) -> float:
    if not portfolio or not portfolio["holdings_weight"]:
        return 0
    max_weight = max(portfolio["holdings_weight"].values())
    return round(max_weight * 100, 4)


def _decision_gap_pp(decision: dict[str, Any] | None, portfolio: dict[str, Any] | None) -> float:
    if not decision or not portfolio:
        return 0
    target_weights = {
        action["symbol"]: action["target_weight"]
        for action in decision["decision_actions"]
        if action["target_weight"] > 0
    }
    symbols = set(target_weights) | set(portfolio["holdings_weight"])
    if not symbols:
        return 0
    return round(
        max(abs(portfolio["holdings_weight"].get(symbol, 0) - target_weights.get(symbol, 0)) for symbol in symbols)
        * 100,
        4,
    )


def _shadow_vs_market_gap_pp(portfolio: dict[str, Any] | None) -> float:
    if not portfolio:
        return 0
    benchmarks = portfolio.get("benchmark_returns", {})
    benchmark_return = sum(benchmarks.values()) / len(benchmarks) if benchmarks else 0
    return round(abs(portfolio["pnl_ratio"] - benchmark_return) * 100, 4)


def _crowding_penalty(market: dict[str, Any] | None) -> float:
    if not market:
        return 0
    return float(market["payload"]["crowding_penalty"])


def _warnings(
    *,
    exposure_deviation_pp: float,
    concentration_risk: float,
    decision_gap: float,
    shadow_gap: float,
    crowding: float,
    market: dict[str, Any] | None,
    research: dict[str, Any] | None,
) -> list[dict[str, str]]:
    warnings: list[dict[str, str]] = []
    if abs(exposure_deviation_pp) >= 10:
        warnings.append(
            _warning(
                "exposure_deviation",
                "high" if abs(exposure_deviation_pp) >= 20 else "medium",
                f"Equity exposure deviates {exposure_deviation_pp} pp from market target midpoint.",
                "portfolio_vs_market",
            )
        )
    if concentration_risk >= 40:
        warnings.append(
            _warning(
                "concentration_risk",
                "medium",
                f"Largest holding weight is {concentration_risk}%.",
                "portfolio_snapshot",
            )
        )
    if decision_gap >= 5:
        warnings.append(
            _warning(
                "research_execution_mismatch",
                "medium",
                f"Portfolio differs from decision target by {decision_gap} pp.",
                "decision_record",
            )
        )
    if shadow_gap >= 2:
        warnings.append(
            _warning(
                "shadow_vs_market_gap",
                "medium",
                f"Shadow return differs from benchmark by {shadow_gap} pp.",
                "portfolio_snapshot",
            )
        )
    if crowding >= 25 or (market and market["payload"]["risk_level"] == "high"):
        warnings.append(
            _warning(
                "market_risk",
                "medium",
                "Market risk or crowding is elevated.",
                "market_snapshot",
            )
        )
    data_gaps = []
    if market:
        data_gaps.extend(market.get("data_gaps", []))
    if research:
        data_gaps.extend(research.get("data_gaps", []))
    if data_gaps:
        warnings.append(_warning("data_gap", "low", "Data gaps require review.", "research_or_market"))
    return warnings


def _warning(code: str, severity: str, message: str, source: str) -> dict[str, str]:
    return {"code": code, "severity": severity, "message": message, "source": source}


def _overall_score(
    *,
    exposure_deviation_pp: float,
    concentration_risk: float,
    decision_gap: float,
    shadow_gap: float,
    crowding: float,
    warning_count: int,
) -> float:
    score = (
        abs(exposure_deviation_pp) * 1.6
        + concentration_risk * 0.35
        + decision_gap * 1.4
        + shadow_gap * 2.0
        + crowding * 0.25
        + warning_count * 3
    )
    return round(max(0, min(100, score)), 4)


def _risk_level(score: float) -> str:
    if score >= 65:
        return "high"
    if score >= 30:
        return "medium"
    return "low"


def _exposure_warning(exposure_deviation_pp: float) -> str:
    if abs(exposure_deviation_pp) < 5:
        return "within_range"
    if exposure_deviation_pp > 0:
        return "above_target"
    return "below_target"


def _is_equity_symbol(symbol: str) -> bool:
    return not symbol.startswith("511")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
