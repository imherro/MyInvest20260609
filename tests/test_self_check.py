from __future__ import annotations

from invest_system.demo import seed_demo_repository
from invest_system.repositories import SQLiteRepository
from invest_system.self_check import run_self_check


def test_system_self_check_passes_for_seeded_history(tmp_path) -> None:
    db_path = tmp_path / "self_check.sqlite"
    seed_demo_repository(SQLiteRepository(db_path))

    result = run_self_check(db_path)

    assert result["status"] == "passed"
    assert {item["name"] for item in result["checks"]} == {
        "json_valid",
        "history_continuity",
        "portfolio_replay",
        "multiday_replay",
        "event_log_consistency",
    }
