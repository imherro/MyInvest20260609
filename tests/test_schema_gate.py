from __future__ import annotations

from copy import deepcopy

import pytest

from invest_system.demo import make_decision_record, make_research_snapshot
from invest_system.validators.policies import PolicyViolation, assert_decision_policy
from invest_system.validators.schema_validator import SchemaValidationError, validate_or_raise


def test_research_schema_accepts_valid_snapshot() -> None:
    payload = make_research_snapshot("market-demo")

    validate_or_raise(payload, "research.schema.json")


def test_research_schema_rejects_missing_common_field() -> None:
    payload = make_research_snapshot("market-demo")
    del payload["executive_summary"]

    with pytest.raises(SchemaValidationError):
        validate_or_raise(payload, "research.schema.json")


def test_decision_policy_blocks_action_when_gates_fail() -> None:
    payload = make_decision_record("market-demo", "research-demo")
    payload = deepcopy(payload)
    payload["decision_actions"][0]["gates"]["valuation"] = "blocked"

    with pytest.raises(PolicyViolation):
        assert_decision_policy(payload)


def test_decision_policy_blocks_research_first_positive_weight() -> None:
    payload = make_decision_record("market-demo", "research-demo")
    payload = deepcopy(payload)
    payload["decision_actions"][-1]["target_weight"] = 0.1

    with pytest.raises(PolicyViolation):
        assert_decision_policy(payload)

