from __future__ import annotations

import pytest

from invest_system.collectors import import_qmt_positions, import_qmt_positions_from_qmt
from invest_system.golden import seed_multiday_repository
from invest_system.repositories import SQLiteRepository
from invest_system.validators.policies import PolicyViolation


def test_qmt_mock_import_appends_market_event_and_target_pool(tmp_path) -> None:
    db_path = tmp_path / "qmt.sqlite"
    repo = SQLiteRepository(db_path)
    csv_path = "tests/fixtures/qmt_positions_sample.csv"

    result = import_qmt_positions(csv_path, repo, "2026-06-15")

    assert result["status"] == "ok"
    counts = repo.table_counts()
    assert counts["target_pool_snapshot"] == 1
    assert counts["event_log"] == 2
    events = repo.timeline()
    assert [event["type"] for event in events] == ["market_event", "target_pool"]
    assert events[0]["payload"]["holdings_weight"] == {
        "159915.SZ": 0.35,
        "159999.SZ": 0.0,
        "510300.SH": 0.4,
        "511360.SH": 0.25,
    }
    assert repo.latest_target_pool()["entries"][0]["symbols"] == ["159915.SZ", "510300.SH", "511360.SH"]


def test_qmt_target_pool_does_not_override_strategy_target_pool(tmp_path) -> None:
    repo = SQLiteRepository(tmp_path / "qmt_strategy_scope.sqlite")
    seed_multiday_repository(repo)
    csv_path = tmp_path / "qmt_actual_positions.csv"
    csv_path.write_text(
        "symbol,holding_weight,bucket,pool_type\n"
        "512880.SH,0.6,actual,approved\n"
        "511360.SH,0.4,actual,approved\n",
        encoding="utf-8",
    )

    result = import_qmt_positions(csv_path, repo, "2026-06-16")
    latest_pool = repo.latest_target_pool()
    replay = repo.replay_state()

    assert result["status"] == "ok"
    assert result["target_pool"]["object_id"] == "target-pool-2026-06-16-qmt-mock"
    assert latest_pool["target_pool_id"] == "target-pool-2026-06-15-golden"
    assert latest_pool["source"] == "seed"
    assert replay["target_pool"]["target_pool_id"] == "target-pool-2026-06-15-golden"
    assert any(
        event["object_id"] == "qmt-mock-2026-06-16"
        and event["payload"]["holdings_weight"] == {"511360.SH": 0.4, "512880.SH": 0.6}
        for event in repo.timeline()
    )


def test_qmt_mock_missing_file_records_blocked_event(tmp_path) -> None:
    db_path = tmp_path / "qmt.sqlite"
    repo = SQLiteRepository(db_path)

    result = import_qmt_positions(tmp_path / "missing.csv", repo, "2026-06-15")

    assert result["status"] == "blocked"
    assert repo.table_counts()["target_pool_snapshot"] == 0
    assert repo.timeline()[0]["payload"]["status"] == "blocked"


def test_qmt_mock_rejects_sensitive_columns(tmp_path) -> None:
    csv_path = tmp_path / "bad.csv"
    csv_path.write_text("symbol,holding_weight,bucket,pool_type,share_count\n510300.SH,0.4,core,approved,100\n")
    repo = SQLiteRepository(tmp_path / "qmt.sqlite")

    with pytest.raises(PolicyViolation):
        import_qmt_positions(csv_path, repo, "2026-06-15")


def test_qmt_live_import_blocks_without_readonly_config(tmp_path, monkeypatch) -> None:
    repo = SQLiteRepository(tmp_path / "qmt.sqlite")
    monkeypatch.setenv("QMT_INSTALL_DIR", str(tmp_path / "missing_qmt"))
    monkeypatch.delenv("QMT_ACCOUNT_ID", raising=False)
    monkeypatch.delenv("QMT_TRADER_PATH", raising=False)
    monkeypatch.delenv("QMT_USER_PATH", raising=False)
    monkeypatch.delenv("QMT_PYTHONPATH", raising=False)

    result = import_qmt_positions_from_qmt(repo, "2026-06-15")

    assert result["status"] == "blocked"
    assert result["reason"] == "qmt_readonly_config_missing"
    assert repo.table_counts()["target_pool_snapshot"] == 0
    assert repo.timeline()[0]["payload"]["data_gaps"] == ["qmt_readonly_config_missing"]
