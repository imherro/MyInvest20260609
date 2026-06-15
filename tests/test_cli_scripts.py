from __future__ import annotations

import json
import subprocess
import sys

from invest_system.demo import make_decision_record, make_market_snapshot, make_research_snapshot
from invest_system.golden import seed_multiday_repository
from invest_system.repositories import SQLiteRepository


def test_append_research_and_decision_scripts_validate_and_insert(tmp_path) -> None:
    db_path = tmp_path / "cli.sqlite"
    market = make_market_snapshot()
    research = make_research_snapshot(market["snapshot_id"])
    decision = make_decision_record(market["snapshot_id"], research["snapshot_id"])
    research_path = tmp_path / "research.json"
    decision_path = tmp_path / "decision.json"
    research_path.write_text(json.dumps(research), encoding="utf-8")
    decision_path.write_text(json.dumps(decision), encoding="utf-8")

    subprocess.run(
        [sys.executable, "scripts/append_research_snapshot.py", "--db", str(db_path), "--input", str(research_path)],
        check=True,
    )
    subprocess.run(
        [sys.executable, "scripts/append_decision.py", "--db", str(db_path), "--input", str(decision_path)],
        check=True,
    )

    repo = SQLiteRepository(db_path)
    assert repo.table_counts()["research_snapshot"] == 1
    assert repo.table_counts()["decision_record"] == 1


def test_migrated_check_scripts_pass_on_multiday_db(tmp_path) -> None:
    db_path = tmp_path / "checks.sqlite"
    seed_multiday_repository(SQLiteRepository(db_path))
    commands = [
        [sys.executable, "scripts/check_ratio_only.py", "--db", str(db_path)],
        [sys.executable, "scripts/check_research_first_gate.py", "--db", str(db_path)],
        [sys.executable, "scripts/check_cross_file_allocation_consistency.py", "--db", str(db_path)],
        [sys.executable, "scripts/project_check.py", "--current-only", "--db", str(db_path)],
        [sys.executable, "scripts/project_check.py", "--db", str(db_path), "--as-of", "2026-06-14"],
    ]
    for command in commands:
        completed = subprocess.run(command, check=True, capture_output=True, text=True)
        assert json.loads(completed.stdout)["status"] == "passed"


def test_full_system_check_script_returns_passed_json(tmp_path) -> None:
    db_path = tmp_path / "full.sqlite"

    completed = subprocess.run(
        [sys.executable, "scripts/run_full_system_check.py", "--db", str(db_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(completed.stdout)

    assert payload["status"] == "passed"
    assert payload["record_counts"]["portfolio_snapshot"] == 3
    assert payload["self_checks"]["2026-06-14"]["replay_confidence_score"] == 1.0
    assert payload["api_checks"]["/system/status"]["status"] == "ok"
