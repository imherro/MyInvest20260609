from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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
    for row in rows:
        symbol = row["symbol"].strip()
        pool_type = row.get("pool_type", "approved").strip() or "approved"
        if pool_type not in ALLOWED_POOL_TYPES:
            raise ValueError(f"unsupported pool_type: {pool_type}")
        if symbol and symbol not in entries[pool_type]:
            entries[pool_type].append(symbol)

    symbols = sorted({symbol for values in entries.values() for symbol in values})
    event = repo.append_market_event(
        object_id=import_id,
        basis_date=basis_date,
        payload=_event_payload(
            import_id=import_id,
            basis_date=basis_date,
            status="imported",
            symbols=symbols,
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


def _event_payload(
    *,
    import_id: str,
    basis_date: str,
    status: str,
    symbols: list[str],
    data_gaps: list[str],
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "event_subtype": "qmt_position_import",
        "import_id": import_id,
        "basis_date": basis_date,
        "generated_at": _utc_now(),
        "status": status,
        "symbols": symbols,
        "data_gaps": data_gaps,
        "privacy": {
            "ratio_only": True,
            "paper_only": True,
        },
    }


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")

