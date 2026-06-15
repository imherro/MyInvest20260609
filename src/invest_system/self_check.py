from __future__ import annotations

from pathlib import Path
from typing import Any

from invest_system.repositories import SQLiteRepository
from invest_system.validators.policies import (
    assert_decision_policy,
    assert_portfolio_policy,
    assert_research_policy,
)
from invest_system.validators.schema_validator import validate_or_raise


SCHEMA_BY_TYPE = {
    "market": "market_snapshot.schema.json",
    "research": "research.schema.json",
    "decision": "decision.schema.json",
    "portfolio": "portfolio.schema.json",
}


def run_self_check(db_path: str | Path) -> dict[str, Any]:
    repo = SQLiteRepository(db_path)
    checks = [
        _check_json_valid(repo),
        _check_history_continuity(repo),
        _check_portfolio_replay(repo),
        _check_event_log_consistency(repo),
    ]
    return {
        "status": "passed" if all(item["passed"] for item in checks) else "failed",
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

    return {
        "name": "history_continuity",
        "passed": not errors,
        "details": {"errors": errors},
    }


def _check_portfolio_replay(repo: SQLiteRepository) -> dict[str, Any]:
    latest = repo.latest_portfolio()
    replay = repo.replay_state()
    replayed = replay.get("portfolio")
    errors: list[str] = []
    if latest and not replayed:
        errors.append("latest_portfolio_not_replayed")
    if latest and replayed and latest["portfolio_id"] != replayed["portfolio_id"]:
        errors.append("latest_portfolio_mismatch")
    return {
        "name": "portfolio_replay",
        "passed": not errors,
        "details": {
            "errors": errors,
            "portfolio_id": replayed["portfolio_id"] if replayed else None,
        },
    }


def _check_event_log_consistency(repo: SQLiteRepository) -> dict[str, Any]:
    counts = repo.table_counts()
    expected = counts["market_snapshot"] + counts["research_snapshot"] + counts["decision_record"] + counts[
        "portfolio_snapshot"
    ]
    errors = []
    if counts["event_log"] != expected:
        errors.append("event_log_count_mismatch")
    return {
        "name": "event_log_consistency",
        "passed": not errors,
        "details": {"errors": errors, "counts": counts},
    }

