from __future__ import annotations

from copy import deepcopy

import pytest

from invest_system.demo import make_decision_record
from invest_system.shadow import ShadowPortfolioEngine


def test_shadow_engine_applies_approved_decision() -> None:
    decision = make_decision_record("market-demo", "research-demo")

    portfolio = ShadowPortfolioEngine().apply_decision(
        decision=decision,
        previous_portfolio=None,
        approved_target_pool={"510300.SH", "159915.SZ", "511360.SH"},
        research_first_symbols={"159999.SZ"},
    )

    assert portfolio["status"] == "simulated"
    assert portfolio["nav_index"] == 100.0
    assert portfolio["holdings_weight"] == {
        "510300.SH": 0.4,
        "159915.SZ": 0.35,
        "511360.SH": 0.25,
    }
    assert all(item["is_paper"] for item in portfolio["paper_trades"])


def test_shadow_engine_blocks_unapproved_decision_without_rebalance() -> None:
    decision = make_decision_record("market-demo", "research-demo")
    decision = deepcopy(decision)
    decision["human_approval"] = False
    decision["status"] = "chatgpt_reviewed"

    portfolio = ShadowPortfolioEngine().apply_decision(
        decision=decision,
        previous_portfolio=None,
        approved_target_pool={"510300.SH", "159915.SZ", "511360.SH"},
        research_first_symbols={"159999.SZ"},
    )

    assert portfolio["status"] == "blocked"
    assert portfolio["paper_trades"] == []
    assert portfolio["holdings_weight"] == {}


def test_shadow_engine_rejects_symbol_outside_approved_pool() -> None:
    decision = make_decision_record("market-demo", "research-demo")

    with pytest.raises(ValueError):
        ShadowPortfolioEngine().apply_decision(
            decision=decision,
            previous_portfolio=None,
            approved_target_pool={"510300.SH", "511360.SH"},
            research_first_symbols={"159999.SZ"},
        )


def test_shadow_engine_rejects_research_first_positive_weight() -> None:
    decision = make_decision_record("market-demo", "research-demo")
    decision = deepcopy(decision)
    decision["decision_actions"][-1]["target_weight"] = 0.1

    with pytest.raises(ValueError):
        ShadowPortfolioEngine().apply_decision(
            decision=decision,
            previous_portfolio=None,
            approved_target_pool={"510300.SH", "159915.SZ", "511360.SH", "159999.SZ"},
            research_first_symbols={"159999.SZ"},
        )

