from __future__ import annotations

import re
from copy import deepcopy
from typing import Any


class CrossLayerIntegrityError(ValueError):
    pass


class CrossLayerLeakError(CrossLayerIntegrityError):
    pass


_A_SHARE_CODE = re.compile(r"\b(?:[036]\d{5}|[15]\d{5})\.(?:SH|SZ)\b", re.IGNORECASE)
_TRACE_FORBIDDEN_KEY_TERMS = (
    "symbol",
    "ticker",
    "stock",
    "stock_id",
    "stock_code",
    "security_id",
    "tradable_id",
    "theme_stock",
)
_TRACE_FORBIDDEN_VALUE_TERMS = (
    "symbol",
    "ticker",
    "stock",
    "security",
    "tradable",
    "stock_id",
    "stock_code",
    "theme_stock",
    "stock_list",
    "representative_symbols",
)
_THEME_FORBIDDEN_KEY_TERMS = ("symbol", "ticker", "stock", "security")
_STOCK_FORBIDDEN_THEME_KEYS = {
    "theme",
    "theme_id",
    "theme_name",
    "theme_list",
    "theme_state",
    "theme_strength",
    "theme_score",
}
_MARKET_FORBIDDEN_KEY_TERMS = ("symbol", "ticker", "stock", "security")
_TRACE_FIELD_NAMES = {"trace", "source_research_ids", "source_research_snapshot_ids"}


class CrossLayerIntegrityValidator:
    def validate_payload(self, payload: dict[str, Any]) -> None:
        module = str(payload.get("module", ""))
        layer = _module_layer(module)
        self.validate_trace(payload)
        if layer == "theme":
            self.validate_theme_layer(payload)
        elif layer == "stock":
            self.validate_stock_layer(payload)
        elif layer == "market":
            self.validate_market_layer(payload)

    def validate_trace(self, payload: dict[str, Any]) -> None:
        for path, key, value in _walk(payload):
            if key in _TRACE_FIELD_NAMES or (path == "$.trace"):
                self._assert_trace_clean(value, path)

    def validate_theme_layer(self, payload: dict[str, Any]) -> None:
        for path, key, value in _walk(payload):
            if key and _A_SHARE_CODE.search(key):
                raise CrossLayerLeakError("THEME_CONTAINS_STOCK_REFERENCE")
            if key and any(term in key.lower() for term in _THEME_FORBIDDEN_KEY_TERMS):
                raise CrossLayerLeakError("THEME_CONTAINS_STOCK_REFERENCE")
            if isinstance(value, str) and _A_SHARE_CODE.search(value):
                raise CrossLayerLeakError("THEME_CONTAINS_STOCK_REFERENCE")

    def validate_stock_layer(self, payload: dict[str, Any]) -> None:
        for path, key, value in _walk(payload.get("payload", {})):
            if key and key.lower() in _STOCK_FORBIDDEN_THEME_KEYS:
                raise CrossLayerLeakError("STOCK_CONTAINS_THEME_BACK_REFERENCE")
            if isinstance(value, str) and _looks_like_theme_mapping(value):
                raise CrossLayerLeakError("STOCK_CONTAINS_THEME_BACK_REFERENCE")

    def validate_market_layer(self, payload: dict[str, Any]) -> None:
        for path, key, value in _walk(payload):
            if key and any(term in key.lower() for term in _MARKET_FORBIDDEN_KEY_TERMS):
                raise CrossLayerLeakError("MARKET_CONTAINS_STOCK_REFERENCE")
            if isinstance(value, str) and _A_SHARE_CODE.search(value):
                raise CrossLayerLeakError("MARKET_CONTAINS_STOCK_REFERENCE")

    def _assert_trace_clean(self, trace: Any, path: str) -> None:
        for item_path, key, value in _walk(trace, path):
            if key and _trace_key_is_forbidden(key):
                raise CrossLayerLeakError("TRACE_CONTAINS_STOCK_REFERENCE")
            if isinstance(value, str) and is_stock_reference_text(value):
                raise CrossLayerLeakError("TRACE_CONTAINS_STOCK_REFERENCE")


def validate_cross_layer_integrity(payload: dict[str, Any]) -> None:
    CrossLayerIntegrityValidator().validate_payload(payload)


def scan_cross_layer_leaks(all_modules: list[dict[str, Any]]) -> None:
    validator = CrossLayerIntegrityValidator()
    theme_terms = _theme_terms(all_modules)
    for payload in all_modules:
        validator.validate_payload(payload)
        if _module_layer(str(payload.get("module", ""))) == "stock":
            _assert_stock_does_not_reference_theme_terms(payload, theme_terms)


def trace_leaks_stock_identity(trace: Any) -> bool:
    try:
        CrossLayerIntegrityValidator()._assert_trace_clean(trace, "$.trace")
    except CrossLayerLeakError:
        return True
    return False


def theme_contains_any_stock_reference(theme: dict[str, Any]) -> bool:
    try:
        CrossLayerIntegrityValidator().validate_theme_layer(theme)
    except CrossLayerLeakError:
        return True
    return False


def sanitize_trace(trace: Any) -> Any:
    if isinstance(trace, dict):
        cleaned: dict[str, Any] = {}
        for key, value in trace.items():
            if _trace_key_is_forbidden(str(key)):
                continue
            sanitized = sanitize_trace(value)
            if sanitized is not None:
                cleaned[key] = sanitized
        return cleaned
    if isinstance(trace, list):
        cleaned_items = [sanitize_trace(item) for item in trace]
        return [item for item in cleaned_items if item is not None]
    if isinstance(trace, str):
        return None if is_stock_reference_text(trace) else trace
    return deepcopy(trace)


def is_stock_reference_text(value: str) -> bool:
    lowered = value.lower()
    return bool(_A_SHARE_CODE.search(value)) or any(term in lowered for term in _TRACE_FORBIDDEN_VALUE_TERMS)


def _trace_key_is_forbidden(key: str) -> bool:
    lowered = key.lower()
    return any(term in lowered for term in _TRACE_FORBIDDEN_KEY_TERMS)


def _module_layer(module: str) -> str | None:
    if module == "market_position":
        return "market"
    if module == "theme_research":
        return "theme"
    if module in {"stock_valuation", "etf_valuation"}:
        return "stock"
    if module in {"portfolio_analysis", "review_score"}:
        return "portfolio"
    return None


def _looks_like_theme_mapping(value: str) -> bool:
    lowered = value.lower()
    return "theme_id" in lowered or "theme_stock" in lowered or "theme_list" in lowered


def _theme_terms(all_modules: list[dict[str, Any]]) -> set[str]:
    terms: set[str] = set()
    for payload in all_modules:
        if _module_layer(str(payload.get("module", ""))) != "theme":
            continue
        inner = payload.get("payload", {})
        for key in ("theme_id", "theme_name"):
            value = inner.get(key)
            if isinstance(value, str) and value:
                terms.add(value.lower())
    return terms


def _assert_stock_does_not_reference_theme_terms(payload: dict[str, Any], theme_terms: set[str]) -> None:
    if not theme_terms:
        return
    for _path, key, value in _walk(payload.get("payload", {})):
        if key and key.lower() in _STOCK_FORBIDDEN_THEME_KEYS:
            raise CrossLayerIntegrityError("STOCK_CONTAINS_THEME_BACK_REFERENCE")
        if isinstance(value, str) and value.lower() in theme_terms:
            raise CrossLayerIntegrityError("STOCK_CONTAINS_THEME_BACK_REFERENCE")


def _walk(value: Any, path: str = "$", key: str | None = None):
    yield path, key, value
    if isinstance(value, dict):
        for child_key, child_value in value.items():
            yield from _walk(child_value, f"{path}.{child_key}", child_key)
    elif isinstance(value, list):
        for index, child_value in enumerate(value):
            yield from _walk(child_value, f"{path}[{index}]", None)
