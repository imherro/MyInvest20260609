from __future__ import annotations

import importlib.util
import os
from typing import Any


def collect_tushare(request: dict[str, Any]) -> dict[str, Any]:
    if not request["allow_network"]:
        return _unavailable("network_disabled")
    token = os.environ.get("TUSHARE_TOKEN")
    if not token:
        return _unavailable("missing_TUSHARE_TOKEN")
    if importlib.util.find_spec("tushare") is None:
        return _unavailable("python_package_missing")

    try:
        import tushare as ts  # type: ignore[import-not-found]

        ts.set_token(token)
        pro = ts.pro_api(token)
        trade_date = request["basis_date"].replace("-", "")
        symbols = [_daily_row(pro, symbol, trade_date) for symbol in request["symbols"]]
        indices = [_index_row(pro, symbol, trade_date) for symbol in request["indices"]]
        return {
            "source": "tushare",
            "status": "ok",
            "indices": [row for row in indices if row is not None],
            "symbols": [row for row in symbols if row is not None],
            "macro": [],
            "data_gaps": [],
            "conflicts": [],
        }
    except Exception as exc:  # noqa: BLE001
        return _failed(str(exc))


def _daily_row(pro: Any, symbol: str, trade_date: str) -> dict[str, Any] | None:
    data = pro.daily(ts_code=symbol, trade_date=trade_date)
    if data is None or data.empty:
        return None
    row = data.iloc[0]
    return {
        "symbol": symbol,
        "last_price": float(row["close"]),
        "daily_return": float(row.get("pct_chg", 0)) / 100,
        "turnover_ratio": 0.01,
        "source": "tushare",
    }


def _index_row(pro: Any, symbol: str, trade_date: str) -> dict[str, Any] | None:
    data = pro.index_daily(ts_code=symbol, trade_date=trade_date)
    if data is None or data.empty:
        return None
    row = data.iloc[0]
    return {
        "symbol": symbol,
        "name": symbol,
        "daily_return": float(row.get("pct_chg", 0)) / 100,
        "source": "tushare",
    }


def _unavailable(reason: str) -> dict[str, Any]:
    return _result("unavailable", reason)


def _failed(reason: str) -> dict[str, Any]:
    return _result("failed", reason)


def _result(status: str, reason: str) -> dict[str, Any]:
    return {
        "source": "tushare",
        "status": status,
        "indices": [],
        "symbols": [],
        "macro": [],
        "data_gaps": [reason],
        "conflicts": [],
    }
