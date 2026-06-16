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
        "/workflow/daily/state",
        "/guidance/state",
        "/usability/state",
        "/research/latest",
        "/market/latest",
        "/target-pool/latest",
        "/decision/latest",
        "/decision/proposal",
        "/decision/explain",
        "/portfolio/state",
        "/portfolio/history",
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
    assert _get(app, "/").json()["data"]["primary_human_entry"] == "/app"


def test_market_refresh_endpoint_appends_snapshot_as_json(tmp_path) -> None:
    db_path = tmp_path / "api.sqlite"
    repo = SQLiteRepository(db_path)
    seed_demo_repository(repo)
    before_counts = repo.table_counts()
    app = create_app(db_path)

    response = _post(app, "/market/refresh?basis_date=2026-06-16&source=mock&allow_network=false")
    payload = response.json()
    after_counts = repo.table_counts()

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert payload["status"] == "ok"
    assert payload["data"]["market_snapshot_id"] == "market-2026-06-16-mock-adapter"
    assert payload["data"]["auto_shadow"]["status"] in {"applied", "skipped"}
    assert after_counts["market_snapshot"] == before_counts["market_snapshot"] + 1
    if payload["data"]["auto_shadow"]["status"] == "applied":
        assert after_counts["decision_record"] == before_counts["decision_record"] + 1
        assert after_counts["portfolio_snapshot"] == before_counts["portfolio_snapshot"] + 1
        assert after_counts["event_log"] == before_counts["event_log"] + 3
    else:
        assert after_counts["event_log"] == before_counts["event_log"] + 1


def test_market_refresh_endpoint_returns_json_on_invalid_source(tmp_path) -> None:
    db_path = tmp_path / "api.sqlite"
    seed_demo_repository(SQLiteRepository(db_path))
    app = create_app(db_path)

    response = _post(app, "/market/refresh?basis_date=2026-06-16&source=bad_source&allow_network=false")
    payload = response.json()

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert payload["status"] == "failed"
    assert payload["data"]["reason"] == "invalid_market_refresh_request"


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


def test_portfolio_history_endpoint_returns_snapshots_and_rebalances(tmp_path) -> None:
    db_path = tmp_path / "api.sqlite"
    seed_demo_repository(SQLiteRepository(db_path))
    app = create_app(db_path)

    response = _get(app, "/portfolio/history")
    data = response.json()["data"]

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert data["snapshot_count"] == 1
    assert data["snapshots"][0]["portfolio_id"] == "shadow-2026-06-15-decision-2026-06-15-demo"
    assert data["snapshots"][0]["source_decision_id"] == "decision-2026-06-15-demo"
    assert data["json_replay_endpoint"] == "/timeline/replay"


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


def _post(app, path: str) -> httpx.Response:
    return asyncio.run(_async_post(app, path))


async def _async_get(app, path: str) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.get(path)


async def _async_post(app, path: str) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.post(path)
