from __future__ import annotations

import json
from copy import deepcopy
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from invest_system.repositories import SQLiteRepository
from invest_system.risk import compute_risk_state
from invest_system.validators.policies import assert_no_sensitive_content
from invest_system.validators.schema_validator import validate_or_raise


DEFAULT_POLICY = {
    "schema_version": "1.0",
    "profile_id": "default_ratio_only_policy",
    "configuration_status": "default",
    "status": "active",
    "risk_bounds": {
        "max_overall_risk_score": 65,
        "max_equity_weight": 0.75,
        "min_cash_weight": 0.05,
        "max_single_holding_weight": 0.45,
        "max_drawdown": -0.08,
    },
    "freshness": {
        "max_snapshot_age_days": 1,
        "require_next_review_not_overdue": True,
    },
    "research_first": {
        "block_new_subject_when_queue_exists": True,
        "block_increase_when_active_holding_lacks_passed_gates": True,
    },
    "execution": {
        "paper_only": True,
        "real_execution_enabled": False,
    },
}

POLICY_PATH = Path("config/investor_policy.json")
CRITICAL_DATA_ITEMS = {"market", "decision", "portfolio", "target_pool"}


def compute_guidance_state(repo: SQLiteRepository, as_of: str | None = None) -> dict[str, Any]:
    repo.init_db()
    policy, policy_source = _load_policy()
    replay = repo.replay_state(as_of)
    timeline = repo.timeline(as_of)
    risk = compute_risk_state(repo, as_of)
    reference_date = _reference_date(as_of, replay, timeline)
    freshness = _data_freshness(replay, reference_date, policy)
    research_first = _research_first_state(replay, timeline)
    risk_boundaries = _risk_boundaries(replay.get("portfolio"), risk, policy)
    checks = _checks(policy, policy_source, freshness, research_first, risk_boundaries, replay)
    readiness = _readiness(checks, research_first, risk_boundaries)
    today_action = _today_action(readiness, checks, research_first, risk_boundaries, policy)
    state = {
        "schema_version": "1.0",
        "status": "ok" if any(replay.get(name) for name in ("market", "research", "decision", "portfolio")) else "empty",
        "as_of": as_of,
        "generated_at": _utc_now(),
        "policy": {
            "profile_id": policy["profile_id"],
            "configuration_status": policy["configuration_status"],
            "source": policy_source,
            "summary": {
                "max_overall_risk_score": policy["risk_bounds"]["max_overall_risk_score"],
                "max_equity_weight": policy["risk_bounds"]["max_equity_weight"],
                "min_cash_weight": policy["risk_bounds"]["min_cash_weight"],
                "max_single_holding_weight": policy["risk_bounds"]["max_single_holding_weight"],
                "max_snapshot_age_days": policy["freshness"]["max_snapshot_age_days"],
                "paper_only": policy["execution"]["paper_only"],
            },
        },
        "readiness": readiness,
        "checks": checks,
        "data_freshness": freshness,
        "research_first": research_first,
        "risk_boundaries": risk_boundaries,
        "today_action": today_action,
        "source_ids": _source_ids(replay, timeline),
    }
    assert_no_sensitive_content(state)
    validate_or_raise(state, "guidance_state.schema.json")
    return state


def _load_policy() -> tuple[dict[str, Any], str]:
    if POLICY_PATH.exists():
        with POLICY_PATH.open("r", encoding="utf-8") as policy_file:
            policy = json.load(policy_file)
        source = "repo_config"
    else:
        policy = deepcopy(DEFAULT_POLICY)
        source = "system_default"
    validate_or_raise(policy, "investor_policy.schema.json")
    assert_no_sensitive_content(policy)
    return policy, source


def _reference_date(as_of: str | None, replay: dict[str, Any], timeline: list[dict[str, Any]]) -> str | None:
    if as_of and len(as_of) == 10:
        return as_of
    dates = [
        payload["basis_date"]
        for payload in replay.values()
        if isinstance(payload, dict) and "basis_date" in payload
    ]
    dates.extend(event["basis_date"] for event in timeline if event.get("basis_date"))
    return max(dates) if dates else None


def _data_freshness(
    replay: dict[str, Any],
    reference_date: str | None,
    policy: dict[str, Any],
) -> dict[str, Any]:
    items = [
        _freshness_item("market", replay.get("market"), reference_date, policy),
        _freshness_item("research", replay.get("research"), reference_date, policy),
        _freshness_item("decision", replay.get("decision"), reference_date, policy),
        _freshness_item("portfolio", replay.get("portfolio"), reference_date, policy),
        _freshness_item("target_pool", replay.get("target_pool"), reference_date, policy),
    ]
    return {"reference_date": reference_date, "items": items}


def _freshness_item(
    name: str,
    payload: dict[str, Any] | None,
    reference_date: str | None,
    policy: dict[str, Any],
) -> dict[str, Any]:
    if payload is None:
        return {
            "name": name,
            "status": "missing",
            "basis_date": None,
            "age_days": None,
            "next_review_date": None,
            "detail": f"{name} 快照缺失。",
        }
    basis_date = payload["basis_date"]
    age_days = _age_days(reference_date, basis_date)
    next_review = payload.get("next_review_date")
    max_age = policy["freshness"]["max_snapshot_age_days"]
    require_next_review = policy["freshness"]["require_next_review_not_overdue"]
    status = "pass"
    detail = f"{name} 快照在配置的新鲜度窗口内。"
    if age_days is not None and age_days > max_age:
        status = "block" if name in CRITICAL_DATA_ITEMS else "warn"
        detail = f"{name} 快照超过配置的新鲜度窗口。"
    elif require_next_review and next_review and reference_date and next_review < reference_date:
        status = "warn"
        detail = f"{name} 复核日期已过期。"
    return {
        "name": name,
        "status": status,
        "basis_date": basis_date,
        "age_days": age_days,
        "next_review_date": next_review,
        "detail": detail,
    }


def _research_first_state(replay: dict[str, Any], timeline: list[dict[str, Any]]) -> dict[str, Any]:
    target_pool = replay.get("target_pool")
    decision = replay.get("decision")
    portfolio = replay.get("portfolio")
    queue: dict[str, dict[str, Any]] = {}
    covered: set[str] = set()
    active_without_passed_gates: set[str] = set()
    approved, research_first, blocked = _target_pool_sets(target_pool)
    active_symbols = _active_symbols(portfolio)
    decisions = _decision_actions_by_symbol(decision)
    decision_research_first = {
        symbol
        for symbol, action in decisions.items()
        if action["gates"].get("research_first")
    }
    current_research_scope = active_symbols | research_first | blocked | decision_research_first

    for item in _research_queue_from_timeline(timeline, current_research_scope):
        queue[item["symbol"]] = item
    for symbol in sorted(research_first):
        queue.setdefault(
            symbol,
            {
                "symbol": symbol,
                "reason": "profile_or_gate_incomplete",
                "blockers": ["profile_or_gate_incomplete"],
                "source": "target_pool",
            },
        )
    for symbol in sorted(blocked):
        queue.setdefault(
            symbol,
            {
                "symbol": symbol,
                "reason": "blocked_in_target_pool",
                "blockers": ["target_pool_blocked"],
                "source": "target_pool",
            },
        )

    for symbol, action in decisions.items():
        if action["gates"].get("research_first"):
            queue[symbol] = {
                "symbol": symbol,
                "reason": "decision_requires_research_first",
                "blockers": ["decision_requires_research_first"],
                "source": "decision_record",
            }
        if _action_has_passed_gates(action):
            covered.add(symbol)

    for symbol in active_symbols:
        action = decisions.get(symbol)
        if symbol in blocked or symbol in research_first:
            active_without_passed_gates.add(symbol)
        elif action is None or not _action_has_passed_gates(action):
            active_without_passed_gates.add(symbol)
        elif approved and symbol not in approved:
            active_without_passed_gates.add(symbol)

    if active_without_passed_gates:
        status = "block"
    elif queue:
        status = "warn"
    elif not active_symbols and not approved:
        status = "missing"
    else:
        status = "pass"
    return {
        "status": status,
        "queue": list(queue.values()),
        "covered_symbols": sorted(covered),
        "active_holdings_without_passed_gates": sorted(active_without_passed_gates),
    }


def _risk_boundaries(
    portfolio: dict[str, Any] | None,
    risk: dict[str, Any],
    policy: dict[str, Any],
) -> dict[str, Any]:
    bounds = policy["risk_bounds"]
    if portfolio is None:
        return {
            "status": "missing",
            "items": [
                _boundary_item("portfolio", "missing", None, None, "portfolio snapshot is missing."),
            ],
        }
    holdings = portfolio.get("holdings_weight", {})
    equity_weight = _equity_weight(holdings)
    cash_weight = float(portfolio["cash_weight"])
    max_holding = max(holdings.values()) if holdings else 0
    drawdown = float(portfolio["drawdown"])
    risk_score = float(risk["overall_risk_score"])
    items = [
        _upper_boundary("overall_risk_score", risk_score, bounds["max_overall_risk_score"]),
        _upper_boundary("equity_weight", equity_weight, bounds["max_equity_weight"]),
        _lower_boundary("cash_weight", cash_weight, bounds["min_cash_weight"]),
        _upper_boundary("single_holding_weight", max_holding, bounds["max_single_holding_weight"]),
        _lower_boundary("drawdown", drawdown, bounds["max_drawdown"]),
    ]
    status = _combined_status([item["status"] for item in items])
    return {"status": status, "items": items}


def _checks(
    policy: dict[str, Any],
    policy_source: str,
    freshness: dict[str, Any],
    research_first: dict[str, Any],
    risk_boundaries: dict[str, Any],
    replay: dict[str, Any],
) -> list[dict[str, Any]]:
    critical_freshness = [
        item
        for item in freshness["items"]
        if item["name"] in CRITICAL_DATA_ITEMS and item["status"] in {"block", "missing"}
    ]
    stale_count = sum(1 for item in freshness["items"] if item["status"] in {"warn", "block", "missing"})
    checks = [
        _check(
            "policy_config",
            "pass" if policy["status"] == "active" else "block",
            "Investor boundary policy",
            "已加载仓库内比例风控配置。" if policy_source == "repo_config" else "正在使用系统默认比例风控配置。",
            "config",
            None,
        ),
        _check(
            "data_freshness",
            "block" if critical_freshness else "warn" if stale_count else "pass",
            "Daily data freshness",
            "关键快照缺失或过期。" if critical_freshness else "部分快照需要复核。" if stale_count else "关键快照满足新鲜度要求。",
            "sqlite_replay",
            "/system/status" if stale_count else None,
        ),
        _check(
            "research_first",
            research_first["status"],
            "ResearchFirst coverage",
            _research_first_check_detail(research_first),
            "target_pool_and_decision",
            "/research/view" if research_first["status"] in {"warn", "block", "missing"} else None,
        ),
        _check(
            "risk_boundaries",
            risk_boundaries["status"],
            "Risk boundaries",
            "一个或多个风控边界需要处理。" if risk_boundaries["status"] in {"warn", "block"} else "组合处在配置风控边界内。",
            "portfolio_and_risk",
            "/risk/state" if risk_boundaries["status"] in {"warn", "block", "missing"} else None,
        ),
        _check(
            "paper_only",
            "pass" if policy["execution"]["paper_only"] and not policy["execution"]["real_execution_enabled"] else "block",
            "Execution boundary",
            "系统保持纸面模拟，不创建外部执行。",
            "execution_policy",
            None,
        ),
        _check(
            "replay_available",
            "pass" if replay.get("portfolio") and replay.get("decision") else "missing",
            "Replay availability",
            "组合可以从当前决策回放。" if replay.get("portfolio") and replay.get("decision") else "回放链路不完整。",
            "event_log",
            "/timeline/replay",
        ),
    ]
    return checks


def _readiness(
    checks: list[dict[str, Any]],
    research_first: dict[str, Any],
    risk_boundaries: dict[str, Any],
) -> dict[str, Any]:
    statuses = [check["status"] for check in checks]
    primary = _primary_blocker(checks)
    if "block" in statuses or "missing" in statuses:
        overall = "blocked"
    elif "warn" in statuses:
        overall = "review_required"
    elif not checks:
        overall = "empty"
    else:
        overall = "ready"
    hard_research_block = bool(research_first["active_holdings_without_passed_gates"])
    can_increase = overall == "ready" and research_first["status"] == "pass" and risk_boundaries["status"] == "pass"
    can_add_new = overall == "ready" and not research_first["queue"]
    return {
        "overall_state": overall,
        "can_increase_risk": can_increase,
        "can_add_new_subject": can_add_new,
        "requires_human_review": overall != "ready" or hard_research_block,
        "primary_blocker": primary,
    }


def _today_action(
    readiness: dict[str, Any],
    checks: list[dict[str, Any]],
    research_first: dict[str, Any],
    risk_boundaries: dict[str, Any],
    policy: dict[str, Any],
) -> dict[str, Any]:
    headline = _headline(readiness, research_first, risk_boundaries)
    steps = _next_required_steps(checks, readiness)
    operations = [
        {
            "operation": "portfolio_review",
            "status": "allowed" if readiness["overall_state"] != "empty" else "blocked",
            "reason": "查看组合是只读行为，可以继续。",
            "endpoint": "/portfolio/state",
        },
        {
            "operation": "increase_risk",
            "status": "allowed" if readiness["can_increase_risk"] else "blocked",
            "reason": "只有数据、研究门槛和风控边界全部通过时才允许。",
            "endpoint": "/risk/state",
        },
        {
            "operation": "new_subject_review",
            "status": "allowed" if readiness["can_add_new_subject"] else "blocked",
            "reason": "ResearchFirst 队列或风控检查未通过时阻断。",
            "endpoint": "/research/latest",
        },
        {
            "operation": "external_execution",
            "status": "blocked",
            "reason": "系统配置为纸面模拟，不提供外部执行。",
            "endpoint": None,
        },
    ]
    do_not_do = [
        "不要把影子组合输出当作外部执行。",
        "ResearchFirst 或风控边界未通过时，不要提高风险。",
        "画像、估值、流动性门槛通过前，不要新增标的。",
    ]
    if not policy["execution"]["paper_only"]:
        do_not_do.append("执行策略恢复为纸面模拟前，不要继续。")
    return {
        "headline": headline,
        "allowed_operations": operations,
        "next_required_steps": steps,
        "do_not_do": do_not_do,
    }


def _source_ids(replay: dict[str, Any], timeline: list[dict[str, Any]]) -> dict[str, Any]:
    market = replay.get("market")
    decision = replay.get("decision")
    portfolio = replay.get("portfolio")
    target_pool = replay.get("target_pool")
    research_ids = [
        event["object_id"]
        for event in timeline
        if event["type"] == "research"
    ]
    return {
        "market_snapshot_id": market.get("snapshot_id") if market else None,
        "decision_id": decision.get("decision_id") if decision else None,
        "portfolio_id": portfolio.get("portfolio_id") if portfolio else None,
        "target_pool_id": target_pool.get("target_pool_id") if target_pool else None,
        "research_snapshot_ids": research_ids,
    }


def _target_pool_sets(target_pool: dict[str, Any] | None) -> tuple[set[str], set[str], set[str]]:
    approved: set[str] = set()
    research_first: set[str] = set()
    blocked: set[str] = set()
    if target_pool is None:
        return approved, research_first, blocked
    for entry in target_pool["entries"]:
        values = set(entry["symbols"])
        if entry["pool_type"] == "approved":
            approved.update(values)
        elif entry["pool_type"] == "research_first":
            research_first.update(values)
        elif entry["pool_type"] == "blocked":
            blocked.update(values)
    return approved, research_first, blocked


def _active_symbols(portfolio: dict[str, Any] | None) -> set[str]:
    if portfolio is None:
        return set()
    return {symbol for symbol, weight in portfolio["holdings_weight"].items() if weight > 0}


def _decision_actions_by_symbol(decision: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if decision is None:
        return {}
    return {action["symbol"]: action for action in decision["decision_actions"]}


def _action_has_passed_gates(action: dict[str, Any]) -> bool:
    gates = action["gates"]
    return (
        not gates["research_first"]
        and gates["profile"] == "pass"
        and gates["valuation"] == "pass"
        and gates["liquidity"] == "pass"
    )


def _research_queue_from_timeline(
    timeline: list[dict[str, Any]],
    current_scope: set[str],
) -> list[dict[str, Any]]:
    queue: dict[str, dict[str, Any]] = {}
    for event in timeline:
        if event["type"] != "research":
            continue
        snapshot = event["payload"]
        payload = snapshot.get("payload", {})
        symbol = payload.get("symbol") or snapshot.get("symbol")
        if symbol and symbol in current_scope:
            if _research_snapshot_requires_first(snapshot):
                blockers = _research_queue_blockers(snapshot)
                queue[symbol] = {
                    "symbol": symbol,
                    "reason": _research_queue_reason(snapshot),
                    "blockers": blockers,
                    "source": event["object_id"],
                }
            else:
                queue.pop(symbol, None)
        for item in payload.get("research_first_list", []):
            symbol = item.get("symbol")
            if symbol and symbol in current_scope:
                reason = item.get("blocking_reason", "research_first_required")
                queue[symbol] = {
                    "symbol": symbol,
                    "reason": reason,
                    "blockers": [reason],
                    "source": event["object_id"],
                }
    return list(queue.values())


def _research_first_check_detail(research_first: dict[str, Any]) -> str:
    if research_first["active_holdings_without_passed_gates"]:
        return "当前持仓仍有门槛未覆盖，阻断提高风险。"
    if research_first["queue"]:
        return "当前目标池或当前决策仍有 ResearchFirst 候选，阻断新增相关标的。"
    if research_first["status"] == "missing":
        return "缺少当前持仓或目标池门槛覆盖信息。"
    return "当前持仓和当前候选已通过门槛覆盖。"


def _research_snapshot_requires_first(snapshot: dict[str, Any]) -> bool:
    return snapshot.get("actionability") == "research_first" or snapshot.get("status") == "blocked"


def _research_queue_reason(snapshot: dict[str, Any]) -> str:
    if snapshot.get("status") == "blocked":
        return "profile_or_gate_incomplete"
    if snapshot.get("actionability") == "research_first":
        return "research_first_required"
    return "research_first_required"


def _research_queue_blockers(snapshot: dict[str, Any]) -> list[str]:
    payload = snapshot.get("payload", {})
    blockers: list[str] = []
    gates = payload.get("gates") or payload.get("gate_status") or payload.get("research_gates") or {}
    if isinstance(gates, dict):
        _append_gate_blocker(blockers, gates.get("profile"), "profile_gate_incomplete")
        _append_gate_blocker(blockers, gates.get("valuation"), "valuation_gate_failed")
        _append_gate_blocker(blockers, gates.get("liquidity"), "liquidity_gate_incomplete")

    text = _research_text(snapshot)
    if _mentions_any(text, ("profile gate fails", "profile missing", "profile incomplete", "画像缺失", "画像不完整")):
        blockers.append("profile_gate_incomplete")
    if _mentions_any(
        text,
        (
            "valuation gate fails",
            "valuation gate failed",
            "valuation fails",
            "valuation pressure is high",
            "valuation percentiles are extreme",
            "估值门槛未通过",
            "估值不通过",
        ),
    ):
        blockers.append("valuation_gate_failed")
    if _mentions_any(text, ("liquidity gate fails", "liquidity gate failed", "liquidity evidence is incomplete", "流动性不通过")):
        blockers.append("liquidity_gate_incomplete")
    if _mentions_any(text, ("duration and credit-quality evidence are incomplete", "credit-quality evidence", "duration evidence")):
        blockers.append("duration_credit_incomplete")
    if snapshot.get("data_gaps"):
        blockers.append("data_gap")
    if not blockers and snapshot.get("actionability") == "research_first":
        blockers.append("research_first_required")
    if not blockers and snapshot.get("status") == "blocked":
        blockers.append("profile_or_gate_incomplete")
    return _unique(blockers)


def _append_gate_blocker(blockers: list[str], value: Any, blocker: str) -> None:
    if value is not None and str(value).lower() != "pass":
        blockers.append(blocker)


def _research_text(snapshot: dict[str, Any]) -> str:
    parts: list[str] = [
        str(snapshot.get("executive_summary", "")),
        " ".join(str(item) for item in snapshot.get("reasoning", [])),
        " ".join(str(item) for item in snapshot.get("risks", [])),
        " ".join(str(item) for item in snapshot.get("data_gaps", [])),
    ]
    return " ".join(parts).lower()


def _mentions_any(text: str, needles: tuple[str, ...]) -> bool:
    return any(needle.lower() in text for needle in needles)


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _boundary_item(
    name: str,
    status: str,
    current: float | None,
    limit: float | None,
    detail: str,
) -> dict[str, Any]:
    return {"name": name, "status": status, "current": current, "limit": limit, "detail": detail}


def _upper_boundary(name: str, current: float, limit: float) -> dict[str, Any]:
    status = "pass" if current <= limit else "block"
    detail = f"{name} 在边界内。" if status == "pass" else f"{name} 超过边界。"
    return _boundary_item(name, status, round(current, 6), limit, detail)


def _lower_boundary(name: str, current: float, limit: float) -> dict[str, Any]:
    status = "pass" if current >= limit else "block"
    detail = f"{name} 在边界内。" if status == "pass" else f"{name} 低于边界。"
    return _boundary_item(name, status, round(current, 6), limit, detail)


def _combined_status(statuses: list[str]) -> str:
    if "block" in statuses:
        return "block"
    if "missing" in statuses:
        return "missing"
    if "warn" in statuses:
        return "warn"
    return "pass"


def _check(
    check_id: str,
    status: str,
    title: str,
    detail: str,
    source: str,
    next_endpoint: str | None,
) -> dict[str, Any]:
    return {
        "check_id": check_id,
        "status": status,
        "title": title,
        "detail": detail,
        "source": source,
        "next_endpoint": next_endpoint,
    }


def _primary_blocker(checks: list[dict[str, Any]]) -> str | None:
    for status in ("block", "missing", "warn"):
        for check in checks:
            if check["status"] == status:
                return check["check_id"]
    return None


def _headline(
    readiness: dict[str, Any],
    research_first: dict[str, Any],
    risk_boundaries: dict[str, Any],
) -> str:
    if readiness["overall_state"] == "blocked":
        if research_first["active_holdings_without_passed_gates"]:
            return "先停在 ResearchFirst：当前持仓补齐门槛前，不能提高风险。"
        if risk_boundaries["status"] == "block":
            return "风控边界阻断：先看风险，再考虑是否调整暴露。"
        return "数据或回放阻断：先刷新并验证，再使用指导。"
    if readiness["overall_state"] == "review_required":
        return "需要先复核：解决警告前，不要提高风险。"
    if readiness["overall_state"] == "ready":
        return "可以进入只读组合复核，继续保持当前边界。"
    return "暂无可用回放状态。"


def _next_required_steps(checks: list[dict[str, Any]], readiness: dict[str, Any]) -> list[dict[str, str]]:
    steps: list[dict[str, str]] = []
    for check in checks:
        endpoint = check["next_endpoint"]
        if check["status"] in {"block", "missing", "warn"} and endpoint:
            steps.append(
                {
                    "step": check["check_id"],
                    "endpoint": endpoint,
                    "reason": check["detail"],
                }
            )
    if not steps and readiness["overall_state"] == "ready":
        steps.append(
                {
                    "step": "portfolio_review",
                    "endpoint": "/portfolio/state",
                    "reason": "全部指导门槛通过，继续只读查看组合。",
                }
            )
    return steps


def _equity_weight(holdings: dict[str, float]) -> float:
    return round(sum(weight for symbol, weight in holdings.items() if not symbol.startswith("511")), 6)


def _age_days(reference_date: str | None, basis_date: str) -> int | None:
    if reference_date is None:
        return None
    return (date.fromisoformat(reference_date) - date.fromisoformat(basis_date)).days


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
