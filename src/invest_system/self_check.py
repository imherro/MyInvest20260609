from __future__ import annotations

from pathlib import Path
from typing import Any

from invest_system.repositories import SQLiteRepository
from invest_system.validators.policies import (
    assert_decision_policy,
    assert_portfolio_policy,
    assert_research_policy,
    assert_target_pool_policy,
)
from invest_system.validators.schema_validator import validate_or_raise


SCHEMA_BY_TYPE = {
    "market": "market_snapshot.schema.json",
    "research": "research.schema.json",
    "target_pool": "target_pool.schema.json",
    "decision": "decision.schema.json",
    "portfolio": "portfolio.schema.json",
}

RESEARCH_PAYLOAD_SCHEMA_BY_MODULE = {
    "etf_valuation": "etf_valuation_payload.schema.json",
    "stock_valuation": "stock_valuation_payload.schema.json",
    "theme_research": "theme_research_payload.schema.json",
    "leader_ranking": "leader_ranking_payload.schema.json",
    "review_score": "review_score_payload.schema.json",
}


def run_self_check(db_path: str | Path, as_of: str | None = None) -> dict[str, Any]:
    repo = SQLiteRepository(db_path)
    checks = [
        _check_json_valid(repo),
        _check_history_continuity(repo),
        _check_portfolio_replay(repo, as_of),
        _check_multiday_replay(repo),
        _check_event_log_consistency(repo),
    ]
    passed_count = sum(1 for item in checks if item["passed"])
    return {
        "status": "passed" if all(item["passed"] for item in checks) else "failed",
        "as_of": as_of,
        "replay_confidence_score": round(passed_count / len(checks), 4),
        "checks": checks,
    }


def _check_json_valid(repo: SQLiteRepository) -> dict[str, Any]:
    errors: list[str] = []
    for row in repo.all_payload_rows():
        payload = row["payload"]
        try:
            validate_or_raise(payload, SCHEMA_BY_TYPE[row["type"]])
            if row["type"] in {"market", "research"}:
                assert_research_policy(payload)
                module_schema = RESEARCH_PAYLOAD_SCHEMA_BY_MODULE.get(payload.get("module"))
                if module_schema:
                    validate_or_raise(payload["payload"], module_schema)
            elif row["type"] == "target_pool":
                assert_target_pool_policy(payload)
            elif row["type"] == "decision":
                assert_decision_policy(payload)
            elif row["type"] == "portfolio":
                assert_portfolio_policy(payload)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{row['table']}:{row['object_id']}:{exc}")
    return {
        "name": "json_valid",
        "passed": not errors,
        "details": {"errors": errors},
    }


def _check_history_continuity(repo: SQLiteRepository) -> dict[str, Any]:
    rows = repo.all_payload_rows()
    market_ids = {row["object_id"] for row in rows if row["type"] == "market"}
    research_ids = {row["object_id"] for row in rows if row["type"] == "research"}
    decision_ids = {row["object_id"] for row in rows if row["type"] == "decision"}
    target_pool_ids = {row["object_id"] for row in rows if row["type"] == "target_pool"}
    errors: list[str] = []

    for row in rows:
        payload = row["payload"]
        if row["type"] == "decision":
            market_id = payload["trace"]["source_market_snapshot_id"]
            if market_id not in market_ids:
                errors.append(f"decision:{row['object_id']}:missing_market:{market_id}")
            for research_id in payload["trace"]["source_research_snapshot_ids"]:
                if research_id not in research_ids:
                    errors.append(f"decision:{row['object_id']}:missing_research:{research_id}")
        if row["type"] == "portfolio":
            decision_id = payload["source_decision_id"]
            if decision_id is not None and decision_id not in decision_ids:
                errors.append(f"portfolio:{row['object_id']}:missing_decision:{decision_id}")
            target_pool_id = payload["source_target_pool_id"]
            if target_pool_id is not None and target_pool_id not in target_pool_ids:
                errors.append(f"portfolio:{row['object_id']}:missing_target_pool:{target_pool_id}")

    return {
        "name": "history_continuity",
        "passed": not errors,
        "details": {"errors": errors},
    }


def _check_portfolio_replay(repo: SQLiteRepository, as_of: str | None) -> dict[str, Any]:
    portfolio_rows = [row for row in repo.all_payload_rows() if row["type"] == "portfolio"]
    expected_id = _latest_portfolio_id_on_or_before(portfolio_rows, as_of) if as_of else (
        portfolio_rows[-1]["payload"]["portfolio_id"] if portfolio_rows else None
    )
    replay = repo.replay_state(as_of)
    replayed = replay.get("portfolio")
    errors: list[str] = []
    if expected_id and not replayed:
        errors.append("latest_portfolio_not_replayed")
    if expected_id and replayed and expected_id != replayed["portfolio_id"]:
        errors.append("latest_portfolio_mismatch")
    return {
        "name": "portfolio_replay",
        "passed": not errors,
        "details": {
            "errors": errors,
            "as_of": as_of,
            "expected_portfolio_id": expected_id,
            "portfolio_id": replayed["portfolio_id"] if replayed else None,
        },
    }


def _check_multiday_replay(repo: SQLiteRepository) -> dict[str, Any]:
    portfolio_rows = [row for row in repo.all_payload_rows() if row["type"] == "portfolio"]
    basis_dates = sorted({row["payload"]["basis_date"] for row in portfolio_rows})
    errors: list[str] = []
    replayed: dict[str, str | None] = {}
    for basis_date in basis_dates:
        expected = _latest_portfolio_id_on_or_before(portfolio_rows, basis_date)
        actual_payload = repo.replay_state(basis_date).get("portfolio")
        actual = actual_payload["portfolio_id"] if actual_payload else None
        replayed[basis_date] = actual
        if expected != actual:
            errors.append(f"as_of:{basis_date}:expected:{expected}:actual:{actual}")
    return {
        "name": "multiday_replay",
        "passed": not errors,
        "details": {
            "errors": errors,
            "basis_dates": basis_dates,
            "replayed": replayed,
        },
    }


def _check_event_log_consistency(repo: SQLiteRepository) -> dict[str, Any]:
    counts = repo.table_counts()
    rows = repo.all_payload_rows()
    events = repo.timeline()
    errors = []
    event_keys = {(event["type"], event["object_id"]) for event in events}
    for row in rows:
        if (row["type"], row["object_id"]) not in event_keys:
            errors.append(f"missing_event:{row['type']}:{row['object_id']}")
    return {
        "name": "event_log_consistency",
        "passed": not errors,
        "details": {"errors": errors, "counts": counts, "event_count": len(events)},
    }


def system_status(db_path: str | Path, as_of: str | None = None) -> dict[str, Any]:
    repo = SQLiteRepository(db_path)
    repo.init_db()
    self_check = run_self_check(db_path, as_of)
    replay_state = repo.replay_state(as_of)
    return {
        "status": "ok",
        "data": {
            "db_initialized": True,
            "record_counts": repo.table_counts(),
            "self_check": self_check,
            "latest_event_timestamp": repo.latest_event_timestamp(),
            "replay_available": replay_state.get("portfolio") is not None,
        },
    }


def _latest_portfolio_id_on_or_before(portfolio_rows: list[dict[str, Any]], basis_date: str | None) -> str | None:
    if basis_date is None:
        return portfolio_rows[-1]["payload"]["portfolio_id"] if portfolio_rows else None
    candidates = [
        row["payload"]
        for row in portfolio_rows
        if row["payload"]["basis_date"] <= basis_date
    ]
    if not candidates:
        return None
    return sorted(candidates, key=lambda payload: (payload["basis_date"], payload["generated_at"]))[-1]["portfolio_id"]
