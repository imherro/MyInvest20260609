from __future__ import annotations

from invest_system.golden import MULTIDAY_DATES, seed_multiday_repository
from invest_system.repositories import SQLiteRepository
from invest_system.self_check import run_self_check


def test_multiday_replay_reconstructs_each_day(tmp_path) -> None:
    db_path = tmp_path / "multiday.sqlite"
    repo = SQLiteRepository(db_path)
    seeded = seed_multiday_repository(repo)

    assert [day["basis_date"] for day in seeded["days"]] == MULTIDAY_DATES
    for day in seeded["days"]:
        replay = repo.replay_state(day["basis_date"])
        assert replay["portfolio"]["portfolio_id"] == day["portfolio"]
        assert replay["portfolio"]["basis_date"] == day["basis_date"]
        assert replay["target_pool"]["target_pool_id"] == day["target_pool"]

    result = run_self_check(db_path, "2026-06-14")
    assert result["status"] == "passed"
    assert result["as_of"] == "2026-06-14"
    assert result["replay_confidence_score"] == 1.0
    assert any(check["name"] == "multiday_replay" for check in result["checks"])

