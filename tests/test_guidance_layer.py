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
    for forbidden in FORBIDDEN_TERMS:
        assert forbidden not in view_response.text


def _prepare_guidance_repo(tmp_path) -> SQLiteRepository:
    repo = SQLiteRepository(tmp_path / "guidance.sqlite")
    seed_multiday_repository(repo)
    market_data = append_market_snapshot_from_adapters(repo, basis_date="2026-06-15", source="mock")
    generate_p0c_research(repo, "2026-06-15", price_data=build_p0c_price_data_from_bundle(market_data["bundle"]))
    return repo


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
