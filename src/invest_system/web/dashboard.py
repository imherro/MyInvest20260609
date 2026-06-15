from __future__ import annotations

import html
from typing import Any

from invest_system.comparison import compute_comparison_state
from invest_system.repositories import SQLiteRepository
from invest_system.risk import compute_risk_state
from invest_system.self_check import system_status
from invest_system.validators.policies import assert_no_sensitive_content


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
    data_gaps = _data_gaps(market, research_items)
    conflicts = _conflicts(market, research_items)
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
            "research": _research_state(research_items),
            "risk": _risk_state(risk),
            "comparison": _comparison_state(comparison),
            "report": _report_state(replay, research_items),
            "replay": {
                "trace": replay.get("trace", {}),
                "event_count": len(timeline),
            },
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
    latest_by_module: dict[str, dict[str, Any]] = {}
    for event in timeline:
        if event["type"] == "research":
            payload = event["payload"]
            latest_by_module[payload.get("module", "unknown")] = payload
    return list(latest_by_module.values())


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
        {"symbol": symbol, "weight": weight}
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
        "holdings": holdings,
    }


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
        f"<td>{html.escape(item['symbol'])}</td>"
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
  <table><thead><tr><th>Symbol</th><th>Weight</th><th>Allocation</th></tr></thead><tbody>{rows}</tbody></table>
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


def _is_equity_symbol(symbol: str) -> bool:
    return not symbol.startswith("511")
