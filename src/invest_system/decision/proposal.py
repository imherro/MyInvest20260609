from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from invest_system.guidance import compute_guidance_state
from invest_system.macro import compute_macro_state
from invest_system.repositories import SQLiteRepository
from invest_system.risk import compute_risk_state
from invest_system.validators.policies import assert_no_sensitive_content
from invest_system.validators.schema_validator import validate_or_raise


PROPOSAL_ACTIONS = {"observe", "research_first", "rebalance_candidate", "no_action"}


def build_decision_proposal(repo: SQLiteRepository, as_of: str | None = None) -> dict[str, Any]:
    repo.init_db()
    replay = repo.replay_state(as_of)
    timeline = repo.timeline(as_of)
    market = replay.get("market")
    decision = replay.get("decision")
    portfolio = replay.get("portfolio")
    research_items = _latest_research_by_module(timeline)
    risk = compute_risk_state(repo, as_of)
    macro = compute_macro_state(repo, as_of)
    guidance = compute_guidance_state(repo, as_of)
    basis_date = _basis_date(as_of, market, portfolio, research_items)
    gate_summary = _gate_summary(guidance, risk, macro, portfolio, market, research_items)
    recommended_action = _recommended_action(gate_summary, risk, macro, research_items, portfolio)
    decision_preview = _decision_preview(
        recommended_action=recommended_action,
        research_items=research_items,
        guidance=guidance,
        decision=decision,
        portfolio=portfolio,
        gate_summary=gate_summary,
    )
    explanation = _explanation(
        recommended_action=recommended_action,
        market=market,
        research_items=research_items,
        risk=risk,
        macro=macro,
        portfolio=portfolio,
        guidance=guidance,
        gate_summary=gate_summary,
    )
    status = "ok" if any([market, research_items, decision, portfolio]) else "empty"
    proposal = {
        "schema_version": "1.0",
        "status": status,
        "proposal_id": f"decision-proposal-{basis_date or 'latest'}",
        "basis_date": basis_date,
        "as_of": as_of,
        "generated_at": _utc_now(),
        "recommended_action": recommended_action if status == "ok" else "no_action",
        "requires_human_review": status != "ok" or _review_state(gate_summary) != "ready",
        "confidence": _confidence(gate_summary, risk, macro, research_items),
        "review_state": _review_state(gate_summary) if status == "ok" else "empty",
        "decision_preview": decision_preview,
        "gate_summary": gate_summary,
        "explanation": explanation,
        "invalidation_conditions": _invalidation_conditions(research_items, risk, macro),
        "source_ids": _source_ids(market, research_items, decision, portfolio, risk, macro, basis_date),
    }
    assert_no_sensitive_content(proposal)
    validate_or_raise(proposal, "decision_proposal.schema.json")
    return proposal


def build_decision_explain(repo: SQLiteRepository, as_of: str | None = None) -> dict[str, Any]:
    proposal = build_decision_proposal(repo, as_of)
    result = {
        "status": "ok" if proposal["status"] == "ok" else "empty",
        "data": {
            "proposal_id": proposal["proposal_id"],
            "basis_date": proposal["basis_date"],
            "recommended_action": proposal["recommended_action"],
            "review_state": proposal["review_state"],
            "explanation": proposal["explanation"],
            "invalidation_conditions": proposal["invalidation_conditions"],
            "source_ids": proposal["source_ids"],
        },
    }
    assert_no_sensitive_content(result)
    return result


def _gate_summary(
    guidance: dict[str, Any],
    risk: dict[str, Any],
    macro: dict[str, Any],
    portfolio: dict[str, Any] | None,
    market: dict[str, Any] | None,
    research_items: list[dict[str, Any]],
) -> dict[str, str]:
    guidance_checks = {item["check_id"]: item["status"] for item in guidance["checks"]}
    risk_status = guidance_checks.get("risk_boundaries", "missing")
    if risk["status"] == "ok" and risk["risk_level"] == "high":
        risk_status = "block"
    elif risk["status"] == "ok" and risk["risk_level"] == "medium" and risk_status == "pass":
        risk_status = "warn"
    macro_status = _macro_status(macro)
    portfolio_status = "missing" if portfolio is None else "warn" if risk.get("exposure_warning") != "within_range" else "pass"
    data_status = guidance_checks.get("data_freshness", "missing")
    if not market or not research_items:
        data_status = "missing"
    return {
        "research_first": guidance_checks.get("research_first", "missing"),
        "risk_boundary": risk_status,
        "macro": macro_status,
        "portfolio": portfolio_status,
        "data": data_status,
    }


def _macro_status(macro: dict[str, Any]) -> str:
    if macro["status"] != "ok":
        return "missing"
    snapshot = macro["macro_snapshot"]
    if snapshot["risk_cycle_state"] == "risk_off":
        return "warn"
    if macro["model_consensus"]["consensus_state"] == "risk_off":
        return "warn"
    return "pass"


def _recommended_action(
    gate_summary: dict[str, str],
    risk: dict[str, Any],
    macro: dict[str, Any],
    research_items: list[dict[str, Any]],
    portfolio: dict[str, Any] | None,
) -> str:
    if gate_summary["data"] in {"missing", "block"} or portfolio is None:
        return "no_action"
    if gate_summary["research_first"] in {"warn", "block", "missing"}:
        return "research_first"
    if gate_summary["risk_boundary"] == "block":
        return "no_action"
    if macro["status"] == "ok" and macro["macro_snapshot"]["risk_cycle_state"] == "risk_off":
        return "observe"
    if risk["status"] == "ok" and risk["exposure_warning"] != "within_range" and gate_summary["risk_boundary"] != "block":
        return "rebalance_candidate"
    if any(item.get("actionability") == "rebalance_candidate" for item in research_items):
        return "rebalance_candidate" if gate_summary["risk_boundary"] in {"pass", "warn"} else "observe"
    return "observe"


def _decision_preview(
    *,
    recommended_action: str,
    research_items: list[dict[str, Any]],
    guidance: dict[str, Any],
    decision: dict[str, Any] | None,
    portfolio: dict[str, Any] | None,
    gate_summary: dict[str, str],
) -> list[dict[str, Any]]:
    symbols = _candidate_symbols(research_items, decision, portfolio)
    if not symbols:
        symbols = ["portfolio_review"]
    decision_actions = _decision_actions_by_symbol(decision)
    research_first_symbols = _research_first_symbols(guidance, research_items)
    current_weights = portfolio.get("holdings_weight", {}) if portfolio else {}
    preview = []
    for symbol in symbols[:12]:
        action = decision_actions.get(symbol)
        gates = _symbol_gates(symbol, action, research_first_symbols, gate_summary)
        current_weight = float(current_weights.get(symbol, 0))
        target_weight = _target_weight(symbol, action, current_weight, gates, recommended_action)
        proposal = _symbol_proposal(recommended_action, gates, current_weight, target_weight)
        preview.append(
            {
                "symbol": symbol,
                "proposal": proposal,
                "current_weight": round(current_weight, 6),
                "target_weight": round(target_weight, 6),
                "delta_weight_pp": round((target_weight - current_weight) * 100, 4),
                "rationale": _symbol_rationale(symbol, proposal, gates, action),
                "gates": gates,
            }
        )
    return preview


def _candidate_symbols(
    research_items: list[dict[str, Any]],
    decision: dict[str, Any] | None,
    portfolio: dict[str, Any] | None,
) -> list[str]:
    symbols: list[str] = []
    for item in research_items:
        payload = item.get("payload", {})
        for candidate in payload.get("action_candidates", []):
            symbol = candidate.get("symbol")
            if symbol:
                symbols.append(symbol)
        for symbol in payload.get("leading_symbols", []):
            if symbol:
                symbols.append(symbol)
        for queued in payload.get("research_first_list", []):
            symbol = queued.get("symbol")
            if symbol:
                symbols.append(symbol)
    if decision:
        symbols.extend(action["symbol"] for action in decision["decision_actions"])
    if portfolio:
        symbols.extend(portfolio["holdings_weight"].keys())
    return list(dict.fromkeys(symbols))


def _research_first_symbols(guidance: dict[str, Any], research_items: list[dict[str, Any]]) -> set[str]:
    symbols = {item["symbol"] for item in guidance["research_first"]["queue"]}
    symbols.update(guidance["research_first"]["active_holdings_without_passed_gates"])
    for item in research_items:
        for queued in item.get("payload", {}).get("research_first_list", []):
            symbol = queued.get("symbol")
            if symbol:
                symbols.add(symbol)
    return symbols


def _decision_actions_by_symbol(decision: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not decision:
        return {}
    return {action["symbol"]: action for action in decision["decision_actions"]}


def _symbol_gates(
    symbol: str,
    action: dict[str, Any] | None,
    research_first_symbols: set[str],
    gate_summary: dict[str, str],
) -> dict[str, Any]:
    if action:
        gates = action["gates"]
        profile = gates["profile"]
        valuation = gates["valuation"]
        liquidity = gates["liquidity"]
        research_first = bool(gates["research_first"])
    else:
        profile = "unknown"
        valuation = "unknown"
        liquidity = "unknown"
        research_first = True
    if symbol in research_first_symbols:
        research_first = True
        if profile == "unknown":
            profile = "blocked"
        if valuation == "unknown":
            valuation = "blocked"
        if liquidity == "unknown":
            liquidity = "blocked"
    return {
        "profile": profile,
        "valuation": valuation,
        "liquidity": liquidity,
        "research_first": research_first,
        "risk_boundary": gate_summary["risk_boundary"],
    }


def _target_weight(
    symbol: str,
    action: dict[str, Any] | None,
    current_weight: float,
    gates: dict[str, Any],
    recommended_action: str,
) -> float:
    if gates["research_first"]:
        return current_weight
    if recommended_action == "rebalance_candidate" and action:
        return float(action["target_weight"])
    return current_weight


def _symbol_proposal(
    recommended_action: str,
    gates: dict[str, Any],
    current_weight: float,
    target_weight: float,
) -> str:
    if gates["research_first"] or any(gates[name] != "pass" for name in ("profile", "valuation", "liquidity")):
        return "research_first"
    if recommended_action == "rebalance_candidate" and abs(target_weight - current_weight) >= 0.0001:
        return "rebalance_candidate"
    if recommended_action in PROPOSAL_ACTIONS:
        return recommended_action if recommended_action != "rebalance_candidate" else "observe"
    return "observe"


def _symbol_rationale(
    symbol: str,
    proposal: str,
    gates: dict[str, Any],
    action: dict[str, Any] | None,
) -> list[str]:
    rationale = []
    if gates["research_first"]:
        rationale.append(f"{symbol} remains blocked by ResearchFirst or incomplete profile gates.")
    elif proposal == "rebalance_candidate":
        rationale.append(f"{symbol} has passed profile, valuation, and liquidity gates in the current decision context.")
    elif proposal == "observe":
        rationale.append(f"{symbol} should remain under observation until the next review signal changes.")
    else:
        rationale.append(f"{symbol} has no actionable proposal under current gates.")
    if action:
        rationale.extend(action.get("rationale", [])[:2])
    return rationale


def _explanation(
    *,
    recommended_action: str,
    market: dict[str, Any] | None,
    research_items: list[dict[str, Any]],
    risk: dict[str, Any],
    macro: dict[str, Any],
    portfolio: dict[str, Any] | None,
    guidance: dict[str, Any],
    gate_summary: dict[str, str],
) -> dict[str, Any]:
    why = [
        _why("market", market.get("snapshot_id") if market else None, _market_finding(market)),
        _why("research", _research_source_id(research_items), _research_finding(research_items)),
        _why("risk", risk["source_ids"].get("portfolio_id"), _risk_finding(risk)),
        _why("macro", macro["source_ids"].get("market_snapshot_id"), _macro_finding(macro)),
        _why("portfolio", portfolio.get("portfolio_id") if portfolio else None, _portfolio_finding(portfolio)),
        _why("guidance", guidance["readiness"].get("primary_blocker"), _guidance_finding(guidance)),
    ]
    blocked = _blocked_reasons(gate_summary, guidance, risk)
    return {
        "why": why,
        "confidence_drivers": _confidence_drivers(recommended_action, gate_summary, risk, macro, research_items),
        "blocked_reasons": blocked,
    }


def _why(stage: str, source_id: str | None, finding: str) -> dict[str, Any]:
    return {"stage": stage, "source_id": source_id, "finding": finding}


def _market_finding(market: dict[str, Any] | None) -> str:
    if not market:
        return "Market snapshot is missing, so proposal cannot rely on market range."
    payload = market["payload"]
    return (
        f"Market score is {payload['market_score']} with equity range "
        f"{round(payload['equity_min'] * 100, 4)}% to {round(payload['equity_max'] * 100, 4)}%."
    )


def _research_finding(research_items: list[dict[str, Any]]) -> str:
    if not research_items:
        return "Research snapshots are missing, so proposal remains non-actionable."
    latest = sorted(research_items, key=lambda item: item["generated_at"])[-1]
    return (
        f"{len(research_items)} current research module(s) are available; latest module "
        f"is {latest['module']} with actionability {latest['actionability']}."
    )


def _risk_finding(risk: dict[str, Any]) -> str:
    if risk["status"] != "ok":
        return "Risk state is unavailable."
    return (
        f"Risk level is {risk['risk_level']} with score {risk['overall_risk_score']} "
        f"and {len(risk['warnings'])} warning(s)."
    )


def _macro_finding(macro: dict[str, Any]) -> str:
    if macro["status"] != "ok":
        return "Macro state is unavailable."
    snapshot = macro["macro_snapshot"]
    return (
        f"Macro risk cycle is {snapshot['risk_cycle_state']} and consensus state is "
        f"{macro['model_consensus']['consensus_state']}."
    )


def _portfolio_finding(portfolio: dict[str, Any] | None) -> str:
    if not portfolio:
        return "Portfolio replay is missing."
    equity_weight = sum(weight for symbol, weight in portfolio["holdings_weight"].items() if not symbol.startswith("511"))
    return f"Shadow portfolio equity weight is {round(equity_weight * 100, 4)}%."


def _guidance_finding(guidance: dict[str, Any]) -> str:
    readiness = guidance["readiness"]
    return f"Guidance state is {readiness['overall_state']} with primary blocker {readiness['primary_blocker']}."


def _confidence_drivers(
    recommended_action: str,
    gate_summary: dict[str, str],
    risk: dict[str, Any],
    macro: dict[str, Any],
    research_items: list[dict[str, Any]],
) -> list[str]:
    drivers = [
        f"Recommended action is {recommended_action}.",
        f"Gate summary is research_first={gate_summary['research_first']}, risk_boundary={gate_summary['risk_boundary']}.",
    ]
    if risk["status"] == "ok":
        drivers.append(f"Risk score contributes {round((1 - risk['overall_risk_score'] / 100), 4)} to confidence.")
    if macro["status"] == "ok":
        drivers.append(f"Macro calibrated confidence is {macro['model_consensus']['calibrated_confidence']}.")
    if research_items:
        drivers.append(f"Research confidence average is {round(_average([item['confidence'] for item in research_items]), 4)}.")
    return drivers


def _blocked_reasons(gate_summary: dict[str, str], guidance: dict[str, Any], risk: dict[str, Any]) -> list[str]:
    reasons = []
    for name, status in gate_summary.items():
        if status in {"block", "missing"}:
            reasons.append(f"{name} gate is {status}.")
    if guidance["research_first"]["queue"]:
        reasons.append("ResearchFirst queue is not empty.")
    if risk["status"] == "ok" and risk["risk_level"] == "high":
        reasons.append("Risk level is high.")
    return reasons


def _invalidation_conditions(
    research_items: list[dict[str, Any]],
    risk: dict[str, Any],
    macro: dict[str, Any],
) -> list[str]:
    conditions = [
        "A newer market snapshot changes risk range or market score.",
        "ResearchFirst queue changes for any candidate symbol.",
        "Profile, valuation, or liquidity gates change.",
        "Shadow portfolio replay source changes.",
    ]
    for item in research_items:
        conditions.extend(item.get("invalidation_conditions", [])[:2])
    if risk["status"] == "ok" and risk["warnings"]:
        conditions.append("Risk warning set changes.")
    if macro["status"] == "ok" and macro["macro_snapshot"]["risk_cycle_state"] == "risk_off":
        conditions.append("Macro state remains risk_off or deteriorates.")
    return list(dict.fromkeys(conditions))


def _source_ids(
    market: dict[str, Any] | None,
    research_items: list[dict[str, Any]],
    decision: dict[str, Any] | None,
    portfolio: dict[str, Any] | None,
    risk: dict[str, Any],
    macro: dict[str, Any],
    basis_date: str | None,
) -> dict[str, Any]:
    return {
        "market_snapshot_id": market.get("snapshot_id") if market else None,
        "research_snapshot_ids": [item["snapshot_id"] for item in research_items],
        "decision_id": decision.get("decision_id") if decision else None,
        "portfolio_id": portfolio.get("portfolio_id") if portfolio else None,
        "risk_state_id": f"risk-derived-{basis_date or 'latest'}" if risk["status"] == "ok" else None,
        "macro_state_id": macro["macro_snapshot"].get("macro_snapshot_id") if macro["status"] == "ok" else None,
    }


def _confidence(
    gate_summary: dict[str, str],
    risk: dict[str, Any],
    macro: dict[str, Any],
    research_items: list[dict[str, Any]],
) -> float:
    values = []
    if research_items:
        values.append(_average([float(item["confidence"]) for item in research_items]))
    if risk["status"] == "ok":
        values.append(max(0, 1 - float(risk["overall_risk_score"]) / 100))
    if macro["status"] == "ok":
        values.append(float(macro["model_consensus"]["calibrated_confidence"]))
    values.append(1.0 if gate_summary["data"] == "pass" else 0.45)
    confidence = _average(values)
    confidence -= sum(0.08 for status in gate_summary.values() if status == "warn")
    confidence -= sum(0.16 for status in gate_summary.values() if status in {"block", "missing"})
    return round(max(0, min(1, confidence)), 4)


def _review_state(gate_summary: dict[str, str]) -> str:
    if any(status in {"block", "missing"} for status in gate_summary.values()):
        return "blocked"
    if any(status == "warn" for status in gate_summary.values()):
        return "review_required"
    return "ready"


def _latest_research_by_module(timeline: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest_by_module: dict[str, dict[str, Any]] = {}
    for event in timeline:
        if event["type"] == "research":
            payload = event["payload"]
            latest_by_module[payload.get("module", "unknown")] = payload
    return list(latest_by_module.values())


def _research_source_id(research_items: list[dict[str, Any]]) -> str | None:
    if not research_items:
        return None
    return ",".join(item["snapshot_id"] for item in research_items)


def _basis_date(
    as_of: str | None,
    market: dict[str, Any] | None,
    portfolio: dict[str, Any] | None,
    research_items: list[dict[str, Any]],
) -> str | None:
    if as_of and len(as_of) == 10:
        return as_of
    dates = []
    if market:
        dates.append(market["basis_date"])
    if portfolio:
        dates.append(portfolio["basis_date"])
    dates.extend(item["basis_date"] for item in research_items)
    return max(dates) if dates else None


def _average(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
