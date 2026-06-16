from __future__ import annotations

import html
from datetime import date
from typing import Any

from invest_system.comparison import compute_comparison_state
from invest_system.macro import compute_macro_state
from invest_system.repositories import SQLiteRepository
from invest_system.risk import compute_risk_state
from invest_system.self_check import system_status
from invest_system.validators.policies import assert_no_sensitive_content
from invest_system.web.symbol_display import display_symbol, symbol_name


VIEW_ROUTES = [
    {"label": "Overview", "href": "/overview"},
    {"label": "Portfolio", "href": "/portfolio/view"},
    {"label": "Research", "href": "/research/view"},
    {"label": "Report", "href": "/report/view"},
]


def build_dashboard_state(repo: SQLiteRepository, as_of: str | None = None) -> dict[str, Any]:
    repo.init_db()
    replay = repo.replay_state(as_of)
    timeline = repo.timeline(as_of)
    status_payload = system_status(repo.db_path, as_of)["data"]
    market = replay.get("market")
    target_pool = replay.get("target_pool")
    portfolio = replay.get("portfolio")
    research_items = _latest_research_by_module(timeline)
    risk = compute_risk_state(repo, as_of)
    comparison = compute_comparison_state(repo, as_of)
    macro = compute_macro_state(repo, as_of)
    data_gaps = _data_gaps(market, research_items)
    conflicts = _conflicts(market, research_items)
    actual_vs_shadow = build_actual_vs_shadow_state(repo, as_of)["data"]
    state = {
        "status": "ok",
        "data": {
            "as_of": as_of,
            "navigation": VIEW_ROUTES,
            "overview": {
                "db_initialized": status_payload["db_initialized"],
                "record_counts": status_payload["record_counts"],
                "self_check_status": status_payload["self_check"]["status"],
                "replay_available": status_payload["replay_available"],
                "latest_event_timestamp": status_payload["latest_event_timestamp"],
                "blocked": bool(data_gaps or conflicts),
                "data_gaps": data_gaps,
                "conflicts": conflicts,
            },
            "market": _market_state(market),
            "target_pool": _target_pool_state(target_pool),
            "portfolio": _portfolio_state(portfolio, market),
            "portfolio_history": build_portfolio_history_state(repo, as_of)["data"],
            "actual_vs_shadow": actual_vs_shadow,
            "daily_refresh": _daily_refresh_state(timeline, as_of, actual_vs_shadow),
            "research": _research_state(research_items),
            "risk": _risk_state(risk),
            "comparison": _comparison_state(comparison),
            "macro": _macro_state(macro),
            "report": _report_state(replay, research_items),
            "replay": {
                "trace": replay.get("trace", {}),
                "event_count": len(timeline),
            },
        },
    }
    assert_no_sensitive_content(state)
    return state


def build_actual_vs_shadow_state(repo: SQLiteRepository, as_of: str | None = None) -> dict[str, Any]:
    repo.init_db()
    replay = repo.replay_state(as_of)
    portfolio = replay.get("portfolio")
    timeline = repo.timeline(as_of)
    qmt_event = _latest_qmt_position_event(timeline)
    shadow_weights = portfolio.get("holdings_weight", {}) if portfolio else {}
    shadow_cash_weight = float(portfolio.get("cash_weight", 0)) if portfolio else 0.0
    actual_weights = _qmt_holdings_weight(qmt_event["payload"]) if qmt_event else {}
    actual_has_ratio = bool(actual_weights)
    symbols = sorted(set(shadow_weights) | set(actual_weights) | _qmt_symbols(qmt_event))
    rows = [
        _actual_vs_shadow_row(symbol, actual_weights, shadow_weights, actual_has_ratio)
        for symbol in symbols
    ]
    if actual_has_ratio or shadow_cash_weight > 0:
        rows.append(
            _cash_actual_vs_shadow_row(
                actual_weights=actual_weights,
                shadow_cash_weight=shadow_cash_weight,
                actual_has_ratio=actual_has_ratio,
            )
        )
    data_gap = None
    if qmt_event is None:
        data_gap = "qmt_position_import_missing"
    elif not actual_has_ratio:
        data_gap = "qmt_holding_weight_missing"
    state = {
        "status": "ok",
        "data": {
            "schema_version": "1.0",
            "as_of": as_of,
            "available": portfolio is not None,
            "source_status": "actual_ratio_available" if actual_has_ratio else "actual_ratio_missing",
            "source_event_id": qmt_event["object_id"] if qmt_event else None,
            "source_basis_date": qmt_event["basis_date"] if qmt_event else None,
            "qmt_read_status": _qmt_read_status(qmt_event, actual_has_ratio),
            "shadow_portfolio_id": portfolio["portfolio_id"] if portfolio else None,
            "actual_equity_weight": _equity_weight(actual_weights) if actual_has_ratio else None,
            "shadow_equity_weight": _equity_weight(shadow_weights) if portfolio else None,
            "active_exposure_pp": (
                round((_equity_weight(shadow_weights) - _equity_weight(actual_weights)) * 100, 4)
                if actual_has_ratio and portfolio
                else None
            ),
            "max_abs_delta_pp": _max_abs_delta(rows),
            "rows": rows,
            "data_gaps": [data_gap] if data_gap else [],
            "notes": _actual_vs_shadow_notes(qmt_event, actual_has_ratio),
        },
    }
    assert_no_sensitive_content(state)
    return state


def build_portfolio_history_state(repo: SQLiteRepository, as_of: str | None = None) -> dict[str, Any]:
    repo.init_db()
    events = [event for event in repo.timeline(as_of) if event["type"] == "portfolio"]
    snapshots = [_portfolio_snapshot_history_item(event) for event in reversed(events)]
    rebalance_records = [
        _portfolio_rebalance_history_item(event, trade)
        for event in reversed(events)
        for trade in event["payload"].get("paper_trades", [])
    ]
    state = {
        "status": "ok",
        "data": {
            "schema_version": "1.0",
            "as_of": as_of,
            "snapshot_count": len(snapshots),
            "rebalance_count": len(rebalance_records),
            "snapshots": snapshots,
            "rebalance_records": rebalance_records,
            "json_replay_endpoint": "/timeline/replay",
        },
    }
    assert_no_sensitive_content(state)
    return state


def render_dashboard_page(state: dict[str, Any], page: str) -> str:
    data = state["data"]
    if page == "dashboard":
        content = (
            _overview_section(data)
            + _risk_section(data)
            + _comparison_section(data)
            + _macro_section(data)
            + _portfolio_section(data)
            + _research_section(data)
            + _report_section(data)
        )
        title = "Dashboard"
    elif page == "overview":
        content = _overview_section(data)
        title = "Overview"
    elif page == "portfolio":
        content = _portfolio_section(data)
        title = "Portfolio"
    elif page == "research":
        content = _research_section(data)
        title = "Research"
    elif page == "report":
        content = _report_section(data)
        title = "Report"
    else:
        raise ValueError(f"unsupported dashboard page: {page}")
    return _page_shell(title, content, data)


def _latest_research_by_module(timeline: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest_by_current_key: dict[str, dict[str, Any]] = {}
    for event in timeline:
        if event["type"] == "research":
            payload = event["payload"]
            latest_by_current_key[_research_current_key(payload)] = payload
    return list(latest_by_current_key.values())


def _research_current_key(payload: dict[str, Any]) -> str:
    module = payload.get("module", "unknown")
    symbol = payload.get("payload", {}).get("symbol") or payload.get("symbol")
    if symbol:
        return f"{module}:{symbol}"
    return module


def _daily_refresh_state(
    timeline: list[dict[str, Any]],
    as_of: str | None,
    actual_vs_shadow: dict[str, Any],
) -> dict[str, Any]:
    reference_date = _reference_date(as_of)
    market_event = _latest_event_for_date(timeline, reference_date, "market")
    research_event = _latest_event_for_date(timeline, reference_date, "research")
    qmt_status = actual_vs_shadow["qmt_read_status"]
    qmt_done = qmt_status["status"] == "success" and qmt_status["last_basis_date"] == reference_date
    items = [
        _daily_refresh_item(
            item_id="market",
            label="市场快照",
            done=market_event is not None,
            last_basis_date=market_event["basis_date"] if market_event else _latest_basis_date(timeline, "market"),
            endpoint="/market/view#market-refresh",
            action_label="刷新市场快照",
            done_detail="今天已有市场快照。",
            pending_detail="今天还没有市场快照。",
        ),
        _daily_refresh_item(
            item_id="research",
            label="研究快照",
            done=research_event is not None,
            last_basis_date=research_event["basis_date"] if research_event else _latest_basis_date(timeline, "research"),
            endpoint="/research/import/view",
            action_label="导入研究 JSON",
            done_detail="今天已有研究快照。",
            pending_detail="今天还没有研究快照。",
        ),
        _daily_refresh_item(
            item_id="qmt",
            label="QMT 实际持仓",
            done=qmt_done,
            last_basis_date=qmt_status["last_basis_date"],
            endpoint="/portfolio/view#qmt-refresh",
            action_label="从 QMT 刷新",
            done_detail="今天已读取实际持仓比例。",
            pending_detail="今天还没有读取实际持仓比例。",
            reason=qmt_status["reason"],
        ),
    ]
    return {
        "schema_version": "1.0",
        "reference_date": reference_date,
        "all_done": all(item["status"] == "done" for item in items),
        "items": items,
    }


def _daily_refresh_item(
    *,
    item_id: str,
    label: str,
    done: bool,
    last_basis_date: str | None,
    endpoint: str,
    action_label: str,
    done_detail: str,
    pending_detail: str,
    reason: str | None = None,
) -> dict[str, Any]:
    return {
        "item_id": item_id,
        "label": label,
        "status": "done" if done else "pending",
        "last_basis_date": last_basis_date,
        "detail": done_detail if done else pending_detail,
        "reason": None if done else reason,
        "endpoint": endpoint,
        "action_label": action_label,
    }


def _reference_date(as_of: str | None) -> str:
    if as_of:
        return as_of[:10]
    return date.today().isoformat()


def _latest_event_for_date(
    timeline: list[dict[str, Any]],
    basis_date: str,
    event_type: str,
) -> dict[str, Any] | None:
    for event in reversed(timeline):
        if event["type"] == event_type and event["basis_date"] == basis_date:
            return event
    return None


def _latest_basis_date(timeline: list[dict[str, Any]], event_type: str) -> str | None:
    for event in reversed(timeline):
        if event["type"] == event_type:
            return event["basis_date"]
    return None


def _market_state(market: dict[str, Any] | None) -> dict[str, Any]:
    if market is None:
        return {"available": False}
    payload = market["payload"]
    return {
        "available": True,
        "snapshot_id": market["snapshot_id"],
        "basis_date": market["basis_date"],
        "market_score": payload["market_score"],
        "risk_level": payload["risk_level"],
        "equity_min": payload["equity_min"],
        "equity_max": payload["equity_max"],
        "confidence": market["confidence"],
        "data_sources": market["data_sources"],
        "data_gaps": market["data_gaps"],
        "conflicts": market["conflicts"],
    }


def _target_pool_state(target_pool: dict[str, Any] | None) -> dict[str, Any]:
    if target_pool is None:
        return {"available": False, "entries": []}
    entries = [
        {
            "pool_type": entry["pool_type"],
            "symbols": entry["symbols"],
            "display_symbols": [display_symbol(symbol) for symbol in entry["symbols"]],
            "count": len(entry["symbols"]),
        }
        for entry in target_pool["entries"]
    ]
    return {
        "available": True,
        "target_pool_id": target_pool["target_pool_id"],
        "basis_date": target_pool["basis_date"],
        "entries": entries,
    }


def _portfolio_state(portfolio: dict[str, Any] | None, market: dict[str, Any] | None) -> dict[str, Any]:
    if portfolio is None:
        return {"available": False, "holdings": []}
    holdings = [
        {
            "symbol": symbol,
            "name": symbol_name(symbol),
            "display_name": display_symbol(symbol),
            "weight": weight,
        }
        for symbol, weight in sorted(portfolio["holdings_weight"].items())
    ]
    equity_weight = round(sum(item["weight"] for item in holdings if _is_equity_symbol(item["symbol"])), 6)
    market_payload = market.get("payload") if market else None
    target_mid = None
    deviation_pp = None
    if market_payload:
        target_mid = round((market_payload["equity_min"] + market_payload["equity_max"]) / 2, 6)
        deviation_pp = round((equity_weight - target_mid) * 100, 4)
    return {
        "available": True,
        "portfolio_id": portfolio["portfolio_id"],
        "basis_date": portfolio["basis_date"],
        "nav_index": portfolio["nav_index"],
        "cash_weight": portfolio["cash_weight"],
        "equity_weight": equity_weight,
        "target_mid": target_mid,
        "deviation_pp": deviation_pp,
        "pnl_ratio": portfolio["pnl_ratio"],
        "turnover": portfolio["turnover"],
        "drawdown": portfolio["drawdown"],
        "benchmark_returns": portfolio["benchmark_returns"],
        "source_decision_id": portfolio["source_decision_id"],
        "source_target_pool_id": portfolio["source_target_pool_id"],
        "paper_changes": [
            {
                "symbol": item["symbol"],
                "display_name": display_symbol(item["symbol"]),
                "action": item["action"],
                "current_weight": item["current_weight"],
                "target_weight": item["target_weight"],
                "delta_weight_pp": item["delta_weight_pp"],
                "reason": item["reason"],
            }
            for item in portfolio["paper_trades"]
        ],
        "holdings": holdings,
    }


def _portfolio_snapshot_history_item(event: dict[str, Any]) -> dict[str, Any]:
    payload = event["payload"]
    holdings = [
        {
            "symbol": symbol,
            "display_name": display_symbol(symbol),
            "weight": weight,
        }
        for symbol, weight in sorted(payload["holdings_weight"].items())
    ]
    return {
        "basis_date": payload["basis_date"],
        "created_at": event["timestamp"],
        "portfolio_id": payload["portfolio_id"],
        "source_decision_id": payload["source_decision_id"],
        "source_target_pool_id": payload["source_target_pool_id"],
        "nav_index": payload["nav_index"],
        "cash_weight": payload["cash_weight"],
        "turnover": payload["turnover"],
        "pnl_ratio": payload["pnl_ratio"],
        "drawdown": payload["drawdown"],
        "paper_trade_count": len(payload.get("paper_trades", [])),
        "holdings": holdings,
    }


def _portfolio_rebalance_history_item(event: dict[str, Any], trade: dict[str, Any]) -> dict[str, Any]:
    payload = event["payload"]
    return {
        "basis_date": payload["basis_date"],
        "created_at": event["timestamp"],
        "portfolio_id": payload["portfolio_id"],
        "source_decision_id": payload["source_decision_id"],
        "symbol": trade["symbol"],
        "display_name": display_symbol(trade["symbol"]),
        "action": trade["action"],
        "current_weight": trade["current_weight"],
        "target_weight": trade["target_weight"],
        "delta_weight_pp": trade["delta_weight_pp"],
        "reason": trade["reason"],
        "is_paper": trade["is_paper"],
    }


def _latest_qmt_position_event(timeline: list[dict[str, Any]]) -> dict[str, Any] | None:
    for event in reversed(timeline):
        if event["type"] == "market_event" and event["payload"].get("event_subtype") == "qmt_position_import":
            return event
    return None


def _qmt_holdings_weight(payload: dict[str, Any]) -> dict[str, float]:
    raw = payload.get("holdings_weight", {})
    if not isinstance(raw, dict):
        return {}
    return {
        str(symbol): round(float(weight), 6)
        for symbol, weight in raw.items()
        if float(weight) >= 0
    }


def _qmt_symbols(event: dict[str, Any] | None) -> set[str]:
    if event is None:
        return set()
    return {str(symbol) for symbol in event["payload"].get("symbols", [])}


def _qmt_read_status(qmt_event: dict[str, Any] | None, actual_has_ratio: bool) -> dict[str, Any]:
    if qmt_event is None:
        return {
            "status": "missing",
            "last_basis_date": None,
            "last_event_id": None,
            "reason": "qmt_position_import_missing",
            "next_action": "refresh_qmt_positions",
            "next_action_label": "打开并登录本机 QMT 后，点击从 QMT 刷新。",
        }

    payload = qmt_event["payload"]
    event_status = str(payload.get("status", "unknown"))
    data_gaps = payload.get("data_gaps", [])
    reason = str(data_gaps[0]) if data_gaps else None
    if event_status == "imported" and actual_has_ratio:
        status = "success"
        next_action = "review_actual_shadow_delta"
        next_action_label = "查看实际持仓与影子组合差异。"
    else:
        status = "blocked" if event_status == "blocked" else "incomplete"
        reason = reason or "qmt_holding_weight_missing"
        next_action, next_action_label = _qmt_next_action(reason)

    return {
        "status": status,
        "last_basis_date": qmt_event["basis_date"],
        "last_event_id": qmt_event["object_id"],
        "reason": reason,
        "next_action": next_action,
        "next_action_label": next_action_label,
    }


def _qmt_next_action(reason: str) -> tuple[str, str]:
    if reason == "qmt_readonly_config_missing":
        return ("set_qmt_readonly_config", "配置本机 QMT 只读路径后重新刷新。")
    if reason in {"qmt_connect_failed", "qmt_read_failed"}:
        return ("open_login_qmt_then_refresh", "确认 QMT 已打开并登录，然后重新刷新。")
    if reason == "qmt_xtquant_sdk_missing":
        return ("select_qmt_python_runtime", "确认本机 QMT SDK 可用后重新刷新。")
    if reason in {"qmt_total_asset_unavailable", "qmt_position_missing"}:
        return ("confirm_qmt_position_source", "确认 QMT 持仓数据可读取后重新刷新。")
    return ("refresh_qmt_positions", "重新从 QMT 刷新实际持仓比例。")


def _actual_vs_shadow_row(
    symbol: str,
    actual_weights: dict[str, float],
    shadow_weights: dict[str, float],
    actual_has_ratio: bool,
) -> dict[str, Any]:
    actual_weight = actual_weights.get(symbol) if actual_has_ratio else None
    shadow_weight = round(float(shadow_weights.get(symbol, 0)), 6)
    delta_pp = round((shadow_weight - float(actual_weight)) * 100, 4) if actual_weight is not None else None
    return {
        "symbol": symbol,
        "display_name": display_symbol(symbol),
        "actual_weight": actual_weight,
        "shadow_weight": shadow_weight,
        "shadow_minus_actual_pp": delta_pp,
        "status": _actual_vs_shadow_status(actual_weight, shadow_weight, delta_pp),
    }


def _cash_actual_vs_shadow_row(
    *,
    actual_weights: dict[str, float],
    shadow_cash_weight: float,
    actual_has_ratio: bool,
) -> dict[str, Any]:
    actual_cash = round(max(0.0, 1 - sum(actual_weights.values())), 6) if actual_has_ratio else None
    delta_pp = round((shadow_cash_weight - float(actual_cash)) * 100, 4) if actual_cash is not None else None
    return {
        "symbol": "CASH",
        "display_name": "现金/未配置",
        "actual_weight": actual_cash,
        "shadow_weight": round(shadow_cash_weight, 6),
        "shadow_minus_actual_pp": delta_pp,
        "status": _actual_vs_shadow_status(actual_cash, shadow_cash_weight, delta_pp),
    }


def _actual_vs_shadow_status(actual_weight: float | None, shadow_weight: float, delta_pp: float | None) -> str:
    if actual_weight is None:
        return "actual_ratio_missing"
    if abs(delta_pp or 0) < 0.01:
        return "aligned"
    if shadow_weight > actual_weight:
        return "shadow_overweight"
    return "shadow_underweight"


def _actual_vs_shadow_notes(qmt_event: dict[str, Any] | None, actual_has_ratio: bool) -> list[str]:
    if qmt_event is None:
        return ["No QMT read-only holding import event is available for actual-weight comparison."]
    if not actual_has_ratio:
        return ["The latest QMT holding import lists symbols but does not include holding ratios."]
    return ["Actual weights come from the latest QMT read-only ratio import; comparison is display-only."]


def _max_abs_delta(rows: list[dict[str, Any]]) -> float | None:
    values = [
        abs(float(row["shadow_minus_actual_pp"]))
        for row in rows
        if row["shadow_minus_actual_pp"] is not None
    ]
    return round(max(values), 4) if values else None


def _research_state(research_items: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "available": bool(research_items),
        "items": [
            {
                "module": item["module"],
                "snapshot_id": item["snapshot_id"],
                "basis_date": item["basis_date"],
                "summary": item["executive_summary"],
                "confidence": item["confidence"],
                "actionability": item["actionability"],
                "next_review_date": item["next_review_date"],
                "data_gaps": item["data_gaps"],
                "conflicts": item["conflicts"],
            }
            for item in research_items
        ],
    }


def _report_state(replay: dict[str, Any], research_items: list[dict[str, Any]]) -> dict[str, Any]:
    market = replay.get("market")
    decision = replay.get("decision")
    portfolio = replay.get("portfolio")
    return {
        "available": any([market, decision, portfolio, research_items]),
        "supported_formats": ["markdown", "html", "pdf"],
        "manifest_preview": {
            "market_snapshot_id": market.get("snapshot_id") if market else None,
            "decision_id": decision.get("decision_id") if decision else None,
            "portfolio_id": portfolio.get("portfolio_id") if portfolio else None,
            "research_snapshot_ids": [item["snapshot_id"] for item in research_items],
        },
        "sections": [
            "executive_summary",
            "market_state",
            "research_insights",
            "decision_log",
            "portfolio_state",
            "risk_section",
        ],
    }


def _risk_state(risk: dict[str, Any]) -> dict[str, Any]:
    return {
        "available": risk["status"] == "ok",
        "overall_risk_score": risk["overall_risk_score"],
        "risk_level": risk["risk_level"],
        "exposure_warning": risk["exposure_warning"],
        "concentration_risk": risk["concentration_risk"],
        "deviation_from_research": risk["deviation_from_research"],
        "shadow_vs_market_gap": risk["shadow_vs_market_gap"],
        "warnings": risk["warnings"],
    }


def _comparison_state(comparison: dict[str, Any]) -> dict[str, Any]:
    return {
        "available": comparison["status"] == "ok",
        "return_comparison": comparison["return_comparison"],
        "drawdown_comparison": comparison["drawdown_comparison"],
        "exposure_comparison": comparison["exposure_comparison"],
        "deviation_analysis": comparison["deviation_analysis"],
        "curve": comparison["curve"],
    }


def _macro_state(macro: dict[str, Any]) -> dict[str, Any]:
    return {
        "available": macro["status"] == "ok",
        "macro_snapshot": macro["macro_snapshot"],
        "model_consensus": macro["model_consensus"],
        "alpha_factor_decomposition": macro["alpha_factor_decomposition"],
    }


def _data_gaps(market: dict[str, Any] | None, research_items: list[dict[str, Any]]) -> list[str]:
    gaps: list[str] = []
    if market:
        gaps.extend(market.get("data_gaps", []))
    for item in research_items:
        gaps.extend(item.get("data_gaps", []))
    return gaps


def _conflicts(market: dict[str, Any] | None, research_items: list[dict[str, Any]]) -> list[str]:
    conflicts: list[str] = []
    if market:
        conflicts.extend(market.get("conflicts", []))
    for item in research_items:
        conflicts.extend(item.get("conflicts", []))
    return conflicts


def _page_shell(title: str, content: str, data: dict[str, Any]) -> str:
    nav = "".join(
        f"<a href=\"{item['href']}\">{html.escape(item['label'])}</a>"
        for item in data["navigation"]
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>MyInvest {html.escape(title)}</title>
  <style>
    :root {{ color-scheme: light; --ink:#172026; --muted:#667085; --line:#d9dee7; --panel:#ffffff; --bg:#f6f8fb; --accent:#0f766e; --warn:#b45309; --bad:#b42318; }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; background: var(--bg); color: var(--ink); font: 14px/1.45 Arial, sans-serif; }}
    header {{ border-bottom: 1px solid var(--line); background: #ffffff; }}
    .wrap {{ max-width: 1180px; margin: 0 auto; padding: 16px 20px; }}
    .top {{ display:flex; justify-content:space-between; gap:16px; align-items:center; }}
    h1 {{ font-size: 22px; margin: 0; letter-spacing: 0; }}
    h2 {{ font-size: 16px; margin: 0 0 12px; letter-spacing: 0; }}
    nav {{ display:flex; flex-wrap:wrap; gap:8px; }}
    nav a {{ color: var(--ink); text-decoration:none; border:1px solid var(--line); padding:7px 10px; border-radius:6px; background:#fff; }}
    main {{ max-width:1180px; margin:0 auto; padding:18px 20px 36px; }}
    section {{ margin: 0 0 18px; }}
    .grid {{ display:grid; grid-template-columns: repeat(4, minmax(0,1fr)); gap:12px; }}
    .panel {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:14px; min-width:0; }}
    .metric {{ color:var(--muted); font-size:12px; }}
    .value {{ font-size:20px; font-weight:700; margin-top:4px; overflow-wrap:anywhere; }}
    table {{ width:100%; border-collapse:collapse; background:#fff; border:1px solid var(--line); }}
    th, td {{ padding:9px 10px; text-align:left; border-bottom:1px solid var(--line); vertical-align:top; overflow-wrap:anywhere; }}
    th {{ color:#344054; background:#eef2f6; font-weight:700; }}
    .bar {{ height:10px; background:#e4e7ec; border-radius:5px; overflow:hidden; min-width:120px; }}
    .fill {{ height:100%; background:var(--accent); }}
    .muted {{ color:var(--muted); }}
    .warn {{ color:var(--warn); font-weight:700; }}
    .bad {{ color:var(--bad); font-weight:700; }}
    .stack {{ display:grid; gap:12px; }}
    @media (max-width: 760px) {{ .top {{ align-items:flex-start; flex-direction:column; }} .grid {{ grid-template-columns: repeat(2, minmax(0,1fr)); }} th,td {{ padding:8px; }} }}
    @media (max-width: 520px) {{ .grid {{ grid-template-columns: 1fr; }} .wrap, main {{ padding-left:12px; padding-right:12px; }} }}
  </style>
</head>
<body>
  <header><div class="wrap top"><h1>MyInvest {html.escape(title)}</h1><nav>{nav}</nav></div></header>
  <main>{content}</main>
</body>
</html>
"""


def _overview_section(data: dict[str, Any]) -> str:
    overview = data["overview"]
    blocked_class = "bad" if overview["blocked"] else "value"
    return f"""
<section>
  <h2>Overview</h2>
  <div class="grid">
    {_metric('Self Check', overview['self_check_status'])}
    {_metric('Replay', 'available' if overview['replay_available'] else 'unavailable')}
    {_metric('Events', data['replay']['event_count'])}
    {_metric('Blocked', 'yes' if overview['blocked'] else 'no', blocked_class)}
  </div>
</section>
"""


def _portfolio_section(data: dict[str, Any]) -> str:
    portfolio = data["portfolio"]
    market = data["market"]
    if not portfolio["available"]:
        return "<section><h2>Portfolio</h2><p class=\"muted\">Portfolio unavailable.</p></section>"
    rows = "".join(
        "<tr>"
        f"<td>{html.escape(item['display_name'])}</td>"
        f"<td>{_percent(item['weight'])}</td>"
        f"<td><div class=\"bar\"><div class=\"fill\" style=\"width:{_bar_width(item['weight'])}%\"></div></div></td>"
        "</tr>"
        for item in portfolio["holdings"]
    )
    target = "unavailable"
    if market["available"]:
        target = f"{_percent(market['equity_min'])} to {_percent(market['equity_max'])}"
    deviation = "unavailable" if portfolio["deviation_pp"] is None else f"{portfolio['deviation_pp']} pp"
    return f"""
<section>
  <h2>Portfolio</h2>
  <div class="grid">
    {_metric('NAV Index', portfolio['nav_index'])}
    {_metric('Equity Weight', _percent(portfolio['equity_weight']))}
    {_metric('Target Range', target)}
    {_metric('Deviation', deviation)}
  </div>
  <table><thead><tr><th>Holding</th><th>Weight</th><th>Allocation</th></tr></thead><tbody>{rows}</tbody></table>
</section>
"""


def _comparison_section(data: dict[str, Any]) -> str:
    comparison = data["comparison"]
    if not comparison["available"]:
        return "<section><h2>Comparison</h2><p class=\"muted\">Comparison state unavailable.</p></section>"
    returns = comparison["return_comparison"]
    exposure = comparison["exposure_comparison"]
    deviation = comparison["deviation_analysis"]
    curve_rows = "".join(
        "<tr>"
        f"<td>{html.escape(item['as_of'])}</td>"
        f"<td>{item['real_proxy_nav']}</td>"
        f"<td>{item['shadow_nav']}</td>"
        f"<td>{item['benchmark_nav']}</td>"
        "</tr>"
        for item in comparison["curve"]
    )
    return f"""
<section>
  <h2>Comparison</h2>
  <div class="grid">
    {_metric('Shadow Return', _percent(returns['shadow_return']))}
    {_metric('Benchmark Return', _percent(returns['benchmark_return']))}
    {_metric('Real Proxy Return', _percent(returns['real_proxy_return']))}
    {_metric('Tracking Gap', f"{deviation['tracking_gap_pp']} pp")}
  </div>
  <div class="grid">
    {_metric('Shadow Equity', _percent(exposure['shadow_equity_weight']))}
    {_metric('Real Proxy Equity', _percent(exposure['real_proxy_equity_weight']))}
    {_metric('Active Exposure', f"{exposure['active_exposure_pp']} pp")}
    {_metric('Allocation Overlap', _percent(deviation['allocation_overlap']))}
  </div>
  <table><thead><tr><th>Date</th><th>Real Proxy NAV</th><th>Shadow NAV</th><th>Benchmark NAV</th></tr></thead><tbody>{curve_rows}</tbody></table>
</section>
"""


def _macro_section(data: dict[str, Any]) -> str:
    macro = data["macro"]
    if not macro["available"]:
        return "<section><h2>Macro</h2><p class=\"muted\">Macro state unavailable.</p></section>"
    snapshot = macro["macro_snapshot"]
    consensus = macro["model_consensus"]
    factors = macro["alpha_factor_decomposition"]["factors"]
    factor_rows = "".join(
        "<tr>"
        f"<td>{html.escape(item['factor'])}</td>"
        f"<td>{item['contribution_score']}</td>"
        f"<td>{html.escape(item['direction'])}</td>"
        f"<td>{html.escape(item['source'])}</td>"
        "</tr>"
        for item in factors
    )
    if not factor_rows:
        factor_rows = "<tr><td>none</td><td>0</td><td>neutral</td><td>macro_state</td></tr>"
    return f"""
<section>
  <h2>Macro</h2>
  <div class="grid">
    {_metric('Liquidity Index', _percent(snapshot['liquidity_index']))}
    {_metric('Rate Pressure', _percent(snapshot['rate_pressure']))}
    {_metric('Inflation Regime', snapshot['inflation_regime'])}
    {_metric('Risk Cycle', snapshot['risk_cycle_state'])}
  </div>
  <div class="grid">
    {_metric('Consensus Score', consensus['consensus_score'])}
    {_metric('Consensus State', consensus['consensus_state'])}
    {_metric('Disagreement', _percent(consensus['disagreement_score']))}
    {_metric('Confidence', _percent(consensus['calibrated_confidence']))}
  </div>
  <table><thead><tr><th>Factor</th><th>Contribution</th><th>Direction</th><th>Source</th></tr></thead><tbody>{factor_rows}</tbody></table>
</section>
"""


def _risk_section(data: dict[str, Any]) -> str:
    risk = data["risk"]
    if not risk["available"]:
        return "<section><h2>Risk</h2><p class=\"muted\">Risk state unavailable.</p></section>"
    badge_class = "bad" if risk["risk_level"] == "high" else "warn" if risk["risk_level"] == "medium" else "value"
    rows = "".join(
        "<tr>"
        f"<td>{html.escape(item['code'])}</td>"
        f"<td>{html.escape(item['severity'])}</td>"
        f"<td>{html.escape(item['message'])}</td>"
        f"<td>{html.escape(item['source'])}</td>"
        "</tr>"
        for item in risk["warnings"]
    )
    if not rows:
        rows = "<tr><td>none</td><td>low</td><td>No active warnings.</td><td>risk_state</td></tr>"
    return f"""
<section>
  <h2>Risk</h2>
  <div class="grid">
    {_metric('Risk Score', risk['overall_risk_score'])}
    {_metric('Risk Level', risk['risk_level'], badge_class)}
    {_metric('Exposure', risk['exposure_warning'])}
    {_metric('Shadow Gap', f"{risk['shadow_vs_market_gap']} pp")}
  </div>
  <table><thead><tr><th>Code</th><th>Severity</th><th>Message</th><th>Source</th></tr></thead><tbody>{rows}</tbody></table>
</section>
"""


def _research_section(data: dict[str, Any]) -> str:
    research = data["research"]
    if not research["available"]:
        return "<section><h2>Research</h2><p class=\"muted\">Research unavailable.</p></section>"
    rows = "".join(
        "<tr>"
        f"<td>{html.escape(item['module'])}</td>"
        f"<td>{html.escape(item['summary'])}</td>"
        f"<td>{_percent(item['confidence'])}</td>"
        f"<td>{html.escape(item['next_review_date'])}</td>"
        "</tr>"
        for item in research["items"]
    )
    return f"""
<section>
  <h2>Research</h2>
  <table><thead><tr><th>Module</th><th>Summary</th><th>Confidence</th><th>Next Review</th></tr></thead><tbody>{rows}</tbody></table>
</section>
"""


def _report_section(data: dict[str, Any]) -> str:
    report = data["report"]
    manifest = report["manifest_preview"]
    research_count = len(manifest["research_snapshot_ids"])
    rows = "".join(f"<tr><td>{html.escape(section)}</td><td>ready</td></tr>" for section in report["sections"])
    return f"""
<section>
  <h2>Report Preview</h2>
  <div class="grid">
    {_metric('Formats', ', '.join(report['supported_formats']))}
    {_metric('Market', manifest['market_snapshot_id'] or 'unavailable')}
    {_metric('Portfolio', manifest['portfolio_id'] or 'unavailable')}
    {_metric('Research Items', research_count)}
  </div>
  <table><thead><tr><th>Section</th><th>Status</th></tr></thead><tbody>{rows}</tbody></table>
</section>
"""


def _metric(label: str, value: Any, value_class: str = "value") -> str:
    return (
        "<div class=\"panel\">"
        f"<div class=\"metric\">{html.escape(str(label))}</div>"
        f"<div class=\"{value_class}\">{html.escape(str(value))}</div>"
        "</div>"
    )


def _percent(value: float | int) -> str:
    return f"{float(value) * 100:.2f}%"


def _bar_width(value: float | int) -> str:
    return f"{max(0, min(100, float(value) * 100)):.2f}"


def _equity_weight(weights: dict[str, float]) -> float:
    return round(sum(weight for symbol, weight in weights.items() if _is_equity_symbol(symbol)), 6)


def _is_equity_symbol(symbol: str) -> bool:
    return not symbol.startswith("511")
