from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from invest_system.adapters import (  # noqa: E402
    append_market_snapshot_from_adapters,
    build_p0c_price_data_from_bundle,
)
from invest_system.golden import MULTIDAY_DATES, seed_multiday_repository  # noqa: E402
from invest_system.repositories import SQLiteRepository  # noqa: E402
from invest_system.research import generate_p0c_research  # noqa: E402
from invest_system.self_check import run_self_check  # noqa: E402
from invest_system.web import create_app  # noqa: E402


DEFAULT_CHECK_DB = Path("temp/full_system_check.sqlite")
API_ENDPOINTS = [
    "/",
    "/market/latest",
    "/research/latest",
    "/target-pool/latest",
    "/decision/latest",
    "/portfolio/state",
    "/timeline/replay",
    "/system/status",
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(DEFAULT_CHECK_DB))
    args = parser.parse_args()
    db_path = Path(args.db)
    if db_path.exists():
        db_path.unlink()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    repo = SQLiteRepository(db_path)
    repo.init_db()
    seed_result = seed_multiday_repository(repo)
    market_data_result = append_market_snapshot_from_adapters(repo, basis_date=MULTIDAY_DATES[-1], source="mock")
    p0c_price_data = build_p0c_price_data_from_bundle(market_data_result["bundle"])
    p0c_result = generate_p0c_research(repo, MULTIDAY_DATES[-1], price_data=p0c_price_data)
    self_checks = {basis_date: run_self_check(db_path, basis_date) for basis_date in MULTIDAY_DATES}
    policy_checks = _run_policy_checks(db_path)
    api_checks = asyncio.run(_run_api_checks(db_path))

    passed = (
        all(item["status"] == "passed" for item in self_checks.values())
        and all(item["status"] == "passed" for item in policy_checks.values())
        and all(item["status"] == "ok" for item in api_checks.values())
    )
    result: dict[str, Any] = {
        "status": "passed" if passed else "failed",
        "seed": seed_result,
        "market_data": market_data_result,
        "p0c_research": p0c_result,
        "record_counts": repo.table_counts(),
        "self_checks": self_checks,
        "policy_checks": policy_checks,
        "api_checks": api_checks,
    }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    if not passed:
        raise SystemExit(1)


def _run_policy_checks(db_path: Path) -> dict[str, dict[str, Any]]:
    commands = {
        "ratio_only": [sys.executable, "scripts/check_ratio_only.py", "--db", str(db_path)],
        "research_first": [sys.executable, "scripts/check_research_first_gate.py", "--db", str(db_path)],
        "allocation_consistency": [
            sys.executable,
            "scripts/check_cross_file_allocation_consistency.py",
            "--db",
            str(db_path),
        ],
        "project_check": [sys.executable, "scripts/project_check.py", "--current-only", "--db", str(db_path)],
    }
    results: dict[str, dict[str, Any]] = {}
    for name, command in commands.items():
        completed = subprocess.run(command, capture_output=True, text=True)
        if completed.returncode == 0:
            results[name] = json.loads(completed.stdout)
        else:
            results[name] = {
                "status": "failed",
                "stdout": completed.stdout,
                "stderr": completed.stderr,
            }
    return results


async def _run_api_checks(db_path: Path) -> dict[str, dict[str, Any]]:
    app = create_app(db_path)
    checks: dict[str, dict[str, Any]] = {}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        for endpoint in API_ENDPOINTS:
            response = await client.get(endpoint)
            payload = response.json()
            checks[endpoint] = {
                "status": "ok" if response.status_code == 200 and payload.get("status") in {"ok", "empty"} else "failed",
                "http_status": response.status_code,
                "content_type": response.headers.get("content-type", ""),
                "json_status": payload.get("status"),
            }
    return checks


if __name__ == "__main__":
    main()
