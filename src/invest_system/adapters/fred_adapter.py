from __future__ import annotations

import json
import os
from typing import Any
from urllib.parse import urlencode
from urllib.request import urlopen


def collect_fred(request: dict[str, Any]) -> dict[str, Any]:
    if not request["allow_network"]:
        return _unavailable("network_disabled")
    api_key = os.environ.get("FRED_API_KEY")
    if not api_key:
        return _unavailable("missing_FRED_API_KEY")

    try:
        value = _fetch_observation(api_key, "DGS10", request["basis_date"])
        if value is None:
            return _unavailable("no_observation")
        return {
            "source": "fred",
            "status": "ok",
            "indices": [],
            "symbols": [],
            "macro": [{"indicator": "DGS10", "value": value, "source": "fred"}],
            "data_gaps": [],
            "conflicts": [],
        }
    except Exception as exc:  # noqa: BLE001
        return _failed(str(exc))


def _fetch_observation(api_key: str, series_id: str, basis_date: str) -> float | None:
    params = urlencode(
        {
            "series_id": series_id,
            "api_key": api_key,
            "file_type": "json",
            "observation_start": basis_date,
            "observation_end": basis_date,
        }
    )
    with urlopen(f"https://api.stlouisfed.org/fred/series/observations?{params}", timeout=10) as response:
        payload = json.loads(response.read().decode("utf-8"))
    observations = payload.get("observations", [])
    if not observations:
        return None
    value = observations[-1].get("value")
    if value in {None, "."}:
        return None
    return float(value)


def _unavailable(reason: str) -> dict[str, Any]:
    return _result("unavailable", reason)


def _failed(reason: str) -> dict[str, Any]:
    return _result("failed", reason)


def _result(status: str, reason: str) -> dict[str, Any]:
    return {
        "source": "fred",
        "status": status,
        "indices": [],
        "symbols": [],
        "macro": [],
        "data_gaps": [reason],
        "conflicts": [],
    }
