from __future__ import annotations

import asyncio

import httpx

from invest_system.demo import seed_demo_repository
from invest_system.repositories import SQLiteRepository
from invest_system.web import create_app


def test_required_api_endpoints_return_json(tmp_path) -> None:
    db_path = tmp_path / "api.sqlite"
    seed_demo_repository(SQLiteRepository(db_path))
    app = create_app(db_path)

    for path in [
        "/",
        "/home",
        "/entry/home_state",
        "/research/latest",
        "/market/latest",
        "/target-pool/latest",
        "/decision/latest",
        "/portfolio/state",
        "/timeline/replay",
        "/comparison/state",
        "/comparison/history",
        "/macro/state",
        "/macro/history",
        "/model/consensus",
        "/risk/state",
        "/risk/history",
        "/system/dashboard_state",
        "/system/status",
    ]:
        response = _get(app, path)
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/json")
        assert response.json()["status"] == "ok"

    assert _get(app, "/").json()["data"]["json_only"] is True


def test_fastapi_html_docs_are_disabled(tmp_path) -> None:
    app = create_app(tmp_path / "api.sqlite")

    response = _get(app, "/docs")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")


def test_timeline_replay_contains_trace(tmp_path) -> None:
    db_path = tmp_path / "api.sqlite"
    seed_demo_repository(SQLiteRepository(db_path))
    app = create_app(db_path)

    response = _get(app, "/timeline/replay")
    data = response.json()["data"]

    assert data["state"]["portfolio"]["source_decision_id"] == "decision-2026-06-15-demo"
    assert data["state"]["portfolio"]["source_target_pool_id"] == "target-pool-2026-06-15-demo"
    assert data["state"]["trace"]["source_market_snapshot_id"] == "market-2026-06-15-demo"
    assert data["state"]["trace"]["source_research_snapshot_ids"] == ["research-2026-06-15-demo"]
    assert [event["type"] for event in data["events"]] == ["market", "research", "target_pool", "decision", "portfolio"]


def test_system_status_reports_self_check(tmp_path) -> None:
    db_path = tmp_path / "api.sqlite"
    seed_demo_repository(SQLiteRepository(db_path))
    app = create_app(db_path)

    response = _get(app, "/system/status")
    data = response.json()["data"]

    assert data["record_counts"]["target_pool_snapshot"] == 1
    assert data["self_check"]["status"] == "passed"
    assert data["self_check"]["replay_confidence_score"] == 1.0
    assert data["latest_event_timestamp"] is not None
    assert data["replay_available"] is True


def _get(app, path: str) -> httpx.Response:
    return asyncio.run(_async_get(app, path))


async def _async_get(app, path: str) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.get(path)
