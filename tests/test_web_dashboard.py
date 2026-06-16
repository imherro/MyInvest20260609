from __future__ import annotations

import asyncio
from typing import Any

import httpx

from invest_system.adapters import append_market_snapshot_from_adapters, build_p0c_price_data_from_bundle
from invest_system.golden import seed_multiday_repository
from invest_system.repositories import SQLiteRepository
from invest_system.research import generate_p0c_research
from invest_system.web import create_app


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
    assert payload["data"]["research"]["available"] is True
    assert payload["data"]["risk"]["available"] is True
    assert payload["data"]["comparison"]["available"] is True
    assert payload["data"]["macro"]["available"] is True
    assert payload["data"]["report"]["available"] is True
    _assert_no_forbidden_terms(payload)


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
        if path in {"/app", "/home_human"}:
            assert 'href="/portfolio/view"' in body
            assert 'href="/portfolio/state"' not in body
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
