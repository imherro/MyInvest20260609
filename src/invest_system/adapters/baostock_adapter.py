from __future__ import annotations

import importlib.util
from typing import Any


def collect_baostock(request: dict[str, Any]) -> dict[str, Any]:
    if not request["allow_network"]:
        return _unavailable("network_disabled")
    if importlib.util.find_spec("baostock") is None:
        return _unavailable("python_package_missing")

    try:
        import baostock as bs  # type: ignore[import-not-found]

        login = bs.login()
        if login.error_code != "0":
            return _failed(f"login_failed:{login.error_msg}")
        symbols = [_history_row(bs, symbol, request["basis_date"]) for symbol in request["symbols"]]
        symbol_rows = [row for row in symbols if row is not None]
        missing_symbols = _missing_codes(request["symbols"], symbol_rows)
        bs.logout()
        return {
            "source": "baostock",
            "status": "ok",
            "indices": [],
            "symbols": symbol_rows,
            "macro": [],
            "data_gaps": [f"missing_symbol:{symbol}" for symbol in missing_symbols],
            "conflicts": [],
        }
    except Exception as exc:  # noqa: BLE001
        return _failed(str(exc))


def _history_row(bs: Any, symbol: str, basis_date: str) -> dict[str, Any] | None:
    query = bs.query_history_k_data_plus(
        _baostock_code(symbol),
        "date,code,close,pctChg,turn",
        start_date=basis_date,
        end_date=basis_date,
        frequency="d",
        adjustflag="3",
    )
    if query.error_code != "0" or not query.next():
        return None
    row = query.get_row_data()
    return {
        "symbol": symbol,
        "last_price": float(row[2]),
        "daily_return": float(row[3]) / 100,
        "turnover_ratio": max(0.0, float(row[4]) / 100),
        "source": "baostock",
    }


def _baostock_code(symbol: str) -> str:
    code, exchange = symbol.split(".")
    prefix = "sh" if exchange == "SH" else "sz"
    return f"{prefix}.{code}"


def _missing_codes(requested: list[str], rows: list[dict[str, Any]]) -> list[str]:
    present = {row["symbol"] for row in rows}
    return [symbol for symbol in requested if symbol not in present]


def _unavailable(reason: str) -> dict[str, Any]:
    return _result("unavailable", reason)


def _failed(reason: str) -> dict[str, Any]:
    return _result("failed", reason)


def _result(status: str, reason: str) -> dict[str, Any]:
    return {
        "source": "baostock",
        "status": status,
        "indices": [],
        "symbols": [],
        "macro": [],
        "data_gaps": [reason],
        "conflicts": [],
    }
