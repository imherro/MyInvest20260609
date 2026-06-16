from __future__ import annotations

import html
from typing import Any

from invest_system.validators.policies import assert_no_sensitive_content


ENDPOINT_LABELS = {
    "/home": "首页状态",
    "/market/latest": "市场状态",
    "/research/latest": "研究结论",
    "/portfolio/state": "组合状态",
    "/risk/state": "风险状态",
    "/macro/state": "宏观状态",
    "/comparison/state": "对比分析",
    "/system/dashboard_state": "完整看板",
    "/guidance/view": "今日行动边界",
}

STEP_LABELS = {
    "Home": "首页",
    "Market": "市场",
    "Research": "研究",
    "Portfolio": "组合",
    "Report": "报告",
    "Risk": "风险",
    "Comparison": "对比",
    "Macro": "宏观",
}

PATH_LABELS = {
    "normal_market": "正常市场路径",
    "high_risk": "高风险路径",
    "volatile_market": "波动市场路径",
}

REFERENCE_PATHS = [
    ("正常市场", ["/market/latest", "/research/latest", "/portfolio/state", "/system/dashboard_state"], "先确认市场和研究，再看组合与报告。"),
    ("高风险", ["/risk/state", "/portfolio/state", "/comparison/state"], "先确认风险来源，再看组合暴露和对比差距。"),
    ("波动市场", ["/macro/state", "/risk/state", "/comparison/state"], "先确认宏观压力，再判断风险和表现差异。"),
]


def build_human_entry_model(home_state: dict[str, Any]) -> dict[str, Any]:
    cards = home_state["cards"]
    next_action = home_state["next_action"]
    navigation_plan = home_state["navigation_plan"]
    model = {
        "as_of": home_state.get("as_of") or "latest",
        "generated_at": home_state["generated_at"],
        "market": _market_interpretation(cards["market_status"]),
        "theme": _theme_interpretation(cards["main_theme"]),
        "risk": _risk_interpretation(cards["risk_snapshot"]),
        "portfolio": _portfolio_interpretation(cards["portfolio_summary"]),
        "next_action": _next_action_interpretation(next_action),
        "active_path": _active_path_interpretation(navigation_plan),
        "reference_paths": _reference_paths(),
    }
    assert_no_sensitive_content(model)
    return model


def render_home_human_page(home_state: dict[str, Any]) -> str:
    model = build_human_entry_model(home_state)
    page = _page_shell(model)
    assert_no_sensitive_content(page)
    return page


def _market_interpretation(card: dict[str, Any]) -> dict[str, Any]:
    state = card["overall_market_state"]
    labels = {
        "constructive": ("偏积极", "市场评分和风险状态支持继续观察组合表现，但仍要保留风险边界。"),
        "balanced": ("均衡", "市场没有给出明显单边信号，适合按系统路径逐项确认。"),
        "defensive": ("偏防御", "市场风险信号偏强，先看风险和宏观，再看组合。"),
        "unavailable": ("暂无足够数据", "当前缺少市场状态，先查看研究或系统状态。"),
    }
    title, explanation = labels.get(state, ("需要确认", "系统暂时无法给出明确市场判断。"))
    return {
        "title": title,
        "detail": explanation,
        "liquidity": _percent(card["liquidity_index"]),
        "risk_label": _risk_label(card["risk_level"]),
    }


def _theme_interpretation(card: dict[str, Any]) -> dict[str, Any]:
    theme = card["current_theme"] or "暂未形成清晰主线"
    clarity = card["clarity_state"]
    clarity_text = {
        "strong": "主线清晰，可以继续核对研究结论。",
        "medium": "主线存在，但还需要结合风险状态确认。",
        "weak": "主线偏弱，先回到研究结论。",
        "unavailable": "研究主线不足，先查看最新研究。",
    }.get(clarity, "主线状态需要确认。")
    leaders = card.get("leading_symbols") or []
    return {
        "title": theme,
        "detail": clarity_text,
        "strength": "暂无" if card.get("strength_score") is None else f"{card['strength_score']:.0f}/100",
        "leaders": "、".join(leaders) if leaders else "暂无",
    }


def _risk_interpretation(card: dict[str, Any]) -> dict[str, Any]:
    risk_level = card["risk_level"]
    detail = {
        "low": "风险信号暂时平稳，可以继续看组合状态。",
        "medium": "风险处在需要关注的区间，先确认风险来源。",
        "high": "风险已经偏高，先看风险模块，不要跳过风险确认。",
        "unknown": "风险状态不足，先查看系统状态或风险模块。",
    }.get(risk_level, "风险状态需要确认。")
    return {
        "title": _risk_label(risk_level),
        "detail": detail,
        "score": f"{card['overall_risk_score']:.0f}/100",
        "exposure": _exposure_label(card["exposure_warning"]),
    }


def _portfolio_interpretation(card: dict[str, Any]) -> dict[str, Any]:
    shadow_return = float(card["shadow_return"])
    benchmark_return = float(card["benchmark_return"])
    gap = shadow_return - benchmark_return
    if gap > 0.005:
        title = "影子组合暂时领先基准"
        detail = "组合表现好于基准，下一步仍要检查风险是否同步上升。"
    elif gap < -0.005:
        title = "影子组合暂时落后基准"
        detail = "组合表现弱于基准，下一步需要看对比分析和风险来源。"
    else:
        title = "影子组合与基准基本持平"
        detail = "当前没有明显超额表现，适合按系统建议继续核对。"
    return {
        "title": title,
        "detail": detail,
        "shadow_return": _signed_percent(shadow_return),
        "benchmark_return": _signed_percent(benchmark_return),
        "drawdown": _signed_percent(float(card["drawdown"])),
    }


def _next_action_interpretation(action: dict[str, Any]) -> dict[str, Any]:
    endpoint = action["recommended_endpoint"]
    reason_code = action["reason_code"]
    reason = {
        "high_risk": "系统检测到风险分数或风险等级偏高，需要先确认风险来源。",
        "volatile_macro": "宏观周期进入偏谨慎状态，需要先看宏观压力。",
        "liquidity_watch": "流动性指标低于正常区间，需要先确认宏观环境。",
        "weak_theme_clarity": "当前主题清晰度不足，需要先回到研究结论。",
        "tracking_gap": "影子组合与基准的差距扩大，需要先看对比分析。",
        "portfolio_exposure_review": "组合暴露偏离目标中枢，需要先看组合状态。",
        "stable_market": "主要信号没有触发高优先级风险，可以先看组合状态。",
    }.get(reason_code, "系统建议先查看下一步模块。")
    return {
        "label": ENDPOINT_LABELS.get(endpoint, endpoint),
        "endpoint": endpoint,
        "priority": _priority_label(action["priority"]),
        "reason": reason,
    }


def _active_path_interpretation(navigation_plan: dict[str, Any]) -> dict[str, Any]:
    path_id = navigation_plan["path_id"]
    steps = [
        {
            "label": STEP_LABELS.get(step["label"], step["label"]),
            "endpoint": step["endpoint"],
            "view": ENDPOINT_LABELS.get(step["endpoint"], step["endpoint"]),
        }
        for step in navigation_plan["steps"]
    ]
    return {
        "title": PATH_LABELS.get(path_id, "当前路径"),
        "steps": steps,
    }


def _reference_paths() -> list[dict[str, Any]]:
    return [
        {
            "title": title,
            "steps": [ENDPOINT_LABELS[endpoint] for endpoint in endpoints],
            "detail": detail,
        }
        for title, endpoints, detail in REFERENCE_PATHS
    ]


def _page_shell(model: dict[str, Any]) -> str:
    content = (
        _hero(model)
        + _status_grid(model)
        + _guidance_entry_section()
        + _next_action_section(model["next_action"])
        + _navigation_section(model["active_path"], model["reference_paths"])
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>MyInvest 人类可读首页</title>
  <style>
    :root {{ color-scheme: light; --ink:#1f2933; --muted:#5f6b7a; --line:#d6dde6; --bg:#f5f7fa; --panel:#ffffff; --accent:#0f766e; --accent-soft:#d7f0ed; --warn:#9a5b00; --bad:#a61b1b; }}
    * {{ box-sizing: border-box; }}
    body {{ margin:0; background:var(--bg); color:var(--ink); font:15px/1.55 Arial, "Microsoft YaHei", sans-serif; }}
    header {{ background:#ffffff; border-bottom:1px solid var(--line); }}
    .wrap {{ max-width:1120px; margin:0 auto; padding:18px 20px; }}
    .top {{ display:flex; justify-content:space-between; gap:16px; align-items:center; }}
    .eyebrow {{ color:var(--muted); font-size:13px; }}
    h1 {{ margin:0; font-size:24px; letter-spacing:0; }}
    h2 {{ margin:0 0 12px; font-size:18px; letter-spacing:0; }}
    h3 {{ margin:0 0 8px; font-size:16px; letter-spacing:0; }}
    p {{ margin:0; }}
    a {{ color:#0f5f58; text-decoration:none; }}
    a:hover {{ text-decoration:underline; }}
    main {{ max-width:1120px; margin:0 auto; padding:20px 20px 40px; }}
    section {{ margin:0 0 18px; }}
    .hero {{ display:grid; grid-template-columns:2fr 1fr; gap:14px; align-items:stretch; }}
    .panel {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:16px; min-width:0; }}
    .summary {{ background:var(--accent-soft); border-color:#9ccfca; }}
    .grid {{ display:grid; grid-template-columns:repeat(4, minmax(0, 1fr)); gap:12px; }}
    .card-title {{ color:var(--muted); font-size:13px; margin-bottom:5px; }}
    .value {{ font-size:20px; font-weight:700; overflow-wrap:anywhere; }}
    .detail {{ color:var(--muted); margin-top:8px; }}
    .metric-row {{ display:flex; flex-wrap:wrap; gap:8px; margin-top:12px; }}
    .metric {{ border:1px solid var(--line); border-radius:6px; padding:5px 8px; background:#fff; color:var(--muted); font-size:13px; }}
    .action {{ border-left:5px solid var(--accent); }}
    .path {{ display:flex; flex-wrap:wrap; gap:8px; align-items:center; }}
    .step {{ border:1px solid var(--line); border-radius:6px; padding:7px 10px; background:#fff; }}
    .arrow {{ color:var(--muted); }}
    .reference {{ display:grid; grid-template-columns:repeat(3, minmax(0, 1fr)); gap:12px; }}
    .warn {{ color:var(--warn); font-weight:700; }}
    .bad {{ color:var(--bad); font-weight:700; }}
    @media (max-width:820px) {{ .hero {{ grid-template-columns:1fr; }} .grid {{ grid-template-columns:repeat(2, minmax(0, 1fr)); }} .reference {{ grid-template-columns:1fr; }} .top {{ align-items:flex-start; flex-direction:column; }} }}
    @media (max-width:520px) {{ .grid {{ grid-template-columns:1fr; }} .wrap, main {{ padding-left:12px; padding-right:12px; }} h1 {{ font-size:22px; }} }}
  </style>
</head>
<body>
  <header>
    <div class="wrap top">
      <div>
        <div class="eyebrow">MyInvest Human Entry</div>
        <h1>今日系统状态</h1>
      </div>
      <div class="eyebrow">日期：{html.escape(str(model["as_of"]))}</div>
    </div>
  </header>
  <main>{content}</main>
</body>
</html>
"""


def _hero(model: dict[str, Any]) -> str:
    market = model["market"]
    next_action = model["next_action"]
    return f"""
<section class="hero">
  <div class="panel summary">
    <h2>现在先看什么</h2>
    <p class="value">{html.escape(next_action["label"])}</p>
    <p class="detail">{html.escape(next_action["reason"])}</p>
  </div>
  <div class="panel">
    <h2>市场状态</h2>
    <p class="value">{html.escape(market["title"])}</p>
    <p class="detail">{html.escape(market["detail"])}</p>
  </div>
</section>
"""


def _status_grid(model: dict[str, Any]) -> str:
    market = model["market"]
    theme = model["theme"]
    risk = model["risk"]
    portfolio = model["portfolio"]
    return f"""
<section>
  <h2>四个重点</h2>
  <div class="grid">
    {_status_card("市场", market["title"], market["detail"], [f"流动性 {market['liquidity']}", f"风险 {market['risk_label']}"])}
    {_status_card("当前主线", theme["title"], theme["detail"], [f"强度 {theme['strength']}", f"代表标的 {theme['leaders']}"])}
    {_status_card("风险", risk["title"], risk["detail"], [f"分数 {risk['score']}", f"暴露 {risk['exposure']}"])}
    {_status_card("影子组合", portfolio["title"], portfolio["detail"], [f"影子 {portfolio['shadow_return']}", f"基准 {portfolio['benchmark_return']}", f"回撤 {portfolio['drawdown']}"])}
  </div>
</section>
"""


def _next_action_section(next_action: dict[str, Any]) -> str:
    return f"""
<section class="panel action">
  <h2>下一步建议</h2>
  <p>建议下一步：<a href="{html.escape(next_action["endpoint"])}">{html.escape(next_action["label"])}</a></p>
  <p class="detail">原因：{html.escape(next_action["reason"])}</p>
  <p class="detail">优先级：{html.escape(next_action["priority"])}</p>
</section>
"""


def _guidance_entry_section() -> str:
    return """
<section class="panel action">
  <h2>今天能不能动</h2>
  <p>先打开：<a href="/guidance/view">今日行动边界</a></p>
  <p class="detail">这里会检查个人风控边界、数据新鲜度、ResearchFirst 覆盖和只读行动限制。</p>
</section>
"""


def _navigation_section(active_path: dict[str, Any], reference_paths: list[dict[str, Any]]) -> str:
    active_steps = _linked_steps(active_path["steps"])
    references = "".join(_reference_path(path) for path in reference_paths)
    return f"""
<section>
  <h2>导航路径</h2>
  <div class="panel">
    <h3>{html.escape(active_path["title"])}</h3>
    <div class="path">{active_steps}</div>
  </div>
</section>
<section>
  <h2>三种常见路径</h2>
  <div class="reference">{references}</div>
</section>
"""


def _status_card(title: str, value: str, detail: str, metrics: list[str]) -> str:
    metric_html = "".join(f"<span class=\"metric\">{html.escape(metric)}</span>" for metric in metrics)
    return f"""
<div class="panel">
  <div class="card-title">{html.escape(title)}</div>
  <div class="value">{html.escape(value)}</div>
  <p class="detail">{html.escape(detail)}</p>
  <div class="metric-row">{metric_html}</div>
</div>
"""


def _linked_steps(steps: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for index, step in enumerate(steps):
        if index:
            parts.append("<span class=\"arrow\">→</span>")
        parts.append(
            "<a class=\"step\" "
            f"href=\"{html.escape(step['endpoint'])}\" "
            f"title=\"{html.escape(step['view'])}\">"
            f"{html.escape(step['label'])}</a>"
        )
    return "".join(parts)


def _reference_path(path: dict[str, Any]) -> str:
    steps = " → ".join(path["steps"])
    return f"""
<div class="panel">
  <h3>{html.escape(path["title"])}</h3>
  <p>{html.escape(steps)}</p>
  <p class="detail">{html.escape(path["detail"])}</p>
</div>
"""


def _risk_label(value: str) -> str:
    return {
        "low": "低",
        "medium": "中等",
        "high": "高",
        "unknown": "未知",
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


def _priority_label(value: str) -> str:
    return {
        "low": "低",
        "medium": "中等",
        "high": "高",
    }.get(value, value)


def _percent(value: float | int) -> str:
    return f"{float(value) * 100:.2f}%"


def _signed_percent(value: float | int) -> str:
    return f"{float(value) * 100:+.2f}%"
