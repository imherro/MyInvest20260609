from __future__ import annotations

import html
from typing import Any

from invest_system.validators.policies import assert_no_sensitive_content


STATUS_LABELS = {
    "ready": "可以进入只读复核",
    "review_required": "需要先复核",
    "blocked": "暂时阻断",
    "empty": "暂无可用状态",
    "pass": "通过",
    "warn": "需关注",
    "block": "阻断",
    "missing": "缺失",
    "allowed": "允许",
    "review_required_operation": "需复核",
}

OPERATION_LABELS = {
    "portfolio_review": "查看组合",
    "increase_risk": "提高风险",
    "new_subject_review": "新增标的",
    "external_execution": "外部执行",
}

STEP_LABELS = {
    "policy_config": "确认风控边界",
    "data_freshness": "更新每日数据",
    "research_first": "补齐研究",
    "risk_boundaries": "查看风险",
    "paper_only": "确认纸面模拟边界",
    "replay_available": "检查回放链路",
    "portfolio_review": "查看组合",
}


def render_guidance_page(state: dict[str, Any]) -> str:
    page = _page_shell(state)
    assert_no_sensitive_content(page)
    return page


def _page_shell(state: dict[str, Any]) -> str:
    readiness = state["readiness"]
    content = (
        _hero(state)
        + _operation_section(state["today_action"]["allowed_operations"])
        + _next_steps_section(state["today_action"]["next_required_steps"])
        + _risk_boundary_section(state["risk_boundaries"])
        + _research_first_section(state["research_first"])
        + _freshness_section(state["data_freshness"])
        + _do_not_do_section(state["today_action"]["do_not_do"])
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>MyInvest 今日行动边界</title>
  <style>
    :root {{ color-scheme: light; --ink:#1f2933; --muted:#5f6b7a; --line:#d6dde6; --bg:#f5f7fa; --panel:#ffffff; --accent:#0f766e; --soft:#d7f0ed; --warn:#9a5b00; --bad:#a61b1b; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; background:var(--bg); color:var(--ink); font:15px/1.55 Arial, "Microsoft YaHei", sans-serif; }}
    header {{ background:#fff; border-bottom:1px solid var(--line); }}
    .wrap {{ max-width:1120px; margin:0 auto; padding:18px 20px; }}
    .top {{ display:flex; justify-content:space-between; gap:16px; align-items:center; }}
    main {{ max-width:1120px; margin:0 auto; padding:20px 20px 40px; }}
    h1 {{ margin:0; font-size:24px; letter-spacing:0; }}
    h2 {{ margin:0 0 12px; font-size:18px; letter-spacing:0; }}
    h3 {{ margin:0 0 8px; font-size:16px; letter-spacing:0; }}
    p {{ margin:0; }}
    a {{ color:#0f5f58; text-decoration:none; }}
    a:hover {{ text-decoration:underline; }}
    section {{ margin:0 0 18px; }}
    .eyebrow {{ color:var(--muted); font-size:13px; }}
    .panel {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:16px; min-width:0; }}
    .hero {{ display:grid; grid-template-columns:2fr 1fr; gap:14px; }}
    .summary {{ background:var(--soft); border-color:#9ccfca; }}
    .value {{ font-size:22px; font-weight:700; overflow-wrap:anywhere; }}
    .detail {{ color:var(--muted); margin-top:8px; }}
    .grid {{ display:grid; grid-template-columns:repeat(4, minmax(0,1fr)); gap:12px; }}
    .stack {{ display:grid; gap:10px; }}
    .row {{ display:flex; flex-wrap:wrap; gap:8px; align-items:center; }}
    .badge {{ border:1px solid var(--line); border-radius:6px; padding:5px 8px; background:#fff; color:var(--muted); font-size:13px; }}
    .pass {{ color:var(--accent); font-weight:700; }}
    .warn {{ color:var(--warn); font-weight:700; }}
    .block, .missing {{ color:var(--bad); font-weight:700; }}
    table {{ width:100%; border-collapse:collapse; background:#fff; border:1px solid var(--line); }}
    th, td {{ padding:9px 10px; text-align:left; border-bottom:1px solid var(--line); vertical-align:top; overflow-wrap:anywhere; }}
    th {{ color:#344054; background:#eef2f6; font-weight:700; }}
    @media (max-width:820px) {{ .hero {{ grid-template-columns:1fr; }} .grid {{ grid-template-columns:repeat(2, minmax(0,1fr)); }} .top {{ align-items:flex-start; flex-direction:column; }} }}
    @media (max-width:520px) {{ .grid {{ grid-template-columns:1fr; }} .wrap, main {{ padding-left:12px; padding-right:12px; }} h1 {{ font-size:22px; }} }}
  </style>
</head>
<body>
  <header>
    <div class="wrap top">
      <div>
        <div class="eyebrow">MyInvest Guidance</div>
        <h1>今日行动边界</h1>
      </div>
      <div class="eyebrow">状态：{html.escape(_state_label(readiness["overall_state"]))}</div>
    </div>
  </header>
  <main>{content}</main>
</body>
</html>
"""


def _hero(state: dict[str, Any]) -> str:
    readiness = state["readiness"]
    action = state["today_action"]
    policy = state["policy"]
    return f"""
<section class="hero">
  <div class="panel summary">
    <h2>今天先做什么</h2>
    <p class="value">{html.escape(action["headline"])}</p>
    <p class="detail">这不是外部执行指令，只是基于当前 JSON 和回放状态生成的只读行动边界。</p>
  </div>
  <div class="panel">
    <h2>当前边界</h2>
    <div class="stack">
      <p>提高风险：<span class="{_bool_class(readiness["can_increase_risk"])}">{_yes_no(readiness["can_increase_risk"])}</span></p>
      <p>新增标的：<span class="{_bool_class(readiness["can_add_new_subject"])}">{_yes_no(readiness["can_add_new_subject"])}</span></p>
      <p>人工复核：<span class="{_bool_class(not readiness["requires_human_review"])}">{_need_label(readiness["requires_human_review"])}</span></p>
      <p class="detail">策略配置：{html.escape(policy["profile_id"])} / {html.escape(policy["configuration_status"])}</p>
    </div>
  </div>
</section>
"""


def _operation_section(operations: list[dict[str, Any]]) -> str:
    rows = "".join(
        "<tr>"
        f"<td>{html.escape(OPERATION_LABELS.get(item['operation'], item['operation']))}</td>"
        f"<td class=\"{html.escape(_operation_class(item['status']))}\">{html.escape(_operation_status(item['status']))}</td>"
        f"<td>{html.escape(item['reason'])}</td>"
        f"<td>{_endpoint(item['endpoint'])}</td>"
        "</tr>"
        for item in operations
    )
    return f"""
<section>
  <h2>今天能不能做</h2>
  <table><thead><tr><th>事项</th><th>结果</th><th>原因</th><th>入口</th></tr></thead><tbody>{rows}</tbody></table>
</section>
"""


def _next_steps_section(steps: list[dict[str, Any]]) -> str:
    cards = "".join(
        "<div class=\"panel\">"
        f"<h3>{html.escape(STEP_LABELS.get(item['step'], item['step']))}</h3>"
        f"<p>{html.escape(item['reason'])}</p>"
        f"<p class=\"detail\"><a href=\"{html.escape(item['endpoint'])}\">{html.escape(item['endpoint'])}</a></p>"
        "</div>"
        for item in steps
    )
    return f"""
<section>
  <h2>下一步</h2>
  <div class="grid">{cards}</div>
</section>
"""


def _risk_boundary_section(risk_boundaries: dict[str, Any]) -> str:
    rows = "".join(
        "<tr>"
        f"<td>{html.escape(_boundary_label(item['name']))}</td>"
        f"<td class=\"{html.escape(item['status'])}\">{html.escape(_status_label(item['status']))}</td>"
        f"<td>{html.escape(_value(item['current']))}</td>"
        f"<td>{html.escape(_value(item['limit']))}</td>"
        f"<td>{html.escape(item['detail'])}</td>"
        "</tr>"
        for item in risk_boundaries["items"]
    )
    return f"""
<section>
  <h2>个人风控边界</h2>
  <table><thead><tr><th>项目</th><th>状态</th><th>当前</th><th>边界</th><th>说明</th></tr></thead><tbody>{rows}</tbody></table>
</section>
"""


def _research_first_section(research_first: dict[str, Any]) -> str:
    if not research_first["queue"] and not research_first["active_holdings_without_passed_gates"]:
        body = "<p>ResearchFirst 覆盖通过，当前没有阻断队列。</p>"
    else:
        rows = "".join(
            "<tr>"
            f"<td>{html.escape(item['symbol'])}</td>"
            f"<td>{html.escape(_research_reason_label(item['reason']))}</td>"
            f"<td>{html.escape(item['source'])}</td>"
            "</tr>"
            for item in research_first["queue"]
        )
        if not rows:
            rows = "<tr><td>none</td><td>active holding gate review required</td><td>decision_record</td></tr>"
        body = f"<table><thead><tr><th>标的</th><th>原因</th><th>来源</th></tr></thead><tbody>{rows}</tbody></table>"
    return f"""
<section class="panel">
  <h2>ResearchFirst 覆盖</h2>
  {body}
</section>
"""


def _freshness_section(freshness: dict[str, Any]) -> str:
    rows = "".join(
        "<tr>"
        f"<td>{html.escape(item['name'])}</td>"
        f"<td class=\"{html.escape(item['status'])}\">{html.escape(_status_label(item['status']))}</td>"
        f"<td>{html.escape(str(item['basis_date'] or 'missing'))}</td>"
        f"<td>{html.escape(str(item['age_days'] if item['age_days'] is not None else 'missing'))}</td>"
        f"<td>{html.escape(item['detail'])}</td>"
        "</tr>"
        for item in freshness["items"]
    )
    return f"""
<section>
  <h2>每日数据新鲜度</h2>
  <table><thead><tr><th>数据</th><th>状态</th><th>日期</th><th>天数</th><th>说明</th></tr></thead><tbody>{rows}</tbody></table>
</section>
"""


def _do_not_do_section(items: list[str]) -> str:
    rows = "".join(f"<li>{html.escape(item)}</li>" for item in items)
    return f"""
<section class="panel">
  <h2>今天不要做</h2>
  <ul>{rows}</ul>
</section>
"""


def _endpoint(endpoint: str | None) -> str:
    if endpoint is None:
        return "无"
    return f"<a href=\"{html.escape(endpoint)}\">{html.escape(endpoint)}</a>"


def _state_label(status: str) -> str:
    return STATUS_LABELS.get(status, status)


def _status_label(status: str) -> str:
    return STATUS_LABELS.get(status, status)


def _operation_status(status: str) -> str:
    if status == "review_required":
        return "需复核"
    return STATUS_LABELS.get(status, status)


def _operation_class(status: str) -> str:
    if status == "review_required":
        return "warn"
    if status == "allowed":
        return "pass"
    return "block"


def _boundary_label(name: str) -> str:
    return {
        "overall_risk_score": "风险分数",
        "equity_weight": "权益比例",
        "cash_weight": "现金比例",
        "single_holding_weight": "单项比例",
        "drawdown": "回撤",
        "portfolio": "组合",
    }.get(name, name)


def _research_reason_label(reason: str) -> str:
    return {
        "profile_or_gate_incomplete": "画像或门槛未完成",
        "blocked_in_target_pool": "目标池阻断",
        "decision_requires_research_first": "决策要求先研究",
        "research_first_required": "需要先研究",
        "profile_missing": "画像缺失",
    }.get(reason, reason)


def _value(value: float | None) -> str:
    if value is None:
        return "暂无"
    if -1 <= value <= 1:
        return f"{value * 100:.2f}%"
    return f"{value:.2f}"


def _yes_no(value: bool) -> str:
    return "可以" if value else "不可以"


def _need_label(value: bool) -> str:
    return "需要" if value else "不需要"


def _bool_class(value: bool) -> str:
    return "pass" if value else "block"
