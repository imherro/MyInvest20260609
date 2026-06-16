from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from invest_system.repositories import SQLiteRepository
from invest_system.validators.cross_layer_integrity import (
    CrossLayerIntegrityError,
    CrossLayerLeakError,
    scan_cross_layer_leaks,
    sanitize_trace,
    theme_contains_any_stock_reference,
    trace_leaks_stock_identity,
    validate_cross_layer_integrity,
)


def test_theme_clean_test_rejects_stock_references() -> None:
    theme = _theme_research_snapshot()

    validate_cross_layer_integrity(theme)
    assert not theme_contains_any_stock_reference(theme)

    leaked = deepcopy(theme)
    leaked["payload"]["leading_indicators"].append("301566.SZ")

    with pytest.raises(CrossLayerLeakError, match="THEME_CONTAINS_STOCK_REFERENCE"):
        validate_cross_layer_integrity(leaked)


def test_stock_can_have_symbol_but_not_theme_back_reference() -> None:
    stock = _stock_research_snapshot()

    validate_cross_layer_integrity(stock)

    leaked = deepcopy(stock)
    leaked["payload"]["theme_id"] = "advanced_electronics_manufacturing_chain"

    with pytest.raises(CrossLayerLeakError, match="STOCK_CONTAINS_THEME_BACK_REFERENCE"):
        validate_cross_layer_integrity(leaked)


def test_trace_leakage_test_rejects_symbols_and_stock_paths() -> None:
    stock = _stock_research_snapshot()
    stock["trace"]["fact_pack_id"] = "stock-research-301566.SZ"

    assert trace_leaks_stock_identity(stock["trace"])
    with pytest.raises(CrossLayerLeakError, match="TRACE_CONTAINS_STOCK_REFERENCE"):
        validate_cross_layer_integrity(stock)


def test_sanitize_trace_removes_stock_identifiers() -> None:
    trace = {
        "fact_pack_id": "research-run",
        "stock_path": "301566.SZ",
        "source_research_snapshot_ids": ["theme-research-2026-06-16", "stock-valuation-301566.SZ"],
    }

    assert sanitize_trace(trace) == {
        "fact_pack_id": "research-run",
        "source_research_snapshot_ids": ["theme-research-2026-06-16"],
    }


def test_scan_cross_layer_leaks_detects_dag_violations() -> None:
    theme = _theme_research_snapshot()
    stock = _stock_research_snapshot()

    scan_cross_layer_leaks([theme, stock])

    leaked_stock = deepcopy(stock)
    leaked_stock["payload"]["theme_name"] = theme["payload"]["theme_name"]

    with pytest.raises(CrossLayerIntegrityError, match="STOCK_CONTAINS_THEME_BACK_REFERENCE"):
        scan_cross_layer_leaks([theme, leaked_stock])


def test_repository_rejects_trace_leak_before_insert(tmp_path) -> None:
    repo = SQLiteRepository(tmp_path / "cross_layer.sqlite")
    repo.init_db()
    stock = _stock_research_snapshot()
    stock["trace"]["fact_pack_id"] = "research-301566.SZ"

    with pytest.raises(CrossLayerLeakError, match="TRACE_CONTAINS_STOCK_REFERENCE"):
        repo.append_research_snapshot(stock)

    assert repo.table_counts()["research_snapshot"] == 0
    assert repo.table_counts()["event_log"] == 0


def _theme_research_snapshot() -> dict[str, Any]:
    return _research_snapshot(
        module="theme_research",
        status="json_validated",
        actionability="observe",
        payload={
            "theme_id": "advanced_electronics_manufacturing_chain",
            "theme_name": "先进电子制造链",
            "sector": "advanced electronics manufacturing",
            "theme_state": "strengthening",
            "signal_type": ["momentum", "structural"],
            "leading_indicators": ["行业成交额变化", "主题指数强弱"],
            "strength_score": 72,
        },
    )


def _stock_research_snapshot() -> dict[str, Any]:
    return _research_snapshot(
        module="stock_valuation",
        status="json_validated",
        actionability="observe",
        payload={
            "symbol": "301566.SZ",
            "valuation_state": "pass",
            "research_first_status": "PASSED",
            "risk_score": 38,
            "signal_type": ["valuation", "liquidity", "structural"],
            "gates": {"profile": "pass", "valuation": "pass", "liquidity": "pass"},
            "reason": ["Profile, valuation, and liquidity gates pass."],
        },
    )


def _research_snapshot(*, module: str, status: str, actionability: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "snapshot_id": f"{module}-cross-layer-test",
        "basis_date": "2026-06-16",
        "generated_at": "2026-06-16T12:00:00Z",
        "module": module,
        "data_sources": ["fixture:cross-layer"],
        "data_gaps": [],
        "conflicts": [],
        "executive_summary": "Fixture research snapshot for cross-layer integrity tests.",
        "key_facts": ["Fixture research follows the module contract."],
        "reasoning": ["The test fixture is intentionally minimal."],
        "risks": ["Fixture can be superseded."],
        "conclusion_strength": "medium",
        "actionability": actionability,
        "confidence": 0.7,
        "invalidation_conditions": ["A newer fixture supersedes this one."],
        "next_review_date": "2026-06-17",
        "must_not_do": ["Do not use this fixture as execution output."],
        "required_human_review": True,
        "status": status,
        "trace": {"fact_pack_id": "cross-layer-fixture", "source_market_snapshot_id": "market-2026-06-16-fixture"},
        "payload": payload,
    }
