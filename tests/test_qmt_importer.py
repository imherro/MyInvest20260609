from __future__ import annotations

import pytest

from invest_system.collectors import import_qmt_positions
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
    assert repo.latest_target_pool()["entries"][0]["symbols"] == ["159915.SZ", "510300.SH", "511360.SH"]


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

