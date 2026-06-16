from __future__ import annotations

import importlib.util
from datetime import date, timedelta
from typing import Any


def collect_yfinance(request: dict[str, Any]) -> dict[str, Any]:
    if not request["allow_network"]:
        return _unavailable("network_disabled")
    if importlib.util.find_spec("yfinance") is None:
        return _unavailable("python_package_missing")

    try:
        import yfinance as yf  # type: ignore[import-not-found]

        basis_date = date.fromisoformat(request["basis_date"])
        symbols = [_history_row(yf, symbol, basis_date) for symbol in request["symbols"]]
        symbol_rows = [row for row in symbols if row is not None]
        missing_symbols = _missing_codes(request["symbols"], symbol_rows)
        return {
            "source": "yfinance",
            "status": "ok",
            "indices": [],
            "symbols": symbol_rows,
            "macro": [],
            "data_gaps": [f"missing_symbol:{symbol}" for symbol in missing_symbols],
            "conflicts": [],
        }
    except Exception as exc:  # noqa: BLE001
        return _failed(str(exc))


def _history_row(yf: Any, symbol: str, basis_date: date) -> dict[str, Any] | None:
    ticker = yf.Ticker(_yf_symbol(symbol))
    start = (basis_date - timedelta(days=10)).isoformat()
    end = (basis_date + timedelta(days=1)).isoformat()
    history = ticker.history(start=start, end=end, interval="1d", auto_adjust=False)
    if history is None or history.empty:
        return None
    history = history[[item.date() <= basis_date for item in history.index]]
    if history.empty:
        return None
    latest = history.iloc[-1]
    previous = history.iloc[-2] if len(history) >= 2 else latest
    close = float(latest["Close"])
    previous_close = float(previous["Close"]) or close
    daily_return = 0 if previous_close == 0 else (close - previous_close) / previous_close
    return {
        "symbol": symbol,
        "last_price": close,
        "daily_return": daily_return,
        "turnover_ratio": 0.01,
        "source": "yfinance",
    }


def _yf_symbol(symbol: str) -> str:
    code, exchange = symbol.split(".")
    if exchange == "SH":
        return f"{code}.SS"
    return f"{code}.SZ"


def _missing_codes(requested: list[str], rows: list[dict[str, Any]]) -> list[str]:
    present = {row["symbol"] for row in rows}
    return [symbol for symbol in requested if symbol not in present]


def _unavailable(reason: str) -> dict[str, Any]:
    return _result("unavailable", reason)


def _failed(reason: str) -> dict[str, Any]:
    return _result("failed", reason)


def _result(status: str, reason: str) -> dict[str, Any]:
    return {
        "source": "yfinance",
        "status": status,
        "indices": [],
        "symbols": [],
        "macro": [],
        "data_gaps": [reason],
        "conflicts": [],
    }
