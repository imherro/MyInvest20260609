from __future__ import annotations

import asyncio
from typing import Any

import httpx

from invest_system.adapters import append_market_snapshot_from_adapters, build_p0c_price_data_from_bundle
from invest_system.golden import seed_multiday_repository
from invest_system.repositories import SQLiteRepository
from invest_system.research import generate_p0c_research
from invest_system.web.dashboard import build_dashboard_state
from invest_system.web import create_app
from invest_system.web.symbol_display import display_symbol


FORBIDDEN_VIEW_TERMS = [
    "account_id",
    "total_asset",
    "market_value",
    "share_count",
    "available_quantity",
    "trade_amount",
    "profit_amount",
    "order_id",
    "fill_id",
    "local_path",
    "absolute_path",
    "<form",
    "下单",
    "委托",
]


def test_dashboard_state_endpoint_returns_json_without_sensitive_fields(tmp_path) -> None:
    db_path = _prepare_dashboard_db(tmp_path)
    app = create_app(db_path)

    response = _get(app, "/system/dashboard_state?as_of=2026-06-15")
    payload = response.json()

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert payload["status"] == "ok"
    assert payload["data"]["overview"]["self_check_status"] == "passed"
    assert payload["data"]["portfolio"]["available"] is True
    assert payload["data"]["portfolio"]["equity_weight"] == 0.75
    assert payload["data"]["portfolio"]["holdings"][0]["display_name"].endswith("（159915.SZ）")
    assert payload["data"]["portfolio"]["holdings"][0]["name"] != "159915.SZ"
    assert payload["data"]["portfolio_history"]["snapshot_count"] == 3
    assert payload["data"]["portfolio_history"]["rebalance_records"]
    assert payload["data"]["portfolio_history"]["rebalance_records"][0]["display_name"].endswith("）")
    assert payload["data"]["actual_vs_shadow"]["source_status"] == "actual_ratio_available"
    assert payload["data"]["actual_vs_shadow"]["qmt_read_status"]["status"] == "success"
    assert payload["data"]["actual_vs_shadow"]["qmt_read_status"]["next_action_label"] == "查看实际持仓与影子组合差异。"
    assert payload["data"]["daily_refresh"]["reference_date"] == "2026-06-15"
    assert payload["data"]["daily_refresh"]["all_done"] is True
    assert {item["item_id"] for item in payload["data"]["daily_refresh"]["items"]} == {"market", "research", "qmt"}
    assert all(item["status"] == "done" for item in payload["data"]["daily_refresh"]["items"])
    assert payload["data"]["actual_vs_shadow"]["actual_equity_weight"] == 0.75
    assert payload["data"]["actual_vs_shadow"]["shadow_equity_weight"] == 0.75
    assert "沪深300ETF华泰柏瑞（510300.SH）" in payload["data"]["target_pool"]["entries"][0]["display_symbols"]
    assert payload["data"]["research"]["available"] is True
    assert payload["data"]["risk"]["available"] is True
    assert payload["data"]["comparison"]["available"] is True
    assert payload["data"]["macro"]["available"] is True
    assert payload["data"]["report"]["available"] is True
    _assert_no_forbidden_terms(payload)


def test_researched_stock_symbols_have_human_readable_names() -> None:
    assert display_symbol("301566.SZ") == "达利凯普（301566.SZ）"
    assert display_symbol("688603.SH") == "天承科技（688603.SH）"


def test_dashboard_keeps_latest_research_by_symbol(tmp_path) -> None:
    repo = SQLiteRepository(tmp_path / "dashboard_symbol_research.sqlite")
    seed_multiday_repository(repo)
    repo.append_research_snapshot(_symbol_research("588000.SH", "observe"))
    repo.append_research_snapshot(_symbol_research("511360.SH", "observe"))

    state = build_dashboard_state(repo, "2026-06-15")
    ids = {item["snapshot_id"] for item in state["data"]["research"]["items"]}

    assert "etf-valuation-2026-06-15-588000.SH-observe-test" in ids
    assert "etf-valuation-2026-06-15-511360.SH-observe-test" in ids


def test_dashboard_view_pages_are_read_only_html(tmp_path) -> None:
    db_path = _prepare_dashboard_db(tmp_path)
    app = create_app(db_path)

    for path in [
        "/app",
        "/home_human",
        "/workflow/daily/view",
        "/guidance/view",
        "/dashboard",
        "/overview",
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
    ]:
        response = _get(app, f"{path}?as_of=2026-06-15")
        body = response.text
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")
        assert "MyInvest" in body
        assert "data-page-shell=\"portal\"" in body
        assert "统一页脚" in body
        assert "/app" in body
        assert "/guidance/view" in body
        if path == "/dashboard":
            assert "风险" in body
            assert "对比" in body
            assert "宏观" in body
        if path in {"/app", "/market/view"}:
            assert "处理方式" in body
            assert "长期估值分位数据不足" in body
            assert "valuation_metrics_limited" not in body
        if path in {"/app", "/overview"}:
            assert "去刷新市场快照" in body
            assert 'href="/market/view#market-refresh"' in body
        if path in {"/app", "/home_human"}:
            assert 'href="/portfolio/view"' in body
            assert 'href="/portfolio/state"' not in body
            assert 'href="/research/view"' in body
            assert 'href="/research/latest"' not in body
        if path == "/app":
            assert "今日刷新状态" in body
            assert "市场快照" in body
            assert "研究快照" in body
            assert "QMT 实际持仓" in body
            assert 'href="/market/view#market-refresh"' in body
            assert 'href="/research/import/view"' in body
            assert 'href="/portfolio/view#qmt-refresh"' in body
        if path == "/portfolio/view":
            assert "组合结论" in body
            assert "自动调仓依据" in body
            assert "怎么核对自动调仓" in body
            assert "怎么核对实际差异" in body
            assert "创业板ETF易方达（159915.SZ）" in body
            assert "沪深300ETF华泰柏瑞（510300.SH）" in body
            assert "短融ETF海富通（511360.SH）" in body
            assert "自动模型对照" in body
            assert "最近纸面变化" in body
            assert "QMT 读取状态" in body
            assert "查看实际持仓与影子组合差异。" in body
            assert "实际持仓 vs 影子组合" in body
            assert "刷新实际持仓" in body
            assert "/portfolio/qmt/refresh" in body
            assert "/portfolio/actual-vs-shadow" in body
            assert "每次纸面调仓记录" in body
            assert "历史组合快照" in body
            assert "/portfolio/history" in body
            assert "/timeline/replay?as_of=2026-06-15" in body
            assert ">159915.SZ<" not in body
        if path == "/market/view":
            assert "市场结论" in body
            assert "市场分数怎么读" in body
            assert "权益目标区间" in body
            assert "行动边界" in body
            assert "查看今日边界" in body
            assert "永赢中证500ETF（退市）（159999.SZ）" in body
            assert "科创50ETF华夏（588000.SH）" in body
            assert "刷新市场快照" in body
            assert "追加写入新的市场快照" in body
            assert 'id="market-refresh"' in body
            assert 'id="market-refresh-button"' in body
            assert "/market/refresh" in body
        if path == "/risk/view":
            assert "风险结论" in body
            assert "风险分数怎么读" in body
            assert "分数和警告的关系" in body
            assert "风险警告怎么读" in body
            assert "今日边界" in body
        if path == "/macro/view":
            assert "宏观结论" in body
            assert "共识分数是宏观周期、市场位置、组合匹配度和研究质量四类模型分数的平均" in body
            assert "因子贡献不是简单相加成共识分数" in body
            assert "共识分数来源" in body
            assert "中文含义" in body
            assert "流动性" in body
            assert "利率压力" in body
            assert "今日边界" in body
        if path == "/research/view":
            assert "研究工作台" in body
            assert "下一项该研究什么" in body
            assert "为什么还没放行" in body
            assert "放行规则" in body
            assert 'href="/research/import/view"' in body
            assert "永赢中证500ETF（退市）（159999.SZ）" in body
            assert "估值证据复核" in body
            assert "/research/valuation-review" in body
            assert "补充研究提示词" in body
            assert "/research/valuation-prompts" in body
        if path == "/decision/view":
            assert "决策结论" in body
            assert "决策依据链" in body
            assert "如何读标的预览" in body
            assert "怎样影响影子组合" in body
            assert "查看影子组合" in body
            assert "创业板ETF易方达（159915.SZ）" in body
        if path == "/report/view":
            assert "每日报告结论" in body
            assert "阅读顺序" in body
            assert "一页式摘要" in body
            assert "今日边界" in body
            assert "报告来源" in body
            assert "来源追溯" in body
        for forbidden in FORBIDDEN_VIEW_TERMS:
            assert forbidden not in body


def test_usability_state_describes_human_entrypoints(tmp_path) -> None:
    db_path = _prepare_dashboard_db(tmp_path)
    app = create_app(db_path)

    response = _get(app, "/usability/state?as_of=2026-06-15")
    payload = response.json()

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert payload["status"] == "ok"
    assert payload["data"]["primary_home"] == "/app"
    assert "/usability/view" in payload["data"]["feature_entrypoints"]
    assert all(item["status"] == "pass" for item in payload["data"]["checks"])
    _assert_no_forbidden_terms(payload)


def _prepare_dashboard_db(tmp_path) -> str:
    db_path = tmp_path / "dashboard.sqlite"
    repo = SQLiteRepository(db_path)
    seed_multiday_repository(repo)
    market_data = append_market_snapshot_from_adapters(repo, basis_date="2026-06-15", source="mock")
    generate_p0c_research(repo, "2026-06-15", price_data=build_p0c_price_data_from_bundle(market_data["bundle"]))
    return str(db_path)


def _symbol_research(symbol: str, actionability: str) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "snapshot_id": f"etf-valuation-2026-06-15-{symbol}-{actionability}-test",
        "basis_date": "2026-06-15",
        "generated_at": "2026-06-15T12:00:00Z",
        "module": "etf_valuation",
        "data_sources": ["fixture:research"],
        "data_gaps": [],
        "conflicts": [],
        "executive_summary": f"{symbol} profile gate passes, valuation gate passes, and liquidity gate passes.",
        "key_facts": [f"{symbol} profile gate passes."],
        "reasoning": ["Profile gate passes, valuation gate passes, and liquidity gate passes."],
        "risks": ["Fixture research can be superseded."],
        "conclusion_strength": "medium",
        "actionability": actionability,
        "confidence": 0.7,
        "invalidation_conditions": ["New evidence supersedes fixture research."],
        "next_review_date": "2026-06-16",
        "must_not_do": ["Do not use fixture research as external execution output."],
        "required_human_review": True,
        "status": "json_validated",
        "trace": {"fact_pack_id": f"fixture-{symbol}", "source_market_snapshot_id": "market-2026-06-15-golden"},
        "payload": {
            "symbol": symbol,
            "valuation_score": 50,
            "fair_value_band_pct": {"low": -0.01, "mid": 0, "high": 0.01},
            "observed_to_fair_value_ratio": 1,
            "deviation": 0,
            "risk_flag": "medium",
            "confidence": 0.7,
            "method": "fixture",
            "tracking_target": "fixture",
            "rating": "Fair",
        },
    }


def _assert_no_forbidden_terms(payload: Any) -> None:
    text = str(payload)
    for forbidden in FORBIDDEN_VIEW_TERMS:
        assert forbidden not in text


def _get(app, path: str) -> httpx.Response:
    return asyncio.run(_async_get(app, path))


async def _async_get(app, path: str) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.get(path)
