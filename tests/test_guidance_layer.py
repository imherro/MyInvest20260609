from __future__ import annotations

import asyncio
from typing import Any

import httpx

from invest_system.adapters import append_market_snapshot_from_adapters, build_p0c_price_data_from_bundle
from invest_system.golden import seed_multiday_repository
from invest_system.guidance import compute_guidance_state
from invest_system.repositories import SQLiteRepository
from invest_system.research import generate_p0c_research
from invest_system.validators.schema_validator import validate_or_raise
from invest_system.web import create_app


FORBIDDEN_TERMS = [
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


def test_guidance_state_is_schema_valid_and_read_only(tmp_path) -> None:
    repo = _prepare_guidance_repo(tmp_path)
    before_counts = repo.table_counts()

    state = compute_guidance_state(repo, "2026-06-15")

    validate_or_raise(state, "guidance_state.schema.json")
    assert state["status"] == "ok"
    assert state["readiness"]["overall_state"] in {"ready", "review_required", "blocked"}
    assert state["readiness"]["can_increase_risk"] is False
    assert state["today_action"]["allowed_operations"]
    assert _operation_status(state, "external_execution") == "blocked"
    assert state["research_first"]["queue"]
    assert repo.table_counts() == before_counts
    _assert_no_forbidden_terms(state)


def test_guidance_api_and_view_are_stable(tmp_path) -> None:
    repo = _prepare_guidance_repo(tmp_path)
    app = create_app(repo.db_path)

    state_response = _get(app, "/guidance/state?as_of=2026-06-15")
    view_response = _get(app, "/guidance/view?as_of=2026-06-15")

    assert state_response.status_code == 200
    assert state_response.headers["content-type"].startswith("application/json")
    assert state_response.json()["status"] == "ok"
    assert state_response.json()["data"]["today_action"]["headline"]
    assert view_response.status_code == 200
    assert view_response.headers["content-type"].startswith("text/html")
    assert "今日行动边界" in view_response.text
    assert "提高风险" in view_response.text
    assert "新增标的" in view_response.text
    assert "ResearchFirst" in view_response.text
    assert 'href="/risk/view"' in view_response.text
    assert 'href="/research/view"' in view_response.text
    assert '&lt;a href="/risk/view"' not in view_response.text
    assert '&lt;a href="/research/view"' not in view_response.text
    assert 'href="/risk/state"' not in view_response.text
    assert 'href="/research/latest"' not in view_response.text
    for forbidden in FORBIDDEN_TERMS:
        assert forbidden not in view_response.text


def test_latest_symbol_research_can_clear_historical_research_first_item(tmp_path) -> None:
    repo = SQLiteRepository(tmp_path / "guidance_clear.sqlite")
    seed_multiday_repository(repo)
    repo.append_research_snapshot(_symbol_research("159999.SZ", "no_action", "finalized"))

    state = compute_guidance_state(repo, "2026-06-15")
    queued_symbols = {item["symbol"] for item in state["research_first"]["queue"]}

    assert "159999.SZ" in queued_symbols

    cleaned_pool = repo.latest_target_pool("2026-06-15")
    cleaned_pool["target_pool_id"] = "target-pool-2026-06-15-clean-test"
    for entry in cleaned_pool["entries"]:
        entry["symbols"] = [symbol for symbol in entry["symbols"] if symbol != "159999.SZ"]
    repo.append_target_pool_snapshot(cleaned_pool)
    cleaned_decision = repo.latest_decision("2026-06-15")
    cleaned_decision["decision_id"] = "decision-2026-06-15-clean-test"
    cleaned_decision["decision_actions"] = [
        action for action in cleaned_decision["decision_actions"] if action["symbol"] != "159999.SZ"
    ]
    repo.append_decision_record(cleaned_decision)

    state = compute_guidance_state(repo, "2026-06-15")
    queued_symbols = {item["symbol"] for item in state["research_first"]["queue"]}

    assert "159999.SZ" not in queued_symbols


def test_research_first_queue_reports_current_blockers(tmp_path) -> None:
    repo = SQLiteRepository(tmp_path / "guidance_blockers.sqlite")
    seed_multiday_repository(repo)
    snapshot = _symbol_research("301566.SZ", "research_first", "blocked")
    snapshot["snapshot_id"] = "stock-valuation-2026-06-15-301566.SZ-blocked-test"
    snapshot["executive_summary"] = (
        "301566.SZ profile and liquidity gates pass, but valuation gate fails; "
        "ResearchFirst remains required."
    )
    snapshot["reasoning"] = [
        "Profile gate passes.",
        "Liquidity gate passes.",
        "Valuation gate fails because peer pressure remains high.",
    ]
    snapshot["data_gaps"] = ["Forward earnings forecast is unavailable in the local structured source."]
    repo.append_research_snapshot(snapshot)
    app = create_app(repo.db_path)

    state = compute_guidance_state(repo, "2026-06-15")
    queued = next(item for item in state["research_first"]["queue"] if item["symbol"] == "301566.SZ")
    view_response = _get(app, "/research/view?as_of=2026-06-15")
    review_response = _get(app, "/research/valuation-review?as_of=2026-06-15")
    prompt_response = _get(app, "/research/valuation-prompts?as_of=2026-06-15")
    review = review_response.json()["data"]
    prompts = prompt_response.json()["data"]

    assert "valuation_gate_failed" in queued["blockers"]
    assert "data_gap" in queued["blockers"]
    assert "当前卡点" in view_response.text
    assert "估值门槛未通过" in view_response.text
    assert "估值证据复核" in view_response.text
    assert "缺少可放行的估值分位" in view_response.text
    assert "补充研究提示词" in view_response.text
    assert "只输出一个合法 JSON 对象" in view_response.text
    assert '<details class="prompt-details">' in view_response.text
    assert '<textarea class="prompt-textarea" readonly rows="6">' in view_response.text
    assert "复制提示词" in view_response.text
    assert review_response.status_code == 200
    assert review_response.headers["content-type"].startswith("application/json")
    assert review["status"] == "review_required"
    assert any(item["symbol"] == "301566.SZ" for item in review["rows"])
    assert "缺少可放行的估值分位" in review["rows"][0]["missing_evidence"][0]
    assert prompt_response.status_code == 200
    assert prompt_response.headers["content-type"].startswith("application/json")
    assert prompts["status"] == "ready"
    assert any(item["symbol"] == "301566.SZ" for item in prompts["prompts"])
    prompt = next(item for item in prompts["prompts"] if item["symbol"] == "301566.SZ")
    assert "达利凯普（301566.SZ）" in prompt["prompt_text"]
    assert "research_snapshot JSON" in prompt["prompt_text"]


def _prepare_guidance_repo(tmp_path) -> SQLiteRepository:
    repo = SQLiteRepository(tmp_path / "guidance.sqlite")
    seed_multiday_repository(repo)
    market_data = append_market_snapshot_from_adapters(repo, basis_date="2026-06-15", source="mock")
    generate_p0c_research(repo, "2026-06-15", price_data=build_p0c_price_data_from_bundle(market_data["bundle"]))
    return repo


def _symbol_research(symbol: str, actionability: str, status: str) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "snapshot_id": f"etf-valuation-2026-06-15-{symbol}-{actionability}-test",
        "basis_date": "2026-06-15",
        "generated_at": "2026-06-15T12:00:00Z",
        "module": "etf_valuation",
        "data_sources": ["fixture:research"],
        "data_gaps": [],
        "conflicts": [],
        "executive_summary": f"{symbol} has been removed from the current target-pool review queue.",
        "key_facts": [f"{symbol} is not a current target-pool candidate."],
        "reasoning": ["Current-only review clears this historical ResearchFirst item."],
        "risks": ["A future active-instrument review can supersede this cleanup snapshot."],
        "conclusion_strength": "medium",
        "actionability": actionability,
        "confidence": 0.7,
        "invalidation_conditions": ["A later target-pool snapshot reintroduces the symbol."],
        "next_review_date": "2026-06-16",
        "must_not_do": ["Do not use fixture research as external execution output."],
        "required_human_review": True,
        "status": status,
        "trace": {"fact_pack_id": f"fixture-{symbol}", "source_market_snapshot_id": "market-2026-06-15-golden"},
        "payload": {
            "symbol": symbol,
            "valuation_score": 0,
            "fair_value_band_pct": {"low": 0, "mid": 0, "high": 0},
            "observed_to_fair_value_ratio": 0,
            "deviation": 0,
            "risk_flag": "high",
            "confidence": 0.7,
            "method": "current_only_cleanup",
            "tracking_target": "not_current_candidate",
            "rating": "Watch",
        },
    }


def _operation_status(state: dict[str, Any], operation: str) -> str:
    for item in state["today_action"]["allowed_operations"]:
        if item["operation"] == operation:
            return item["status"]
    raise AssertionError(f"operation not found: {operation}")


def _assert_no_forbidden_terms(payload: Any) -> None:
    text = str(payload)
    for forbidden in FORBIDDEN_TERMS:
        assert forbidden not in text


def _get(app, path: str) -> httpx.Response:
    return asyncio.run(_async_get(app, path))


async def _async_get(app, path: str) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.get(path)
