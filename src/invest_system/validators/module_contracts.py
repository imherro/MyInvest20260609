from __future__ import annotations

import re
from typing import Any


class ModuleContractViolation(ValueError):
    pass


class ThemeValidationError(ModuleContractViolation):
    pass


SIGNAL_TYPES = ("liquidity", "valuation", "momentum", "structural", "risk_event")
THEME_STATES = ("emerging", "strengthening", "dominant", "weakening", "exhausted")

MODULE_CONTRACTS = {
    "market": {
        "allowed_outputs": ("macro_trend", "liquidity_state", "risk_regime"),
        "forbidden_outputs": ("symbols", "themes"),
    },
    "theme": {
        "allowed_outputs": ("theme_state", "sector", "signal_type"),
        "forbidden_outputs": ("symbols", "stock_list"),
    },
    "stock": {
        "allowed_outputs": ("valuation_state", "research_first_status", "risk_score"),
        "forbidden_outputs": ("macro_view", "theme_strength"),
    },
}

THEME_MODULES = {"theme_research"}
STOCK_MODULES = {"stock_valuation"}
MARKET_MODULES = {"market_position"}

_A_SHARE_CODE = re.compile(r"\b(?:[036]\d{5}|[15]\d{5})\.(?:SH|SZ)\b", re.IGNORECASE)
_THEME_FORBIDDEN_KEYS = {
    "symbol",
    "symbols",
    "stock",
    "stocks",
    "stock_code",
    "stock_codes",
    "stock_list",
    "individual_security_list",
    "leading_symbols",
    "related_etfs",
    "tradable_baskets",
    "ticker_mapping",
    "display_symbols",
}
_STOCK_FORBIDDEN_KEYS = {"theme_list", "theme_strength", "macro_view"}
_MARKET_FORBIDDEN_KEYS = {"symbols", "themes", "theme_list"}


def validate_module_contract(output: dict[str, Any]) -> None:
    module = output.get("module")
    if module in THEME_MODULES:
        validate_no_cross_layer_leak(output, "theme")
        payload = output.get("payload", {})
        assert_signal_type(payload.get("signal_type"), "$.payload.signal_type")
        _assert_theme_state(payload)
    elif module in STOCK_MODULES:
        validate_no_cross_layer_leak(output, "stock")
        payload = output.get("payload", {})
        assert_signal_type(payload.get("signal_type"), "$.payload.signal_type")
        _validate_stock_research_first_gate(output)
    elif module in MARKET_MODULES:
        validate_no_cross_layer_leak(output, "market")
        payload = output.get("payload", {})
        assert_signal_type(payload.get("signal_type"), "$.payload.signal_type")


def validate_payload_contract(module: str, payload: dict[str, Any]) -> None:
    if module in THEME_MODULES:
        validate_no_cross_layer_leak(payload, "theme")
    elif module in STOCK_MODULES:
        validate_no_cross_layer_leak(payload, "stock")
    elif module in MARKET_MODULES:
        validate_no_cross_layer_leak(payload, "market")


def validate_no_cross_layer_leak(output: Any, layer: str) -> None:
    forbidden = _forbidden_keys(layer)
    for path, key, value in _walk(output):
        if key and _key_is_forbidden(layer, key, forbidden):
            if layer == "theme":
                raise ThemeValidationError(f"{path}: theme层禁止包含任何股票代码或股票字段")
            raise ModuleContractViolation(f"{path}: {layer} layer forbids {key}")
        if layer == "theme" and isinstance(value, str) and _A_SHARE_CODE.search(value):
            raise ThemeValidationError("theme层禁止包含任何股票代码")
        if layer == "market" and key and key.lower() == "symbol":
            raise ModuleContractViolation(f"{path}: market layer forbids symbol output")


def assert_signal_type(values: Any, path: str = "$.signal_type") -> None:
    if not isinstance(values, list) or not values:
        raise ModuleContractViolation(f"{path}: signal_type must be a non-empty list")
    invalid = [value for value in values if value not in SIGNAL_TYPES]
    if invalid:
        raise ModuleContractViolation(f"{path}: unsupported signal_type {invalid}")


def _validate_stock_research_first_gate(output: dict[str, Any]) -> None:
    payload = output.get("payload", {})
    gates = payload.get("gates", {})
    if not isinstance(gates, dict):
        raise ModuleContractViolation("$.payload.gates: stock research requires explicit gates")
    missing_or_blocked = [
        name
        for name in ("profile", "valuation", "liquidity")
        if gates.get(name) in {None, "missing", "blocked", "fail"}
    ]
    if missing_or_blocked:
        if output.get("status") != "blocked":
            raise ModuleContractViolation("$.status: incomplete stock gates must fail closed as blocked")
        if output.get("actionability") != "research_first":
            raise ModuleContractViolation("$.actionability: incomplete stock gates require research_first")
        if payload.get("research_first_status") != "BLOCKED":
            raise ModuleContractViolation("$.payload.research_first_status: incomplete gates require BLOCKED")


def _assert_theme_state(payload: Any) -> None:
    if not isinstance(payload, dict):
        raise ModuleContractViolation("$.payload: theme payload must be an object")
    if payload.get("theme_state") not in THEME_STATES:
        raise ModuleContractViolation("$.payload.theme_state: invalid theme_state")


def _key_is_forbidden(layer: str, key: str, forbidden: set[str]) -> bool:
    lowered = key.lower()
    if lowered in forbidden:
        return True
    if layer == "theme" and any(term in lowered for term in ("symbol", "stock", "ticker")):
        return True
    return False


def _forbidden_keys(layer: str) -> set[str]:
    if layer == "theme":
        return _THEME_FORBIDDEN_KEYS
    if layer == "stock":
        return _STOCK_FORBIDDEN_KEYS
    if layer == "market":
        return _MARKET_FORBIDDEN_KEYS
    raise ModuleContractViolation(f"unsupported layer: {layer}")


def _walk(value: Any, path: str = "$", key: str | None = None):
    yield path, key, value
    if isinstance(value, dict):
        for child_key, child_value in value.items():
            yield from _walk(child_value, f"{path}.{child_key}", child_key)
    elif isinstance(value, list):
        for index, child_value in enumerate(value):
            yield from _walk(child_value, f"{path}[{index}]", None)
