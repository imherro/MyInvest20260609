from __future__ import annotations

import asyncio
from copy import deepcopy
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
    preview_by_symbol = {item["symbol"]: item for item in proposal["decision_preview"]}

    assert proposal["status"] == "ok"
    assert proposal["recommended_action"] in {"observe", "research_first", "rebalance_candidate", "no_action"}
    assert proposal["decision_preview"]
    assert preview_by_symbol["510300.SH"]["proposal"] == "no_action"
    assert preview_by_symbol["159915.SZ"]["proposal"] == "no_action"
    assert preview_by_symbol["511360.SH"]["proposal"] == "no_action"
    assert preview_by_symbol["159999.SZ"]["proposal"] == "research_first"
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


def test_symbol_research_snapshots_are_not_collapsed_by_module(tmp_path) -> None:
    repo = SQLiteRepository(tmp_path / "decision_symbol_research.sqlite")
    seed_multiday_repository(repo)
    _append_current_target_pool_symbols(repo, ["301566.SZ", "688603.SH"], "research_first")
    repo.append_research_snapshot(_symbol_research("301566.SZ", 0.7))
    repo.append_research_snapshot(_symbol_research("688603.SH", 0.69))

    proposal = build_decision_proposal(repo, "2026-06-15")
    preview_by_symbol = {item["symbol"]: item for item in proposal["decision_preview"]}

    assert {"301566.SZ", "688603.SH"}.issubset(preview_by_symbol)
    assert preview_by_symbol["301566.SZ"]["proposal"] == "research_first"
    assert preview_by_symbol["301566.SZ"]["gates"] == {
        "profile": "pass",
        "valuation": "blocked",
        "liquidity": "pass",
        "research_first": True,
        "risk_boundary": "block",
    }


def test_historical_failed_research_is_not_a_decision_candidate(tmp_path) -> None:
    repo = SQLiteRepository(tmp_path / "decision_historical_scope.sqlite")
    seed_multiday_repository(repo)
    repo.append_research_snapshot(_symbol_research("301566.SZ", 0.7))

    proposal = build_decision_proposal(repo, "2026-06-15")
    preview_symbols = {item["symbol"] for item in proposal["decision_preview"]}

    assert "301566.SZ" not in preview_symbols


def test_current_cleanup_research_is_not_a_decision_candidate(tmp_path) -> None:
    repo = SQLiteRepository(tmp_path / "decision_cleanup.sqlite")
    seed_multiday_repository(repo)
    cleaned_decision = repo.latest_decision("2026-06-15")
    cleaned_decision["decision_id"] = "decision-2026-06-15-clean-test"
    cleaned_decision["decision_actions"] = [
        action for action in cleaned_decision["decision_actions"] if action["symbol"] != "159999.SZ"
    ]
    repo.append_decision_record(cleaned_decision)
    repo.append_research_snapshot(_cleanup_research("159999.SZ"))

    proposal = build_decision_proposal(repo, "2026-06-15")
    preview_symbols = {item["symbol"] for item in proposal["decision_preview"]}

    assert "159999.SZ" not in preview_symbols


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


def _append_current_target_pool_symbols(repo: SQLiteRepository, symbols: list[str], pool_type: str) -> None:
    target_pool = deepcopy(repo.latest_target_pool("2026-06-15"))
    target_pool["target_pool_id"] = f"target-pool-2026-06-15-{pool_type}-symbols-test"
    for entry in target_pool["entries"]:
        entry["symbols"] = [symbol for symbol in entry["symbols"] if symbol not in symbols]
        if entry["pool_type"] == pool_type:
            entry["symbols"].extend(symbols)
    repo.append_target_pool_snapshot(target_pool)


def _cleanup_research(symbol: str) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "snapshot_id": f"etf-valuation-2026-06-15-{symbol}-cleanup-test",
        "basis_date": "2026-06-15",
        "generated_at": "2026-06-15T12:00:00Z",
        "module": "etf_valuation",
        "data_sources": ["fixture:research"],
        "data_gaps": [],
        "conflicts": [],
        "executive_summary": f"{symbol} is removed from current target-pool review.",
        "key_facts": [f"{symbol} is not a current candidate."],
        "reasoning": ["Current-only cleanup should not create a decision candidate."],
        "risks": ["A future active-instrument review can supersede this cleanup snapshot."],
        "conclusion_strength": "medium",
        "actionability": "no_action",
        "confidence": 0.7,
        "invalidation_conditions": ["A later target-pool snapshot reintroduces the symbol."],
        "next_review_date": "2026-06-16",
        "must_not_do": ["Do not use fixture research as external execution output."],
        "required_human_review": True,
        "status": "finalized",
        "trace": {"fact_pack_id": f"fixture-{symbol}", "source_market_snapshot_id": "market-2026-06-15-golden"},
        "payload": {
            "symbol": symbol,
            "valuation_score": 0,
            "fair_value_band_pct": {"low": 0, "mid": 0, "high": 0},
            "observed_to_fair_value_ratio": 0,
            "deviation": 0,
            "risk_flag": "high",
            "confidence": 0.7,
            "method": "current_target_pool_cleanup",
            "tracking_target": "not_current_candidate",
            "rating": "Watch",
        },
    }


def _symbol_research(symbol: str, confidence: float) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "snapshot_id": f"stock-valuation-2026-06-15-{symbol}-test",
        "basis_date": "2026-06-15",
        "generated_at": "2026-06-16T04:20:17Z",
        "module": "stock_valuation",
        "data_sources": ["test:fixture"],
        "data_gaps": ["long_horizon_valuation_unavailable"],
        "conflicts": [],
        "executive_summary": f"{symbol} profile and liquidity pass, while valuation remains blocked.",
        "key_facts": [
            "Profile gate passes because identity is confirmed.",
            "Liquidity gate passes because recent activity evidence is present.",
            "Valuation gate fails because valuation pressure remains high.",
        ],
        "reasoning": [
            "Profile gate passes.",
            "Valuation gate fails.",
            "Liquidity gate passes.",
        ],
        "risks": ["Valuation pressure remains unresolved."],
        "conclusion_strength": "medium",
        "actionability": "research_first",
        "confidence": confidence,
        "invalidation_conditions": ["A newer complete-day valuation record changes the gate."],
        "next_review_date": "2026-06-23",
        "must_not_do": ["Do not use this snapshot as external execution output."],
        "required_human_review": True,
        "status": "blocked",
        "trace": {"fact_pack_id": f"test-{symbol}"},
        "payload": {
            "symbol": symbol,
            "valuation_state": "fail",
            "research_first_status": "BLOCKED",
            "risk_score": 80,
            "signal_type": ["valuation", "liquidity", "structural", "risk_event"],
            "gates": {"profile": "pass", "valuation": "fail", "liquidity": "pass"},
            "reason": ["Valuation gate fails, so ResearchFirst remains fail-closed."],
        },
    }


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
