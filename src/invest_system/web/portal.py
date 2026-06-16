from __future__ import annotations

import html
from typing import Any

from invest_system.decision import build_decision_proposal
from invest_system.entry import build_home_state
from invest_system.guidance import compute_guidance_state
from invest_system.repositories import SQLiteRepository
from invest_system.validators.policies import assert_no_sensitive_content
from invest_system.web.dashboard import build_dashboard_state
from invest_system.web.data_gap_display import unique_data_gap_descriptions
from invest_system.web.symbol_display import display_symbol
from invest_system.workflow import build_daily_workflow_state


NAV_ITEMS = [
    {"label": "首页", "href": "/app", "page": "home"},
    {"label": "每日", "href": "/workflow/daily/view", "page": "daily"},
    {"label": "今日边界", "href": "/guidance/view", "page": "guidance"},
    {"label": "市场", "href": "/market/view", "page": "market"},
    {"label": "风险", "href": "/risk/view", "page": "risk"},
    {"label": "宏观", "href": "/macro/view", "page": "macro"},
    {"label": "对比", "href": "/comparison/view", "page": "comparison"},
    {"label": "决策", "href": "/decision/view", "page": "decision"},
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
    "risk": "风险状态",
    "macro": "宏观状态",
    "comparison": "对比分析",
    "decision": "决策预览",
    "portfolio": "影子组合",
    "research": "研究队列",
    "research_import": "研究 JSON 导入",
    "report": "报告预览",
    "system": "系统状态",
    "usability": "易用性检查",
}

USABILITY_ENDPOINTS = [
    "/app",
    "/workflow/daily/view",
    "/guidance/view",
    "/market/view",
    "/risk/view",
    "/macro/view",
    "/comparison/view",
    "/decision/view",
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
    "/target-pool/latest": "/research/view",
    "/research/latest": "/research/view",
    "/research/import": "/research/import/view",
    "/research/import/validate": "/research/import/view",
    "/decision/latest": "/decision/view",
    "/decision/proposal": "/decision/view",
    "/decision/explain": "/decision/view",
    "/portfolio/state": "/portfolio/view",
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
            "usability": usability,
        },
    }
    assert_no_sensitive_content(state)
    return state


def build_usability_state(repo: SQLiteRepository, as_of: str | None = None) -> dict[str, Any]:
    portal = build_portal_state(repo, as_of)
    return {"status": "ok", "data": portal["data"]["usability"]}


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
            "页脚固定展示只读边界、JSON 事实源和纸面模拟边界。",
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
            "页面只读取 SQLite 与 JSON 回放状态，不写入业务数据。",
            "/system/dashboard_state",
        ),
        _usability_check(
            "read_only_boundary",
            "pass",
            "只读边界",
            "浏览器页面没有提交控件，也不会触发外部执行。",
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
    button {{ border:1px solid #8ec8c1; border-radius:6px; padding:8px 11px; background:var(--soft); color:var(--accent-ink); font-weight:800; cursor:pointer; }}
    button.secondary {{ border-color:var(--line); background:#fff; color:var(--ink); }}
    pre {{ white-space:pre-wrap; overflow:auto; margin:0; border:1px solid var(--line); border-radius:8px; background:#fff; padding:12px; font:13px/1.45 Consolas, "Courier New", monospace; }}
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
        <p class="detail">研究、决策、影子组合分层显示；浏览器界面不写入核心数据。</p>
      </div>
    </section>
    {content}
  </main>
  <footer>
    <div class="wrap footer-grid">
      <div>统一页脚：只读系统 / JSON 为事实源 / 影子组合仅纸面模拟 / 不连接外部执行。</div>
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
        ("风险状态", "/risk/view", "查看风控分数、暴露提示、集中度和风险警告。"),
        ("宏观状态", "/macro/view", "查看流动性、利率压力、风险周期和模型共识。"),
        ("对比分析", "/comparison/view", "比较影子组合、真实代理和基准的比例表现。"),
        ("决策预览", "/decision/view", "查看只读建议、门槛状态和解释追溯链。"),
        ("影子组合", "/portfolio/view", "查看纸面模拟组合比例、偏离和回放来源。"),
        ("研究队列", "/research/view", "查看最新研究快照和 ResearchFirst 队列。"),
        ("研究导入", "/research/import/view", "粘贴研究 JSON，先校验，再追加写入系统。"),
        ("报告预览", "/report/view", "查看可生成报告的章节与来源编号。"),
        ("系统状态", "/system/view", "查看自检、回放、记录数量和 JSON 入口。"),
        ("易用性检查", "/usability/view", "检查入口、页头、页脚、引导和只读边界。"),
    ]
    feature_cards = "".join(_feature_card(title, href, detail) for title, href, detail in features)
    flow = data["usability"]["human_flow"]
    flow_steps = _linked_flow(flow)
    readiness = guidance["readiness"]
    overview = dashboard["overview"]
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
<section>
  <h2>功能入口</h2>
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
  <div class="panel"><h2>数据缺口</h2>{gaps}</div>
  <div class="panel"><h2>冲突提示</h2>{conflicts}</div>
</section>
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


def _market_content(data: dict[str, Any]) -> str:
    market = data["dashboard"]["market"]
    target_pool = data["dashboard"]["target_pool"]
    if not market["available"]:
        return _empty_section("市场状态", "市场快照暂不可用，请先查看系统状态。")
    pool_rows = [
        [entry["pool_type"], "、".join(entry.get("display_symbols", entry["symbols"])), str(entry["count"])]
        for entry in target_pool["entries"]
    ]
    return f"""
<section>
  <h2>市场状态</h2>
  <div class="grid-4">
    {_metric_card("市场评分", market["market_score"])}
    {_metric_card("风险等级", market["risk_level"])}
    {_metric_card("权益下限", _percent(market["equity_min"]))}
    {_metric_card("权益上限", _percent(market["equity_max"]))}
  </div>
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
  <h2>目标池</h2>
  {_table(["类型", "标的", "数量"], pool_rows)}
</section>
"""


def _risk_content(data: dict[str, Any]) -> str:
    risk = data["dashboard"]["risk"]
    if not risk["available"]:
        return _empty_section("风险状态", "风险状态暂不可用，请先查看系统状态。")
    warning_rows = [
        [item["code"], item["severity"], item["message"], item["source"]]
        for item in risk["warnings"]
    ]
    if not warning_rows:
        warning_rows = [["none", "low", "当前没有风险警告。", "risk_state"]]
    return f"""
<section>
  <h2>风险状态</h2>
  <div class="grid-4">
    {_metric_card("风险分数", risk["overall_risk_score"])}
    {_metric_card("风险等级", risk["risk_level"], _risk_class(risk["risk_level"]))}
    {_metric_card("暴露提示", _exposure_label(risk["exposure_warning"]))}
    {_metric_card("影子差距", f"{risk['shadow_vs_market_gap']} pp")}
  </div>
</section>
<section>
  <h2>风险警告</h2>
  {_table(["代码", "等级", "说明", "来源"], warning_rows)}
</section>
<section class="grid-3">
  {_metric_card("集中度风险", risk["concentration_risk"])}
  {_metric_card("研究偏离", risk["deviation_from_research"])}
  {_metric_card("暴露状态", _exposure_label(risk["exposure_warning"]))}
</section>
"""


def _macro_content(data: dict[str, Any]) -> str:
    macro = data["dashboard"]["macro"]
    if not macro["available"]:
        return _empty_section("宏观状态", "宏观状态暂不可用，请先查看系统状态。")
    snapshot = macro["macro_snapshot"]
    consensus = macro["model_consensus"]
    factors = macro["alpha_factor_decomposition"]["factors"]
    rows = [
        [item["factor"], item["contribution_score"], item["direction"], item["source"]]
        for item in factors
    ]
    if not rows:
        rows = [["none", "0", "neutral", "macro_state"]]
    return f"""
<section>
  <h2>宏观状态</h2>
  <div class="grid-4">
    {_metric_card("流动性", _percent(snapshot["liquidity_index"]))}
    {_metric_card("利率压力", _percent(snapshot["rate_pressure"]))}
    {_metric_card("通胀状态", snapshot["inflation_regime"])}
    {_metric_card("风险周期", snapshot["risk_cycle_state"])}
  </div>
</section>
<section>
  <h2>模型共识</h2>
  <div class="grid-4">
    {_metric_card("共识分数", consensus["consensus_score"])}
    {_metric_card("共识状态", consensus["consensus_state"])}
    {_metric_card("分歧", _percent(consensus["disagreement_score"]))}
    {_metric_card("置信度", _percent(consensus["calibrated_confidence"]))}
  </div>
</section>
<section>
  <h2>因子分解</h2>
  {_table(["因子", "贡献", "方向", "来源"], rows)}
</section>
"""


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
    return f"""
<section>
  <h2>今日决策预览</h2>
  <div class="grid-4">
    {_metric_card("建议", _endpoint_action_label(proposal["recommended_action"]))}
    {_metric_card("复核状态", _workflow_status_label(proposal["review_state"]))}
    {_metric_card("置信度", _percent(proposal["confidence"]))}
    {_metric_card("人工复核", _need_label(proposal["requires_human_review"]))}
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


def _portfolio_content(data: dict[str, Any]) -> str:
    portfolio = data["dashboard"]["portfolio"]
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
    return f"""
<section>
  <h2>影子组合状态</h2>
  <div class="grid-4">
    {_metric_card("净值指数", portfolio["nav_index"])}
    {_metric_card("权益比例", _percent(portfolio["equity_weight"]))}
    {_metric_card("目标范围", target)}
    {_metric_card("偏离", "暂无" if portfolio["deviation_pp"] is None else f"{portfolio['deviation_pp']} pp")}
  </div>
</section>
<section>
  <h2>持仓比例</h2>
  {_table(["标的", "比例", "分布"], rows, raw_columns={2})}
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
"""


def _research_content(data: dict[str, Any]) -> str:
    research = data["dashboard"]["research"]
    guidance = data["guidance"]
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
        [display_symbol(item["symbol"]), _research_reason_label(item["reason"]), item["source"]]
        for item in queue
    ]
    if not queue_rows:
        queue_rows = [["none", "当前没有 ResearchFirst 队列。", "guidance"]]
    return f"""
<section class="panel">
  <h2>研究入口</h2>
  <p><a href="/research/import/view">导入新的研究 JSON</a></p>
  <p class="detail">适合导入市场研究、主线研究或其它已校验研究快照。</p>
</section>
<section>
  <h2>最新研究快照</h2>
  {_table(["模块", "摘要", "置信度", "行动性", "下次复核"], rows)}
</section>
<section>
  <h2>ResearchFirst 队列</h2>
  {_table(["标的", "原因", "来源"], queue_rows)}
</section>
"""


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
    return f"""
<section>
  <h2>报告预览</h2>
  <div class="grid-4">
    {_metric_card("格式", "、".join(report["supported_formats"]))}
    {_metric_card("市场快照", manifest["market_snapshot_id"] or "暂无")}
    {_metric_card("组合快照", manifest["portfolio_id"] or "暂无")}
    {_metric_card("研究数量", len(manifest["research_snapshot_ids"]))}
  </div>
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
        ["POST /research/import/validate", "研究导入校验 JSON"],
        ["POST /research/import", "研究追加导入 JSON"],
        ["/decision/proposal", "决策预览 JSON"],
        ["/decision/explain", "决策解释 JSON"],
        ["/system/dashboard_state", "综合看板 JSON"],
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
        "/research/view": "研究队列",
        "/research/import/view": "研究导入",
        "/research/import/validate": "研究导入校验 JSON",
        "/research/import": "研究追加导入 JSON",
        "/research/latest": "研究 JSON",
        "/report/view": "报告预览",
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
