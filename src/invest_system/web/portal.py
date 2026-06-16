from __future__ import annotations

import html
from typing import Any

from invest_system.decision import build_decision_proposal
from invest_system.entry import build_home_state
from invest_system.guidance import compute_guidance_state
from invest_system.repositories import SQLiteRepository
from invest_system.validators.policies import assert_no_sensitive_content
from invest_system.web.dashboard import build_dashboard_state
from invest_system.web.data_gap_display import describe_data_gap, unique_data_gap_descriptions
from invest_system.web.symbol_display import display_symbol
from invest_system.workflow import build_daily_workflow_state


NAV_ITEMS = [
    {"label": "首页", "href": "/app", "page": "home"},
    {"label": "每日", "href": "/workflow/daily/view", "page": "daily"},
    {"label": "今日边界", "href": "/guidance/view", "page": "guidance"},
    {"label": "市场", "href": "/market/view", "page": "market"},
    {"label": "主线", "href": "/theme/view", "page": "theme"},
    {"label": "风险", "href": "/risk/view", "page": "risk"},
    {"label": "宏观", "href": "/macro/view", "page": "macro"},
    {"label": "对比", "href": "/comparison/view", "page": "comparison"},
    {"label": "决策", "href": "/decision/view", "page": "decision"},
    {"label": "目标池", "href": "/target-pool/view", "page": "target_pool"},
    {"label": "组合", "href": "/portfolio/view", "page": "portfolio"},
    {"label": "研究", "href": "/research/view", "page": "research"},
    {"label": "报告", "href": "/report/view", "page": "report"},
    {"label": "系统", "href": "/system/view", "page": "system"},
]

PAGE_TITLES = {
    "home": "自然人首页",
    "entry": "自然人首页",
    "dashboard": "综合看板",
    "overview": "总览",
    "daily": "每日研究工作流",
    "guidance": "今日行动边界",
    "market": "市场状态",
    "theme": "主线研究",
    "risk": "风险状态",
    "macro": "宏观状态",
    "comparison": "对比分析",
    "decision": "决策预览",
    "target_pool": "策略目标池",
    "portfolio": "影子组合",
    "research": "研究队列",
    "research_import": "研究 JSON 导入",
    "report": "每日报告",
    "system": "系统状态",
    "usability": "易用性检查",
}

USABILITY_ENDPOINTS = [
    "/app",
    "/workflow/daily/view",
    "/guidance/view",
    "/market/view",
    "/theme/view",
    "/risk/view",
    "/macro/view",
    "/comparison/view",
    "/decision/view",
    "/target-pool/view",
    "/portfolio/view",
    "/research/view",
    "/research/import/view",
    "/report/view",
    "/system/view",
    "/usability/view",
]

HUMAN_ENDPOINT_MAP = {
    "/home": "/app",
    "/entry/home_state": "/app",
    "/workflow/daily/state": "/workflow/daily/view",
    "/guidance/state": "/guidance/view",
    "/market/latest": "/market/view",
    "/theme/state": "/theme/view",
    "/target-pool/latest": "/target-pool/view",
    "/research/latest": "/research/view",
    "/research/valuation-review": "/research/view#valuation-review",
    "/research/valuation-prompts": "/research/view#valuation-prompts",
    "/research/import": "/research/import/view",
    "/research/import/validate": "/research/import/view",
    "/decision/latest": "/decision/view",
    "/decision/proposal": "/decision/view",
    "/decision/explain": "/decision/view",
    "/portfolio/state": "/portfolio/view",
    "/portfolio/history": "/portfolio/view",
    "/portfolio/actual-vs-shadow": "/portfolio/view",
    "/risk/state": "/risk/view",
    "/macro/state": "/macro/view",
    "/comparison/state": "/comparison/view",
    "/system/status": "/system/view",
    "/system/dashboard_state": "/dashboard",
    "/usability/state": "/usability/view",
}


def build_portal_state(repo: SQLiteRepository, as_of: str | None = None) -> dict[str, Any]:
    dashboard = build_dashboard_state(repo, as_of)["data"]
    home = build_home_state(repo, as_of)
    guidance = compute_guidance_state(repo, as_of)
    decision_proposal = build_decision_proposal(repo, as_of)
    daily_workflow = build_daily_workflow_state(repo, as_of)
    research_valuation_review = build_research_valuation_review_state(repo, as_of)["data"]
    research_valuation_prompts = _build_research_valuation_prompt_payload(
        research_valuation_review,
        as_of,
    )
    usability = _build_usability_payload(dashboard, home, guidance)
    state = {
        "status": "ok",
        "data": {
            "schema_version": "1.0",
            "as_of": as_of,
            "navigation": NAV_ITEMS,
            "primary_home": "/app",
            "dashboard": dashboard,
            "home": home,
            "daily_workflow": daily_workflow,
            "decision_proposal": decision_proposal,
            "guidance": guidance,
            "research_valuation_review": research_valuation_review,
            "research_valuation_prompts": research_valuation_prompts,
            "usability": usability,
        },
    }
    assert_no_sensitive_content(state)
    return state


def build_usability_state(repo: SQLiteRepository, as_of: str | None = None) -> dict[str, Any]:
    portal = build_portal_state(repo, as_of)
    return {"status": "ok", "data": portal["data"]["usability"]}


def build_research_valuation_review_state(repo: SQLiteRepository, as_of: str | None = None) -> dict[str, Any]:
    repo.init_db()
    guidance = compute_guidance_state(repo, as_of)
    timeline = repo.timeline(as_of)
    research_events = {
        event["object_id"]: event
        for event in timeline
        if event["type"] == "research"
    }
    rows = [
        _valuation_review_row(item, research_events.get(item["source"]))
        for item in guidance["research_first"]["queue"]
        if "valuation_gate_failed" in item.get("blockers", [])
    ]
    rows.sort(key=lambda item: item["symbol"])
    payload = {
        "status": "ok",
        "data": {
            "schema_version": "1.0",
            "as_of": as_of,
            "status": "review_required" if rows else "clear",
            "blocked_count": len(rows),
            "human_endpoint": "/research/view#valuation-review",
            "json_endpoint": "/research/valuation-review",
            "rows": rows,
            "notes": [
                "This is a read-only valuation review derived from ResearchFirst queue and research snapshots.",
                "It does not change decisions, portfolio state, or any external execution system.",
            ],
        },
    }
    assert_no_sensitive_content(payload)
    return payload


def build_research_valuation_prompt_state(repo: SQLiteRepository, as_of: str | None = None) -> dict[str, Any]:
    review = build_research_valuation_review_state(repo, as_of)["data"]
    payload = {
        "status": "ok",
        "data": _build_research_valuation_prompt_payload(review, as_of),
    }
    assert_no_sensitive_content(payload)
    return payload


def _build_research_valuation_prompt_payload(
    review: dict[str, Any],
    as_of: str | None,
) -> dict[str, Any]:
    prompts = [_valuation_prompt_item(row) for row in review["rows"]]
    return {
        "schema_version": "1.0",
        "as_of": as_of,
        "status": "ready" if prompts else "clear",
        "prompt_count": len(prompts),
        "human_endpoint": "/research/view#valuation-prompts",
        "json_endpoint": "/research/valuation-prompts",
        "import_endpoint": "/research/import/view",
        "prompts": prompts,
        "notes": [
            "These prompts are read-only research-layer prompts derived from valuation review rows.",
            "They request research_snapshot JSON only and do not create decisions or portfolio changes.",
        ],
    }


def render_portal_page(state: dict[str, Any], page: str) -> str:
    if page not in PAGE_TITLES:
        raise ValueError(f"unsupported portal page: {page}")
    data = state["data"]
    if page in {"home", "entry", "dashboard"}:
        content = _home_content(data)
        active = "home"
    elif page == "overview":
        content = _overview_content(data)
        active = "home"
    elif page == "daily":
        content = _daily_workflow_content(data)
        active = "daily"
    elif page == "guidance":
        content = _guidance_content(data)
        active = "guidance"
    elif page == "market":
        content = _market_content(data)
        active = "market"
    elif page == "theme":
        content = _theme_content(data)
        active = "theme"
    elif page == "risk":
        content = _risk_content(data)
        active = "risk"
    elif page == "macro":
        content = _macro_content(data)
        active = "macro"
    elif page == "comparison":
        content = _comparison_content(data)
        active = "comparison"
    elif page == "decision":
        content = _decision_content(data)
        active = "decision"
    elif page == "target_pool":
        content = _target_pool_content(data)
        active = "target_pool"
    elif page == "portfolio":
        content = _portfolio_content(data)
        active = "portfolio"
    elif page == "research":
        content = _research_content(data)
        active = "research"
    elif page == "research_import":
        content = _research_import_content(data)
        active = "research"
    elif page == "report":
        content = _report_content(data)
        active = "report"
    elif page == "system":
        content = _system_content(data)
        active = "system"
    else:
        content = _usability_content(data)
        active = "usability"
    page_html = _page_shell(PAGE_TITLES[page], active, content, data)
    assert_no_sensitive_content(page_html)
    return page_html


def _build_usability_payload(
    dashboard: dict[str, Any],
    home: dict[str, Any],
    guidance: dict[str, Any],
) -> dict[str, Any]:
    feature_count = len(USABILITY_ENDPOINTS)
    next_action_endpoint = _human_endpoint(home.get("next_action", {}).get("recommended_endpoint") or "/home")
    checks = [
        _usability_check(
            "primary_home",
            "pass",
            "统一首页",
            "自然人入口固定为 /app，旧入口继续可用。",
            "/app",
        ),
        _usability_check(
            "unified_header",
            "pass",
            "统一页头",
            "主要浏览页面使用同一组导航入口。",
            "/app",
        ),
        _usability_check(
            "unified_footer",
            "pass",
            "统一页脚",
            "页脚固定展示执行边界、JSON 事实源和纸面模拟边界。",
            "/app",
        ),
        _usability_check(
            "feature_entrypoints",
            "pass" if feature_count >= 8 else "warn",
            "功能入口",
            f"当前提供 {feature_count} 个自然人可点击入口。",
            "/app",
        ),
        _usability_check(
            "daily_workflow_visible",
            "pass",
            "每日工作流",
            "每日研究闭环有独立状态页和统一导航入口。",
            "/workflow/daily/view",
        ),
        _usability_check(
            "research_import_visible",
            "pass",
            "研究导入",
            "研究 JSON 可先校验，再追加写入。",
            "/research/import/view",
        ),
        _usability_check(
            "decision_proposal_visible",
            "pass",
            "决策预览",
            "可解释决策草案有独立入口，并保持只读。",
            "/decision/view",
        ),
        _usability_check(
            "theme_research_visible",
            "pass" if dashboard["research"]["theme"]["available"] else "warn",
            "主线研究",
            "主线研究有独立页面，展开当前主线、备选主线、代表板块和关注方向。",
            "/theme/view",
        ),
        _usability_check(
            "target_pool_scope_visible",
            "pass",
            "目标池边界",
            "策略目标池和 QMT 实际持仓对照分开展示，不把实际持仓当成系统推荐池。",
            "/target-pool/view",
        ),
        _usability_check(
            "next_action_visible",
            "pass" if home.get("next_action", {}).get("recommended_endpoint") else "warn",
            "下一步引导",
            "首页直接显示系统建议先看的模块。",
            next_action_endpoint,
        ),
        _usability_check(
            "guidance_boundary_visible",
            "pass" if guidance.get("today_action", {}).get("headline") else "warn",
            "今日行动边界",
            "今日行动边界页显示可做、不可做和下一步复核项。",
            "/guidance/view",
        ),
        _usability_check(
            "json_source_available",
            "pass" if dashboard["overview"]["replay_available"] else "warn",
            "JSON 事实源",
            "页面读取 SQLite 与 JSON 回放状态；刷新按钮只追加快照。",
            "/system/dashboard_state",
        ),
        _usability_check(
            "read_only_boundary",
            "pass",
            "执行边界",
            "浏览器页面只允许受控追加研究或市场快照，不触发外部执行。",
            "/system/view",
        ),
    ]
    status = "passed" if all(item["status"] == "pass" for item in checks) else "review_required"
    payload = {
        "schema_version": "1.0",
        "status": status,
        "primary_home": "/app",
        "feature_entrypoints": USABILITY_ENDPOINTS,
        "checks": checks,
        "human_flow": [
            {"step": "打开首页", "endpoint": "/app"},
            {"step": "查看每日工作流", "endpoint": "/workflow/daily/view"},
            {"step": "查看决策预览", "endpoint": "/decision/view"},
            {"step": "查看今日边界", "endpoint": "/guidance/view"},
            {"step": "按下一步引导进入模块", "endpoint": next_action_endpoint},
            {"step": "查看组合、风险、研究或报告", "endpoint": "/dashboard"},
            {"step": "需要追溯时查看 JSON", "endpoint": "/timeline/replay"},
        ],
    }
    assert_no_sensitive_content(payload)
    return payload


def _usability_check(check_id: str, status: str, title: str, detail: str, endpoint: str) -> dict[str, Any]:
    return {
        "check_id": check_id,
        "status": status,
        "title": title,
        "detail": detail,
        "endpoint": endpoint,
    }


def _page_shell(title: str, active: str, content: str, data: dict[str, Any]) -> str:
    nav = "".join(_nav_item(item, active) for item in data["navigation"])
    today = _today_summary(data)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>MyInvest {html.escape(title)}</title>
  <style>
    :root {{ color-scheme: light; --ink:#172026; --muted:#667085; --line:#d9dee7; --bg:#f6f8fb; --panel:#ffffff; --soft:#e8f3f1; --accent:#0f766e; --accent-ink:#0b4f49; --warn:#9a5b00; --bad:#a61b1b; --good:#0b6b4f; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; background:var(--bg); color:var(--ink); font:15px/1.55 Arial, "Microsoft YaHei", sans-serif; }}
    a {{ color:var(--accent-ink); text-decoration:none; }}
    a:hover {{ text-decoration:underline; }}
    header {{ background:#fff; border-bottom:1px solid var(--line); position:sticky; top:0; z-index:10; }}
    .wrap {{ max-width:1200px; margin:0 auto; padding:14px 20px; }}
    .top {{ display:flex; align-items:center; justify-content:space-between; gap:16px; }}
    .brand {{ display:grid; gap:3px; min-width:180px; }}
    .brand-title {{ font-weight:800; font-size:20px; letter-spacing:0; }}
    .brand-subtitle {{ color:var(--muted); font-size:12px; }}
    nav {{ display:flex; flex-wrap:wrap; gap:7px; justify-content:flex-end; }}
    nav a {{ border:1px solid var(--line); border-radius:6px; padding:7px 9px; color:var(--ink); background:#fff; font-size:13px; }}
    nav a.active {{ border-color:#8ec8c1; background:var(--soft); color:var(--accent-ink); font-weight:700; }}
    main {{ max-width:1200px; margin:0 auto; padding:18px 20px 34px; }}
    section {{ margin:0 0 18px; }}
    h1 {{ margin:0; font-size:24px; letter-spacing:0; }}
    h2 {{ margin:0 0 12px; font-size:18px; letter-spacing:0; }}
    h3 {{ margin:0 0 8px; font-size:16px; letter-spacing:0; }}
    p {{ margin:0; }}
    footer {{ border-top:1px solid var(--line); background:#fff; }}
    .footer-grid {{ display:grid; grid-template-columns:2fr 1fr; gap:16px; color:var(--muted); font-size:13px; }}
    .footer-links {{ display:flex; flex-wrap:wrap; gap:10px; justify-content:flex-end; }}
    .hero {{ display:grid; grid-template-columns:minmax(0, 1.6fr) minmax(280px, 0.9fr); gap:14px; align-items:stretch; }}
    .panel {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:16px; min-width:0; }}
    .highlight {{ background:var(--soft); border-color:#a3d2cc; }}
    .grid-2 {{ display:grid; grid-template-columns:repeat(2, minmax(0, 1fr)); gap:12px; }}
    .grid-3 {{ display:grid; grid-template-columns:repeat(3, minmax(0, 1fr)); gap:12px; }}
    .grid-4 {{ display:grid; grid-template-columns:repeat(4, minmax(0, 1fr)); gap:12px; }}
    .feature-grid {{ display:grid; grid-template-columns:repeat(4, minmax(0, 1fr)); gap:12px; }}
    .feature {{ display:flex; flex-direction:column; gap:8px; min-height:126px; }}
    .feature a {{ font-weight:800; color:var(--ink); }}
    .detail {{ color:var(--muted); margin-top:8px; }}
    .small {{ color:var(--muted); font-size:13px; }}
    .label {{ color:var(--muted); font-size:13px; margin-bottom:4px; }}
    .value {{ font-size:22px; font-weight:800; overflow-wrap:anywhere; }}
    .badge-row {{ display:flex; flex-wrap:wrap; gap:8px; margin-top:12px; }}
    .badge {{ border:1px solid var(--line); border-radius:6px; padding:5px 8px; background:#fff; color:var(--muted); font-size:13px; }}
    .inline-control {{ display:inline-flex; align-items:center; gap:8px; border:1px solid var(--line); border-radius:6px; padding:7px 9px; background:#fff; color:var(--muted); }}
    .pass, .good {{ color:var(--good); font-weight:800; }}
    .warn {{ color:var(--warn); font-weight:800; }}
    .block, .bad, .missing {{ color:var(--bad); font-weight:800; }}
    .path {{ display:flex; flex-wrap:wrap; gap:8px; align-items:center; }}
    .step {{ border:1px solid var(--line); border-radius:6px; padding:7px 10px; background:#fff; }}
    .arrow {{ color:var(--muted); }}
    table {{ width:100%; border-collapse:collapse; background:#fff; border:1px solid var(--line); }}
    th, td {{ padding:9px 10px; text-align:left; border-bottom:1px solid var(--line); vertical-align:top; overflow-wrap:anywhere; }}
    th {{ color:#344054; background:#eef2f6; font-weight:800; }}
    .table-scroll {{ overflow:auto; }}
    .bar {{ height:10px; background:#e4e7ec; border-radius:5px; overflow:hidden; min-width:120px; }}
    .fill {{ height:100%; background:var(--accent); }}
    .two-pane {{ display:grid; grid-template-columns:minmax(0, 1fr) minmax(260px, 0.7fr); gap:12px; }}
    textarea {{ width:100%; min-height:300px; resize:vertical; border:1px solid var(--line); border-radius:8px; padding:12px; font:13px/1.45 Consolas, "Courier New", monospace; color:var(--ink); background:#fff; }}
    input {{ border:0; color:var(--ink); background:transparent; font:inherit; }}
    button {{ border:1px solid #8ec8c1; border-radius:6px; padding:8px 11px; background:var(--soft); color:var(--accent-ink); font-weight:800; cursor:pointer; }}
    button:disabled {{ opacity:0.6; cursor:wait; }}
    button.secondary {{ border-color:var(--line); background:#fff; color:var(--ink); }}
    pre {{ white-space:pre-wrap; overflow:auto; margin:0; border:1px solid var(--line); border-radius:8px; background:#fff; padding:12px; font:13px/1.45 Consolas, "Courier New", monospace; }}
    .prompt-details {{ min-width:260px; }}
    .prompt-details summary {{ cursor:pointer; font-weight:800; color:var(--accent-ink); }}
    .prompt-textarea {{ min-height:120px; max-height:220px; margin-top:8px; resize:vertical; }}
    .prompt-actions {{ display:flex; align-items:center; flex-wrap:wrap; gap:8px; margin-top:8px; }}
    .copy-status {{ color:var(--muted); font-size:13px; }}
    @media (max-width:900px) {{ .top {{ align-items:flex-start; flex-direction:column; }} nav {{ justify-content:flex-start; }} .hero, .two-pane, .footer-grid {{ grid-template-columns:1fr; }} .footer-links {{ justify-content:flex-start; }} .feature-grid, .grid-4 {{ grid-template-columns:repeat(2, minmax(0, 1fr)); }} .grid-3 {{ grid-template-columns:1fr; }} }}
    @media (max-width:560px) {{ .wrap, main {{ padding-left:12px; padding-right:12px; }} .feature-grid, .grid-4, .grid-2 {{ grid-template-columns:1fr; }} h1 {{ font-size:22px; }} }}
  </style>
</head>
<body data-page-shell="portal">
  <header>
    <div class="wrap top">
      <div class="brand">
        <div class="brand-title">MyInvest</div>
        <div class="brand-subtitle">只读研究与影子组合回放</div>
      </div>
      <nav aria-label="主导航">{nav}</nav>
    </div>
  </header>
  <main>
    <section class="hero">
      <div class="panel highlight">
        <h1>{html.escape(title)}</h1>
        <p class="detail">{today}</p>
      </div>
      <div class="panel">
        <h2>使用边界</h2>
        <p>所有页面只读取 JSON 与 SQLite 回放结果。</p>
        <p class="detail">研究、决策、影子组合分层显示；浏览器界面只允许受控追加快照，不触发交易。</p>
      </div>
    </section>
    {content}
  </main>
  <footer>
    <div class="wrap footer-grid">
      <div>统一页脚：JSON 为事实源 / 受控追加快照 / 影子组合仅纸面模拟 / 不连接外部执行。</div>
      <div class="footer-links">
        <a href="/usability/view">易用性检查</a>
        <a href="/system/status">系统 JSON</a>
        <a href="/timeline/replay">回放 JSON</a>
      </div>
    </div>
  </footer>
</body>
</html>
"""


def _nav_item(item: dict[str, str], active: str) -> str:
    class_name = "active" if item["page"] == active else ""
    return (
        f"<a class=\"{class_name}\" href=\"{html.escape(item['href'])}\">"
        f"{html.escape(item['label'])}</a>"
    )


def _today_summary(data: dict[str, Any]) -> str:
    guidance = data["guidance"]
    home = data["home"]
    headline = guidance.get("today_action", {}).get("headline")
    next_endpoint = _human_endpoint(home.get("next_action", {}).get("recommended_endpoint", "/guidance/view"))
    if headline:
        return (
            f"{html.escape(headline)} "
            f"<a href=\"{html.escape(next_endpoint)}\">进入下一步</a>"
        )
    return "先看今日行动边界，再进入市场、风险、组合或研究页面。"


def _home_priority_cards(data: dict[str, Any]) -> str:
    dashboard = data["dashboard"]
    guidance = data["guidance"]
    queue = guidance["research_first"]["queue"]
    valuation_review = data["research_valuation_review"]
    cards = [
        (
            "每日报告",
            "/report/view",
            _report_headline(data),
            "先看今天总摘要、阅读顺序和来源编号。",
        ),
        (
            "研究工作台",
            "/research/view#research-workbench",
            _research_workbench_title(queue, valuation_review),
            "处理 ResearchFirst 队列、估值复核和补充研究提示词。",
        ),
        (
            "组合核对",
            "/portfolio/view",
            _portfolio_conclusion_label(
                dashboard["portfolio"],
                dashboard["actual_vs_shadow"],
                dashboard["market"],
            ),
            "核对影子组合、实际持仓比例、纸面调仓和历史快照。",
        ),
    ]
    return "".join(_priority_entry_card(title, href, status, detail) for title, href, status, detail in cards)


def _priority_entry_card(title: str, href: str, status: str, detail: str) -> str:
    return f"""
<div class="panel feature">
  <a href="{html.escape(href)}">{html.escape(title)}</a>
  <p class="value">{html.escape(status)}</p>
  <p class="small">{html.escape(detail)}</p>
</div>
"""


def _home_content(data: dict[str, Any]) -> str:
    home = data["home"]
    guidance = data["guidance"]
    dashboard = data["dashboard"]
    next_action = home["next_action"]
    next_endpoint = _human_endpoint(next_action["recommended_endpoint"])
    features = [
        ("每日工作流", "/workflow/daily/view", "检查今天市场、主线、边界、组合和报告是否形成闭环。"),
        ("今日行动边界", "/guidance/view", "先判断今天能不能提高风险、新增标的或只读复核。"),
        ("市场状态", "/market/view", "查看市场评分、风险等级、权益比例边界和数据缺口。"),
        ("主线研究", "/theme/view", "查看 AI、半导体、电力设备、机器人等方向是否进入当前主线。"),
        ("风险状态", "/risk/view", "查看风控分数、暴露提示、集中度和风险警告。"),
        ("宏观状态", "/macro/view", "查看流动性、利率压力、风险周期和模型共识。"),
        ("对比分析", "/comparison/view", "比较影子组合、真实代理和基准的比例表现。"),
        ("决策预览", "/decision/view", "查看只读建议、门槛状态和解释追溯链。"),
        ("策略目标池", "/target-pool/view", "区分系统策略候选、ResearchFirst 范围和 QMT 实际持仓对照。"),
        ("影子组合", "/portfolio/view", "查看纸面模拟组合比例、偏离和回放来源。"),
        ("研究队列", "/research/view", "查看最新研究快照和 ResearchFirst 队列。"),
        ("研究导入", "/research/import/view", "粘贴研究 JSON，先校验，再追加写入系统。"),
        ("每日报告", "/report/view", "查看今天的结论摘要、阅读顺序和来源编号。"),
        ("系统状态", "/system/view", "查看自检、回放、记录数量和 JSON 入口。"),
        ("易用性检查", "/usability/view", "检查入口、页头、页脚、引导和执行边界。"),
    ]
    feature_cards = "".join(_feature_card(title, href, detail) for title, href, detail in features)
    priority_cards = _home_priority_cards(data)
    flow = data["usability"]["human_flow"]
    flow_steps = _linked_flow(flow)
    readiness = guidance["readiness"]
    overview = dashboard["overview"]
    daily_refresh = dashboard["daily_refresh"]
    return f"""
<section class="two-pane">
  <div class="panel">
    <h2>今日系统状态</h2>
    <div class="label">下一步建议</div>
    <p class="value"><a href="{html.escape(next_endpoint)}">{html.escape(_endpoint_label(next_endpoint))}</a></p>
    <p class="detail">{html.escape(_reason_label(next_action['reason_code']))}</p>
    <div class="badge-row">
      <span class="badge">优先级 {_priority_label(next_action['priority'])}</span>
      <span class="badge">今日状态 {_readiness_label(readiness['overall_state'])}</span>
      <span class="badge">自检 {html.escape(str(overview['self_check_status']))}</span>
    </div>
  </div>
  <div class="panel">
    <h2>今天能不能动</h2>
    <p>提高风险：<span class="{_bool_class(readiness['can_increase_risk'])}">{_yes_no(readiness['can_increase_risk'])}</span></p>
    <p>新增标的：<span class="{_bool_class(readiness['can_add_new_subject'])}">{_yes_no(readiness['can_add_new_subject'])}</span></p>
    <p>人工复核：<span class="{_bool_class(not readiness['requires_human_review'])}">{_need_label(readiness['requires_human_review'])}</span></p>
    <p class="detail"><a href="/guidance/view">打开今日行动边界</a></p>
  </div>
</section>
{_daily_refresh_strip(daily_refresh)}
<section>
  <h2>优先入口</h2>
  <p class="detail">打开系统后先看这三处：先读结论，再处理研究卡点，最后核对组合。</p>
  <div class="feature-grid">{priority_cards}</div>
</section>
<section>
  <h2>全部功能入口</h2>
  <div class="feature-grid">{feature_cards}</div>
</section>
<section class="panel">
  <h2>导航路径</h2>
  <div class="path">{flow_steps}</div>
</section>
{_overview_content(data)}
"""


def _overview_content(data: dict[str, Any]) -> str:
    overview = data["dashboard"]["overview"]
    counts = overview["record_counts"]
    count_cards = "".join(_metric_card(name, value) for name, value in counts.items())
    gaps = _data_gap_table(overview["data_gaps"])
    gap_actions = """
    <div class="badge-row">
      <a class="step" href="/market/view#market-refresh">去刷新市场快照</a>
      <a class="step" href="/market/latest">查看市场 JSON</a>
    </div>
    """
    conflicts = _list_items(overview["conflicts"], "当前没有冲突提示。")
    return f"""
<section>
  <h2>系统总览</h2>
  <div class="grid-4">
    {_metric_card("自检", overview["self_check_status"])}
    {_metric_card("回放", "可用" if overview["replay_available"] else "不可用")}
    {_metric_card("事件数", data["dashboard"]["replay"]["event_count"])}
    {_metric_card("阻断", "是" if overview["blocked"] else "否")}
  </div>
</section>
<section>
  <h2>记录数量</h2>
  <div class="grid-4">{count_cards}</div>
</section>
<section class="grid-2">
  <div class="panel"><h2>数据缺口</h2>{gaps}{gap_actions}</div>
  <div class="panel"><h2>冲突提示</h2>{conflicts}</div>
</section>
"""


def _daily_refresh_strip(daily_refresh: dict[str, Any]) -> str:
    cards = "".join(_daily_refresh_card(item) for item in daily_refresh["items"])
    status = "全部完成" if daily_refresh["all_done"] else "仍有待处理"
    return f"""
<section>
  <h2>今日刷新状态</h2>
  <p class="detail">参考日期：{html.escape(str(daily_refresh["reference_date"]))}；状态：{html.escape(status)}。</p>
  <div class="grid-3">{cards}</div>
</section>
"""


def _daily_refresh_card(item: dict[str, Any]) -> str:
    status_class = "good" if item["status"] == "done" else "warn"
    last_date = item["last_basis_date"] or "暂无"
    reason = item["reason"] or "无"
    return f"""
<div class="panel">
  <div class="label">{html.escape(item["label"])}</div>
  <p class="{status_class}">{html.escape(_daily_refresh_status_label(item["status"]))}</p>
  <p class="detail">{html.escape(item["detail"])}</p>
  <p class="small">最后日期：{html.escape(str(last_date))}</p>
  <p class="small">原因：{html.escape(_daily_refresh_reason_label(reason))}</p>
  <p class="detail"><a href="{html.escape(item["endpoint"])}">{html.escape(item["action_label"])}</a></p>
</div>
"""


def _daily_workflow_content(data: dict[str, Any]) -> str:
    workflow = data["daily_workflow"]
    primary = workflow["primary_next_action"]
    rows = [
        [
            item["title"],
            _workflow_status_label(item["status"]),
            item["detail"],
            item["basis_date"] or "暂无",
            _link(item["view_endpoint"]),
            _link(item["json_endpoint"]),
        ]
        for item in workflow["steps"]
    ]
    source_rows = [[key, value or "暂无"] for key, value in workflow["source_ids"].items()]
    return f"""
<section class="two-pane">
  <div class="panel highlight">
    <h2>今天先做什么</h2>
    <p class="value"><a href="{html.escape(primary['endpoint'])}">{html.escape(primary['label'])}</a></p>
    <p class="detail">{html.escape(primary['reason'])}</p>
    <div class="badge-row">
      <span class="badge">状态 {_workflow_status_label(workflow['status'])}</span>
      <span class="badge">参考日期 {html.escape(str(workflow['reference_date'] or '暂无'))}</span>
    </div>
  </div>
  <div class="panel">
    <h2>工作流边界</h2>
    {_list_items(workflow["safe_operations"], "暂无可用操作。")}
  </div>
</section>
<section>
  <h2>每日闭环</h2>
  {_table(["步骤", "状态", "说明", "日期", "页面", "JSON"], rows, raw_columns={4, 5})}
</section>
<section class="grid-2">
  <div class="panel">
    <h2>来源编号</h2>
    {_table(["字段", "编号"], source_rows)}
  </div>
  <div class="panel">
    <h2>不要做</h2>
    {_list_items(workflow["blocked_operations"], "暂无额外限制。")}
  </div>
</section>
"""


def _guidance_content(data: dict[str, Any]) -> str:
    guidance = data["guidance"]
    readiness = guidance["readiness"]
    operations = guidance["today_action"]["allowed_operations"]
    checks = guidance["checks"]
    steps = guidance["today_action"]["next_required_steps"]
    return f"""
<section>
  <h2>今日行动边界</h2>
  <div class="grid-4">
    {_metric_card("总体状态", _readiness_label(readiness["overall_state"]))}
    {_metric_card("提高风险", _yes_no(readiness["can_increase_risk"]), _bool_class(readiness["can_increase_risk"]))}
    {_metric_card("新增标的", _yes_no(readiness["can_add_new_subject"]), _bool_class(readiness["can_add_new_subject"]))}
    {_metric_card("人工复核", _need_label(readiness["requires_human_review"]), _bool_class(not readiness["requires_human_review"]))}
  </div>
</section>
{_guidance_research_first_scope(guidance["research_first"])}
<section>
  <h2>今天能不能做</h2>
  {_table(["事项", "结果", "原因", "入口"], [_operation_row(item) for item in operations], raw_columns={3})}
</section>
<section>
  <h2>下一步复核项</h2>
  {_table(["步骤", "原因", "入口"], [_next_step_row(item) for item in steps], raw_columns={2})}
</section>
<section>
  <h2>边界检查</h2>
  {_table(["检查", "状态", "说明", "入口"], [_check_row(item) for item in checks], raw_columns={3})}
</section>
<section class="panel">
  <h2>今天不要做</h2>
  {_list_items(guidance["today_action"]["do_not_do"], "暂无额外限制。")}
</section>
"""


def _guidance_research_first_scope(research_first: dict[str, Any]) -> str:
    active_rows = [
        [
            display_symbol(symbol),
            "当前持仓门槛未覆盖",
            "阻断提高风险",
            "组合页",
        ]
        for symbol in research_first["active_holdings_without_passed_gates"]
    ]
    if not active_rows:
        active_rows = [["无", "当前持仓已覆盖", "不阻断提高风险", "guidance"]]

    queue_rows = [
        [
            display_symbol(item["symbol"]),
            _research_reason_label(item["reason"]),
            _research_blocker_label(item.get("blockers", [])),
            item["source"],
        ]
        for item in research_first["queue"]
    ]
    if not queue_rows:
        queue_rows = [["无", "当前候选队列已清空", "不阻断新增候选", "guidance"]]

    return f"""
<section class="grid-2">
  <div class="panel">
    <h2>当前持仓门槛</h2>
    <p class="detail">这里只看已经持有的标的；未覆盖时阻断提高风险，但不代表历史候选仍要补研究。</p>
    {_table(["标的", "状态", "影响", "入口"], active_rows)}
  </div>
  <div class="panel">
    <h2>当前候选 ResearchFirst</h2>
    <p class="detail">这里只看最新目标池和当前决策里的候选；历史或已排除候选只保留研究记录，不影响全局状态。</p>
    {_table(["标的", "原因", "当前卡点", "来源"], queue_rows)}
  </div>
</section>
"""


def _theme_content(data: dict[str, Any]) -> str:
    theme = data["dashboard"]["research"]["theme"]
    if not theme["available"]:
        return _empty_section("主线研究", "当前没有 theme_research 快照，请先导入或生成主线研究 JSON。")
    primary = theme["primary"] or {}
    mainline_rows = [
        [
            item["rank"],
            item["display_theme"],
            _theme_alias_text(item),
            _theme_strength_text(item["strength_score"]),
            _theme_phase_label(item.get("phase") or item.get("continuity")),
            "、".join(item["plates"]) if item["plates"] else "暂无",
            "、".join(item["display_symbols"]) if item["display_symbols"] else "暂无",
            _theme_research_first_label(item.get("research_first")),
        ]
        for item in theme["mainlines"]
    ]
    if not mainline_rows:
        mainline_rows = [["暂无", "主线研究暂不可用", "无", "暂无", "暂无", "暂无", "暂无", "待研究"]]
    watch_rows = [
        [
            item["theme"],
            _theme_watch_status_label(item["status"]),
            "、".join(item["matched_mainlines"]) if item["matched_mainlines"] else "未进入前三主线",
            item["detail"],
        ]
        for item in theme["watchlist"]
    ]
    evidence_rows = [
        [item["display_theme"], evidence]
        for item in theme["mainlines"]
        for evidence in item.get("evidence", [])
    ]
    if not evidence_rows:
        evidence_rows = [["暂无", theme["summary"]]]
    return f"""
<section class="two-pane">
  <div class="panel highlight">
    <h2>当前第一主线</h2>
    <p class="value">{html.escape(str(primary.get("display_theme", "暂无主线")))}</p>
    <p class="detail">{html.escape(_theme_primary_detail(theme, primary))}</p>
    <div class="badge-row">
      <span class="badge">强度 {html.escape(_theme_strength_text(primary.get("strength_score")))}</span>
      <span class="badge">置信度 {_percent(theme["confidence"])}</span>
      <span class="badge">下次复核 {html.escape(str(theme["next_review_date"]))}</span>
    </div>
  </div>
  <div class="panel">
    <h2>怎么读</h2>
    <p>主线研究回答“现在市场最强的方向是什么”，不回答“应该买哪个标的”。</p>
    <p class="detail">代表标的只是研究对象，必须继续经过画像、估值、流动性和 ResearchFirst 门槛。</p>
  </div>
</section>
<section class="grid-2">
  <div class="panel">
    <h2>为什么之前看不到</h2>
    <p>之前页面只展示 theme_research 的压缩摘要，AI、半导体等方向藏在 key_facts 和 payload.evidence 里。</p>
    <p class="detail">现在本页把这些字段展开成主线、板块、代表标的和关注方向。</p>
  </div>
  <div class="panel">
    <h2>来源追溯</h2>
    <p>快照：{html.escape(str(theme["snapshot_id"]))}</p>
    <p class="detail">基准日：{html.escape(str(theme["basis_date"]))}；行动性：{html.escape(str(theme["actionability"]))}。</p>
    <p class="detail"><a href="/theme/state">主线研究 JSON</a>　<a href="/research/view">研究工作台</a></p>
  </div>
</section>
<section>
  <h2>当前主线排序</h2>
  {_table(["排序", "主线", "你熟悉的说法", "强度", "阶段", "包含板块", "代表标的", "门槛状态"], mainline_rows)}
</section>
<section>
  <h2>你关心的方向</h2>
  <p class="detail">这张表专门回答 AI、半导体、电力设备、机器人是否进入当前主线。</p>
  {_table(["方向", "状态", "对应主线", "说明"], watch_rows)}
</section>
<section>
  <h2>证据摘录</h2>
  {_table(["主线", "证据"], evidence_rows)}
</section>
"""


def _market_content(data: dict[str, Any]) -> str:
    market = data["dashboard"]["market"]
    guidance = data["guidance"]
    target_pool = data["dashboard"]["target_pool"]
    if not market["available"]:
        return _empty_section("市场状态", "市场快照暂不可用，请先查看系统状态。")
    pool_entries = target_pool["entries"] if target_pool.get("available") else []
    pool_rows = [
        [entry["pool_type"], "、".join(entry.get("display_symbols", entry["symbols"])), str(entry["count"])]
        for entry in pool_entries
    ]
    if not pool_rows:
        pool_rows = [["暂无", "策略目标池暂不可用", "0"]]
    return f"""
<section class="two-pane">
  <div class="panel highlight">
    <h2>市场结论</h2>
    <p class="value">{html.escape(_market_conclusion_label(market))}</p>
    <p class="detail">{html.escape(_market_conclusion_detail(market, guidance))}</p>
    <div class="badge-row">
      <a class="step" href="/guidance/view">查看今日边界</a>
      <a class="step" href="/decision/view">查看决策预览</a>
    </div>
  </div>
  <div class="panel">
    <h2>行动边界</h2>
    <p>{html.escape(_market_boundary_text(guidance))}</p>
    <p class="detail">市场页只回答“环境如何”和“目标暴露区间在哪里”，不直接给出单一标的操作。</p>
  </div>
</section>
<section>
  <h2>市场状态</h2>
  <div class="grid-4">
    {_metric_card("市场评分", _score_out_of_100(market["market_score"]))}
    {_metric_card("风险等级", _market_risk_label(market["risk_level"]), _risk_class(market["risk_level"]))}
    {_metric_card("权益下限", _percent(market["equity_min"]))}
    {_metric_card("权益上限", _percent(market["equity_max"]))}
  </div>
</section>
<section class="grid-2">
  <div class="panel">
    <h2>市场分数怎么读</h2>
    <p>市场评分是 0 到 100 的环境分数，来自只读市场快照；分数越高，环境越偏积极，分数越低，越偏防守。</p>
    <p class="detail">风险等级会把评分、数据质量、拥挤度和市场宽度一起压缩成低、中、高三档。</p>
  </div>
  <div class="panel">
    <h2>权益目标区间</h2>
    <p>{html.escape(_market_equity_range_text(market))}</p>
    <p class="detail">这个区间是组合复核的参照边界，具体比例仍要经过 ResearchFirst、风险页和决策预览。</p>
  </div>
</section>
<section class="panel" id="market-refresh">
  <h2>刷新市场快照</h2>
  <p>追加写入新的市场快照，不覆盖历史记录。</p>
  <div class="badge-row">
    <label class="inline-control">基准日期 <input id="market-refresh-date" type="date" value="{html.escape(market["basis_date"])}"></label>
    <button type="button" id="market-refresh-button">刷新市场快照</button>
    <a class="step" href="/market/latest">查看市场 JSON</a>
  </div>
  <pre id="market-refresh-result">等待刷新。</pre>
</section>
<section class="grid-2">
  <div class="panel">
    <h2>来源与缺口</h2>
    <p>来源：{html.escape("、".join(market["data_sources"]))}</p>
    <div class="detail">{_data_gap_table(market["data_gaps"])}</div>
  </div>
  <div class="panel">
    <h2>冲突提示</h2>
    {_list_items(market["conflicts"], "当前没有市场冲突提示。")}
  </div>
</section>
<section>
  <h2>策略目标池</h2>
  <p class="detail">这里是系统用于 ResearchFirst、决策预览和影子组合的策略候选范围。QMT 实际持仓只在组合页做对照，不会覆盖这里。</p>
  <div class="badge-row">
    <a class="step" href="/target-pool/view">查看目标池说明</a>
    <a class="step" href="/target-pool/latest">策略目标池 JSON</a>
  </div>
  {_table(["类型", "标的", "数量"], pool_rows)}
</section>
<script>
(() => {{
  const button = document.getElementById('market-refresh-button');
  const input = document.getElementById('market-refresh-date');
  const result = document.getElementById('market-refresh-result');
  button.addEventListener('click', async () => {{
    const basisDate = input.value;
    if (!basisDate) {{
      result.textContent = JSON.stringify({{ status: 'failed', data: {{ reason: 'missing_basis_date' }} }}, null, 2);
      return;
    }}
    button.disabled = true;
    result.textContent = '正在刷新市场快照...';
    try {{
      const url = `/market/refresh?basis_date=${{encodeURIComponent(basisDate)}}&source=auto&allow_network=true`;
      const response = await fetch(url, {{ method: 'POST' }});
      const data = await response.json();
      result.textContent = JSON.stringify(data, null, 2);
      if (data.status === 'ok') {{
        result.textContent += '\\n\\n刷新完成。页面会在 1 秒后重新加载。';
        window.setTimeout(() => window.location.reload(), 1000);
      }}
    }} catch (error) {{
      result.textContent = JSON.stringify({{ status: 'failed', data: {{ reason: 'refresh_request_failed' }} }}, null, 2);
    }} finally {{
      button.disabled = false;
    }}
  }});
}})();
</script>
"""


def _target_pool_content(data: dict[str, Any]) -> str:
    target_pool = data["dashboard"]["target_pool"]
    actual = data["dashboard"]["actual_vs_shadow"]
    available = target_pool.get("available", False)
    source = _target_pool_source_label(str(target_pool.get("source", "unknown"))) if available else "暂无"
    pool_id = str(target_pool.get("target_pool_id", "暂无"))
    basis_date = str(target_pool.get("basis_date", "暂无"))
    pool_rows = [
        [entry["pool_type"], "、".join(entry.get("display_symbols", entry["symbols"])), str(entry["count"])]
        for entry in target_pool.get("entries", [])
    ]
    if not pool_rows:
        pool_rows = [["暂无", "策略目标池暂不可用", "0"]]
    actual_rows = [
        [
            item["display_name"],
            _weight_or_missing(item["actual_weight"]),
            _weight_or_missing(item["shadow_weight"]),
            _delta_or_missing(item["shadow_minus_actual_pp"]),
            _actual_shadow_status_label(item["status"]),
        ]
        for item in actual["rows"]
    ]
    if not actual_rows:
        actual_rows = [["暂无", "缺少实际比例", "无", "无", "待刷新"]]
    qmt_status = actual["qmt_read_status"]
    return f"""
<section class="two-pane">
  <div class="panel highlight">
    <h2>策略目标池</h2>
    <p class="value">{html.escape(source)}</p>
    <p class="detail">策略目标池是系统当前承认的候选范围，用于 ResearchFirst、决策预览和影子组合生成。</p>
    <div class="badge-row">
      <span class="badge">目标池 {html.escape(pool_id)}</span>
      <span class="badge">日期 {html.escape(basis_date)}</span>
      <a class="step" href="/target-pool/latest">查看策略目标池 JSON</a>
    </div>
  </div>
  <div class="panel">
    <h2>QMT 实际持仓对照</h2>
    <p class="value">{html.escape(_qmt_read_status_label(qmt_status["status"]))}</p>
    <p class="detail">QMT 实际持仓对照来自只读比例读取，只用于核对实际配置；它不是系统推荐池，也不会覆盖策略目标池。</p>
    <div class="badge-row">
      <a class="step" href="/portfolio/view">查看组合页</a>
      <a class="step" href="/portfolio/actual-vs-shadow">查看实际/影子对照 JSON</a>
    </div>
  </div>
</section>
<section class="grid-2">
  <div class="panel">
    <h2>怎么区分</h2>
    <p>策略目标池回答“系统当前允许哪些候选进入研究、决策和影子组合”。</p>
    <p class="detail">QMT 实际持仓回答“你现在实际配置比例和影子组合差在哪里”。两者都只展示比例，不包含金额、数量或账户细节。</p>
  </div>
  <div class="panel">
    <h2>什么时候影响全局提示</h2>
    <p>只有当前持仓、当前策略目标池、当前决策里的 ResearchFirst 会影响全局 readiness。</p>
    <p class="detail">历史失败研究或已排除候选只作为研究档案保留，不应卡住全站提示。</p>
  </div>
</section>
<section>
  <h2>当前策略目标池</h2>
  {_table(["类型", "标的", "数量"], pool_rows)}
</section>
<section>
  <h2>QMT 实际持仓 vs 影子组合</h2>
  <p class="detail">这一块是组合核对信息，实际持仓不是目标池来源；需要刷新实际持仓时请进入组合页。</p>
  {_table(["标的", "QMT 实际比例", "影子比例", "影子-实际", "状态"], actual_rows)}
</section>
"""


def _risk_content(data: dict[str, Any]) -> str:
    risk = data["dashboard"]["risk"]
    guidance = data["guidance"]
    if not risk["available"]:
        return _empty_section("风险状态", "风险状态暂不可用，请先查看系统状态。")
    warning_rows = [
        [
            _risk_warning_label(item["code"]),
            _severity_label(item["severity"]),
            item["message"],
            _risk_warning_meaning(item),
            _risk_source_label(item["source"]),
        ]
        for item in risk["warnings"]
    ]
    if not warning_rows:
        warning_rows = [["无", "低", "当前没有风险警告。", "无需处理。", "风险状态"]]
    return f"""
<section class="two-pane">
  <div class="panel highlight">
    <h2>风险结论</h2>
    <p class="value">{html.escape(_risk_conclusion_label(risk))}</p>
    <p class="detail">{html.escape(_risk_conclusion_detail(risk, guidance))}</p>
    <div class="badge-row">
      <a class="step" href="/guidance/view">查看今日边界</a>
      <a class="step" href="/portfolio/view">查看组合</a>
    </div>
  </div>
  <div class="panel">
    <h2>今日边界</h2>
    <p>{html.escape(_risk_boundary_text(risk, guidance))}</p>
    <p class="detail">风险页只说明阻断或复核原因，不能绕过研究门槛和决策记录。</p>
  </div>
</section>
<section>
  <h2>风险状态</h2>
  <div class="grid-4">
    {_metric_card("风险分数", _score_out_of_100(risk["overall_risk_score"]))}
    {_metric_card("风险等级", _risk_level_label(risk["risk_level"]), _risk_class(risk["risk_level"]))}
    {_metric_card("暴露提示", _exposure_label(risk["exposure_warning"]))}
    {_metric_card("影子差距", f"{risk['shadow_vs_market_gap']} pp")}
  </div>
</section>
<section class="grid-2">
  <div class="panel">
    <h2>风险分数怎么读</h2>
    <p>风险分数是 0 到 100 的综合压力分数，越高越需要先处理风险。65 以上为高风险，30 到 65 为中等风险，30 以下为低风险。</p>
    <p class="detail">它由暴露偏离、集中度、研究与决策差距、影子组合差距、拥挤度和警告数量共同生成。</p>
  </div>
  <div class="panel">
    <h2>分数和警告的关系</h2>
    <p>风险警告说明“分数为什么上升”，风险分数说明“整体压力有多大”。两者要一起看。</p>
    <p class="detail">如果警告存在，先处理警告来源；如果没有警告，再看组合和决策是否匹配。</p>
  </div>
</section>
<section>
  <h2>风险警告怎么读</h2>
  {_table(["风险项", "等级", "说明", "代表含义", "来源"], warning_rows)}
</section>
<section class="grid-3">
  {_metric_card("集中度风险", risk["concentration_risk"])}
  {_metric_card("研究偏离", risk["deviation_from_research"])}
  {_metric_card("暴露状态", _exposure_label(risk["exposure_warning"]))}
</section>
"""


def _market_conclusion_label(market: dict[str, Any]) -> str:
    score = float(market["market_score"])
    risk_level = market["risk_level"]
    if risk_level == "high" or score < 40:
        return "市场偏防守"
    if score >= 60 and risk_level == "low":
        return "市场偏积极"
    if score >= 60:
        return "评分偏积极，风险仍需复核"
    return "市场均衡偏观察"


def _market_conclusion_detail(market: dict[str, Any], guidance: dict[str, Any]) -> str:
    score = _score_out_of_100(market["market_score"])
    risk = _market_risk_label(market["risk_level"])
    range_text = _market_equity_range_text(market)
    base = f"市场评分 {score}，市场风险等级为{risk}，{range_text}"
    readiness = guidance.get("readiness", {})
    if not readiness.get("can_increase_risk", False):
        return base + " 今日边界未允许提高风险，先处理研究、风险或数据缺口。"
    return base + " 可以进入只读复核，但仍要以今日边界和决策预览为准。"


def _market_boundary_text(guidance: dict[str, Any]) -> str:
    readiness = guidance.get("readiness", {})
    if not readiness.get("can_increase_risk", False):
        return "今日边界没有放行提高风险；市场页只能提示环境，不改变影子组合目标。"
    return "今日边界允许进入下一步复核；仍需要风险页、研究页和决策预览共同确认。"


def _market_equity_range_text(market: dict[str, Any]) -> str:
    return f"权益目标区间为 {_percent(market['equity_min'])} 到 {_percent(market['equity_max'])}。"


def _market_risk_label(value: str) -> str:
    return {
        "low": "低",
        "medium": "中等",
        "high": "高",
    }.get(value, value)


def _risk_conclusion_label(risk: dict[str, Any]) -> str:
    level = risk["risk_level"]
    warning_count = len(risk["warnings"])
    if level == "high":
        return "风险偏高，先处理边界"
    if warning_count:
        return "存在风险警告，先复核来源"
    if level == "medium":
        return "风险中等，需要观察"
    return "风险较低，保持复核"


def _risk_conclusion_detail(risk: dict[str, Any], guidance: dict[str, Any]) -> str:
    score = _score_out_of_100(risk["overall_risk_score"])
    level = _risk_level_label(risk["risk_level"])
    warnings = len(risk["warnings"])
    exposure = _exposure_label(risk["exposure_warning"])
    base = f"风险分数 {score}，等级为{level}，暴露提示为{exposure}，当前有 {warnings} 条风险警告。"
    readiness = guidance.get("readiness", {})
    if not readiness.get("can_increase_risk", False):
        return base + " 今日边界未允许提高风险，先按警告来源复核。"
    return base + " 可以继续进入组合和决策复核。"


def _risk_boundary_text(risk: dict[str, Any], guidance: dict[str, Any]) -> str:
    readiness = guidance.get("readiness", {})
    if risk["risk_level"] == "high":
        return "风险等级为高，先处理风险警告和组合暴露，再看后续决策。"
    if risk["warnings"]:
        return "存在风险警告，先确认警告来源是否已经被研究或市场快照解释。"
    if not readiness.get("can_increase_risk", False):
        return "风险页没有高风险警告，但今日边界仍未放行提高风险。"
    return "风险页没有形成阻断，可继续查看决策预览和影子组合。"


def _risk_level_label(value: str) -> str:
    return {
        "low": "低",
        "medium": "中等",
        "high": "高",
    }.get(value, value)


def _severity_label(value: str) -> str:
    return {
        "low": "低",
        "medium": "中等",
        "high": "高",
    }.get(value, value)


def _risk_warning_label(value: str) -> str:
    return {
        "exposure_deviation": "权益暴露偏离",
        "concentration_risk": "集中度偏高",
        "research_execution_mismatch": "研究与组合偏离",
        "shadow_vs_market_gap": "影子组合偏离市场",
        "market_risk": "市场风险抬升",
        "data_gap": "数据缺口",
    }.get(value, value)


def _risk_warning_meaning(item: dict[str, str]) -> str:
    return {
        "exposure_deviation": "当前权益比例偏离市场目标中枢，需要回到组合页核对。",
        "concentration_risk": "最大单项比例偏高，组合分散度需要复核。",
        "research_execution_mismatch": "组合状态和决策目标不一致，需要看决策预览。",
        "shadow_vs_market_gap": "影子组合相对基准偏离，需要看对比分析。",
        "market_risk": "市场拥挤度或风险等级偏高，需要先看市场页。",
        "data_gap": "研究或市场输入不完整，需要先补数据。",
    }.get(item["code"], "该风险项需要人工复核来源。")


def _risk_source_label(value: str) -> str:
    return {
        "portfolio_vs_market": "组合与市场目标",
        "portfolio_snapshot": "组合快照",
        "decision_record": "决策记录",
        "market_snapshot": "市场快照",
        "research_or_market": "研究或市场数据",
        "risk_state": "风险状态",
    }.get(value, value)


def _macro_content(data: dict[str, Any]) -> str:
    macro = data["dashboard"]["macro"]
    if not macro["available"]:
        return _empty_section("宏观状态", "宏观状态暂不可用，请先查看系统状态。")
    snapshot = macro["macro_snapshot"]
    consensus = macro["model_consensus"]
    factors = macro["alpha_factor_decomposition"]["factors"]
    guidance = data["guidance"]
    model_rows = [
        [
            _macro_model_label(item["model_id"]),
            f"{float(item['score']):.2f} / 100",
            _percent(item["confidence"]),
            _macro_model_role(item["model_id"]),
            "；".join(item.get("evidence", [])),
        ]
        for item in consensus.get("models", [])
    ]
    if not model_rows:
        model_rows = [["none", "0 / 100", "0.00%", "暂无模型来源。", "暂无证据。"]]
    factor_rows = [
        [
            _macro_factor_label(item["factor"]),
            _macro_factor_meaning(item["factor"]),
            item["contribution_score"],
            _macro_direction_label(item["direction"]),
            _macro_factor_interpretation(item),
            _macro_source_label(item["source"]),
        ]
        for item in factors
    ]
    if not factor_rows:
        factor_rows = [["none", "暂无", "0", "中性", "暂无解释。", "宏观状态"]]
    return f"""
<section class="two-pane">
  <div class="panel highlight">
    <h2>宏观结论</h2>
    <p class="value">{html.escape(_macro_conclusion_label(consensus["consensus_state"]))}</p>
    <p class="detail">{html.escape(_macro_conclusion_detail(consensus, guidance))}</p>
    <div class="badge-row">
      <span class="badge">共识 {_score_out_of_100(consensus["consensus_score"])}</span>
      <span class="badge">置信度 {_percent(consensus["calibrated_confidence"])}</span>
      <span class="badge">分歧 {_percent(consensus["disagreement_score"])}</span>
    </div>
  </div>
  <div class="panel">
    <h2>行动边界</h2>
    <p>{html.escape(_macro_boundary_text(guidance))}</p>
    <p class="detail"><a href="/guidance/view">查看今日行动边界</a></p>
  </div>
</section>
<section>
  <h2>宏观状态</h2>
  <div class="grid-4">
    {_metric_card("流动性", _percent(snapshot["liquidity_index"]))}
    {_metric_card("利率压力", _percent(snapshot["rate_pressure"]))}
    {_metric_card("通胀状态", _inflation_label(snapshot["inflation_regime"]))}
    {_metric_card("风险周期", _macro_cycle_label(snapshot["risk_cycle_state"]))}
  </div>
  <p class="detail">这些是宏观环境输入：流动性越高越友好，利率压力越高越偏谨慎。</p>
</section>
<section>
  <h2>模型共识</h2>
  <div class="grid-4">
    {_metric_card("共识分数", _score_out_of_100(consensus["consensus_score"]))}
    {_metric_card("共识状态", _macro_cycle_label(consensus["consensus_state"]))}
    {_metric_card("分歧", _percent(consensus["disagreement_score"]))}
    {_metric_card("置信度", _percent(consensus["calibrated_confidence"]))}
  </div>
  <p class="detail">共识分数是宏观周期、市场位置、组合匹配度和研究质量四类模型分数的平均；它不是收益预测，也不是行动指令。</p>
</section>
<section>
  <h2>共识分数来源</h2>
  {_table(["模型", "分数", "置信度", "作用", "证据"], model_rows)}
</section>
<section class="panel">
  <h2>分数和因子的关系</h2>
  <p>共识分数回答“当前环境偏积极还是偏谨慎”；因子分解回答“哪些信号在推动这个判断”。两者相关，但因子贡献不是简单相加成共识分数。</p>
  <div class="path">
    <span class="step">基础数据</span><span class="arrow">→</span>
    <span class="step">宏观状态</span><span class="arrow">→</span>
    <span class="step">模型共识</span><span class="arrow">→</span>
    <span class="step">因子解释</span><span class="arrow">→</span>
    <a class="step" href="/guidance/view">今日边界</a>
  </div>
</section>
<section>
  <h2>因子分解</h2>
  <p class="detail">贡献值范围是 -1 到 +1：正数表示偏支持风险友好，负数表示偏谨慎，接近 0 表示影响较弱。</p>
  {_table(["因子", "中文含义", "贡献", "方向", "怎么读", "来源"], factor_rows)}
</section>
"""


def _macro_conclusion_label(state: str) -> str:
    return {
        "risk_on": "宏观环境偏积极",
        "neutral": "宏观环境中性",
        "risk_off": "宏观环境偏谨慎",
    }.get(state, state)


def _macro_conclusion_detail(consensus: dict[str, Any], guidance: dict[str, Any]) -> str:
    score = _score_out_of_100(consensus["consensus_score"])
    state = consensus["consensus_state"]
    if state == "risk_on":
        base = f"共识分数 {score}，当前宏观和市场信号偏风险友好。"
    elif state == "risk_off":
        base = f"共识分数 {score}，当前宏观和市场信号偏防守。"
    else:
        base = f"共识分数 {score}，当前宏观和市场信号没有明显单边方向。"
    readiness = guidance.get("readiness", {})
    if not readiness.get("can_increase_risk", False):
        return base + " 但今日边界仍未允许提高风险，先处理 ResearchFirst、风险和数据缺口。"
    return base + " 可以继续进入只读复核，最终仍以今日边界和决策预览为准。"


def _macro_boundary_text(guidance: dict[str, Any]) -> str:
    readiness = guidance.get("readiness", {})
    if not readiness.get("can_increase_risk", False):
        return "宏观页只解释环境，不直接改变组合。即使宏观偏积极，也不能绕过 ResearchFirst、风险边界和决策预览。"
    return "宏观页只解释环境。若要进入下一步，仍需回到今日行动边界和决策预览做只读复核。"


def _score_out_of_100(value: float | int) -> str:
    return f"{float(value):.2f} / 100"


def _macro_model_label(value: str) -> str:
    return {
        "macro_cycle": "宏观周期",
        "market_position": "市场位置",
        "portfolio_alignment": "组合匹配度",
        "research_quality": "研究质量",
    }.get(value, value)


def _macro_model_role(value: str) -> str:
    return {
        "macro_cycle": "用流动性和利率压力判断宏观环境。",
        "market_position": "用市场评分判断当前市场强弱。",
        "portfolio_alignment": "用组合暴露和市场目标区间判断是否匹配。",
        "research_quality": "用研究快照置信度判断输入质量。",
    }.get(value, "解释该模型对共识分数的贡献。")


def _macro_factor_label(value: str) -> str:
    return {
        "macro_liquidity": "流动性",
        "rate_pressure": "利率压力",
        "market_momentum": "市场动量",
        "portfolio_alignment": "组合匹配度",
        "shadow_alpha_proxy": "影子相对表现",
    }.get(value, value)


def _macro_factor_meaning(value: str) -> str:
    return {
        "macro_liquidity": "资金环境是否宽松。",
        "rate_pressure": "利率或资金成本压力是否偏高。",
        "market_momentum": "市场评分反映的强弱状态。",
        "portfolio_alignment": "组合风险暴露是否贴近市场目标。",
        "shadow_alpha_proxy": "影子组合相对基准的解释性代理。",
    }.get(value, "用于解释宏观判断的输入信号。")


def _macro_factor_interpretation(item: dict[str, Any]) -> str:
    factor = item["factor"]
    direction = item["direction"]
    if factor == "rate_pressure":
        if direction == "positive":
            return "利率压力较低，对风险环境有利。"
        if direction == "negative":
            return "利率压力较高，宏观环境更谨慎。"
        return "利率压力影响不明显。"
    if direction == "positive":
        return "当前信号偏支持风险友好。"
    if direction == "negative":
        return "当前信号偏谨慎。"
    return "当前信号影响较弱。"


def _macro_direction_label(value: str) -> str:
    return {
        "positive": "正向",
        "negative": "负向",
        "neutral": "中性",
    }.get(value, value)


def _macro_source_label(value: str) -> str:
    return {
        "macro_snapshot": "宏观快照",
        "market_snapshot": "市场快照",
        "portfolio_snapshot": "组合快照",
    }.get(value, value)


def _macro_cycle_label(value: str) -> str:
    return {
        "risk_on": "偏积极",
        "neutral": "中性",
        "risk_off": "偏谨慎",
        "balanced": "均衡",
    }.get(value, value)


def _inflation_label(value: str) -> str:
    return {
        "benign": "温和",
        "neutral": "中性",
        "elevated": "偏高",
    }.get(value, value)


def _comparison_content(data: dict[str, Any]) -> str:
    comparison = data["dashboard"]["comparison"]
    if not comparison["available"]:
        return _empty_section("对比分析", "对比状态暂不可用，请先查看系统状态。")
    returns = comparison["return_comparison"]
    drawdown = comparison["drawdown_comparison"]
    exposure = comparison["exposure_comparison"]
    deviation = comparison["deviation_analysis"]
    curve_rows = [
        [item["as_of"], item["real_proxy_nav"], item["shadow_nav"], item["benchmark_nav"]]
        for item in comparison["curve"]
    ]
    return f"""
<section>
  <h2>收益对比</h2>
  <div class="grid-4">
    {_metric_card("影子组合", _percent(returns["shadow_return"]))}
    {_metric_card("真实代理", _percent(returns["real_proxy_return"]))}
    {_metric_card("基准", _percent(returns["benchmark_return"]))}
    {_metric_card("跟踪差距", f"{deviation['tracking_gap_pp']} pp")}
  </div>
</section>
<section>
  <h2>暴露与回撤</h2>
  <div class="grid-4">
    {_metric_card("影子权益", _percent(exposure["shadow_equity_weight"]))}
    {_metric_card("真实代理权益", _percent(exposure["real_proxy_equity_weight"]))}
    {_metric_card("主动暴露", f"{exposure['active_exposure_pp']} pp")}
    {_metric_card("影子回撤", _percent(drawdown["shadow_drawdown"]))}
  </div>
</section>
<section>
  <h2>回放曲线</h2>
  {_table(["日期", "真实代理", "影子组合", "基准"], curve_rows)}
</section>
"""


def _decision_content(data: dict[str, Any]) -> str:
    proposal = data["decision_proposal"]
    if proposal["status"] == "empty":
        return _empty_section("决策预览", "缺少研究、风险或组合来源，暂时无法生成决策预览。")
    gate_rows = [[key, _workflow_status_label(value)] for key, value in proposal["gate_summary"].items()]
    preview_rows = [
        [
            display_symbol(item["symbol"]),
            _endpoint_action_label(item["proposal"]),
            _percent(item["current_weight"]),
            _percent(item["target_weight"]),
            f"{item['delta_weight_pp']} pp",
            _gate_summary_text(item["gates"]),
        ]
        for item in proposal["decision_preview"]
    ]
    why_rows = [
        [item["stage"], item["source_id"] or "derived", item["finding"]]
        for item in proposal["explanation"]["why"]
    ]
    source_rows = _decision_source_rows(proposal["source_ids"])
    return f"""
<section class="two-pane">
  <div class="panel highlight">
    <h2>决策结论</h2>
    <p class="value">{html.escape(_decision_conclusion_label(proposal))}</p>
    <p class="detail">{html.escape(_decision_conclusion_detail(proposal))}</p>
    <div class="badge-row">
      <a class="step" href="/guidance/view">查看今日边界</a>
      <a class="step" href="/portfolio/view">查看影子组合</a>
    </div>
  </div>
  <div class="panel">
    <h2>决策依据链</h2>
    <p>{html.escape(_decision_boundary_text(proposal))}</p>
    {_table(["来源", "当前记录"], source_rows)}
  </div>
</section>
<section>
  <h2>今日决策预览</h2>
  <div class="grid-4">
    {_metric_card("建议", _endpoint_action_label(proposal["recommended_action"]))}
    {_metric_card("复核状态", _workflow_status_label(proposal["review_state"]))}
    {_metric_card("置信度", _percent(proposal["confidence"]))}
    {_metric_card("人工复核", _need_label(proposal["requires_human_review"]))}
  </div>
</section>
<section class="grid-2">
  <div class="panel">
    <h2>如何读标的预览</h2>
    <p>当前比例是影子组合现在的比例，目标比例是本次只读预览给出的参照比例，变化使用百分点表示。</p>
    <p class="detail">如果建议显示“先补研究”，说明 ResearchFirst 或门槛仍未放行，不进入纸面调仓参照。</p>
  </div>
  <div class="panel">
    <h2>怎样影响影子组合</h2>
    <p>影子组合只读取已经记录的决策和目标池，自动生成纸面组合快照。</p>
    <p class="detail">本页是预览和解释；是否已经进入影子组合，以组合页的来源决策和纸面变化记录为准。</p>
  </div>
</section>
<section>
  <h2>门槛状态</h2>
  {_table(["门槛", "状态"], gate_rows)}
</section>
<section>
  <h2>标的级预览</h2>
  {_table(["标的", "建议", "当前比例", "目标比例", "变化", "门槛"], preview_rows)}
</section>
<section>
  <h2>为什么这么建议</h2>
  {_table(["环节", "来源", "说明"], why_rows)}
</section>
<section class="grid-2">
  <div class="panel">
    <h2>阻断原因</h2>
    {_list_items(proposal["explanation"]["blocked_reasons"], "当前没有阻断原因。")}
  </div>
  <div class="panel">
    <h2>失效条件</h2>
    {_list_items(proposal["invalidation_conditions"], "暂无失效条件。")}
  </div>
</section>
<section class="panel">
  <h2>JSON 追溯</h2>
  <p><a href="/decision/proposal">查看决策预览 JSON</a></p>
  <p class="detail"><a href="/decision/explain">查看解释链 JSON</a></p>
</section>
"""


def _decision_conclusion_label(proposal: dict[str, Any]) -> str:
    action = proposal["recommended_action"]
    review_state = proposal["review_state"]
    if review_state == "blocked":
        return "当前决策被阻断"
    if action == "research_first":
        return "先补研究，再看决策"
    if action == "rebalance_candidate":
        return "存在再平衡候选"
    if action == "observe":
        return "保持观察"
    return "今日不行动"


def _decision_conclusion_detail(proposal: dict[str, Any]) -> str:
    action = _endpoint_action_label(proposal["recommended_action"])
    review_state = _workflow_status_label(proposal["review_state"])
    confidence = _percent(proposal["confidence"])
    blocked_count = len(proposal["explanation"]["blocked_reasons"])
    review = _need_label(proposal["requires_human_review"])
    base = f"建议为{action}，复核状态为{review_state}，置信度 {confidence}，人工复核{review}。"
    if blocked_count:
        return base + f" 当前有 {blocked_count} 条阻断原因，先看下方阻断原因和门槛状态。"
    return base + " 当前没有阻断原因，继续用标的级预览和组合页核对。"


def _decision_boundary_text(proposal: dict[str, Any]) -> str:
    gate_summary = proposal["gate_summary"]
    blocked = [key for key, value in gate_summary.items() if value in {"block", "missing"}]
    warned = [key for key, value in gate_summary.items() if value == "warn"]
    if blocked:
        labels = "、".join(_decision_gate_label(item) for item in blocked)
        return f"存在阻断门槛：{labels}。先处理这些来源，再看是否进入组合参照。"
    if warned:
        labels = "、".join(_decision_gate_label(item) for item in warned)
        return f"存在需要复核的门槛：{labels}。本页只能作为只读预览。"
    return "研究、风险、宏观、组合和数据门槛当前没有阻断，可继续看组合页核对纸面结果。"


def _decision_source_rows(source_ids: dict[str, Any]) -> list[list[Any]]:
    research_count = len(source_ids.get("research_snapshot_ids", []))
    return [
        ["市场快照", source_ids.get("market_snapshot_id") or "暂无"],
        ["研究快照", f"{research_count} 条"],
        ["决策记录", source_ids.get("decision_id") or "暂无"],
        ["组合快照", source_ids.get("portfolio_id") or "暂无"],
        ["风险状态", source_ids.get("risk_state_id") or "暂无"],
        ["宏观状态", source_ids.get("macro_state_id") or "暂无"],
    ]


def _decision_gate_label(value: str) -> str:
    return {
        "research_first": "ResearchFirst",
        "risk_boundary": "风险边界",
        "macro": "宏观状态",
        "portfolio": "组合匹配",
        "data": "数据新鲜度",
    }.get(value, value)


def _portfolio_content(data: dict[str, Any]) -> str:
    portfolio = data["dashboard"]["portfolio"]
    history = data["dashboard"]["portfolio_history"]
    actual = data["dashboard"]["actual_vs_shadow"]
    qmt_status = actual["qmt_read_status"]
    market = data["dashboard"]["market"]
    if not portfolio["available"]:
        return _empty_section("影子组合", "组合快照暂不可用，请先查看系统状态。")
    target = "暂无"
    if market["available"]:
        target = f"{_percent(market['equity_min'])} 到 {_percent(market['equity_max'])}"
    rows = [
        [
            item["display_name"],
            _percent(item["weight"]),
            f"<div class=\"bar\"><div class=\"fill\" style=\"width:{_bar_width(item['weight'])}%\"></div></div>",
        ]
        for item in portfolio["holdings"]
    ]
    change_rows = [
        [
            item["display_name"],
            _change_label(item["action"]),
            _percent(item["current_weight"]),
            _percent(item["target_weight"]),
            f"{item['delta_weight_pp']} pp",
        ]
        for item in portfolio["paper_changes"]
    ]
    if not change_rows:
        change_rows = [["无", "不变", "无", "无", "0 pp"]]
    actual_rows = [
        [
            item["display_name"],
            _weight_or_missing(item["actual_weight"]),
            _percent(item["shadow_weight"]),
            _delta_or_missing(item["shadow_minus_actual_pp"]),
            _actual_shadow_status_label(item["status"]),
        ]
        for item in actual["rows"]
    ]
    if not actual_rows:
        actual_rows = [["暂无", "缺少实际比例", "无", "无", "待刷新"]]
    rebalance_rows = [
        [
            item["basis_date"],
            item["display_name"],
            _change_label(item["action"]),
            _percent(item["current_weight"]),
            _percent(item["target_weight"]),
            f"{item['delta_weight_pp']} pp",
            item["source_decision_id"],
        ]
        for item in history["rebalance_records"]
    ]
    if not rebalance_rows:
        rebalance_rows = [["暂无", "无", "无", "无", "无", "0 pp", "暂无"]]
    snapshot_rows = [
        [
            item["basis_date"],
            _percent(item["cash_weight"]),
            _percent(item["turnover"]),
            _percent(item["pnl_ratio"]),
            item["paper_trade_count"],
            _holdings_summary(item["holdings"]),
            _timeline_link(item["basis_date"]),
        ]
        for item in history["snapshots"]
    ]
    if not snapshot_rows:
        snapshot_rows = [["暂无", "无", "无", "无", 0, "无", "无"]]
    return f"""
<section class="two-pane">
  <div class="panel highlight">
    <h2>组合结论</h2>
    <p class="value">{html.escape(_portfolio_conclusion_label(portfolio, actual, market))}</p>
    <p class="detail">{html.escape(_portfolio_conclusion_detail(portfolio, actual, target))}</p>
    <div class="badge-row">
      <a class="step" href="/decision/view">查看决策依据</a>
      <a class="step" href="/portfolio/history">查看组合历史 JSON</a>
    </div>
  </div>
  <div class="panel">
    <h2>自动调仓依据</h2>
    <p>{html.escape(_portfolio_auto_rebalance_text(portfolio, history))}</p>
    <p class="detail">来源决策：{html.escape(str(portfolio["source_decision_id"]))}；来源目标池：{html.escape(str(portfolio["source_target_pool_id"]))}。</p>
  </div>
</section>
<section>
  <h2>影子组合状态</h2>
  <div class="grid-4">
    {_metric_card("净值指数", portfolio["nav_index"])}
    {_metric_card("权益比例", _percent(portfolio["equity_weight"]))}
    {_metric_card("目标范围", target)}
    {_metric_card("偏离", "暂无" if portfolio["deviation_pp"] is None else f"{portfolio['deviation_pp']} pp")}
  </div>
</section>
<section class="grid-2">
  <div class="panel">
    <h2>怎么核对自动调仓</h2>
    <p>先看“最近纸面变化”，确认本次每个标的的原比例、目标比例和变化；再看“每次纸面调仓记录”，核对历史来源决策。</p>
    <p class="detail">影子组合是实际持仓的参照物，不需要你手动维护影子比例。</p>
  </div>
  <div class="panel">
    <h2>怎么核对实际差异</h2>
    <p>“实际持仓 vs 影子组合”只比较比例差异，用来告诉你实际配置和系统参照之间偏在哪里。</p>
    <p class="detail">如果 QMT 读取状态不是已读取，先刷新实际持仓比例，再看差异。</p>
  </div>
</section>
<section class="panel">
  <h2>自动模型对照</h2>
  <p>影子组合由系统根据最新市场边界、研究门槛、标的池和风控约束自动维护。</p>
  <p class="detail">它只生成纸面组合快照，用来和实际持仓对照；不会连接外部执行，也不需要你手动操作影子组合。</p>
  <p class="detail">来源决策：{html.escape(str(portfolio["source_decision_id"]))}</p>
</section>
<section class="panel">
  <h2>历史快照在哪里看</h2>
  <p>人看的历史快照就在本页下方；系统原始回放在 <a href="/timeline/replay">历史回放 JSON</a>。</p>
  <p class="detail">组合专用 JSON 在 <a href="/portfolio/history">组合历史 JSON</a>。输入历史日期时，也可以用 <a href="/portfolio/view?as_of=2026-06-15">按日期查看组合页</a>。</p>
</section>
<section class="panel">
  <h2>QMT 读取状态</h2>
  <div class="grid-4">
    {_metric_card("状态", _qmt_read_status_label(qmt_status["status"]))}
    {_metric_card("最后日期", qmt_status["last_basis_date"] or "尚未读取")}
    {_metric_card("原因", _qmt_reason_label(qmt_status["reason"]))}
    {_metric_card("下一步", qmt_status["next_action_label"])}
  </div>
  <p class="detail">来源：{html.escape(str(qmt_status["last_event_id"] or "暂无 QMT 读取快照"))}</p>
</section>
<section id="qmt-refresh" class="panel">
  <h2>刷新实际持仓</h2>
  <p>从本机 QMT 只读读取持仓比例，追加为历史快照来源；页面只展示比例，不展示金额类字段、数量类字段或账户细节。</p>
  <div class="badge-row">
    <label class="inline-control">日期 <input id="qmt-refresh-date" type="date" aria-label="QMT 读取日期"></label>
    <button type="button" id="qmt-refresh-button">从 QMT 刷新</button>
  </div>
  <pre id="qmt-refresh-result">等待刷新。</pre>
</section>
<section>
  <h2>实际持仓 vs 影子组合</h2>
  <div class="grid-4">
    {_metric_card("实际权益", _weight_or_missing(actual["actual_equity_weight"]))}
    {_metric_card("影子权益", _weight_or_missing(actual["shadow_equity_weight"]))}
    {_metric_card("权益差异", _delta_or_missing(actual["active_exposure_pp"]))}
    {_metric_card("最大单项差异", _delta_or_missing(actual["max_abs_delta_pp"]))}
  </div>
  <p class="detail">来源：{html.escape(str(actual["source_event_id"] or "缺少 QMT 比例快照"))}</p>
  <p class="detail">结构化 JSON：<a href="/portfolio/actual-vs-shadow">实际/影子对照 JSON</a></p>
  {_table(["标的", "实际比例", "影子比例", "影子-实际", "状态"], actual_rows)}
</section>
<section>
  <h2>持仓比例</h2>
  {_table(["标的", "比例", "分布"], rows, raw_columns={2})}
</section>
<section>
  <h2>最近纸面变化</h2>
  {_table(["标的", "动作", "原比例", "目标比例", "变化"], change_rows)}
</section>
<section>
  <h2>每次纸面调仓记录</h2>
  {_table(["日期", "标的", "动作", "原比例", "目标比例", "变化", "来源决策"], rebalance_rows)}
</section>
<section>
  <h2>历史组合快照</h2>
  {_table(["日期", "现金", "换手", "收益率", "调仓数", "持仓摘要", "回放"], snapshot_rows, raw_columns={6})}
</section>
<section>
  <h2>纸面表现</h2>
  <div class="grid-4">
    {_metric_card("收益率", _percent(portfolio["pnl_ratio"]))}
    {_metric_card("换手", _percent(portfolio["turnover"]))}
    {_metric_card("回撤", _percent(portfolio["drawdown"]))}
    {_metric_card("现金比例", _percent(portfolio["cash_weight"]))}
  </div>
</section>
<script>
(() => {{
  const dateInput = document.getElementById('qmt-refresh-date');
  const button = document.getElementById('qmt-refresh-button');
  const result = document.getElementById('qmt-refresh-result');
  if (dateInput && !dateInput.value) {{
    dateInput.value = new Date().toISOString().slice(0, 10);
  }}
  button.addEventListener('click', async () => {{
    const basisDate = dateInput.value;
    if (!basisDate) {{
      result.textContent = JSON.stringify({{ status: 'failed', data: {{ reason: 'missing_basis_date' }} }}, null, 2);
      return;
    }}
    button.disabled = true;
    result.textContent = '正在读取 QMT...';
    try {{
      const response = await fetch('/portfolio/qmt/refresh?basis_date=' + encodeURIComponent(basisDate), {{ method: 'POST' }});
      const data = await response.json();
      result.textContent = JSON.stringify(data, null, 2);
      if (data.status === 'ok') {{
        window.location.href = '/portfolio/view';
      }}
    }} catch (error) {{
      result.textContent = JSON.stringify({{ status: 'failed', data: {{ reason: 'qmt_refresh_request_failed' }} }}, null, 2);
    }} finally {{
      button.disabled = false;
    }}
  }});
}})();
</script>
"""


def _portfolio_conclusion_label(
    portfolio: dict[str, Any],
    actual: dict[str, Any],
    market: dict[str, Any],
) -> str:
    deviation = portfolio["deviation_pp"]
    if deviation is not None and abs(float(deviation)) <= 5:
        label = "影子组合接近目标范围"
    elif deviation is not None and float(deviation) > 0:
        label = "影子权益高于目标中枢"
    elif deviation is not None:
        label = "影子权益低于目标中枢"
    elif market["available"]:
        label = "影子组合等待目标核对"
    else:
        label = "影子组合等待市场边界"
    if actual["source_status"] != "actual_ratio_available":
        return label + "，实际对照待刷新"
    return label


def _portfolio_conclusion_detail(
    portfolio: dict[str, Any],
    actual: dict[str, Any],
    target: str,
) -> str:
    deviation = "暂无" if portfolio["deviation_pp"] is None else f"{portfolio['deviation_pp']} pp"
    change_count = len(portfolio["paper_changes"])
    actual_status = (
        "实际持仓比例已读取"
        if actual["source_status"] == "actual_ratio_available"
        else "实际持仓比例尚未读取"
    )
    return (
        f"影子权益比例 {_percent(portfolio['equity_weight'])}，目标范围 {target}，"
        f"相对目标中枢偏离 {deviation}，本次纸面变化 {change_count} 条。{actual_status}。"
    )


def _portfolio_auto_rebalance_text(
    portfolio: dict[str, Any],
    history: dict[str, Any],
) -> str:
    change_count = len(portfolio["paper_changes"])
    rebalance_count = history["rebalance_count"]
    if change_count:
        return f"系统按已记录决策自动生成 {change_count} 条本次纸面变化，并保留 {rebalance_count} 条历史纸面调仓记录。"
    return f"本次没有新的纸面变化；历史中保留 {rebalance_count} 条纸面调仓记录，可继续用于回放核对。"


def _research_content(data: dict[str, Any]) -> str:
    research = data["dashboard"]["research"]
    guidance = data["guidance"]
    valuation_review = data["research_valuation_review"]
    valuation_prompts = data["research_valuation_prompts"]
    if not research["available"]:
        return _empty_section("研究队列", "研究快照暂不可用，请先查看系统状态。")
    rows = [
        [
            item["module"],
            item["summary"],
            _percent(item["confidence"]),
            item["actionability"],
            item["next_review_date"],
        ]
        for item in research["items"]
    ]
    queue = guidance["research_first"]["queue"]
    queue_rows = [
        [
            display_symbol(item["symbol"]),
            _research_reason_label(item["reason"]),
            _research_blocker_label(item.get("blockers", [])),
            item["source"],
        ]
        for item in queue
    ]
    if not queue_rows:
        queue_rows = [["none", "当前没有 ResearchFirst 队列。", "无", "guidance"]]
    return f"""
<section class="two-pane">
  <div class="panel highlight">
    <h2>研究工作台</h2>
    <p class="value">{html.escape(_research_workbench_title(queue, valuation_review))}</p>
    <p class="detail">{html.escape(_research_workbench_detail(queue, valuation_review, valuation_prompts))}</p>
    <div class="badge-row">
      <a class="step" href="#research-workbench">查看研究清单</a>
      <a class="step" href="/research/import/view">导入研究 JSON</a>
    </div>
  </div>
  <div class="panel">
    <h2>放行规则</h2>
    <p>当前持仓、最新目标池和当前决策里的标的，只有画像、估值、流动性门槛都通过，才会从当前 ResearchFirst 队列移出。</p>
    <p class="detail">历史或已排除候选只保留研究记录；是否进入决策和影子组合，以当前目标池、决策页和组合页为准。</p>
  </div>
</section>
{_research_workbench_section(queue, valuation_review, valuation_prompts)}
<section class="panel">
  <h2>研究入口</h2>
  <p><a href="/research/import/view">导入新的研究 JSON</a>　<a href="#valuation-review">查看估值证据复核</a>　<a href="#valuation-prompts">生成补充研究提示词</a></p>
  <p class="detail">适合导入市场研究、主线研究或其它已校验研究快照。</p>
</section>
{_theme_summary_section(research["theme"])}
<section>
  <h2>最新研究快照</h2>
  {_table(["模块", "摘要", "置信度", "行动性", "下次复核"], rows)}
</section>
<section>
  <h2>ResearchFirst 队列</h2>
  {_table(["标的", "原因", "当前卡点", "来源"], queue_rows)}
</section>
{_valuation_review_section(valuation_review)}
{_valuation_prompt_section(valuation_prompts)}
"""


def _theme_summary_section(theme: dict[str, Any]) -> str:
    if not theme["available"]:
        return """
<section class="panel">
  <h2>主线研究摘要</h2>
  <p>当前没有 theme_research 快照。</p>
</section>
"""
    primary = theme["primary"] or {}
    watch = [
        f"{item['theme']}：{_theme_watch_status_label(item['status'])}"
        for item in theme["watchlist"]
    ]
    return f"""
<section class="panel">
  <h2>主线研究摘要</h2>
  <p class="value">{html.escape(str(primary.get("display_theme", "暂无主线")))}</p>
  <p class="detail">{html.escape(_theme_primary_detail(theme, primary))}</p>
  <p class="detail">关注方向：{html.escape("；".join(watch))}</p>
  <p class="detail"><a href="/theme/view">打开主线研究页</a>　<a href="/theme/state">查看主线 JSON</a></p>
</section>
"""


def _research_workbench_title(
    queue: list[dict[str, Any]],
    valuation_review: dict[str, Any],
) -> str:
    if queue:
        return f"下一项：{display_symbol(queue[0]['symbol'])}"
    if valuation_review["rows"]:
        return f"下一项：{valuation_review['rows'][0]['display_name']}"
    return "当前没有 ResearchFirst 待办"


def _research_workbench_detail(
    queue: list[dict[str, Any]],
    valuation_review: dict[str, Any],
    valuation_prompts: dict[str, Any],
) -> str:
    queue_count = len(queue)
    review_count = valuation_review["blocked_count"]
    prompt_count = valuation_prompts["prompt_count"]
    if queue_count:
        first = queue[0]
        reason = _research_reason_label(first["reason"])
        blockers = _research_blocker_label(first.get("blockers", []))
        return (
            f"当前队列里还有 {queue_count} 个标的。优先处理 {display_symbol(first['symbol'])}，"
            f"原因是{reason}，当前卡点是{blockers}。估值复核 {review_count} 项，提示词 {prompt_count} 条。"
        )
    if review_count:
        return f"ResearchFirst 队列未列出新标的，但仍有 {review_count} 项估值复核需要确认。"
    return "当前没有需要先补研究的标的；可以继续看决策页和组合页。"


def _research_workbench_section(
    queue: list[dict[str, Any]],
    valuation_review: dict[str, Any],
    valuation_prompts: dict[str, Any],
) -> str:
    rows = _research_workbench_rows(queue, valuation_review, valuation_prompts)
    return f"""
<section id="research-workbench">
  <h2>下一项该研究什么</h2>
  <p class="detail">这张表只合并当前 ResearchFirst 队列、估值复核和补充研究提示词；历史或已排除候选不会阻断这里。</p>
  {_table(["标的", "状态", "为什么还没放行", "下一步", "入口"], rows, raw_columns={4})}
</section>
"""


def _research_workbench_rows(
    queue: list[dict[str, Any]],
    valuation_review: dict[str, Any],
    valuation_prompts: dict[str, Any],
) -> list[list[Any]]:
    review_by_symbol = {
        item["symbol"]: item
        for item in valuation_review["rows"]
    }
    prompt_symbols = {
        item["symbol"]
        for item in valuation_prompts["prompts"]
    }
    rows: list[list[Any]] = []
    for item in queue:
        symbol = item["symbol"]
        review = review_by_symbol.get(symbol)
        next_step = review["next_step"] if review else _research_queue_next_step(item)
        entry = _research_workbench_entry(review is not None, symbol in prompt_symbols)
        rows.append(
            [
                display_symbol(symbol),
                _research_reason_label(item["reason"]),
                _research_blocker_label(item.get("blockers", [])),
                next_step,
                entry,
            ]
        )
    if not rows:
        rows = [["无", "已清空", "当前没有 ResearchFirst 队列。", "继续查看决策页或组合页。", _link("/decision/view")]]
    return rows


def _research_queue_next_step(item: dict[str, Any]) -> str:
    blockers = item.get("blockers", [])
    if "valuation_gate_failed" in blockers:
        return "先看估值证据复核，再复制提示词补充研究。"
    if "profile_gate_incomplete" in blockers or "profile_or_gate_incomplete" in blockers:
        return "补充画像、估值和流动性证据，导入新的研究 JSON。"
    if "liquidity_gate_incomplete" in blockers:
        return "补充流动性证据，导入新的研究 JSON。"
    if "duration_credit_incomplete" in blockers:
        return "补充久期和信用质量风险证据，导入新的研究 JSON。"
    if "target_pool_blocked" in blockers:
        return "先确认目标池阻断原因，再决定是否继续研究。"
    return "补充研究证据并导入新的研究 JSON，再复核队列。"


def _research_workbench_entry(has_review: bool, has_prompt: bool) -> str:
    links = ['<a href="/research/import/view">导入研究 JSON</a>']
    if has_review:
        links.insert(0, '<a href="#valuation-review">看复核</a>')
    if has_prompt:
        links.insert(0, '<a href="#valuation-prompts">复制提示词</a>')
    return "　".join(links)


def _valuation_review_section(review: dict[str, Any]) -> str:
    rows = [
        [
            item["display_name"],
            item["status_label"],
            item["evidence_summary"],
            "；".join(item["missing_evidence"]),
            item["next_step"],
            item["source_snapshot_id"] or "无",
        ]
        for item in review["rows"]
    ]
    if not rows:
        rows = [["none", "当前没有估值阻断", "无", "无", "继续查看 ResearchFirst 队列。", "guidance"]]
    return f"""
<section id="valuation-review">
  <h2>估值证据复核</h2>
  <p class="detail">这里只读解释为什么“研究已做”但仍未从 ResearchFirst 放行。</p>
  <p class="detail"><a href="/research/valuation-review">查看复核 JSON</a></p>
  {_table(["标的", "状态", "已有证据", "缺什么", "下一步", "来源快照"], rows)}
</section>
"""


def _valuation_prompt_section(prompt_state: dict[str, Any]) -> str:
    rows = [
        [
            item["display_name"],
            item["module"],
            item["source_snapshot_id"] or "无",
            _prompt_text_control(item["prompt_text"]),
        ]
        for item in prompt_state["prompts"]
    ]
    if not rows:
        rows = [["none", "无", "无", "当前没有需要生成的估值补充研究提示词。"]]
        raw_columns: set[int] = set()
    else:
        raw_columns = {3}
    return f"""
<section id="valuation-prompts">
  <h2>补充研究提示词</h2>
  <p class="detail">复制对应标的的提示词到新的研究对话，完成后把 research_snapshot JSON 导入系统。</p>
  <p class="detail"><a href="/research/valuation-prompts">查看提示词 JSON</a></p>
  {_table(["标的", "模块", "来源快照", "提示词"], rows, raw_columns=raw_columns)}
</section>
<script>
(() => {{
  document.querySelectorAll('[data-prompt-copy]').forEach((button) => {{
    button.addEventListener('click', async () => {{
      const wrapper = button.closest('.prompt-details');
      const textarea = wrapper ? wrapper.querySelector('textarea') : null;
      const status = wrapper ? wrapper.querySelector('[data-copy-status]') : null;
      if (!textarea) return;
      try {{
        await navigator.clipboard.writeText(textarea.value);
        if (status) status.textContent = '已复制';
      }} catch (error) {{
        textarea.focus();
        textarea.select();
        document.execCommand('copy');
        if (status) status.textContent = '已复制';
      }}
    }});
  }});
}})();
</script>
"""


def _prompt_text_control(prompt_text: str) -> str:
    escaped = html.escape(prompt_text)
    return (
        '<details class="prompt-details">'
        "<summary>打开提示词</summary>"
        f'<textarea class="prompt-textarea" readonly rows="6">{escaped}</textarea>'
        '<div class="prompt-actions">'
        '<button type="button" data-prompt-copy>复制提示词</button>'
        '<span class="copy-status" data-copy-status></span>'
        "</div>"
        "</details>"
    )


def _valuation_prompt_item(row: dict[str, Any]) -> dict[str, Any]:
    symbol = row["symbol"]
    module = row["source_module"] or _research_module_for_symbol(symbol)
    missing_evidence = "；".join(row["missing_evidence"])
    data_gap_actions = "；".join(row["data_gap_actions"]) if row["data_gap_actions"] else "无明确数据缺口处理动作"
    prompt_text = "\n".join(
        [
            "你是 MyInvest 研究层助手，只做研究，不做决策或执行。",
            f"任务：补充 {row['display_name']} 的估值复核证据，并输出可导入系统的 research_snapshot JSON。",
            f"标的代码：{symbol}",
            f"建议模块：{module}",
            f"来源研究快照：{row['source_snapshot_id']}",
            f"来源日期：{row['source_basis_date'] or '未标明'}",
            f"当前阻断：{row['blocker_label']}",
            f"已有证据：{row['evidence_summary']}",
            f"需要补充：{missing_evidence}",
            f"数据缺口处理：{data_gap_actions}",
            "请完成以下研究：",
            "1. 复核标的画像、主营或指数跟踪对象，说明是否仍符合研究对象定义。",
            "2. 补充估值证据，包括长期估值分位、同业对比、盈利或成长假设、风险折价；ETF 需补充折溢价和跟踪指数相对位置。",
            "3. 复核流动性证据是否足以支持估值结论；无法取得的数据必须写入 data_gaps。",
            "4. 明确 profile、valuation、liquidity 三个门槛是否通过；任一门槛未通过时 actionability 必须为 research_first。",
            "输出限制：只输出一个合法 JSON 对象，不要 Markdown，不要自由文本。",
            "JSON 类型：research_snapshot；schema_version=1.0；payload.symbol 必须等于上述标的代码。",
            "禁止输出 decision_record、portfolio_snapshot、真实执行指令、金额、数量或账户信息。",
        ]
    )
    item = {
        "symbol": symbol,
        "display_name": row["display_name"],
        "module": module,
        "source_snapshot_id": row["source_snapshot_id"],
        "source_basis_date": row["source_basis_date"],
        "prompt_title": f"{row['display_name']} 估值补充研究",
        "prompt_text": prompt_text,
        "expected_output": "research_snapshot_json",
        "import_endpoint": "/research/import/view",
    }
    assert_no_sensitive_content(item)
    return item


def _research_module_for_symbol(symbol: str) -> str:
    if symbol.startswith(("159", "510", "511", "512", "588")):
        return "etf_valuation"
    return "stock_valuation"


def _valuation_review_row(queue_item: dict[str, Any], event: dict[str, Any] | None) -> dict[str, Any]:
    snapshot = event["payload"] if event else {}
    symbol = queue_item["symbol"]
    blockers = queue_item.get("blockers", [])
    data_gaps = [str(item) for item in snapshot.get("data_gaps", [])]
    gap_descriptions = [describe_data_gap(item) for item in data_gaps]
    row = {
        "symbol": symbol,
        "display_name": display_symbol(symbol),
        "status": "blocked",
        "status_label": "估值复核未通过",
        "blockers": blockers,
        "blocker_label": _research_blocker_label(blockers),
        "evidence_summary": _valuation_evidence_summary(snapshot),
        "missing_evidence": _valuation_missing_evidence(blockers, gap_descriptions),
        "next_step": _valuation_next_step(gap_descriptions),
        "source_snapshot_id": snapshot.get("snapshot_id") or queue_item.get("source"),
        "source_module": snapshot.get("module"),
        "source_basis_date": snapshot.get("basis_date") or (event["basis_date"] if event else None),
        "confidence": snapshot.get("confidence"),
        "actionability": snapshot.get("actionability"),
        "data_gap_titles": [item["title"] for item in gap_descriptions],
        "data_gap_actions": [item["next_step"] for item in gap_descriptions],
    }
    assert_no_sensitive_content(row)
    return row


def _valuation_evidence_summary(snapshot: dict[str, Any]) -> str:
    if not snapshot:
        return "没有找到对应研究快照，只保留队列来源。"
    text = _snapshot_text(snapshot)
    facts: list[str] = []
    if _contains_any(text, ("profile gate passes", "profile and liquidity gates pass", "画像通过", "画像门槛通过")):
        facts.append("画像证据通过")
    if _contains_any(text, ("liquidity gate passes", "profile and liquidity gates pass", "流动性通过", "流动性门槛通过")):
        facts.append("流动性证据通过")
    if _contains_any(text, ("valuation gate fails", "valuation fails", "valuation pressure is high", "估值门槛未通过", "估值不通过")):
        facts.append("估值证据未通过")

    payload = snapshot.get("payload", {})
    score = payload.get("valuation_score") if isinstance(payload, dict) else None
    if isinstance(score, int | float):
        facts.append(f"估值分 {float(score):.2f}/100")
    risk_flag = payload.get("risk_flag") if isinstance(payload, dict) else None
    if risk_flag:
        facts.append(f"风险标记 {risk_flag}")
    rating = payload.get("rating") if isinstance(payload, dict) else None
    if rating:
        facts.append(f"评级 {rating}")
    if facts:
        return "；".join(_unique_text(facts))
    return "研究快照确认该标的仍需 ResearchFirst。"


def _valuation_missing_evidence(blockers: list[str], gap_descriptions: list[dict[str, str]]) -> list[str]:
    items: list[str] = []
    if "valuation_gate_failed" in blockers:
        items.append("缺少可放行的估值分位、同业对比或基本面支撑证据。")
    if "profile_gate_incomplete" in blockers:
        items.append("画像门槛仍需补证。")
    if "liquidity_gate_incomplete" in blockers:
        items.append("流动性门槛仍需补证。")
    for description in gap_descriptions:
        items.append(description["title"])
    if not items:
        items.append("研究快照没有列出明确缺口，需要复核来源。")
    return _unique_text(items)


def _valuation_next_step(gap_descriptions: list[dict[str, str]]) -> str:
    if gap_descriptions:
        first_action = gap_descriptions[0]["next_step"]
        return f"{first_action} 完成后导入新的研究 JSON，再复核队列。"
    return "补充估值证据并导入新的研究 JSON，再复核队列。"


def _snapshot_text(snapshot: dict[str, Any]) -> str:
    parts = [
        str(snapshot.get("executive_summary", "")),
        " ".join(str(item) for item in snapshot.get("key_facts", [])),
        " ".join(str(item) for item in snapshot.get("reasoning", [])),
        " ".join(str(item) for item in snapshot.get("risks", [])),
        " ".join(str(item) for item in snapshot.get("data_gaps", [])),
    ]
    return " ".join(parts).lower()


def _contains_any(text: str, needles: tuple[str, ...]) -> bool:
    return any(needle.lower() in text for needle in needles)


def _unique_text(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _research_import_content(data: dict[str, Any]) -> str:
    workflow = data["daily_workflow"]
    mainline_step = next(
        (item for item in workflow["steps"] if item["step_id"] == "mainline_research"),
        None,
    )
    current_status = mainline_step["detail"] if mainline_step else "等待研究 JSON。"
    return f"""
<section class="two-pane">
  <div class="panel highlight">
    <h2>研究 JSON 导入</h2>
    <p>只接受 research_snapshot JSON。先校验，再追加写入。</p>
    <p class="detail">{html.escape(current_status)}</p>
  </div>
  <div class="panel">
    <h2>导入边界</h2>
    <p>导入只写入 research_snapshot 和 event_log，保持 append-only。</p>
    <p class="detail">代表标的只能作为研究对象，仍受 ResearchFirst、估值和流动性门槛约束。</p>
  </div>
</section>
<section class="grid-2">
  <div class="panel">
    <h2>粘贴 JSON</h2>
    <textarea id="research-json" spellcheck="false" aria-label="研究 JSON"></textarea>
    <div class="badge-row">
      <button type="button" id="validate-research">校验 JSON</button>
      <button type="button" id="append-research" class="secondary">追加导入</button>
    </div>
  </div>
  <div class="panel">
    <h2>结果</h2>
    <pre id="research-import-result">等待输入。</pre>
  </div>
</section>
<section class="panel">
  <h2>需要满足</h2>
  <ul>
    <li>必须符合 research.schema.json。</li>
    <li>已知模块必须符合对应 payload schema。</li>
    <li>不得包含策略禁止字段或外部执行指令。</li>
    <li>snapshot_id 不得与历史研究重复。</li>
  </ul>
</section>
<script>
(() => {{
  const input = document.getElementById('research-json');
  const result = document.getElementById('research-import-result');
  const validateButton = document.getElementById('validate-research');
  const appendButton = document.getElementById('append-research');
  const run = async (url) => {{
    let payload;
    try {{
      payload = JSON.parse(input.value);
    }} catch (error) {{
      result.textContent = JSON.stringify({{ status: 'failed', data: {{ reason: 'JSON 解析失败' }} }}, null, 2);
      return;
    }}
    const response = await fetch(url, {{
      method: 'POST',
      headers: {{ 'Content-Type': 'application/json' }},
      body: JSON.stringify(payload)
    }});
    const data = await response.json();
    result.textContent = JSON.stringify(data, null, 2);
  }};
  validateButton.addEventListener('click', () => run('/research/import/validate'));
  appendButton.addEventListener('click', () => run('/research/import'));
}})();
</script>
"""


def _report_content(data: dict[str, Any]) -> str:
    report = data["dashboard"]["report"]
    manifest = report["manifest_preview"]
    rows = [[section, "ready"] for section in report["sections"]]
    summary_rows = _report_summary_rows(data)
    source_rows = _report_source_rows(manifest)
    return f"""
<section class="two-pane">
  <div class="panel highlight">
    <h2>每日报告结论</h2>
    <p class="value">{html.escape(_report_headline(data))}</p>
    <p class="detail">{html.escape(_report_detail(data))}</p>
    <div class="badge-row">
      <a class="step" href="/guidance/view">今日边界</a>
      <a class="step" href="/decision/view">决策预览</a>
      <a class="step" href="/portfolio/view">影子组合</a>
    </div>
  </div>
  <div class="panel">
    <h2>阅读顺序</h2>
    <div class="path">
      <a class="step" href="/guidance/view">边界</a><span class="arrow">→</span>
      <a class="step" href="/market/view">市场</a><span class="arrow">→</span>
      <a class="step" href="/risk/view">风险</a><span class="arrow">→</span>
      <a class="step" href="/research/view">研究</a><span class="arrow">→</span>
      <a class="step" href="/decision/view">决策</a><span class="arrow">→</span>
      <a class="step" href="/portfolio/view">组合</a>
    </div>
    <p class="detail">报告页只汇总当前状态；事实源仍是 SQLite 回放和 JSON 快照。</p>
  </div>
</section>
<section>
  <h2>一页式摘要</h2>
  {_table(["模块", "结论", "关键依据", "入口"], summary_rows, raw_columns={3})}
</section>
<section>
  <h2>报告来源</h2>
  <div class="grid-4">
    {_metric_card("格式", "、".join(report["supported_formats"]))}
    {_metric_card("市场快照", manifest["market_snapshot_id"] or "暂无")}
    {_metric_card("组合快照", manifest["portfolio_id"] or "暂无")}
    {_metric_card("研究数量", len(manifest["research_snapshot_ids"]))}
  </div>
</section>
<section>
  <h2>来源追溯</h2>
  {_table(["来源", "编号"], source_rows)}
</section>
<section>
  <h2>章节</h2>
  {_table(["章节", "状态"], rows)}
</section>
<section class="panel">
  <h2>追溯入口</h2>
  <p><a href="/timeline/replay">查看完整时间线 JSON</a></p>
  <p class="detail">报告只是派生视图，追溯仍以 SQLite 与 JSON 快照为准。</p>
</section>
"""


def _report_headline(data: dict[str, Any]) -> str:
    guidance = data["guidance"]
    proposal = data["decision_proposal"]
    research_queue = guidance["research_first"]["queue"]
    if research_queue:
        return f"先处理研究队列：{display_symbol(research_queue[0]['symbol'])}"
    if proposal["status"] != "empty":
        return _decision_conclusion_label(proposal)
    return guidance.get("today_action", {}).get("headline") or "先看今日边界"


def _report_detail(data: dict[str, Any]) -> str:
    guidance = data["guidance"]
    readiness = guidance["readiness"]
    risk = data["dashboard"]["risk"]
    research_queue = guidance["research_first"]["queue"]
    parts = [
        f"今日状态：{_readiness_label(readiness['overall_state'])}",
        f"提高风险：{_yes_no(readiness['can_increase_risk'])}",
        f"新增标的：{_yes_no(readiness['can_add_new_subject'])}",
    ]
    if risk["available"]:
        parts.append(f"风险：{_risk_level_label(risk['risk_level'])}")
    if research_queue:
        parts.append(f"ResearchFirst 待办 {len(research_queue)} 项")
    return "；".join(parts) + "。"


def _report_summary_rows(data: dict[str, Any]) -> list[list[Any]]:
    dashboard = data["dashboard"]
    guidance = data["guidance"]
    market = dashboard["market"]
    theme = dashboard["research"]["theme"]
    risk = dashboard["risk"]
    macro = dashboard["macro"]
    portfolio = dashboard["portfolio"]
    actual = dashboard["actual_vs_shadow"]
    valuation_review = data["research_valuation_review"]
    valuation_prompts = data["research_valuation_prompts"]
    proposal = data["decision_proposal"]
    queue = guidance["research_first"]["queue"]

    rows: list[list[Any]] = [
        [
            "今日边界",
            _readiness_label(guidance["readiness"]["overall_state"]),
            _report_guidance_basis(guidance),
            _link("/guidance/view"),
        ]
    ]
    if market["available"]:
        rows.append(
            [
                "市场",
                _market_conclusion_label(market),
                _market_equity_range_text(market),
                _link("/market/view"),
            ]
        )
    if theme["available"]:
        primary = theme["primary"] or {}
        rows.append(
            [
                "主线",
                str(primary.get("display_theme", "暂无主线")),
                _theme_report_basis(theme),
                _link("/theme/view"),
            ]
        )
    if macro["available"]:
        consensus = macro["model_consensus"]
        rows.append(
            [
                "宏观",
                _macro_conclusion_label(consensus["consensus_state"]),
                _macro_conclusion_detail(consensus, guidance),
                _link("/macro/view"),
            ]
        )
    if risk["available"]:
        rows.append(
            [
                "风险",
                _risk_conclusion_label(risk),
                _risk_conclusion_detail(risk, guidance),
                _link("/risk/view"),
            ]
        )
    rows.append(
        [
            "研究",
            _research_workbench_title(queue, valuation_review),
            _research_workbench_detail(queue, valuation_review, valuation_prompts),
            _link("/research/view"),
        ]
    )
    if proposal["status"] != "empty":
        rows.append(
            [
                "决策",
                _decision_conclusion_label(proposal),
                _decision_conclusion_detail(proposal),
                _link("/decision/view"),
            ]
        )
    if portfolio["available"]:
        rows.append(
            [
                "组合",
                _portfolio_conclusion_label(portfolio, actual, market),
                _portfolio_conclusion_detail(portfolio, actual, _report_market_target(market)),
                _link("/portfolio/view"),
            ]
        )
    return rows


def _report_guidance_basis(guidance: dict[str, Any]) -> str:
    readiness = guidance["readiness"]
    return (
        f"提高风险 {_yes_no(readiness['can_increase_risk'])}；"
        f"新增标的 {_yes_no(readiness['can_add_new_subject'])}；"
        f"人工复核 {_need_label(readiness['requires_human_review'])}。"
    )


def _report_market_target(market: dict[str, Any]) -> str:
    if not market["available"]:
        return "暂无"
    return f"{_percent(market['equity_min'])} 到 {_percent(market['equity_max'])}"


def _report_source_rows(manifest: dict[str, Any]) -> list[list[Any]]:
    return [
        ["市场快照", manifest["market_snapshot_id"] or "暂无"],
        ["决策记录", manifest["decision_id"] or "暂无"],
        ["组合快照", manifest["portfolio_id"] or "暂无"],
        ["研究快照", f"{len(manifest['research_snapshot_ids'])} 条"],
    ]


def _system_content(data: dict[str, Any]) -> str:
    dashboard = data["dashboard"]
    overview = dashboard["overview"]
    trace = dashboard["replay"]["trace"]
    rows = [[key, value] for key, value in trace.items()]
    if not rows:
        rows = [["trace", "暂无回放链路。"]]
    api_rows = [
        ["/home", "自然人入口 JSON"],
        ["/workflow/daily/state", "每日工作流 JSON"],
        ["/guidance/state", "今日行动边界 JSON"],
        ["/theme/state", "主线研究 JSON"],
        ["/target-pool/latest", "策略目标池 JSON"],
        ["POST /research/import/validate", "研究导入校验 JSON"],
        ["POST /research/import", "研究追加导入 JSON"],
        ["/research/valuation-review", "估值复核 JSON"],
        ["/research/valuation-prompts", "补充研究提示词 JSON"],
        ["/decision/proposal", "决策预览 JSON"],
        ["/decision/explain", "决策解释 JSON"],
        ["/portfolio/actual-vs-shadow", "实际/影子对照 JSON"],
        ["/system/dashboard_state", "综合看板 JSON"],
        ["/portfolio/history", "组合历史 JSON"],
        ["/usability/state", "易用性检查 JSON"],
        ["/timeline/replay", "历史回放 JSON"],
        ["/system/status", "系统自检 JSON"],
    ]
    return f"""
<section>
  <h2>系统状态</h2>
  <div class="grid-4">
    {_metric_card("自检", overview["self_check_status"])}
    {_metric_card("数据库", "已初始化" if overview["db_initialized"] else "未初始化")}
    {_metric_card("回放", "可用" if overview["replay_available"] else "不可用")}
    {_metric_card("最新事件", overview["latest_event_timestamp"] or "暂无")}
  </div>
</section>
<section>
  <h2>回放链路</h2>
  {_table(["字段", "来源编号"], rows)}
</section>
<section>
  <h2>JSON 入口</h2>
  {_table(["接口", "说明"], api_rows)}
</section>
"""


def _usability_content(data: dict[str, Any]) -> str:
    usability = data["usability"]
    check_rows = [
        [item["title"], _status_label(item["status"]), item["detail"], _link(item["endpoint"])]
        for item in usability["checks"]
    ]
    flow = _linked_flow(usability["human_flow"])
    entry_rows = [[endpoint, _endpoint_label(endpoint)] for endpoint in usability["feature_entrypoints"]]
    return f"""
<section>
  <h2>易用性检查</h2>
  <div class="grid-3">
    {_metric_card("检查状态", _status_label(usability["status"]), "good" if usability["status"] == "passed" else "warn")}
    {_metric_card("统一首页", usability["primary_home"])}
    {_metric_card("入口数量", len(usability["feature_entrypoints"]))}
  </div>
</section>
<section>
  <h2>检查项</h2>
  {_table(["项目", "状态", "说明", "入口"], check_rows, raw_columns={3})}
</section>
<section class="panel">
  <h2>自然人使用流程</h2>
  <div class="path">{flow}</div>
</section>
<section>
  <h2>全部入口</h2>
  {_table(["入口", "用途"], entry_rows)}
</section>
"""


def _feature_card(title: str, href: str, detail: str) -> str:
    return f"""
<div class="panel feature">
  <a href="{html.escape(href)}">{html.escape(title)}</a>
  <p class="small">{html.escape(detail)}</p>
</div>
"""


def _metric_card(label: str, value: Any, value_class: str = "value") -> str:
    return (
        "<div class=\"panel\">"
        f"<div class=\"label\">{html.escape(str(label))}</div>"
        f"<div class=\"{html.escape(value_class)}\">{html.escape(str(value))}</div>"
        "</div>"
    )


def _table(headers: list[str], rows: list[list[Any]], raw_columns: set[int] | None = None) -> str:
    raw_columns = raw_columns or set()
    head = "".join(f"<th>{html.escape(str(header))}</th>" for header in headers)
    body = "".join(_table_row(row, raw_columns) for row in rows)
    return f"<div class=\"table-scroll\"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>"


def _table_row(row: list[Any], raw_columns: set[int]) -> str:
    cells = []
    for index, value in enumerate(row):
        if index in raw_columns:
            cells.append(f"<td>{value}</td>")
        else:
            cells.append(f"<td>{html.escape(str(value))}</td>")
    return f"<tr>{''.join(cells)}</tr>"


def _operation_row(item: dict[str, Any]) -> list[Any]:
    return [
        _operation_label(item["operation"]),
        _operation_status(item["status"]),
        item["reason"],
        _human_link(item["endpoint"]) if item["endpoint"] else "无",
    ]


def _next_step_row(item: dict[str, Any]) -> list[Any]:
    return [
        _step_label(item["step"]),
        item["reason"],
        _human_link(item["endpoint"]),
    ]


def _check_row(item: dict[str, Any]) -> list[Any]:
    return [
        item["title"],
        _status_label(item["status"]),
        item["detail"],
        _human_link(item["next_endpoint"]) if item.get("next_endpoint") else "无",
    ]


def _linked_flow(steps: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for index, step in enumerate(steps):
        if index:
            parts.append("<span class=\"arrow\">→</span>")
        parts.append(
            f"<a class=\"step\" href=\"{html.escape(step['endpoint'])}\">"
            f"{html.escape(step['step'])}</a>"
        )
    return "".join(parts)


def _list_items(items: list[Any], empty_text: str) -> str:
    if not items:
        return f"<p class=\"detail\">{html.escape(empty_text)}</p>"
    rows = "".join(f"<li>{html.escape(str(item))}</li>" for item in items)
    return f"<ul>{rows}</ul>"


def _data_gap_table(gaps: list[str]) -> str:
    rows = [
        [item["title"], item["impact"], item["next_step"]]
        for item in unique_data_gap_descriptions(gaps)
    ]
    if not rows:
        return "<p class=\"detail\">当前没有数据缺口。</p>"
    return _table(["缺口", "影响", "处理方式"], rows)


def _empty_section(title: str, detail: str) -> str:
    return f"<section class=\"panel\"><h2>{html.escape(title)}</h2><p>{html.escape(detail)}</p></section>"


def _link(endpoint: str) -> str:
    label = _endpoint_label(endpoint)
    return f"<a href=\"{html.escape(endpoint)}\">{html.escape(label)}</a>"


def _human_link(endpoint: str) -> str:
    return _link(_human_endpoint(endpoint))


def _human_endpoint(endpoint: str) -> str:
    return HUMAN_ENDPOINT_MAP.get(endpoint, endpoint)


def _endpoint_label(endpoint: str) -> str:
    return {
        "/app": "首页",
        "/workflow/daily/view": "每日工作流",
        "/workflow/daily/state": "每日工作流 JSON",
        "/home": "首页 JSON",
        "/home_human": "自然人首页",
        "/guidance/view": "今日行动边界",
        "/guidance/state": "今日边界 JSON",
        "/market/view": "市场状态",
        "/market/latest": "市场 JSON",
        "/theme/view": "主线研究",
        "/theme/state": "主线研究 JSON",
        "/target-pool/view": "策略目标池",
        "/target-pool/latest": "策略目标池 JSON",
        "/risk/view": "风险状态",
        "/risk/state": "风险 JSON",
        "/macro/view": "宏观状态",
        "/macro/state": "宏观 JSON",
        "/comparison/view": "对比分析",
        "/comparison/state": "对比 JSON",
        "/decision/view": "决策预览",
        "/decision/proposal": "决策预览 JSON",
        "/decision/explain": "决策解释 JSON",
        "/portfolio/view": "影子组合",
        "/portfolio/state": "组合 JSON",
        "/portfolio/history": "组合历史 JSON",
        "/portfolio/actual-vs-shadow": "实际/影子对照 JSON",
        "/research/view": "研究结论",
        "/research/import/view": "研究导入",
        "/research/valuation-review": "估值复核 JSON",
        "/research/valuation-prompts": "补充研究提示词 JSON",
        "/research/import/validate": "研究导入校验 JSON",
        "/research/import": "研究追加导入 JSON",
        "/research/latest": "研究 JSON",
        "/report/view": "每日报告",
        "/dashboard": "综合看板",
        "/overview": "总览",
        "/system/view": "系统状态",
        "/system/status": "系统 JSON",
        "/system/dashboard_state": "看板 JSON",
        "/timeline/replay": "历史回放 JSON",
        "/usability/view": "易用性检查",
        "/usability/state": "易用性 JSON",
    }.get(endpoint, endpoint)


def _reason_label(reason_code: str) -> str:
    return {
        "high_risk": "风险分数或等级偏高，先确认风险来源。",
        "volatile_macro": "宏观状态偏谨慎，先确认宏观压力。",
        "liquidity_watch": "流动性偏低，先看宏观状态。",
        "weak_theme_clarity": "研究主线不够清晰，先回到研究。",
        "tracking_gap": "影子组合跟踪差距偏大，先做对比分析。",
        "portfolio_exposure_review": "组合暴露偏离目标中枢，先看组合。",
        "stable_market": "主要信号稳定，可以先看组合。",
    }.get(reason_code, "系统建议先查看下一步模块。")


def _operation_label(value: str) -> str:
    return {
        "portfolio_review": "查看组合",
        "increase_risk": "提高风险",
        "new_subject_review": "新增标的",
        "external_execution": "外部执行",
    }.get(value, value)


def _change_label(value: str) -> str:
    return {
        "increase": "提高比例",
        "decrease": "降低比例",
        "hold": "保持不变",
    }.get(value, value)


def _weight_or_missing(value: float | int | None) -> str:
    if value is None:
        return "缺少实际比例"
    return _percent(value)


def _delta_or_missing(value: float | int | None) -> str:
    if value is None:
        return "缺少实际比例"
    return f"{float(value):.4f} pp"


def _actual_shadow_status_label(value: str) -> str:
    return {
        "actual_ratio_missing": "缺少实际比例",
        "aligned": "一致",
        "shadow_overweight": "影子更高",
        "shadow_underweight": "影子更低",
    }.get(value, value)


def _daily_refresh_status_label(value: str) -> str:
    return {
        "done": "已完成",
        "pending": "待处理",
    }.get(value, value)


def _daily_refresh_reason_label(value: str) -> str:
    if value == "无":
        return value
    return {
        "qmt_readonly_config_missing": "本机 QMT 只读配置缺失",
        "qmt_xtquant_sdk_missing": "QMT SDK 不可用",
        "qmt_connect_failed": "QMT 未连接",
        "qmt_read_failed": "QMT 读取失败",
        "qmt_total_asset_unavailable": "QMT 比例基准不可用",
        "qmt_position_missing": "未读到持仓比例",
        "qmt_holding_weight_missing": "缺少实际比例",
        "qmt_position_import_missing": "尚未读取实际持仓比例",
    }.get(value, value)


def _qmt_read_status_label(value: str) -> str:
    return {
        "success": "已读取",
        "blocked": "读取受阻",
        "incomplete": "数据不完整",
        "missing": "尚未读取",
    }.get(value, value)


def _qmt_reason_label(value: str | None) -> str:
    if value is None:
        return "无"
    return {
        "qmt_position_import_missing": "尚未读取实际持仓比例",
        "qmt_holding_weight_missing": "缺少实际比例",
        "qmt_readonly_config_missing": "本机 QMT 只读配置缺失",
        "qmt_xtquant_sdk_missing": "QMT SDK 不可用",
        "qmt_connect_failed": "QMT 未连接",
        "qmt_read_failed": "QMT 读取失败",
        "qmt_total_asset_unavailable": "QMT 比例基准不可用",
        "qmt_position_missing": "未读到持仓比例",
        "qmt_weight_total_invalid": "持仓比例合计异常",
    }.get(value, value)


def _theme_primary_detail(theme: dict[str, Any], primary: dict[str, Any]) -> str:
    if not primary:
        return "当前没有可展示的主线。"
    plates = "、".join(primary.get("plates", [])) or "暂无板块明细"
    aliases = _theme_alias_text(primary)
    return (
        f"强度 {_theme_strength_text(primary.get('strength_score'))}，"
        f"阶段 {_theme_phase_label(primary.get('phase') or primary.get('continuity'))}，"
        f"包含 {plates}。你熟悉的说法：{aliases}。"
    )


def _theme_report_basis(theme: dict[str, Any]) -> str:
    primary = theme.get("primary") or {}
    watch = [
        f"{item['theme']}={_theme_watch_status_label(item['status'])}"
        for item in theme.get("watchlist", [])
    ]
    return (
        f"强度 {_theme_strength_text(primary.get('strength_score'))}；"
        f"关注方向 {'；'.join(watch) if watch else '暂无'}。"
    )


def _theme_alias_text(item: dict[str, Any]) -> str:
    aliases = item.get("aliases", [])
    return "、".join(aliases) if aliases else "暂无别名"


def _theme_strength_text(value: Any) -> str:
    if value is None:
        return "暂无"
    return _score_out_of_100(value)


def _theme_phase_label(value: Any) -> str:
    if value is None:
        return "暂无"
    return {
        "early": "早期",
        "mid": "中段",
        "late": "后段",
        "strong_continuation": "强延续",
        "continuation_watch": "延续观察",
        "new": "新出现",
    }.get(str(value), str(value))


def _theme_research_first_label(value: Any) -> str:
    if value is True:
        return "代表标的先 ResearchFirst"
    if value is False:
        return "未标记 ResearchFirst"
    return "待确认"


def _theme_watch_status_label(value: str) -> str:
    return {
        "included": "已进入当前主线",
        "not_in_top_mainlines": "未进入前三主线",
    }.get(value, value)


def _target_pool_source_label(value: str) -> str:
    return {
        "strategy": "策略研究与决策",
        "market_research": "市场研究生成",
        "decision": "决策记录生成",
        "demo": "演示数据",
        "seed": "种子数据",
        "golden": "验收基准数据",
        "qmt_position_import": "QMT 只读导入记录",
    }.get(value, value)


def _holdings_summary(holdings: list[dict[str, Any]]) -> str:
    if not holdings:
        return "无持仓"
    return "；".join(
        f"{item['display_name']} {_percent(item['weight'])}"
        for item in holdings
    )


def _timeline_link(basis_date: str) -> str:
    endpoint = f"/timeline/replay?as_of={basis_date}"
    return f"<a href=\"{html.escape(endpoint)}\">回放</a>"


def _operation_status(value: str) -> str:
    return {
        "allowed": "允许",
        "blocked": "阻断",
        "review_required": "需复核",
    }.get(value, value)


def _step_label(value: str) -> str:
    return {
        "policy_config": "确认风控边界",
        "data_freshness": "更新每日数据",
        "research_first": "补齐研究",
        "risk_boundaries": "查看风险",
        "paper_only": "确认纸面模拟边界",
        "replay_available": "检查回放链路",
        "portfolio_review": "查看组合",
    }.get(value, value)


def _status_label(value: str) -> str:
    return {
        "pass": "通过",
        "warn": "需关注",
        "block": "阻断",
        "missing": "缺失",
        "passed": "通过",
        "review_required": "需要复核",
    }.get(value, value)


def _workflow_status_label(value: str) -> str:
    return {
        "pass": "通过",
        "warn": "需复核",
        "block": "阻断",
        "missing": "缺失",
        "ready": "已就绪",
        "review_required": "需要复核",
        "action_required": "需要处理",
    }.get(value, value)


def _endpoint_action_label(value: str) -> str:
    return {
        "observe": "观察",
        "research_first": "先补研究",
        "rebalance_candidate": "再平衡候选",
        "no_action": "不行动",
        "ready": "已就绪",
        "blocked": "阻断",
        "empty": "暂无状态",
    }.get(value, value)


def _gate_summary_text(gates: dict[str, Any]) -> str:
    items = [
        f"profile={gates['profile']}",
        f"valuation={gates['valuation']}",
        f"liquidity={gates['liquidity']}",
        f"research_first={gates['research_first']}",
        f"risk={gates['risk_boundary']}",
    ]
    return "; ".join(items)


def _readiness_label(value: str) -> str:
    return {
        "ready": "可以只读复核",
        "review_required": "需要先复核",
        "blocked": "暂时阻断",
        "empty": "暂无状态",
    }.get(value, value)


def _priority_label(value: str) -> str:
    return {
        "low": "低",
        "medium": "中等",
        "high": "高",
    }.get(value, value)


def _research_reason_label(value: str) -> str:
    return {
        "profile_or_gate_incomplete": "画像或门槛未完成",
        "blocked_in_target_pool": "目标池阻断",
        "decision_requires_research_first": "决策要求先研究",
        "research_first_required": "需要先研究",
        "profile_missing": "画像缺失",
    }.get(value, value)


def _research_blocker_label(values: list[str]) -> str:
    if not values:
        return "未标明"
    labels = {
        "profile_gate_incomplete": "画像门槛未通过",
        "valuation_gate_failed": "估值门槛未通过",
        "liquidity_gate_incomplete": "流动性门槛未通过",
        "duration_credit_incomplete": "久期或信用质量证据不足",
        "data_gap": "仍有数据缺口",
        "research_first_required": "仍需先研究",
        "profile_or_gate_incomplete": "画像或门槛未完成",
        "target_pool_blocked": "目标池阻断",
        "blocked_in_target_pool": "目标池阻断",
        "decision_requires_research_first": "决策要求先研究",
        "profile_missing": "画像缺失",
    }
    return "；".join(labels.get(value, value) for value in values)


def _exposure_label(value: str) -> str:
    return {
        "within_range": "在目标范围内",
        "above_target": "高于目标中枢",
        "below_target": "低于目标中枢",
        "overweight": "高于目标中枢",
        "underweight": "低于目标中枢",
        "no_replay_state": "暂无回放状态",
        "unavailable": "暂无",
    }.get(value, value)


def _risk_class(value: str) -> str:
    if value == "high":
        return "bad"
    if value == "medium":
        return "warn"
    return "good"


def _bool_class(value: bool) -> str:
    return "good" if value else "bad"


def _yes_no(value: bool) -> str:
    return "可以" if value else "不可以"


def _need_label(value: bool) -> str:
    return "需要" if value else "不需要"


def _percent(value: float | int) -> str:
    return f"{float(value) * 100:.2f}%"


def _bar_width(value: float | int) -> str:
    return f"{max(0, min(100, float(value) * 100)):.2f}"
