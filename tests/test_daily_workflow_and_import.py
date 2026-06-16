from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

import httpx

from invest_system.adapters import append_market_snapshot_from_adapters, build_p0c_price_data_from_bundle
from invest_system.golden import seed_multiday_repository
from invest_system.repositories import SQLiteRepository
from invest_system.research import generate_p0c_research
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
]


def test_daily_workflow_state_reports_next_action(tmp_path) -> None:
    db_path = _prepare_workflow_db(tmp_path)
    app = create_app(db_path)

    response = _get(app, "/workflow/daily/state?as_of=2026-06-15")
    payload = response.json()

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert payload["status"] == "ok"
    assert payload["data"]["status"] in {"ready", "review_required", "action_required"}
    assert payload["data"]["primary_next_action"]["endpoint"].startswith("/")
    assert {item["step_id"] for item in payload["data"]["steps"]} == {
        "market_snapshot",
        "mainline_research",
        "guidance_boundary",
        "decision_proposal",
        "shadow_portfolio",
        "report_preview",
    }
    assert payload["data"]["decision_preview"]["endpoint"] == "/decision/proposal"
    _assert_no_forbidden_terms(payload)


def test_research_import_validate_and_append_are_append_only(tmp_path) -> None:
    db_path = tmp_path / "import.sqlite"
    repo = SQLiteRepository(db_path)
    repo.init_db()
    app = create_app(db_path)
    payload = _theme_research_snapshot("theme-import-2026-06-15")

    validate_response = _post(app, "/research/import/validate", payload)
    validate_payload = validate_response.json()

    assert validate_response.status_code == 200
    assert validate_response.headers["content-type"].startswith("application/json")
    assert validate_payload["status"] == "ok"
    assert validate_payload["data"]["status"] == "pass"
    assert validate_payload["data"]["append_allowed"] is True
    assert repo.table_counts()["research_snapshot"] == 0

    import_response = _post(app, "/research/import", payload)
    import_payload = import_response.json()

    assert import_response.status_code == 200
    assert import_response.headers["content-type"].startswith("application/json")
    assert import_payload["status"] == "ok"
    assert import_payload["data"]["snapshot_id"] == payload["snapshot_id"]
    assert import_payload["data"]["auto_shadow"]["status"] == "skipped"
    assert import_payload["data"]["auto_shadow"]["reason"] == "missing_market_target_pool_or_portfolio"
    assert repo.table_counts()["research_snapshot"] == 1
    assert repo.table_counts()["event_log"] == 1

    duplicate_response = _post(app, "/research/import", payload)
    duplicate_payload = duplicate_response.json()

    assert duplicate_payload["status"] == "failed"
    assert duplicate_payload["data"]["append_allowed"] is False
    assert repo.table_counts()["research_snapshot"] == 1
    _assert_no_forbidden_terms(duplicate_payload)


def test_research_import_errors_do_not_echo_sensitive_fields(tmp_path) -> None:
    db_path = tmp_path / "import.sqlite"
    repo = SQLiteRepository(db_path)
    repo.init_db()
    app = create_app(db_path)
    payload = deepcopy(_theme_research_snapshot("theme-import-sensitive"))
    payload["total_asset"] = 1

    response = _post(app, "/research/import/validate", payload)
    body = response.text

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["status"] == "failed"
    assert "blocked_field" in body
    _assert_no_forbidden_terms(body)


def test_daily_workflow_and_import_views_use_portal_shell(tmp_path) -> None:
    db_path = _prepare_workflow_db(tmp_path)
    app = create_app(db_path)

    for path in ["/workflow/daily/view", "/research/import/view"]:
        response = _get(app, f"{path}?as_of=2026-06-15")
        body = response.text
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")
        assert "data-page-shell=\"portal\"" in body
        assert "统一页脚" in body
        assert "<form" not in body
        _assert_no_forbidden_terms(body)


def _prepare_workflow_db(tmp_path) -> str:
    db_path = tmp_path / "workflow.sqlite"
    repo = SQLiteRepository(db_path)
    seed_multiday_repository(repo)
    market_data = append_market_snapshot_from_adapters(repo, basis_date="2026-06-15", source="mock")
    generate_p0c_research(repo, "2026-06-15", price_data=build_p0c_price_data_from_bundle(market_data["bundle"]))
    return str(db_path)


def _theme_research_snapshot(snapshot_id: str) -> dict[str, Any]:
    generated_at = datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
    return {
        "schema_version": "1.0",
        "snapshot_id": snapshot_id,
        "basis_date": "2026-06-15",
        "generated_at": generated_at,
        "module": "theme_research",
        "data_sources": ["manual_json_import"],
        "data_gaps": ["manual_import_source_requires_review"],
        "conflicts": [],
        "executive_summary": "Manual imported theme research stays inside ResearchFirst review.",
        "key_facts": ["Representative symbols are research objects only."],
        "reasoning": ["The import path validates schema and policy before append-only persistence."],
        "risks": ["Manual import can be stale if the source research is not refreshed."],
        "conclusion_strength": "medium",
        "actionability": "research_first",
        "confidence": 0.62,
        "invalidation_conditions": ["Newer market data changes the theme ranking."],
        "next_review_date": "2026-06-16",
        "must_not_do": ["Do not convert this research directly into external execution."],
        "required_human_review": True,
        "status": "json_validated",
        "trace": {"fact_pack_id": "manual-import-theme-fact-pack", "source_market_snapshot_id": None},
        "payload": {
            "theme": "manual import mainline",
            "strength_score": 62,
            "leading_symbols": ["510300.SH"],
            "phase": "mid",
            "related_etfs": [],
            "evidence": ["Manual import test evidence."],
        },
    }


def _assert_no_forbidden_terms(payload: Any) -> None:
    text = str(payload)
    for forbidden in FORBIDDEN_TERMS:
        assert forbidden not in text


def _get(app, path: str) -> httpx.Response:
    return asyncio.run(_async_get(app, path))


def _post(app, path: str, payload: dict[str, Any]) -> httpx.Response:
    return asyncio.run(_async_post(app, path, payload))


async def _async_get(app, path: str) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.get(path)


async def _async_post(app, path: str, payload: dict[str, Any]) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.post(path, json=payload)
