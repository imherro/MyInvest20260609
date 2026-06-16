from __future__ import annotations

from typing import Any


def collect_mock(request: dict[str, Any]) -> dict[str, Any]:
    symbols = request["symbols"]
    indices = request["indices"]
    mock_prices = {
        "510300.SH": (3.82, 0.0042, 0.024),
        "159915.SZ": (2.18, -0.0015, 0.031),
        "002920.SZ": (28.6, 0.006, 0.018),
        "511360.SH": (101.2, 0.0004, 0.008),
    }
    mock_indices = {
        "000001.SH": ("上证指数", 3387.42, 0.0026),
        "000300.SH": ("CSI300", 3985.16, 0.0035),
        "000905.SH": ("CSI500", 5912.34, 0.0018),
    }
    return {
        "source": "mock",
        "status": "ok",
        "indices": [
            {
                "symbol": symbol,
                "name": mock_indices.get(symbol, (symbol, None, 0.0))[0],
                "last_price": mock_indices.get(symbol, (symbol, None, 0.0))[1],
                "daily_return": mock_indices.get(symbol, (symbol, None, 0.0))[2],
                "source": "mock",
            }
            for symbol in indices
        ],
        "symbols": [
            {
                "symbol": symbol,
                "last_price": mock_prices.get(symbol, (1.0, 0.0, 0.01))[0],
                "daily_return": mock_prices.get(symbol, (1.0, 0.0, 0.01))[1],
                "turnover_ratio": mock_prices.get(symbol, (1.0, 0.0, 0.01))[2],
                "source": "mock",
            }
            for symbol in symbols
        ],
        "macro": [{"indicator": "cn_liquidity_proxy", "value": 0.52, "source": "mock"}],
        "data_gaps": [],
        "conflicts": [],
    }
