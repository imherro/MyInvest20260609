from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from invest_system.demo import make_decision_record, make_market_snapshot, make_research_snapshot
from invest_system.repositories import SQLiteRepository
from invest_system.shadow import ShadowPortfolioEngine


MULTIDAY_DATES = ["2026-06-13", "2026-06-14", "2026-06-15"]


def seed_multiday_repository(repo: SQLiteRepository) -> dict[str, Any]:
    repo.init_db()
    previous_portfolio: dict[str, Any] | None = None
    inserted: list[dict[str, str]] = []

    for index, basis_date in enumerate(MULTIDAY_DATES):
        qmt_event_id = f"qmt-mock-{basis_date}"
        repo.append_market_event(
            object_id=qmt_event_id,
            basis_date=basis_date,
            payload={
                "schema_version": "1.0",
                "event_subtype": "qmt_position_import",
                "import_id": qmt_event_id,
                "basis_date": basis_date,
                "generated_at": _utc_now(),
                "status": "imported",
                "symbols": _symbols_for_day(index),
                "data_gaps": [],
                "privacy": {"ratio_only": True, "paper_only": True},
            },
        )
        market = _market_for_day(index, basis_date)
        research = _research_for_day(index, basis_date, market["snapshot_id"])
        target_pool = _target_pool_for_day(index, basis_date)
        decision = _decision_for_day(index, basis_date, market["snapshot_id"], research["snapshot_id"])

        repo.append_market_snapshot(market)
        repo.append_research_snapshot(research)
        repo.append_target_pool_snapshot(target_pool)
        repo.append_decision_record(decision)
        portfolio = ShadowPortfolioEngine(repo).apply_decision(
            decision=decision,
            previous_portfolio=previous_portfolio,
            market_returns=_market_returns_for_day(index),
            benchmark_returns={"CSI300": round(index * 0.002, 6)},
        )
        repo.append_portfolio_snapshot(portfolio)
        previous_portfolio = portfolio
        inserted.append(
            {
                "basis_date": basis_date,
                "market": market["snapshot_id"],
                "research": research["snapshot_id"],
                "target_pool": target_pool["target_pool_id"],
                "decision": decision["decision_id"],
                "portfolio": portfolio["portfolio_id"],
            }
        )

    return {"status": "ok", "days": inserted}


def _market_for_day(index: int, basis_date: str) -> dict[str, Any]:
    payload = deepcopy(make_market_snapshot())
    payload["snapshot_id"] = f"market-{basis_date}-golden"
    payload["basis_date"] = basis_date
    payload["generated_at"] = _utc_now()
    payload["next_review_date"] = _next_date(index)
    payload["trace"]["fact_pack_id"] = f"fact-pack-{basis_date}-golden"
    payload["payload"]["market_score"] = 60 + index
    return payload


def _research_for_day(index: int, basis_date: str, market_id: str) -> dict[str, Any]:
    payload = deepcopy(make_research_snapshot(market_id))
    payload["snapshot_id"] = f"research-{basis_date}-golden"
    payload["basis_date"] = basis_date
    payload["generated_at"] = _utc_now()
    payload["next_review_date"] = _next_date(index)
    payload["trace"]["fact_pack_id"] = f"fact-pack-{basis_date}-golden"
    payload["trace"]["source_market_snapshot_id"] = market_id
    payload["payload"]["deviation_pp"]["growth"] = -5.0 + index
    return payload


def _target_pool_for_day(index: int, basis_date: str) -> dict[str, Any]:
    approved = ["510300.SH", "159915.SZ", "511360.SH"]
    research_first = ["159999.SZ"]
    if index >= 1:
        research_first.append("588000.SH")
    if index >= 2:
        approved.append("512000.SH")
    return {
        "schema_version": "1.0",
        "target_pool_id": f"target-pool-{basis_date}-golden",
        "basis_date": basis_date,
        "generated_at": _utc_now(),
        "source": "seed",
        "status": "active",
        "entries": [
            {"pool_type": "approved", "symbols": approved},
            {"pool_type": "research_first", "symbols": research_first},
            {"pool_type": "blocked", "symbols": []},
        ],
    }


def _decision_for_day(index: int, basis_date: str, market_id: str, research_id: str) -> dict[str, Any]:
    payload = deepcopy(make_decision_record(market_id, research_id))
    payload["decision_id"] = f"decision-{basis_date}-golden"
    payload["basis_date"] = basis_date
    payload["generated_at"] = _utc_now()
    payload["source_research_ids"] = [research_id]
    payload["trace"]["source_market_snapshot_id"] = market_id
    payload["trace"]["source_research_snapshot_ids"] = [research_id]
    weights = _weights_for_day(index)
    for action in payload["decision_actions"]:
        if action["symbol"] in weights:
            target = weights[action["symbol"]]
            action["target_weight"] = target
            action["delta_weight_pp"] = round((target - action["current_weight"]) * 100, 4)
    return payload


def _weights_for_day(index: int) -> dict[str, float]:
    if index == 0:
        return {"510300.SH": 0.4, "159915.SZ": 0.35, "511360.SH": 0.25}
    if index == 1:
        return {"510300.SH": 0.38, "159915.SZ": 0.37, "511360.SH": 0.25}
    return {"510300.SH": 0.34, "159915.SZ": 0.41, "511360.SH": 0.25}


def _symbols_for_day(index: int) -> list[str]:
    symbols = ["510300.SH", "159915.SZ", "511360.SH", "159999.SZ"]
    if index >= 1:
        symbols.append("588000.SH")
    if index >= 2:
        symbols.append("512000.SH")
    return symbols


def _market_returns_for_day(index: int) -> dict[str, float]:
    if index == 0:
        return {}
    if index == 1:
        return {"510300.SH": 0.004, "159915.SZ": -0.002, "511360.SH": 0.001}
    return {"510300.SH": -0.003, "159915.SZ": 0.006, "511360.SH": 0.001}


def _next_date(index: int) -> str:
    if index + 1 >= len(MULTIDAY_DATES):
        return "2026-06-16"
    return MULTIDAY_DATES[index + 1]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")

