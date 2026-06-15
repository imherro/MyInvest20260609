from __future__ import annotations

import asyncio

import httpx

from invest_system.adapters import append_market_snapshot_from_adapters, build_p0c_price_data_from_bundle
from invest_system.golden import seed_multiday_repository
from invest_system.repositories import SQLiteRepository
from invest_system.research import generate_p0c_research
from invest_system.risk import compute_risk_history, compute_risk_state
from invest_system.validators.schema_validator import validate_or_raise
from invest_system.web import create_app


def test_compute_risk_state_is_schema_valid_and_read_only(tmp_path) -> None:
    repo = _prepare_risk_repo(tmp_path)
    before_counts = repo.table_counts()

    risk_state = compute_risk_state(repo, "2026-06-15")

    assert risk_state["status"] == "ok"
    validate_or_raise(risk_state, "risk_state.schema.json")
    assert risk_state["overall_risk_score"] >= 0
    assert risk_state["source_ids"]["portfolio_id"] == "shadow-2026-06-15-decision-2026-06-15-golden"
    assert repo.table_counts() == before_counts


def test_compute_risk_history_uses_existing_portfolio_dates(tmp_path) -> None:
    repo = _prepare_risk_repo(tmp_path)

    history = compute_risk_history(repo)

    assert history["status"] == "ok"
    assert [item["as_of"] for item in history["data"]["items"]] == ["2026-06-13", "2026-06-14", "2026-06-15"]
    assert all(item["portfolio_id"] for item in history["data"]["items"])


def test_risk_api_endpoints_return_json(tmp_path) -> None:
    repo = _prepare_risk_repo(tmp_path)
    app = create_app(repo.db_path)

    state_response = _get(app, "/risk/state?as_of=2026-06-15")
    history_response = _get(app, "/risk/history")

    assert state_response.status_code == 200
    assert state_response.headers["content-type"].startswith("application/json")
    assert state_response.json()["data"]["status"] == "ok"
    assert history_response.status_code == 200
    assert history_response.headers["content-type"].startswith("application/json")
    assert history_response.json()["status"] == "ok"


def _prepare_risk_repo(tmp_path) -> SQLiteRepository:
    repo = SQLiteRepository(tmp_path / "risk.sqlite")
    seed_multiday_repository(repo)
    market_data = append_market_snapshot_from_adapters(repo, basis_date="2026-06-15", source="mock")
    generate_p0c_research(repo, "2026-06-15", price_data=build_p0c_price_data_from_bundle(market_data["bundle"]))
    return repo


def _get(app, path: str) -> httpx.Response:
    return asyncio.run(_async_get(app, path))


async def _async_get(app, path: str) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.get(path)
