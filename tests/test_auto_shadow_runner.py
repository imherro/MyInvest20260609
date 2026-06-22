from __future__ import annotations

from invest_system.golden import seed_multiday_repository
from invest_system.guidance import compute_guidance_state
from invest_system.repositories import SQLiteRepository
from invest_system.shadow import run_auto_shadow_portfolio


def test_auto_shadow_runner_applies_model_rebalance_append_only(tmp_path) -> None:
    repo = SQLiteRepository(tmp_path / "auto_shadow.sqlite")
    seed_multiday_repository(repo)
    before = repo.table_counts()

    result = run_auto_shadow_portfolio(repo, trigger="test_auto_shadow")
    after = repo.table_counts()
    portfolio = repo.latest_portfolio()
    guidance = compute_guidance_state(repo)

    assert result["status"] == "applied"
    assert result["decision_id"].startswith("decision-2026-06-15-auto-shadow-")
    assert result["portfolio_id"].startswith("shadow-2026-06-15-decision-2026-06-15-auto-shadow-")
    assert after["decision_record"] == before["decision_record"] + 1
    assert after["portfolio_snapshot"] == before["portfolio_snapshot"] + 1
    assert after["event_log"] == before["event_log"] + 2
    assert portfolio["cash_weight"] >= 0.05
    assert round(portfolio["holdings_weight"]["510300.SH"] + portfolio["holdings_weight"]["159915.SZ"], 6) <= 0.65
    assert "159999.SZ" not in portfolio["holdings_weight"]
    assert "588000.SH" not in portfolio["holdings_weight"]
    assert all(item["is_paper"] for item in portfolio["paper_trades"])
    assert guidance["risk_boundaries"]["status"] == "pass"


def test_auto_shadow_runner_skips_when_model_target_unchanged(tmp_path) -> None:
    repo = SQLiteRepository(tmp_path / "auto_shadow_skip.sqlite")
    seed_multiday_repository(repo)
    first = run_auto_shadow_portfolio(repo, trigger="test_auto_shadow")
    before = repo.table_counts()

    second = run_auto_shadow_portfolio(repo, trigger="test_auto_shadow")
    after = repo.table_counts()

    assert first["status"] == "applied"
    assert second["status"] == "skipped"
    assert second["reason"] == "model_target_unchanged"
    assert after == before


def test_auto_shadow_runner_refreshes_nav_when_target_unchanged_with_returns(tmp_path) -> None:
    repo = SQLiteRepository(tmp_path / "auto_shadow_refresh.sqlite")
    seed_multiday_repository(repo)
    first = run_auto_shadow_portfolio(repo, trigger="test_auto_shadow")
    before = repo.table_counts()
    previous = repo.latest_portfolio()

    second = run_auto_shadow_portfolio(
        repo,
        trigger="test_auto_shadow",
        market_returns={
            "159915.SZ": -0.01,
            "510300.SH": 0.01,
            "511360.SH": 0.001,
        },
        benchmark_returns={"沪深300": 0.01},
    )
    after = repo.table_counts()
    portfolio = repo.latest_portfolio()

    assert first["status"] == "applied"
    assert second["status"] == "applied"
    assert second["reason"] == "market_return_refresh"
    assert second["paper_changes"] == []
    assert after["decision_record"] == before["decision_record"] + 1
    assert after["portfolio_snapshot"] == before["portfolio_snapshot"] + 1
    assert after["event_log"] == before["event_log"] + 2
    assert portfolio["holdings_weight"] == previous["holdings_weight"]
    assert portfolio["nav_index"] != previous["nav_index"]
