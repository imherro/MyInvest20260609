from __future__ import annotations

import asyncio
from typing import Any

import httpx

from invest_system.adapters import append_market_snapshot_from_adapters, build_p0c_price_data_from_bundle
from invest_system.entry import build_home_state
from invest_system.golden import seed_multiday_repository
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


def test_home_state_is_schema_valid_and_read_only(tmp_path) -> None:
    repo = _prepare_entry_repo(tmp_path)
    before_counts = repo.table_counts()

    state = build_home_state(repo, "2026-06-15")

    assert state["status"] == "ok"
    validate_or_raise(state, "entry_home_state.schema.json")
    assert state["cards"]["market_status"]["overall_market_state"] in {"balanced", "constructive", "defensive"}
    assert state["cards"]["main_theme"]["current_theme"] == "adapter_market_breadth"
    assert state["next_action"]["recommended_endpoint"].startswith("/")
    assert state["navigation_plan"]["steps"][0]["endpoint"] == "/home"
    assert repo.table_counts() == before_counts
    _assert_no_forbidden_terms(state)


def test_home_and_entry_api_return_json(tmp_path) -> None:
    repo = _prepare_entry_repo(tmp_path)
    app = create_app(repo.db_path)

    home_response = _get(app, "/home?as_of=2026-06-15")
    entry_response = _get(app, "/entry/home_state?as_of=2026-06-15")

    assert home_response.status_code == 200
    assert home_response.headers["content-type"].startswith("application/json")
    assert home_response.json()["data"]["next_action"]["reasoning"]
    assert entry_response.status_code == 200
    assert entry_response.headers["content-type"].startswith("application/json")
    assert entry_response.json()["data"]["navigation_plan"]["shortcuts"]


def test_next_action_endpoint_is_followable(tmp_path) -> None:
    repo = _prepare_entry_repo(tmp_path)
    app = create_app(repo.db_path)
    home = _get(app, "/home?as_of=2026-06-15").json()["data"]

    response = _get(app, f"{home['next_action']['recommended_endpoint']}?as_of=2026-06-15")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["status"] in {"ok", "empty"}


def _prepare_entry_repo(tmp_path) -> SQLiteRepository:
    repo = SQLiteRepository(tmp_path / "entry.sqlite")
    seed_multiday_repository(repo)
    market_data = append_market_snapshot_from_adapters(repo, basis_date="2026-06-15", source="mock")
    generate_p0c_research(repo, "2026-06-15", price_data=build_p0c_price_data_from_bundle(market_data["bundle"]))
    return repo


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
