from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from invest_system.adapters import append_market_snapshot_from_adapters, build_p0c_price_data_from_bundle
from invest_system.decision import build_decision_proposal
from invest_system.repositories import SQLiteRepository
from invest_system.research import generate_p0c_research
from invest_system.research.theme_impact import describe_llm_supplement_need, describe_theme_research_impact
from invest_system.self_check import run_self_check
from invest_system.shadow import run_auto_shadow_portfolio
from invest_system.validators.policies import assert_no_sensitive_content


def run_daily_auto_research(
    repo: SQLiteRepository,
    *,
    basis_date: str,
    source: str = "auto",
    allow_network: bool = True,
) -> dict[str, Any]:
    repo.init_db()
    market_result = append_market_snapshot_from_adapters(
        repo,
        basis_date=basis_date,
        source=source,
        allow_network=allow_network,
    )
    price_data = build_p0c_price_data_from_bundle(market_result["bundle"])
    research_result = generate_p0c_research(repo, basis_date, price_data=price_data)
    auto_shadow = run_auto_shadow_portfolio(
        repo,
        trigger="daily_auto_research",
        as_of=basis_date,
        market_returns=_market_returns_from_bundle(market_result["bundle"]),
        benchmark_returns=_benchmark_returns_from_bundle(market_result["bundle"]),
    )
    decision_proposal = build_decision_proposal(repo, basis_date)
    self_check = run_self_check(repo.db_path, basis_date, current_only=True)
    theme_snapshot = _latest_theme_snapshot(repo, basis_date)
    theme_impact = describe_theme_research_impact(theme_snapshot)
    result = {
        "schema_version": "1.0",
        "status": "ok" if self_check["status"] == "passed" else "failed",
        "basis_date": basis_date,
        "generated_at": _utc_now(),
        "mode": "automatic_baseline",
        "stages": [
            _stage(
                "market_data",
                "采集市场数据",
                "program_rule",
                "ok",
                "程序从只读数据源采集行情、指数、成交和流动性数据。",
                market_result.get("market_snapshot_id"),
            ),
            _stage(
                "market_snapshot",
                "生成市场快照",
                "program_rule",
                "ok",
                "程序把市场数据写成 append-only market_snapshot。",
                market_result.get("market_snapshot_id"),
            ),
            _stage(
                "theme_snapshot",
                "生成自动主线快照",
                "program_rule",
                "ok",
                "程序按行业强弱、动量、流动性和宽度生成基础 theme_research。",
                theme_snapshot.get("snapshot_id") if theme_snapshot else None,
            ),
            _stage(
                "decision_proposal",
                "更新决策建议",
                "program_rule",
                "ok" if decision_proposal["status"] == "ok" else "skipped",
                "程序按 ResearchFirst、风险边界、宏观、目标池和持仓比例生成只读建议。",
                decision_proposal.get("proposal_id"),
            ),
            _stage(
                "shadow_portfolio",
                "更新影子组合",
                "program_rule",
                auto_shadow["status"],
                "程序只更新纸面组合；不写 QMT，不产生真实委托。",
                auto_shadow.get("portfolio_id"),
            ),
            _stage(
                "self_check",
                "系统自检",
                "program_rule",
                self_check["status"],
                "程序检查 JSON、schema、ResearchFirst、回放和一致性。",
                None,
            ),
        ],
        "market": {
            "snapshot_id": market_result.get("market_snapshot_id"),
            "source": source,
            "allow_network": allow_network,
        },
        "research": {
            "inserted": research_result["inserted"],
            "theme_impact": theme_impact,
        },
        "decision": {
            "proposal_id": decision_proposal.get("proposal_id"),
            "recommended_action": decision_proposal.get("recommended_action"),
            "review_state": decision_proposal.get("review_state"),
            "confidence": decision_proposal.get("confidence"),
        },
        "auto_shadow": auto_shadow,
        "llm_supplement": describe_llm_supplement_need(theme_snapshot),
        "self_check": self_check,
    }
    assert_no_sensitive_content(result)
    return result


def _latest_theme_snapshot(repo: SQLiteRepository, basis_date: str) -> dict[str, Any] | None:
    latest: dict[str, Any] | None = None
    for event in repo.timeline(basis_date):
        if event["type"] == "research" and event["payload"].get("module") == "theme_research":
            latest = event["payload"]
    return latest


def _stage(
    step_id: str,
    label: str,
    actor: str,
    status: str,
    detail: str,
    object_id: str | None,
) -> dict[str, Any]:
    return {
        "step_id": step_id,
        "label": label,
        "actor": actor,
        "status": status,
        "detail": detail,
        "object_id": object_id,
    }


def _market_returns_from_bundle(bundle: dict[str, Any]) -> dict[str, float]:
    returns: dict[str, float] = {}
    for item in bundle.get("symbols", []):
        symbol = item.get("symbol")
        if symbol:
            returns[str(symbol)] = float(item.get("daily_return", 0))
    return returns


def _benchmark_returns_from_bundle(bundle: dict[str, Any]) -> dict[str, float]:
    returns: dict[str, float] = {}
    for item in bundle.get("indices", []):
        name = item.get("name") or item.get("symbol")
        if name:
            returns[str(name)] = float(item.get("daily_return", 0))
    return returns


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
