from __future__ import annotations

import importlib.util
from typing import Any


def collect_yfinance(request: dict[str, Any]) -> dict[str, Any]:
    if not request["allow_network"]:
        return _unavailable("network_disabled")
    if importlib.util.find_spec("yfinance") is None:
        return _unavailable("python_package_missing")

    try:
        import yfinance as yf  # type: ignore[import-not-found]

        symbols = [_history_row(yf, symbol) for symbol in request["symbols"]]
        return {
            "source": "yfinance",
            "status": "ok",
            "indices": [],
            "symbols": [row for row in symbols if row is not None],
            "macro": [],
            "data_gaps": [],
            "conflicts": [],
        }
    except Exception as exc:  # noqa: BLE001
        return _failed(str(exc))


def _history_row(yf: Any, symbol: str) -> dict[str, Any] | None:
    ticker = yf.Ticker(_yf_symbol(symbol))
    history = ticker.history(period="5d", interval="1d", auto_adjust=False)
    if history is None or history.empty:
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
