from __future__ import annotations

from typing import Any


def describe_theme_research_impact(theme_snapshot: dict[str, Any] | None) -> dict[str, Any]:
    if theme_snapshot is None:
        return {
            "source_type": "missing",
            "source_label": "暂无主线快照",
            "program_data_contribution": 0.0,
            "llm_supplement_contribution": 0.0,
            "theme_display_impact": "unavailable",
            "decision_impact": "none",
            "position_weight_impact": 0.0,
            "score_role": "not_available",
            "notes": ["缺少 theme_research，先运行自动研究；自动数据不足时再补充大模型研究 JSON。"],
        }
    source_type = _theme_source_type(theme_snapshot)
    program_weight, llm_weight = _theme_contribution_weights(source_type)
    return {
        "source_type": source_type,
        "source_label": _theme_source_label(source_type),
        "program_data_contribution": program_weight,
        "llm_supplement_contribution": llm_weight,
        "theme_display_impact": "primary_theme_state_and_watchlist",
        "decision_impact": "theme_clarity_and_research_confidence_only",
        "position_weight_impact": 0.0,
        "score_role": "auxiliary_non_decision",
        "notes": [
            "主线快照影响主线展示、首页引导和研究平均置信度。",
            "主线快照不生成标的、不决定仓位，不能绕过 ResearchFirst 和风险边界。",
            "大模型补充只用于政策、产业链、事件解释等非结构化证据。",
        ],
    }


def describe_llm_supplement_need(theme_snapshot: dict[str, Any] | None) -> dict[str, Any]:
    if theme_snapshot is None:
        return _llm_need(
            "required",
            "missing_theme_snapshot",
            "缺少主线快照。先运行自动研究；若仍无结构化主题证据，再补充大模型研究 JSON。",
        )
    payload = theme_snapshot.get("payload", {})
    theme_state = payload.get("theme_state")
    confidence = float(theme_snapshot.get("confidence", 0))
    data_gaps = theme_snapshot.get("data_gaps", [])
    if theme_state in {"weakening", "exhausted"}:
        return _llm_need(
            "recommended",
            "weak_theme_state",
            "主线状态偏弱，适合补充政策、产业链和事件解释，但不能直接影响标的或仓位。",
        )
    if confidence < 0.55 or len(data_gaps) >= 3:
        return _llm_need(
            "recommended",
            "insufficient_theme_evidence",
            "自动数据证据不足，建议补充大模型主线研究 JSON。",
        )
    return _llm_need(
        "not_required",
        "automatic_theme_available",
        "自动主线快照可用；大模型不是今日必需步骤。",
    )


def _theme_source_type(theme_snapshot: dict[str, Any]) -> str:
    sources = " ".join(str(item).lower() for item in theme_snapshot.get("data_sources", []))
    trace = theme_snapshot.get("trace", {})
    fact_pack = str(trace.get("fact_pack_id", "")).lower()
    has_program = any(
        token in sources or token in fact_pack
        for token in ("tushare", "baostock", "yfinance", "fred", "p0c", "adapter", "mainline-theme")
    )
    has_llm = any(token in sources or token in fact_pack for token in ("llm", "chatgpt", "manual", "import"))
    if has_program and has_llm:
        return "mixed"
    if has_llm:
        return "llm_supplement"
    if has_program:
        return "program_auto"
    return "program_auto"


def _theme_contribution_weights(source_type: str) -> tuple[float, float]:
    if source_type == "mixed":
        return 0.8, 0.2
    if source_type == "llm_supplement":
        return 0.0, 1.0
    if source_type == "program_auto":
        return 1.0, 0.0
    return 0.0, 0.0


def _theme_source_label(source_type: str) -> str:
    return {
        "program_auto": "程序自动主线快照",
        "llm_supplement": "大模型补充主线快照",
        "mixed": "程序数据 + 大模型补充",
        "missing": "暂无主线快照",
    }.get(source_type, "程序自动主线快照")


def _llm_need(status: str, reason_code: str, reason: str) -> dict[str, Any]:
    return {
        "status": status,
        "reason_code": reason_code,
        "reason": reason,
        "allowed_contribution": [
            "政策和产业链解释",
            "主题逻辑和领先指标补充",
            "风险、失效条件和数据缺口说明",
        ],
        "forbidden_contribution": [
            "股票代码或代表性标的",
            "买卖建议",
            "仓位建议",
            "绕过 ResearchFirst 的行动结论",
        ],
    }
