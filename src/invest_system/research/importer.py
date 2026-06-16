from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from invest_system.repositories import SQLiteRepository
from invest_system.validators.policies import (
    SENSITIVE_FIELD_NAMES,
    SENSITIVE_TERMS,
    WINDOWS_ABSOLUTE_PATH,
    PolicyViolation,
    assert_no_sensitive_content,
    assert_research_policy,
)
from invest_system.validators.module_contracts import validate_module_contract
from invest_system.validators.research_schemas import RESEARCH_PAYLOAD_SCHEMA_BY_MODULE
from invest_system.validators.schema_validator import validate_or_raise


def validate_research_import(repo: SQLiteRepository, payload: Any) -> dict[str, Any]:
    repo.init_db()
    checks: list[dict[str, Any]] = []
    if not isinstance(payload, dict):
        checks.append(_check("json_object", "failed", "输入必须是 JSON 对象。"))
        return _validation_payload(payload, checks)

    _append_schema_checks(checks, payload)
    _append_policy_checks(checks, payload)
    _append_duplicate_check(checks, repo, payload)
    result = _validation_payload(payload, checks)
    assert_no_sensitive_content(result)
    return result


def append_research_import(repo: SQLiteRepository, payload: Any) -> dict[str, Any]:
    validation = validate_research_import(repo, payload)
    if not validation["append_allowed"]:
        return {"status": "failed", "data": validation}
    inserted = repo.append_research_snapshot(payload)
    result = {
        "status": "ok",
        "data": {
            "snapshot_id": payload["snapshot_id"],
            "basis_date": payload["basis_date"],
            "module": payload["module"],
            "inserted": inserted,
            "validation": validation,
        },
    }
    assert_no_sensitive_content(result)
    return result


def _append_schema_checks(checks: list[dict[str, Any]], payload: dict[str, Any]) -> None:
    try:
        validate_or_raise(payload, "research.schema.json")
        checks.append(_check("research_schema", "pass", "research.schema.json 校验通过。"))
    except Exception as exc:  # noqa: BLE001
        checks.append(_check("research_schema", "failed", _safe_error(exc)))
        return

    module_schema = RESEARCH_PAYLOAD_SCHEMA_BY_MODULE.get(payload.get("module"))
    if not module_schema:
        checks.append(_check("module_payload_schema", "failed", "该模块没有强制 payload schema，拒绝导入。"))
        return
    try:
        validate_or_raise(payload["payload"], module_schema)
        checks.append(_check("module_payload_schema", "pass", f"{module_schema} 校验通过。"))
    except Exception as exc:  # noqa: BLE001
        checks.append(_check("module_payload_schema", "failed", _safe_error(exc)))
        return
    try:
        validate_module_contract(payload)
        checks.append(_check("module_contract", "pass", "模块分层合同校验通过。"))
    except Exception as exc:  # noqa: BLE001
        checks.append(_check("module_contract", "failed", _safe_error(exc)))


def _append_policy_checks(checks: list[dict[str, Any]], payload: dict[str, Any]) -> None:
    try:
        assert_research_policy(payload)
        checks.append(_check("research_policy", "pass", "ratio-only 与 ResearchFirst 策略校验通过。"))
    except KeyError:
        checks.append(_check("research_policy", "failed", "研究 JSON 缺少策略校验所需字段。"))
    except PolicyViolation:
        checks.append(_check("research_policy", "failed", "研究 JSON 包含策略禁止的字段、文本或行动组合。"))
    except Exception as exc:  # noqa: BLE001
        checks.append(_check("research_policy", "failed", _safe_error(exc)))


def _append_duplicate_check(checks: list[dict[str, Any]], repo: SQLiteRepository, payload: dict[str, Any]) -> None:
    snapshot_id = payload.get("snapshot_id")
    if not snapshot_id:
        checks.append(_check("duplicate_snapshot_id", "skipped", "缺少 snapshot_id，无法检查重复。"))
        return
    exists = any(
        event["type"] == "research" and event["object_id"] == snapshot_id
        for event in repo.timeline()
    )
    if exists:
        checks.append(_check("duplicate_snapshot_id", "failed", "该研究编号已存在，拒绝重复导入。"))
    else:
        checks.append(_check("duplicate_snapshot_id", "pass", "研究编号未在历史中出现。"))


def _validation_payload(payload: Any, checks: list[dict[str, Any]]) -> dict[str, Any]:
    failed = any(item["status"] == "failed" for item in checks)
    warnings = any(item["status"] == "warn" for item in checks)
    status = "failed" if failed else "warn" if warnings else "pass"
    if isinstance(payload, dict):
        snapshot_id = _safe_metadata(payload.get("snapshot_id"))
        basis_date = _safe_metadata(payload.get("basis_date"))
        module = _safe_metadata(payload.get("module"))
    else:
        snapshot_id = None
        basis_date = None
        module = None
    return {
        "schema_version": "1.0",
        "status": status,
        "validated_at": _utc_now(),
        "snapshot_id": snapshot_id,
        "basis_date": basis_date,
        "module": module,
        "checks": checks,
        "append_allowed": status == "pass",
    }


def _check(check_id: str, status: str, detail: str) -> dict[str, str]:
    return {"check_id": check_id, "status": status, "detail": detail}


def _safe_error(exc: Exception) -> str:
    text = str(exc)
    for field in SENSITIVE_FIELD_NAMES:
        text = re.sub(re.escape(field), "blocked_field", text, flags=re.IGNORECASE)
    for term in SENSITIVE_TERMS:
        text = text.replace(term, "blocked_text")
    text = WINDOWS_ABSOLUTE_PATH.sub("local_path_blocked", text)
    if len(text) > 500:
        text = text[:500] + "..."
    return text or "校验失败。"


def _safe_metadata(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    for field in SENSITIVE_FIELD_NAMES:
        text = re.sub(re.escape(field), "blocked_field", text, flags=re.IGNORECASE)
    for term in SENSITIVE_TERMS:
        text = text.replace(term, "blocked_text")
    text = WINDOWS_ABSOLUTE_PATH.sub("local_path_blocked", text)
    return text


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
