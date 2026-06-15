from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from invest_system.repositories import SQLiteRepository
from invest_system.shadow import ShadowPortfolioEngine


def seed_demo_repository(repo: SQLiteRepository) -> dict[str, Any]:
    repo.init_db()
    market = make_market_snapshot()
    research = make_research_snapshot(market["snapshot_id"])
    decision = make_decision_record(market["snapshot_id"], research["snapshot_id"])
    portfolio = ShadowPortfolioEngine().apply_decision(
        decision=decision,
        previous_portfolio=None,
        approved_target_pool={"510300.SH", "159915.SZ", "511360.SH"},
        research_first_symbols={"159999.SZ"},
        market_returns={},
        benchmark_returns={"CSI300": 0.0},
    )

    return {
        "market": repo.append_market_snapshot(market),
        "research": repo.append_research_snapshot(research),
        "decision": repo.append_decision_record(decision),
        "portfolio": repo.append_portfolio_snapshot(portfolio),
    }


def make_market_snapshot() -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "snapshot_id": "market-2026-06-15-demo",
        "basis_date": "2026-06-15",
        "generated_at": _utc_now(),
        "module": "market_position",
        "data_sources": ["fixture:index_breadth", "fixture:liquidity"],
        "data_gaps": [],
        "conflicts": [],
        "executive_summary": "Market risk budget supports a balanced equity range.",
        "key_facts": ["Breadth is neutral.", "Liquidity stress is not elevated."],
        "reasoning": ["The score is above neutral while crowding is controlled."],
        "risks": ["Policy shock can lower the valid equity range."],
        "conclusion_strength": "medium",
        "actionability": "rebalance_candidate",
        "confidence": 0.72,
        "invalidation_conditions": ["Breadth deterioration exceeds the configured threshold."],
        "next_review_date": "2026-06-16",
        "must_not_do": ["Do not treat this as real broker execution."],
        "required_human_review": True,
        "status": "human_approved",
        "trace": {"fact_pack_id": "fact-pack-2026-06-15-demo", "source_market_snapshot_id": None},
        "payload": {
            "market_score": 62,
            "equity_min": 0.45,
            "equity_max": 0.65,
            "risk_level": "medium",
            "reason": ["Neutral breadth and controlled crowding."],
            "crowding_penalty": 8,
        },
    }


def make_research_snapshot(source_market_snapshot_id: str) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "snapshot_id": "research-2026-06-15-demo",
        "basis_date": "2026-06-15",
        "generated_at": _utc_now(),
        "module": "portfolio_analysis",
        "data_sources": ["fixture:portfolio_weights", "fixture:market_snapshot"],
        "data_gaps": [],
        "conflicts": [],
        "executive_summary": "Portfolio research identifies approved rebalance candidates and one blocked subject.",
        "key_facts": ["Core bucket is below target.", "One observed symbol lacks a complete profile."],
        "reasoning": ["Approved pool symbols can be simulated; blocked symbols stay at zero weight."],
        "risks": ["Theme reversal can make the target weights stale."],
        "conclusion_strength": "medium",
        "actionability": "rebalance_candidate",
        "confidence": 0.7,
        "invalidation_conditions": ["Approved pool membership changes."],
        "next_review_date": "2026-06-16",
        "must_not_do": ["Do not simulate blocked subjects with positive weight."],
        "required_human_review": True,
        "status": "human_approved",
        "trace": {
            "fact_pack_id": "fact-pack-2026-06-15-demo",
            "source_market_snapshot_id": source_market_snapshot_id,
        },
        "payload": {
            "bucket_weights": {"core": 0.4, "growth": 0.35, "defensive": 0.25},
            "target_ranges": {
                "core": {"min": 0.3, "max": 0.5},
                "growth": {"min": 0.25, "max": 0.5},
                "defensive": {"min": 0.1, "max": 0.35},
            },
            "deviation_pp": {"core": 0.0, "growth": -5.0, "defensive": 5.0},
            "research_first_list": [{"symbol": "159999.SZ", "blocking_reason": "profile_missing"}],
            "action_candidates": [{"symbol": "510300.SH", "target_weight": 0.4}],
        },
    }


def make_decision_record(source_market_snapshot_id: str, source_research_snapshot_id: str) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "decision_id": "decision-2026-06-15-demo",
        "basis_date": "2026-06-15",
        "generated_at": _utc_now(),
        "source_research_ids": [source_research_snapshot_id],
        "status": "human_approved",
        "required_human_review": True,
        "chatgpt_reviewed": True,
        "human_approval": True,
        "decision_actions": [
            {
                "symbol": "510300.SH",
                "action": "buy",
                "current_weight": 0,
                "target_weight": 0.4,
                "delta_weight_pp": 40.0,
                "rationale": ["Approved broad-market candidate with passed gates."],
                "gates": {
                    "profile": "pass",
                    "valuation": "pass",
                    "liquidity": "pass",
                    "research_first": False,
                },
            },
            {
                "symbol": "159915.SZ",
                "action": "buy",
                "current_weight": 0,
                "target_weight": 0.35,
                "delta_weight_pp": 35.0,
                "rationale": ["Approved growth bucket candidate with passed gates."],
                "gates": {
                    "profile": "pass",
                    "valuation": "pass",
                    "liquidity": "pass",
                    "research_first": False,
                },
            },
            {
                "symbol": "511360.SH",
                "action": "buy",
                "current_weight": 0,
                "target_weight": 0.25,
                "delta_weight_pp": 25.0,
                "rationale": ["Approved defensive bucket candidate with passed gates."],
                "gates": {
                    "profile": "pass",
                    "valuation": "pass",
                    "liquidity": "pass",
                    "research_first": False,
                },
            },
            {
                "symbol": "159999.SZ",
                "action": "research_first",
                "current_weight": 0,
                "target_weight": 0,
                "delta_weight_pp": 0,
                "rationale": ["Profile is incomplete, so simulation weight remains zero."],
                "gates": {
                    "profile": "blocked",
                    "valuation": "blocked",
                    "liquidity": "blocked",
                    "research_first": True,
                },
            },
        ],
        "risk_notes": ["This decision is for shadow simulation only."],
        "trace": {
            "source_market_snapshot_id": source_market_snapshot_id,
            "source_research_snapshot_ids": [source_research_snapshot_id],
        },
    }


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")

