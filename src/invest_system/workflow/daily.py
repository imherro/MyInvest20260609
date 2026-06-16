from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from invest_system.decision import build_decision_proposal
from invest_system.guidance import compute_guidance_state
from invest_system.repositories import SQLiteRepository
from invest_system.validators.policies import assert_no_sensitive_content
from invest_system.web.dashboard import build_dashboard_state


def build_daily_workflow_state(repo: SQLiteRepository, as_of: str | None = None) -> dict[str, Any]:
    repo.init_db()
    replay = repo.replay_state(as_of)
    timeline = repo.timeline(as_of)
    dashboard = build_dashboard_state(repo, as_of)["data"]
    guidance = compute_guidance_state(repo, as_of)
    decision_proposal = build_decision_proposal(repo, as_of)
    reference_date = _reference_date(as_of, replay, timeline)
    latest_mainline = _latest_research_by_module(timeline, "theme_research")
    steps = [
        _market_step(replay.get("market"), reference_date),
        _mainline_step(latest_mainline, reference_date),
        _guidance_step(guidance),
        _decision_step(decision_proposal),
        _portfolio_step(replay.get("portfolio"), replay.get("decision"), reference_date),
        _report_step(dashboard["report"]),
    ]
    primary = _primary_next_action(steps)
    state = {
        "schema_version": "1.0",
        "status": _overall_status(steps),
        "as_of": as_of,
        "reference_date": reference_date,
        "generated_at": _utc_now(),
        "primary_next_action": primary,
        "decision_preview": {
            "recommended_action": decision_proposal["recommended_action"],
            "review_state": decision_proposal["review_state"],
            "confidence": decision_proposal["confidence"],
            "endpoint": "/decision/proposal",
        },
        "steps": steps,
        "source_ids": _source_ids(replay, latest_mainline),
        "safe_operations": [
            "只读查看每日工作流状态",
            "追加导入已校验的研究 JSON",
            "查看今日行动边界",
            "查看影子组合回放",
        ],
        "blocked_operations": [
            "不要从每日工作流直接生成外部执行",
            "不要绕过 ResearchFirst 创建单标的行动",
            "不要覆盖历史快照",
        ],
    }
    assert_no_sensitive_content(state)
    return state


def _market_step(market: dict[str, Any] | None, reference_date: str | None) -> dict[str, Any]:
    if market is None:
        return _step(
            "market_snapshot",
            "市场数据",
            "missing",
            "缺少市场快照，先执行市场数据采集或导入。",
            "/market/view",
            "/market/latest",
        )
    if reference_date and market["basis_date"] < reference_date:
        return _step(
            "market_snapshot",
            "市场数据",
            "warn",
            "市场快照早于当前参考日期，需要复核。",
            "/market/view",
            "/market/latest",
            market["basis_date"],
        )
    return _step(
        "market_snapshot",
        "市场数据",
        "pass",
        "市场快照已进入系统。",
        "/market/view",
        "/market/latest",
        market["basis_date"],
        market["snapshot_id"],
    )


def _mainline_step(research: dict[str, Any] | None, reference_date: str | None) -> dict[str, Any]:
    if research is None:
        return _step(
            "mainline_research",
            "主线研究",
            "missing",
            "缺少 theme_research 主线研究，先生成或导入主线研究 JSON。",
            "/research/import/view",
            "/research/import/validate",
        )
    if reference_date and research["basis_date"] < reference_date:
        return _step(
            "mainline_research",
            "主线研究",
            "warn",
            "主线研究早于当前参考日期，需要更新或复核。",
            "/research/import/view",
            "/research/latest",
            research["basis_date"],
            research["snapshot_id"],
        )
    return _step(
        "mainline_research",
        "主线研究",
        "pass",
        "主线研究已进入系统；主题层只展示状态和领先指标，不下钻股票代码。",
        "/research/view",
        "/research/latest",
        research["basis_date"],
        research["snapshot_id"],
    )


def _guidance_step(guidance: dict[str, Any]) -> dict[str, Any]:
    readiness = guidance["readiness"]["overall_state"]
    if readiness == "blocked":
        status = "block"
        detail = "今日行动边界处于阻断状态，先处理阻断项。"
    elif readiness == "review_required":
        status = "warn"
        detail = "今日行动边界需要复核，暂不提高风险。"
    elif readiness == "ready":
        status = "pass"
        detail = "今日行动边界可进入只读复核。"
    else:
        status = "missing"
        detail = "今日行动边界缺少可用回放状态。"
    return _step("guidance_boundary", "今日行动边界", status, detail, "/guidance/view", "/guidance/state")


def _decision_step(proposal: dict[str, Any]) -> dict[str, Any]:
    if proposal["status"] == "empty":
        status = "missing"
        detail = "缺少可解释决策草案来源，先补齐研究、风险和组合状态。"
    elif proposal["review_state"] == "blocked":
        status = "block"
        detail = f"今日决策预览为 {proposal['recommended_action']}，但门槛仍有阻断。"
    elif proposal["review_state"] == "review_required":
        status = "warn"
        detail = f"今日决策预览为 {proposal['recommended_action']}，需要人工复核。"
    else:
        status = "pass"
        detail = f"今日决策预览为 {proposal['recommended_action']}，可进入解释链查看。"
    return _step(
        "decision_proposal",
        "决策预览",
        status,
        detail,
        "/decision/view",
        "/decision/proposal",
        proposal["basis_date"],
        proposal["proposal_id"],
    )


def _portfolio_step(
    portfolio: dict[str, Any] | None,
    decision: dict[str, Any] | None,
    reference_date: str | None,
) -> dict[str, Any]:
    if portfolio is None:
        return _step(
            "shadow_portfolio",
            "影子组合",
            "missing",
            "缺少影子组合快照，无法完成今日回放闭环。",
            "/portfolio/view",
            "/portfolio/state",
        )
    if decision is None or not portfolio.get("source_decision_id"):
        return _step(
            "shadow_portfolio",
            "影子组合",
            "warn",
            "影子组合存在，但决策来源需要复核。",
            "/portfolio/view",
            "/portfolio/state",
            portfolio["basis_date"],
            portfolio["portfolio_id"],
        )
    if reference_date and portfolio["basis_date"] < reference_date:
        return _step(
            "shadow_portfolio",
            "影子组合",
            "warn",
            "影子组合早于当前参考日期，需要回放复核。",
            "/portfolio/view",
            "/portfolio/state",
            portfolio["basis_date"],
            portfolio["portfolio_id"],
        )
    return _step(
        "shadow_portfolio",
        "影子组合",
        "pass",
        "影子组合回放链路可用。",
        "/portfolio/view",
        "/portfolio/state",
        portfolio["basis_date"],
        portfolio["portfolio_id"],
    )


def _report_step(report: dict[str, Any]) -> dict[str, Any]:
    if not report["available"]:
        return _step(
            "report_preview",
            "报告预览",
            "missing",
            "缺少可用报告来源，先补齐市场、研究、决策或组合。",
            "/report/view",
            "/system/dashboard_state",
        )
    return _step(
        "report_preview",
        "报告预览",
        "pass",
        "报告预览可用，可继续追溯来源编号。",
        "/report/view",
        "/system/dashboard_state",
    )


def _step(
    step_id: str,
    title: str,
    status: str,
    detail: str,
    view_endpoint: str,
    json_endpoint: str,
    basis_date: str | None = None,
    source_id: str | None = None,
) -> dict[str, Any]:
    return {
        "step_id": step_id,
        "title": title,
        "status": status,
        "detail": detail,
        "view_endpoint": view_endpoint,
        "json_endpoint": json_endpoint,
        "basis_date": basis_date,
        "source_id": source_id,
    }


def _primary_next_action(steps: list[dict[str, Any]]) -> dict[str, Any]:
    for status in ("block", "missing", "warn"):
        for step in steps:
            if step["status"] == status:
                return {
                    "step_id": step["step_id"],
                    "label": step["title"],
                    "status": step["status"],
                    "reason": step["detail"],
                    "endpoint": step["view_endpoint"],
                }
    return {
        "step_id": "guidance_boundary",
        "label": "今日行动边界",
        "status": "pass",
        "reason": "每日工作流闭环已就绪，先从今日行动边界进入复核。",
        "endpoint": "/guidance/view",
    }


def _overall_status(steps: list[dict[str, Any]]) -> str:
    statuses = [step["status"] for step in steps]
    if "block" in statuses or "missing" in statuses:
        return "action_required"
    if "warn" in statuses:
        return "review_required"
    return "ready"


def _source_ids(replay: dict[str, Any], mainline: dict[str, Any] | None) -> dict[str, Any]:
    market = replay.get("market")
    decision = replay.get("decision")
    portfolio = replay.get("portfolio")
    return {
        "market_snapshot_id": market.get("snapshot_id") if market else None,
        "mainline_research_snapshot_id": mainline.get("snapshot_id") if mainline else None,
        "decision_id": decision.get("decision_id") if decision else None,
        "portfolio_id": portfolio.get("portfolio_id") if portfolio else None,
    }


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


def _latest_research_by_module(timeline: list[dict[str, Any]], module: str) -> dict[str, Any] | None:
    latest = None
    for event in timeline:
        if event["type"] != "research":
            continue
        payload = event["payload"]
        if payload.get("module") == module:
            latest = payload
    return latest


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
