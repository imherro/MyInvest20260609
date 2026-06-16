from __future__ import annotations

import asyncio
from typing import Any

import httpx

from invest_system.adapters import append_market_snapshot_from_adapters, build_p0c_price_data_from_bundle
from invest_system.decision import build_decision_explain, build_decision_proposal
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
    "buy",
    "sell",
]


def test_decision_proposal_is_schema_valid_and_read_only(tmp_path) -> None:
    repo = _prepare_decision_repo(tmp_path)
    before_counts = repo.table_counts()

    proposal = build_decision_proposal(repo, "2026-06-15")

    assert proposal["status"] == "ok"
    assert proposal["recommended_action"] in {"observe", "research_first", "rebalance_candidate", "no_action"}
    assert proposal["decision_preview"]
    assert proposal["explanation"]["why"]
    validate_or_raise(proposal, "decision_proposal.schema.json")
    assert repo.table_counts() == before_counts
    _assert_no_forbidden_terms(proposal)


def test_decision_explain_endpoint_returns_traceable_json(tmp_path) -> None:
    repo = _prepare_decision_repo(tmp_path)
    app = create_app(repo.db_path)

    proposal_response = _get(app, "/decision/proposal?as_of=2026-06-15")
    explain_response = _get(app, "/decision/explain?as_of=2026-06-15")

    assert proposal_response.status_code == 200
    assert proposal_response.headers["content-type"].startswith("application/json")
    assert proposal_response.json()["data"]["source_ids"]["market_snapshot_id"]
    assert explain_response.status_code == 200
    assert explain_response.headers["content-type"].startswith("application/json")
    assert explain_response.json()["data"]["explanation"]["why"]
    _assert_no_forbidden_terms(proposal_response.json())
    _assert_no_forbidden_terms(explain_response.json())


def test_decision_view_uses_portal_shell(tmp_path) -> None:
    repo = _prepare_decision_repo(tmp_path)
    app = create_app(repo.db_path)

    response = _get(app, "/decision/view?as_of=2026-06-15")
    body = response.text

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "data-page-shell=\"portal\"" in body
    assert "今日决策预览" in body
    assert "为什么这么建议" in body
    assert "<form" not in body
    _assert_no_forbidden_terms(body)


def test_build_decision_explain_is_read_only(tmp_path) -> None:
    repo = _prepare_decision_repo(tmp_path)
    before_counts = repo.table_counts()

    explain = build_decision_explain(repo, "2026-06-15")

    assert explain["status"] == "ok"
    assert explain["data"]["recommended_action"] in {"observe", "research_first", "rebalance_candidate", "no_action"}
    assert repo.table_counts() == before_counts
    _assert_no_forbidden_terms(explain)


def _prepare_decision_repo(tmp_path) -> SQLiteRepository:
    repo = SQLiteRepository(tmp_path / "decision_proposal.sqlite")
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
