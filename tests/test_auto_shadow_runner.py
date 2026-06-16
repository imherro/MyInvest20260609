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
