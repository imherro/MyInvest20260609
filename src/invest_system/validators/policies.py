from __future__ import annotations

import re
from typing import Any


class PolicyViolation(ValueError):
    pass


SENSITIVE_FIELD_NAMES = {
    "account_id",
    "total_asset",
    "cash_balance",
    "position_amount",
    "market_value",
    "share_count",
    "available_quantity",
    "trade_amount",
    "profit_amount",
    "order_id",
    "fill_id",
    "trade_id",
    "local_path",
    "absolute_path",
}

SENSITIVE_TERMS = (
    "真实账户号",
    "总资产",
    "持仓金额",
    "股数",
    "真实订单",
    "成交明细",
)

WINDOWS_ABSOLUTE_PATH = re.compile(r"[A-Za-z]:\\")


def assert_no_sensitive_content(payload: Any) -> None:
    for path, key, value in _walk(payload):
        normalized = key.lower() if key else ""
        if normalized in SENSITIVE_FIELD_NAMES:
            raise PolicyViolation(f"{path}: sensitive field is not allowed")
        if isinstance(value, str):
            if WINDOWS_ABSOLUTE_PATH.search(value):
                raise PolicyViolation(f"{path}: local absolute path is not allowed")
            if any(term in value for term in SENSITIVE_TERMS):
                raise PolicyViolation(f"{path}: sensitive text is not allowed")


def assert_research_policy(payload: dict[str, Any]) -> None:
    assert_no_sensitive_content(payload)
    if payload["conclusion_strength"] == "weak" and payload["actionability"] == "rebalance_candidate":
        raise PolicyViolation("$.actionability: weak conclusion cannot be a rebalance candidate")


def assert_decision_policy(payload: dict[str, Any]) -> None:
    assert_no_sensitive_content(payload)
    if payload["status"] == "finalized" and not (payload["chatgpt_reviewed"] and payload["human_approval"]):
        raise PolicyViolation("$.status: finalized requires ChatGPT review and human approval")

    for index, item in enumerate(payload["decision_actions"]):
        gates = item["gates"]
        action = item["action"]
        if gates["research_first"] and item["target_weight"] != 0:
            raise PolicyViolation(f"$.decision_actions[{index}]: ResearchFirst target weight must be 0")
        if gates["research_first"] and action not in {"research_first", "hold", "no_action"}:
            raise PolicyViolation(f"$.decision_actions[{index}]: ResearchFirst cannot enter an actionable decision")
        if action in {"buy", "sell", "rebalance_candidate"}:
            if any(gates[name] != "pass" for name in ("profile", "valuation", "liquidity")):
                raise PolicyViolation(f"$.decision_actions[{index}]: actionable decision requires all gates to pass")


def assert_portfolio_policy(payload: dict[str, Any]) -> None:
    assert_no_sensitive_content(payload)
    constraints = payload["constraints"]
    if payload["status"] == "simulated" and not all(constraints.values()):
        raise PolicyViolation("$.constraints: simulated portfolio requires every constraint to pass")

    total_weight = payload["cash_weight"] + sum(payload["holdings_weight"].values())
    if abs(total_weight - 1.0) > 0.0001:
        raise PolicyViolation("$.holdings_weight: holdings plus cash must equal 1")

    for index, item in enumerate(payload["paper_trades"]):
        if not item["is_paper"]:
            raise PolicyViolation(f"$.paper_trades[{index}]: shadow execution must be paper-only")


def _walk(value: Any, path: str = "$", key: str | None = None):
    yield path, key, value
    if isinstance(value, dict):
        for child_key, child_value in value.items():
            child_path = f"{path}.{child_key}"
            yield from _walk(child_value, child_path, child_key)
    elif isinstance(value, list):
        for index, child_value in enumerate(value):
            yield from _walk(child_value, f"{path}[{index}]", None)

