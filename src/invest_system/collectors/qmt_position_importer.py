from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from invest_system.local_env import load_local_env
from invest_system.repositories import SQLiteRepository
from invest_system.validators.policies import SENSITIVE_FIELD_NAMES, PolicyViolation


ALLOWED_POOL_TYPES = {"approved", "research_first", "blocked"}


def import_qmt_positions(csv_path: str | Path, repo: SQLiteRepository, basis_date: str) -> dict[str, Any]:
    path = Path(csv_path)
    repo.init_db()
    import_id = f"qmt-mock-{basis_date}"
    if not path.exists():
        event_payload = _event_payload(
            import_id=import_id,
            basis_date=basis_date,
            status="blocked",
            symbols=[],
            data_gaps=["qmt_mock_file_missing"],
        )
        event = repo.append_market_event(object_id=import_id, basis_date=basis_date, payload=event_payload)
        return {"status": "blocked", "event": event, "target_pool": None}

    rows = _read_rows(path)
    entries: dict[str, list[str]] = {pool_type: [] for pool_type in ALLOWED_POOL_TYPES}
    holdings_weight: dict[str, float] = {}
    for row in rows:
        symbol = row["symbol"].strip()
        pool_type = row.get("pool_type", "approved").strip() or "approved"
        if pool_type not in ALLOWED_POOL_TYPES:
            raise ValueError(f"unsupported pool_type: {pool_type}")
        if symbol and symbol not in entries[pool_type]:
            entries[pool_type].append(symbol)
        if symbol:
            holdings_weight[symbol] = _holding_weight(row["holding_weight"], symbol)

    total_weight = round(sum(holdings_weight.values()), 6)
    if total_weight > 1.000001:
        raise ValueError("holding_weight total cannot exceed 1")

    symbols = sorted({symbol for values in entries.values() for symbol in values})
    event = repo.append_market_event(
        object_id=import_id,
        basis_date=basis_date,
        payload=_event_payload(
            import_id=import_id,
            basis_date=basis_date,
            status="imported",
            symbols=symbols,
            holdings_weight={symbol: holdings_weight[symbol] for symbol in sorted(holdings_weight)},
            data_gaps=[],
        ),
    )
    target_pool_payload = {
        "schema_version": "1.0",
        "target_pool_id": f"target-pool-{basis_date}-qmt-mock",
        "basis_date": basis_date,
        "generated_at": _utc_now(),
        "source": "qmt_mock",
        "status": "active",
        "entries": [
            {"pool_type": "approved", "symbols": sorted(entries["approved"])},
            {"pool_type": "research_first", "symbols": sorted(entries["research_first"])},
            {"pool_type": "blocked", "symbols": sorted(entries["blocked"])},
        ],
    }
    target_pool = repo.append_target_pool_snapshot(target_pool_payload)
    return {"status": "ok", "event": event, "target_pool": target_pool}


def import_qmt_positions_from_qmt(repo: SQLiteRepository, basis_date: str) -> dict[str, Any]:
    repo.init_db()
    import_id = f"qmt-live-{basis_date}"
    try:
        holdings_weight = _read_live_qmt_holdings()
    except _QmtReadBlocked as exc:
        event = repo.append_market_event(
            object_id=import_id,
            basis_date=basis_date,
            payload=_event_payload(
                import_id=import_id,
                basis_date=basis_date,
                status="blocked",
                symbols=[],
                data_gaps=[exc.reason],
            ),
        )
        return {"status": "blocked", "reason": exc.reason, "event": event, "target_pool": None}

    symbols = sorted(holdings_weight)
    if not symbols:
        event = repo.append_market_event(
            object_id=import_id,
            basis_date=basis_date,
            payload=_event_payload(
                import_id=import_id,
                basis_date=basis_date,
                status="blocked",
                symbols=[],
                data_gaps=["qmt_position_missing"],
            ),
        )
        return {"status": "blocked", "reason": "qmt_position_missing", "event": event, "target_pool": None}

    event = repo.append_market_event(
        object_id=import_id,
        basis_date=basis_date,
        payload=_event_payload(
            import_id=import_id,
            basis_date=basis_date,
            status="imported",
            symbols=symbols,
            data_gaps=[],
            holdings_weight=holdings_weight,
        ),
    )
    target_pool_payload = {
        "schema_version": "1.0",
        "target_pool_id": f"target-pool-{basis_date}-qmt-live",
        "basis_date": basis_date,
        "generated_at": _utc_now(),
        "source": "qmt_live",
        "status": "active",
        "entries": [
            {"pool_type": "approved", "symbols": symbols},
            {"pool_type": "research_first", "symbols": []},
            {"pool_type": "blocked", "symbols": []},
        ],
    }
    target_pool = repo.append_target_pool_snapshot(target_pool_payload)
    return {"status": "ok", "event": event, "target_pool": target_pool}


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        if reader.fieldnames is None:
            raise ValueError("CSV header is required")
        lowered = {name.lower() for name in reader.fieldnames}
        forbidden = sorted(lowered & SENSITIVE_FIELD_NAMES)
        if forbidden:
            raise PolicyViolation(f"QMT mock CSV contains sensitive fields: {', '.join(forbidden)}")
        required = {"symbol", "holding_weight", "bucket", "pool_type"}
        missing = sorted(required - lowered)
        if missing:
            raise ValueError(f"QMT mock CSV missing required fields: {', '.join(missing)}")
        rows = [dict(row) for row in reader]
    return rows


def _holding_weight(value: str, symbol: str) -> float:
    try:
        weight = float(value)
    except ValueError as exc:
        raise ValueError(f"invalid holding_weight for {symbol}") from exc
    if weight < 0 or weight > 1:
        raise ValueError(f"holding_weight for {symbol} must be between 0 and 1")
    return round(weight, 6)


class _QmtReadBlocked(RuntimeError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _read_live_qmt_holdings() -> dict[str, float]:
    config = _qmt_readonly_config()
    if not config["trader_path"] or not config["account_id"]:
        raise _QmtReadBlocked("qmt_readonly_config_missing")
    _extend_qmt_runtime(config)
    try:
        from xtquant.xttrader import XtQuantTrader  # type: ignore[import-not-found]
        from xtquant.xttype import StockAccount  # type: ignore[import-not-found]
    except Exception as exc:  # pragma: no cover - depends on local QMT SDK
        return _read_live_qmt_holdings_subprocess(config, exc)

    return _query_qmt_holdings(
        XtQuantTrader=XtQuantTrader,
        StockAccount=StockAccount,
        trader_path=config["trader_path"],
        account_id=config["account_id"],
        account_type=config["account_type"],
    )


def _query_qmt_holdings(
    *,
    XtQuantTrader: Any,
    StockAccount: Any,
    trader_path: str,
    account_id: str,
    account_type: str,
) -> dict[str, float]:
    try:  # pragma: no cover - depends on local QMT runtime
        session_id = int(os.environ.get("QMT_SESSION_ID", str(int(time.time()))))
        trader = XtQuantTrader(trader_path, session_id)
        trader.start()
        connect_result = trader.connect()
        if connect_result not in (0, None):
            raise _QmtReadBlocked("qmt_connect_failed")
        account = StockAccount(account_id, account_type)
        asset = trader.query_stock_asset(account)
        positions = trader.query_stock_positions(account) or []
    except _QmtReadBlocked:
        raise
    except Exception as exc:
        raise _QmtReadBlocked("qmt_read_failed") from exc

    total_asset = _read_float_attr(asset, "total_asset")
    if total_asset <= 0:
        raise _QmtReadBlocked("qmt_total_asset_unavailable")

    weights: dict[str, float] = {}
    for position in positions:
        symbol = _normalize_qmt_symbol(str(_read_attr(position, "stock_code", "")))
        market_value = _read_float_attr(position, "market_value")
        if not symbol or market_value <= 0:
            continue
        weights[symbol] = round(market_value / total_asset, 6)
    if sum(weights.values()) > 1.000001:
        raise _QmtReadBlocked("qmt_weight_total_invalid")
    return dict(sorted(weights.items()))


def _qmt_readonly_config() -> dict[str, str]:
    load_local_env()
    install_dir_raw = os.environ.get("QMT_INSTALL_DIR", "").strip()
    install_dir = Path(install_dir_raw) if install_dir_raw else None
    trader_path = os.environ.get("QMT_TRADER_PATH") or os.environ.get("QMT_USER_PATH")
    if not trader_path and install_dir is not None:
        default_trader_path = install_dir / "userdata_mini"
        trader_path = str(default_trader_path) if default_trader_path.exists() else ""
    qmt_pythonpath = os.environ.get("QMT_PYTHONPATH")
    if not qmt_pythonpath and install_dir is not None:
        default_pythonpath = install_dir / "python" / "Lib" / "site-packages"
        qmt_pythonpath = str(default_pythonpath) if default_pythonpath.exists() else ""
    qmt_bin_path = install_dir / "bin.x64" if install_dir is not None else None
    qmt_dll_path = install_dir / "python" / "DLLs" if install_dir is not None else None
    detected_account_id = _detect_qmt_account_id(install_dir / "userdata_mini" / "users") if install_dir else None
    account_id = os.environ.get("QMT_ACCOUNT_ID") or detected_account_id
    return {
        "install_dir": str(install_dir) if install_dir is not None else "",
        "trader_path": trader_path or "",
        "pythonpath": qmt_pythonpath or "",
        "bin_path": str(qmt_bin_path) if qmt_bin_path is not None and qmt_bin_path.exists() else "",
        "dll_path": str(qmt_dll_path) if qmt_dll_path is not None and qmt_dll_path.exists() else "",
        "account_id": account_id or "",
        "account_type": os.environ.get("QMT_ACCOUNT_TYPE", "STOCK"),
    }


def _detect_qmt_account_id(users_dir: Path) -> str | None:
    if not users_dir.exists():
        return None
    candidates = [
        child.name
        for child in users_dir.iterdir()
        if child.is_dir() and child.name.isdigit() and len(child.name) >= 6
    ]
    return candidates[0] if len(candidates) == 1 else None


def _extend_qmt_runtime(config: dict[str, str]) -> None:
    for item in config["pythonpath"].split(os.pathsep):
        if item and item not in sys.path:
            sys.path.insert(0, item)
    for key in ("bin_path", "dll_path"):
        item = config.get(key, "")
        if item:
            os.environ["PATH"] = item + os.pathsep + os.environ.get("PATH", "")
            add_dll_directory = getattr(os, "add_dll_directory", None)
            if add_dll_directory:
                try:
                    add_dll_directory(item)
                except OSError:
                    pass


def _read_live_qmt_holdings_subprocess(config: dict[str, str], import_error: Exception) -> dict[str, float]:
    command = _qmt_python_command()
    if command is None:
        raise _QmtReadBlocked("qmt_xtquant_sdk_missing") from import_error
    code = _qmt_subprocess_code()
    env = os.environ.copy()
    env.update(
        {
            "QMT_TRADER_PATH": config["trader_path"],
            "QMT_ACCOUNT_ID": config["account_id"],
            "QMT_ACCOUNT_TYPE": config["account_type"],
            "QMT_PYTHONPATH": config["pythonpath"],
            "QMT_BIN_PATH": config["bin_path"],
            "QMT_DLL_PATH": config["dll_path"],
        }
    )
    timeout = int(os.environ.get("QMT_READ_TIMEOUT_SEC", "30"))
    completed = subprocess.run(
        [*command, "-c", code],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )
    if completed.returncode != 0:
        raise _QmtReadBlocked("qmt_read_failed")
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise _QmtReadBlocked("qmt_read_failed") from exc
    if payload.get("status") != "ok":
        raise _QmtReadBlocked(str(payload.get("reason") or "qmt_read_failed"))
    weights = payload.get("holdings_weight", {})
    if not isinstance(weights, dict):
        raise _QmtReadBlocked("qmt_read_failed")
    return {str(symbol): round(float(weight), 6) for symbol, weight in sorted(weights.items())}


def _qmt_python_command() -> list[str] | None:
    configured = os.environ.get("QMT_PYTHON_EXE")
    if configured:
        return [configured]
    try:
        probe = subprocess.run(["py", "-3.11", "-V"], capture_output=True, text=True, timeout=5)
    except OSError:
        return None
    return ["py", "-3.11"] if probe.returncode == 0 else None


def _qmt_subprocess_code() -> str:
    return r'''
import json
import os
import sys
import time


def emit(payload):
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def add_runtime():
    for item in os.environ.get("QMT_PYTHONPATH", "").split(os.pathsep):
        if item and item not in sys.path:
            sys.path.insert(0, item)
    for key in ("QMT_BIN_PATH", "QMT_DLL_PATH"):
        item = os.environ.get(key, "")
        if item:
            os.environ["PATH"] = item + os.pathsep + os.environ.get("PATH", "")
            add_dll_directory = getattr(os, "add_dll_directory", None)
            if add_dll_directory:
                try:
                    add_dll_directory(item)
                except OSError:
                    pass


def read_attr(value, name, default=None):
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def read_float_attr(value, name):
    try:
        return float(read_attr(value, name, 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def normalize_symbol(symbol):
    value = str(symbol).strip().upper()
    if not value:
        return ""
    if "." in value:
        return value
    if value.startswith(("5", "6", "9")):
        return value + ".SH"
    return value + ".SZ"


try:
    add_runtime()
    from xtquant.xttrader import XtQuantTrader
    from xtquant.xttype import StockAccount
    trader_path = os.environ.get("QMT_TRADER_PATH")
    account_id = os.environ.get("QMT_ACCOUNT_ID")
    account_type = os.environ.get("QMT_ACCOUNT_TYPE", "STOCK")
    if not trader_path or not account_id:
        emit({"status": "blocked", "reason": "qmt_readonly_config_missing"})
        raise SystemExit(0)
    trader = XtQuantTrader(trader_path, int(os.environ.get("QMT_SESSION_ID", str(int(time.time())))))
    trader.start()
    connect_result = trader.connect()
    if connect_result not in (0, None):
        emit({"status": "blocked", "reason": "qmt_connect_failed"})
        raise SystemExit(0)
    account = StockAccount(account_id, account_type)
    asset = trader.query_stock_asset(account)
    total_asset = read_float_attr(asset, "total_asset")
    if total_asset <= 0:
        emit({"status": "blocked", "reason": "qmt_total_asset_unavailable"})
        raise SystemExit(0)
    weights = {}
    for position in trader.query_stock_positions(account) or []:
        symbol = normalize_symbol(read_attr(position, "stock_code", ""))
        market_value = read_float_attr(position, "market_value")
        if symbol and market_value > 0:
            weights[symbol] = round(market_value / total_asset, 6)
    if sum(weights.values()) > 1.000001:
        emit({"status": "blocked", "reason": "qmt_weight_total_invalid"})
        raise SystemExit(0)
    emit({"status": "ok", "holdings_weight": dict(sorted(weights.items()))})
except Exception:
    emit({"status": "blocked", "reason": "qmt_read_failed"})
'''


def _read_attr(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _read_float_attr(value: Any, name: str) -> float:
    raw = _read_attr(value, name, 0)
    try:
        return float(raw or 0)
    except (TypeError, ValueError):
        return 0.0


def _normalize_qmt_symbol(symbol: str) -> str:
    value = symbol.strip().upper()
    if not value:
        return ""
    if "." in value:
        return value
    if value.startswith(("5", "6", "9")):
        return f"{value}.SH"
    return f"{value}.SZ"


def _event_payload(
    *,
    import_id: str,
    basis_date: str,
    status: str,
    symbols: list[str],
    data_gaps: list[str],
    holdings_weight: dict[str, float] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "event_subtype": "qmt_position_import",
        "import_id": import_id,
        "basis_date": basis_date,
        "generated_at": _utc_now(),
        "status": status,
        "symbols": symbols,
        "holdings_weight": holdings_weight or {},
        "data_gaps": data_gaps,
        "privacy": {
            "ratio_only": True,
            "paper_only": True,
        },
    }


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
