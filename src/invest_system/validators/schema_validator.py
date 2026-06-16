from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any


SCHEMA_ROOT = Path(__file__).resolve().parents[3] / "schemas"


@dataclass
class SchemaValidationError(ValueError):
    errors: list[str]

    def __str__(self) -> str:
        return "; ".join(self.errors)


class SchemaViolationError(SchemaValidationError):
    pass


def load_schema(schema_name: str) -> dict[str, Any]:
    schema_path = SCHEMA_ROOT / schema_name
    with schema_path.open("r", encoding="utf-8") as schema_file:
        return json.load(schema_file)


def validate_or_raise(payload: dict[str, Any], schema_name: str) -> None:
    schema = load_schema(schema_name)
    errors: list[str] = []
    _validate_value(payload, schema, "$", errors)
    if errors:
        raise SchemaViolationError(errors)


def validate(payload: dict[str, Any], schema_name: str) -> dict[str, Any]:
    try:
        validate_or_raise(payload, schema_name)
    except SchemaValidationError as exc:
        return {"valid": False, "errors": exc.errors}
    return {"valid": True, "errors": []}


def _validate_value(value: Any, schema: dict[str, Any], path: str, errors: list[str]) -> None:
    expected_type = schema.get("type")
    if expected_type is not None and not _type_matches(value, expected_type):
        errors.append(f"{path}: expected {expected_type}, got {type(value).__name__}")
        return

    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: value is not in allowed enum")

    if isinstance(value, str):
        _validate_string(value, schema, path, errors)
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        _validate_number(value, schema, path, errors)
    elif isinstance(value, list):
        _validate_array(value, schema, path, errors)
    elif isinstance(value, dict):
        _validate_object(value, schema, path, errors)


def _type_matches(value: Any, expected_type: str | list[str]) -> bool:
    if isinstance(expected_type, list):
        return any(_type_matches(value, item) for item in expected_type)
    if expected_type == "object":
        return isinstance(value, dict)
    if expected_type == "array":
        return isinstance(value, list)
    if expected_type == "string":
        return isinstance(value, str)
    if expected_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type == "boolean":
        return isinstance(value, bool)
    if expected_type == "null":
        return value is None
    return False


def _validate_string(value: str, schema: dict[str, Any], path: str, errors: list[str]) -> None:
    if "minLength" in schema and len(value) < schema["minLength"]:
        errors.append(f"{path}: string is shorter than minLength")
    if schema.get("format") == "date":
        try:
            date.fromisoformat(value)
        except ValueError:
            errors.append(f"{path}: invalid date format")
    if schema.get("format") == "date-time":
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            errors.append(f"{path}: invalid date-time format")


def _validate_number(value: int | float, schema: dict[str, Any], path: str, errors: list[str]) -> None:
    if "minimum" in schema and value < schema["minimum"]:
        errors.append(f"{path}: number is below minimum")
    if "maximum" in schema and value > schema["maximum"]:
        errors.append(f"{path}: number is above maximum")


def _validate_array(value: list[Any], schema: dict[str, Any], path: str, errors: list[str]) -> None:
    if "minItems" in schema and len(value) < schema["minItems"]:
        errors.append(f"{path}: array has fewer items than minItems")
    item_schema = schema.get("items")
    if item_schema:
        for index, item in enumerate(value):
            _validate_value(item, item_schema, f"{path}[{index}]", errors)


def _validate_object(value: dict[str, Any], schema: dict[str, Any], path: str, errors: list[str]) -> None:
    required = schema.get("required", [])
    for key in required:
        if key not in value:
            errors.append(f"{path}.{key}: missing required field")

    properties = schema.get("properties", {})
    additional = schema.get("additionalProperties", True)
    for key, item in value.items():
        child_path = f"{path}.{key}"
        if key in properties:
            _validate_value(item, properties[key], child_path, errors)
        elif additional is False:
            errors.append(f"{child_path}: additional property is not allowed")
        elif isinstance(additional, dict):
            _validate_value(item, additional, child_path, errors)
