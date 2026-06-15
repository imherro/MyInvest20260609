from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from invest_system.repositories import SQLiteRepository


class ShadowPortfolioEngine:
    def __init__(self, repo: SQLiteRepository, rebalance_threshold: float = 0.03) -> None:
        self.repo = repo
        self.rebalance_threshold = rebalance_threshold

    def apply_decision(
        self,
        *,
        decision: dict[str, Any],
        previous_portfolio: dict[str, Any] | None,
        market_returns: dict[str, float] | None = None,
        benchmark_returns: dict[str, float] | None = None,
        as_of: str | None = None,
    ) -> dict[str, Any]:
        market_returns = market_returns or {}
        benchmark_returns = benchmark_returns or {}
        previous = previous_portfolio or _empty_portfolio()
        target_pool = self.repo.target_pool_sets(as_of)

        if not _is_decision_approved(decision):
            return self._blocked_snapshot(decision, previous, benchmark_returns, target_pool["target_pool_id"])

        current_weights = dict(previous.get("holdings_weight", {}))
        target_weights = self._target_weights(decision, target_pool)
        pnl_ratio = sum(current_weights.get(symbol, 0) * market_returns.get(symbol, 0) for symbol in current_weights)
        nav_index = round(previous["nav_index"] * (1 + pnl_ratio), 6)
        paper_trades = self._paper_trades(current_weights, target_weights)
        turnover = round(sum(abs(item["target_weight"] - item["current_weight"]) for item in paper_trades) / 2, 6)
        cash_weight = round(1 - sum(target_weights.values()), 6)

        if cash_weight < -0.000001:
            raise ValueError("target weights cannot exceed 1")

        return {
            "schema_version": "1.0",
            "portfolio_id": f"shadow-{decision['basis_date']}-{decision['decision_id']}",
            "basis_date": decision["basis_date"],
            "generated_at": _utc_now(),
            "source_decision_id": decision["decision_id"],
            "source_target_pool_id": target_pool["target_pool_id"],
            "status": "simulated",
            "nav_index": nav_index,
            "cash_weight": max(cash_weight, 0),
            "holdings_weight": target_weights,
            "paper_trades": paper_trades,
            "turnover": turnover,
            "drawdown": min(0, round(pnl_ratio, 6)),
            "benchmark_returns": benchmark_returns,
            "pnl_ratio": round(pnl_ratio, 6),
            "constraints": {
                "approved_target_pool_only": True,
                "research_first_weight_zero": True,
                "paper_only": True,
            },
        }

    def _target_weights(
        self,
        decision: dict[str, Any],
        target_pool: dict[str, set[str] | str | None],
    ) -> dict[str, float]:
        target_weights: dict[str, float] = {}
        approved_symbols = target_pool["approved"]
        research_first_symbols = target_pool["research_first"]
        blocked_symbols = target_pool["blocked"]
        if not isinstance(approved_symbols, set) or not isinstance(research_first_symbols, set):
            raise ValueError("target pool state is unavailable")
        if not isinstance(blocked_symbols, set):
            raise ValueError("target pool state is unavailable")

        for action in decision["decision_actions"]:
            symbol = action["symbol"]
            target_weight = action["target_weight"]
            is_research_first = action["gates"]["research_first"] or symbol in research_first_symbols
            if is_research_first and target_weight > 0:
                raise ValueError("ResearchFirst symbol cannot receive shadow weight")
            if symbol in blocked_symbols and target_weight > 0:
                raise ValueError("blocked symbol cannot receive shadow weight")
            if target_weight > 0 and symbol not in approved_symbols:
                raise ValueError("shadow portfolio cannot use symbols outside approved target pool")
            if target_weight > 0:
                target_weights[symbol] = round(target_weight, 6)
        return target_weights

    def _paper_trades(
        self, current_weights: dict[str, float], target_weights: dict[str, float]
    ) -> list[dict[str, Any]]:
        paper_trades: list[dict[str, Any]] = []
        symbols = sorted(set(current_weights) | set(target_weights))
        for symbol in symbols:
            current_weight = current_weights.get(symbol, 0)
            target_weight = target_weights.get(symbol, 0)
            delta = target_weight - current_weight
            if abs(delta) <= self.rebalance_threshold:
                continue
            paper_trades.append(
                {
                    "symbol": symbol,
                    "action": "increase" if delta > 0 else "decrease",
                    "current_weight": round(current_weight, 6),
                    "target_weight": round(target_weight, 6),
                    "delta_weight_pp": round(delta * 100, 4),
                    "is_paper": True,
                    "reason": "decision_target_weight_rebalance",
                }
            )
        return paper_trades

    def _blocked_snapshot(
        self,
        decision: dict[str, Any],
        previous: dict[str, Any],
        benchmark_returns: dict[str, float],
        source_target_pool_id: str | None,
    ) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "portfolio_id": f"blocked-{decision['basis_date']}-{decision['decision_id']}",
            "basis_date": decision["basis_date"],
            "generated_at": _utc_now(),
            "source_decision_id": decision["decision_id"],
            "source_target_pool_id": source_target_pool_id,
            "status": "blocked",
            "nav_index": previous["nav_index"],
            "cash_weight": previous["cash_weight"],
            "holdings_weight": previous["holdings_weight"],
            "paper_trades": [],
            "turnover": 0,
            "drawdown": previous.get("drawdown", 0),
            "benchmark_returns": benchmark_returns,
            "pnl_ratio": 0,
            "constraints": {
                "approved_target_pool_only": True,
                "research_first_weight_zero": True,
                "paper_only": True,
            },
        }


def _is_decision_approved(decision: dict[str, Any]) -> bool:
    return decision["status"] in {"human_approved", "finalized"} and decision["chatgpt_reviewed"] and decision[
        "human_approval"
    ]


def _empty_portfolio() -> dict[str, Any]:
    return {
        "nav_index": 100.0,
        "cash_weight": 1.0,
        "holdings_weight": {},
        "drawdown": 0,
        "source_target_pool_id": None,
    }


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
