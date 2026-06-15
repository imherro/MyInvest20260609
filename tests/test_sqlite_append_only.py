from __future__ import annotations

import sqlite3
from contextlib import closing
from copy import deepcopy

import pytest

from invest_system.demo import (
    make_decision_record,
    make_market_snapshot,
    make_research_snapshot,
    make_target_pool_snapshot,
)
from invest_system.repositories import SQLiteRepository
from invest_system.shadow import ShadowPortfolioEngine
from invest_system.validators.schema_validator import SchemaValidationError


def test_repository_appends_all_snapshot_types(tmp_path) -> None:
    repo = SQLiteRepository(tmp_path / "test.sqlite")
    repo.init_db()
    market = make_market_snapshot()
    research = make_research_snapshot(market["snapshot_id"])
    target_pool = make_target_pool_snapshot()
    decision = make_decision_record(market["snapshot_id"], research["snapshot_id"])
    repo.append_market_snapshot(market)
    repo.append_research_snapshot(research)
    repo.append_target_pool_snapshot(target_pool)
    repo.append_decision_record(decision)
    portfolio = ShadowPortfolioEngine(repo).apply_decision(
        decision=decision,
        previous_portfolio=None,
    )

    repo.append_portfolio_snapshot(portfolio)

    assert repo.table_counts() == {
        "market_snapshot": 1,
        "research_snapshot": 1,
        "target_pool_snapshot": 1,
        "decision_record": 1,
        "portfolio_snapshot": 1,
        "event_log": 5,
    }


def test_repository_rejects_invalid_research_before_insert(tmp_path) -> None:
    repo = SQLiteRepository(tmp_path / "test.sqlite")
    repo.init_db()
    payload = make_research_snapshot("market-demo")
    payload = deepcopy(payload)
    del payload["key_facts"]

    with pytest.raises(SchemaValidationError):
        repo.append_research_snapshot(payload)

    assert repo.table_counts()["research_snapshot"] == 0


def test_snapshot_tables_are_append_only(tmp_path) -> None:
    db_path = tmp_path / "test.sqlite"
    repo = SQLiteRepository(db_path)
    repo.init_db()
    repo.append_market_snapshot(make_market_snapshot())

    with closing(sqlite3.connect(db_path)) as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE market_snapshot SET status = 'blocked' WHERE id = 1")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("DELETE FROM market_snapshot WHERE id = 1")


def test_target_pool_snapshot_is_append_only(tmp_path) -> None:
    db_path = tmp_path / "test.sqlite"
    repo = SQLiteRepository(db_path)
    repo.init_db()
    repo.append_target_pool_snapshot(make_target_pool_snapshot())

    with closing(sqlite3.connect(db_path)) as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE target_pool_snapshot SET status = 'blocked' WHERE id = 1")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("DELETE FROM target_pool_snapshot WHERE id = 1")
