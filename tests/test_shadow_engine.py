from __future__ import annotations

from copy import deepcopy

import pytest

from invest_system.demo import make_decision_record
from invest_system.demo import make_target_pool_snapshot
from invest_system.repositories import SQLiteRepository
from invest_system.shadow import ShadowPortfolioEngine


def test_shadow_engine_applies_approved_decision() -> None:
    decision = make_decision_record("market-demo", "research-demo")
    repo = _repo_with_target_pool()

    portfolio = ShadowPortfolioEngine(repo).apply_decision(
        decision=decision,
        previous_portfolio=None,
    )

    assert portfolio["status"] == "simulated"
    assert portfolio["nav_index"] == 100.0
    assert portfolio["holdings_weight"] == {
        "510300.SH": 0.4,
        "159915.SZ": 0.35,
        "511360.SH": 0.25,
    }
    assert portfolio["source_target_pool_id"] == "target-pool-2026-06-15-demo"
    assert all(item["is_paper"] for item in portfolio["paper_trades"])


def test_shadow_engine_blocks_unapproved_decision_without_rebalance() -> None:
    decision = make_decision_record("market-demo", "research-demo")
    decision = deepcopy(decision)
    decision["human_approval"] = False
    decision["status"] = "chatgpt_reviewed"
    repo = _repo_with_target_pool()

    portfolio = ShadowPortfolioEngine(repo).apply_decision(
        decision=decision,
        previous_portfolio=None,
    )

    assert portfolio["status"] == "blocked"
    assert portfolio["paper_trades"] == []
    assert portfolio["holdings_weight"] == {}


def test_shadow_engine_rejects_symbol_outside_approved_pool() -> None:
    decision = make_decision_record("market-demo", "research-demo")
    target_pool = make_target_pool_snapshot()
    target_pool = deepcopy(target_pool)
    target_pool["entries"][0]["symbols"].remove("159915.SZ")
    repo = _repo_with_target_pool(target_pool)

    with pytest.raises(ValueError):
        ShadowPortfolioEngine(repo).apply_decision(
            decision=decision,
            previous_portfolio=None,
        )


def test_shadow_engine_rejects_research_first_positive_weight() -> None:
    decision = make_decision_record("market-demo", "research-demo")
    decision = deepcopy(decision)
    decision["decision_actions"][-1]["target_weight"] = 0.1
    repo = _repo_with_target_pool()

    with pytest.raises(ValueError):
        ShadowPortfolioEngine(repo).apply_decision(
            decision=decision,
            previous_portfolio=None,
        )


def _repo_with_target_pool(target_pool: dict | None = None) -> SQLiteRepository:
    import os
    import tempfile

    fd, path = tempfile.mkstemp(suffix=".sqlite")
    os.close(fd)
    repo = SQLiteRepository(path)
    repo.init_db()
    repo.append_target_pool_snapshot(target_pool or make_target_pool_snapshot())
    return repo
