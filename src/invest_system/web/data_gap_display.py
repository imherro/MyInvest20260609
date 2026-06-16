from __future__ import annotations

from typing import Any


def describe_data_gap(gap: str) -> dict[str, str]:
    code = gap.split(":", 1)[0]
    detail = gap.split(":", 1)[1] if ":" in gap else ""

    if gap.startswith("fred:missing_FRED_API_KEY"):
        return _description(
            "FRED 宏观密钥未被当前进程读取",
            "美国利率等宏观序列不能进入当日市场判断。",
            "确认本地 .env 有 FRED_API_KEY，并重新采集市场数据。",
        )
    if gap.startswith("fred:no_observation"):
        return _description(
            "FRED 当日没有已发布观测值",
            "宏观利率数据存在发布时间滞后，不能按当天完整数据使用。",
            "使用最近一个已发布日期，或等待 FRED 发布后重新采集。",
        )
    if gap.startswith("fred:network_disabled"):
        return _description(
            "FRED 网络采集未开启",
            "宏观序列不会联网更新，只能保留缺口说明。",
            "执行市场采集时开启网络数据源。",
        )
    if gap.startswith("fred:fred_request_failed"):
        return _description(
            "FRED 请求失败",
            "宏观序列暂时不可用，系统会降低置信度。",
            "稍后重试，或检查本机网络与 FRED 服务可用性。",
        )
    if gap.startswith("macro_policy_limited"):
        return _description(
            "宏观/政策结构化数据不足",
            "市场判断缺少成体系的宏观和政策输入。",
            "接入 FRED、政策日历或导入宏观研究 JSON。",
        )
    if gap.startswith("valuation_metrics_limited") or gap.startswith("Long-horizon valuation percentile"):
        return _description(
            "长期估值分位数据不足",
            "估值只能用溢价折价、跟踪指数和相对位置代理，结论更保守。",
            "补充长期估值分位数据；没有数据时继续保留该披露。",
        )
    if gap.startswith("ETF portfolio constituents"):
        return _description(
            "ETF 持仓成分不是实时完整数据",
            "只能使用最新披露持仓，不能当作实时底层资产穿透。",
            "等待基金披露更新；需要更细时接入基金公司或交易所清单数据。",
        )
    if gap.startswith("Intraday spread") or gap.startswith("intraday_and_after_close"):
        return _description(
            "盘中价差和收盘确认不足",
            "流动性、折溢价和成交质量不能做实时确认。",
            "接入 QMT/实时行情，或收盘后重新刷新。",
        )
    if gap.startswith("live_data_adapter_not_connected"):
        return _description(
            "实时数据源未连接",
            "系统不能使用实时行情或本地终端确认，只能按已有快照判断。",
            "开启网络采集；如需要 QMT 实时确认，先打开并登录本地 QMT。",
        )
    if gap.startswith("same_day_complete_data_unavailable"):
        basis = detail or "当日"
        return _description(
            "当日完整数据尚不可用",
            f"{basis} 的完整日线或收盘后数据还不能确认。",
            "使用最近一个完整交易日；收盘后再采集一次。",
        )
    if gap.startswith("representative_symbol_profile_valuation_liquidity_gates_not_completed"):
        return _description(
            "主题层旧下钻缺口",
            "旧主题研究曾包含标的下钻信息；新合同下该信息不再影响全局 readiness。",
            "改用目标池、ResearchFirst 队列和标的研究页处理具体标的。",
        )
    if gap.startswith("tushare:missing_TUSHARE_TOKEN"):
        return _description(
            "Tushare 密钥未被当前进程读取",
            "A 股结构化数据不能更新。",
            "确认本地 .env 有 TUSHARE_TOKEN，并重新采集市场数据。",
        )
    if code in {"tushare", "baostock", "yfinance"}:
        return _description(
            f"{code} 数据源缺口",
            "对应结构化数据源没有提供完整记录。",
            "检查数据源可用性；必要时用其它来源交叉验证或保留披露。",
        )
    return _description(
        "未归类数据缺口",
        "系统保留该缺口用于追溯，相关结论会更保守。",
        "复核对应研究快照；必要时补充结构化数据或人工研究 JSON。",
    )


def unique_data_gap_descriptions(gaps: list[str]) -> list[dict[str, Any]]:
    descriptions = []
    seen = set()
    for gap in gaps:
        description = describe_data_gap(gap)
        key = (description["title"], description["impact"], description["next_step"])
        if key in seen:
            continue
        seen.add(key)
        descriptions.append(description)
    return descriptions


def _description(title: str, impact: str, next_step: str) -> dict[str, str]:
    return {"title": title, "impact": impact, "next_step": next_step}
