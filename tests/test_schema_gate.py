from __future__ import annotations

from copy import deepcopy

import pytest

from invest_system.demo import make_decision_record, make_research_snapshot, make_target_pool_snapshot
from invest_system.repositories import SQLiteRepository
from invest_system.research.importer import validate_research_import
from invest_system.validators.module_contracts import ModuleContractViolation, ThemeValidationError, validate_module_contract
from invest_system.validators.policies import PolicyViolation, assert_decision_policy, assert_target_pool_policy
from invest_system.validators.schema_validator import SchemaValidationError, validate_or_raise


def test_research_schema_accepts_valid_snapshot() -> None:
    payload = make_research_snapshot("market-demo")

    validate_or_raise(payload, "research.schema.json")


def test_research_schema_rejects_missing_common_field() -> None:
    payload = make_research_snapshot("market-demo")
    del payload["executive_summary"]

    with pytest.raises(SchemaValidationError):
        validate_or_raise(payload, "research.schema.json")


def test_decision_policy_blocks_action_when_gates_fail() -> None:
    payload = make_decision_record("market-demo", "research-demo")
    payload = deepcopy(payload)
    payload["decision_actions"][0]["gates"]["valuation"] = "blocked"

    with pytest.raises(PolicyViolation):
        assert_decision_policy(payload)


def test_decision_policy_blocks_research_first_positive_weight() -> None:
    payload = make_decision_record("market-demo", "research-demo")
    payload = deepcopy(payload)
    payload["decision_actions"][-1]["target_weight"] = 0.1

    with pytest.raises(PolicyViolation):
        assert_decision_policy(payload)


def test_target_pool_schema_accepts_valid_snapshot() -> None:
    validate_or_raise(make_target_pool_snapshot(), "target_pool.schema.json")


def test_target_pool_policy_rejects_duplicate_pool_membership() -> None:
    payload = make_target_pool_snapshot()
    payload = deepcopy(payload)
    payload["entries"][1]["symbols"].append("510300.SH")

    with pytest.raises(PolicyViolation):
        assert_target_pool_policy(payload)


def test_theme_schema_rejects_legacy_symbol_fields() -> None:
    payload = _theme_payload()
    payload["leading_symbols"] = ["301566.SZ"]

    with pytest.raises(SchemaValidationError):
        validate_or_raise(payload, "theme_research_payload.schema.json")


def test_theme_contract_rejects_stock_code_text() -> None:
    snapshot = _research_snapshot("theme_research", _theme_payload())
    snapshot["key_facts"] = ["Theme text must not leak 301566.SZ."]

    with pytest.raises(ThemeValidationError):
        validate_module_contract(snapshot)


def test_research_import_fails_closed_on_theme_contract_violation(tmp_path) -> None:
    repo = SQLiteRepository(tmp_path / "schema_gate.sqlite")
    snapshot = _research_snapshot("theme_research", _theme_payload())
    snapshot["payload"]["stock_list"] = ["301566.SZ"]

    validation = validate_research_import(repo, snapshot)

    assert validation["status"] == "failed"
    assert validation["append_allowed"] is False
    assert any(item["check_id"] == "module_payload_schema" for item in validation["checks"])


def test_research_import_rejects_legacy_leader_ranking_module(tmp_path) -> None:
    repo = SQLiteRepository(tmp_path / "leader_ranking_gate.sqlite")
    snapshot = _research_snapshot(
        "leader_ranking",
        {
            "theme": "advanced_electronics_manufacturing_chain",
            "rankings": [{"symbol": "301566.SZ", "score": 80, "reason": ["legacy mixed layer"]}],
        },
    )

    validation = validate_research_import(repo, snapshot)

    assert validation["status"] == "failed"
    assert validation["append_allowed"] is False
    assert any(
        item["check_id"] == "module_payload_schema" and item["status"] == "failed"
        for item in validation["checks"]
    )


def test_stock_research_first_gate_requires_blocked_status(tmp_path) -> None:
    repo = SQLiteRepository(tmp_path / "stock_gate.sqlite")
    repo.init_db()
    snapshot = _research_snapshot("stock_valuation", _stock_payload())
    snapshot["status"] = "json_validated"
    snapshot["actionability"] = "observe"

    with pytest.raises(ModuleContractViolation):
        repo.append_research_snapshot(snapshot)


def test_stock_research_first_gate_accepts_fail_closed_block(tmp_path) -> None:
    repo = SQLiteRepository(tmp_path / "stock_gate_pass.sqlite")
    repo.init_db()
    snapshot = _research_snapshot("stock_valuation", _stock_payload())

    inserted = repo.append_research_snapshot(snapshot)

    assert inserted["object_id"] == snapshot["snapshot_id"]


def _theme_payload() -> dict:
    return {
        "theme_id": "advanced_electronics_manufacturing_chain",
        "theme_name": "先进电子制造链",
        "sector": "advanced electronics manufacturing",
        "theme_state": "strengthening",
        "signal_type": ["momentum", "structural"],
        "leading_indicators": ["AI hardware", "半导体", "先进封装"],
        "strength_score": 72,
    }


def _stock_payload() -> dict:
    return {
        "symbol": "301566.SZ",
        "valuation_state": "missing",
        "research_first_status": "BLOCKED",
        "risk_score": 70,
        "signal_type": ["valuation", "liquidity", "structural"],
        "gates": {"profile": "missing", "valuation": "missing", "liquidity": "missing"},
        "reason": ["RESEARCH_FIRST_GATE blocks incomplete stock research."],
    }


def _research_snapshot(module: str, payload: dict) -> dict:
    return {
        "schema_version": "1.0",
        "snapshot_id": f"{module}-schema-gate-test",
        "basis_date": "2026-06-15",
        "generated_at": "2026-06-15T12:00:00Z",
        "module": module,
        "data_sources": ["fixture:schema"],
        "data_gaps": [],
        "conflicts": [],
        "executive_summary": "Fixture research snapshot for schema gate tests.",
        "key_facts": ["Fixture research follows the module contract."],
        "reasoning": ["The test fixture is intentionally minimal."],
        "risks": ["Fixture can be superseded."],
        "conclusion_strength": "medium",
        "actionability": "research_first" if module == "stock_valuation" else "observe",
        "confidence": 0.7,
        "invalidation_conditions": ["A newer fixture supersedes this one."],
        "next_review_date": "2026-06-16",
        "must_not_do": ["Do not use this fixture as execution output."],
        "required_human_review": True,
        "status": "blocked" if module == "stock_valuation" else "json_validated",
        "trace": {"fact_pack_id": f"{module}-schema-gate"},
        "payload": payload,
    }
