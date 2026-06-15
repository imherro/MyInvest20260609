from __future__ import annotations

import asyncio

import httpx

from invest_system.adapters import append_market_snapshot_from_adapters, build_p0c_price_data_from_bundle
from invest_system.comparison import compute_comparison_history, compute_comparison_state
from invest_system.golden import seed_multiday_repository
from invest_system.repositories import SQLiteRepository
from invest_system.research import generate_p0c_research
from invest_system.validators.schema_validator import validate_or_raise
from invest_system.web import create_app


def test_compute_comparison_state_is_schema_valid_and_read_only(tmp_path) -> None:
    repo = _prepare_comparison_repo(tmp_path)
    before_counts = repo.table_counts()

    comparison = compute_comparison_state(repo, "2026-06-15")

    assert comparison["status"] == "ok"
    validate_or_raise(comparison, "comparison_state.schema.json")
    assert comparison["source_ids"]["shadow_portfolio_id"] == "shadow-2026-06-15-decision-2026-06-15-golden"
    assert comparison["deviation_analysis"]["allocation_overlap"] >= 0
    assert comparison["curve"]
    assert repo.table_counts() == before_counts


def test_compute_comparison_history_returns_portfolio_timeline(tmp_path) -> None:
    repo = _prepare_comparison_repo(tmp_path)

    history = compute_comparison_history(repo)

    assert history["status"] == "ok"
    assert [item["as_of"] for item in history["data"]["items"]] == ["2026-06-13", "2026-06-14", "2026-06-15"]
    assert all("tracking_gap_pp" in item for item in history["data"]["items"])


def test_comparison_api_endpoints_return_json(tmp_path) -> None:
    repo = _prepare_comparison_repo(tmp_path)
    app = create_app(repo.db_path)

    state_response = _get(app, "/comparison/state?as_of=2026-06-15")
    history_response = _get(app, "/comparison/history")

    assert state_response.status_code == 200
    assert state_response.headers["content-type"].startswith("application/json")
    assert state_response.json()["data"]["status"] == "ok"
    assert history_response.status_code == 200
    assert history_response.headers["content-type"].startswith("application/json")
    assert history_response.json()["status"] == "ok"


def _prepare_comparison_repo(tmp_path) -> SQLiteRepository:
    repo = SQLiteRepository(tmp_path / "comparison.sqlite")
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
