from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from invest_system.repositories import DEFAULT_DB_PATH, SQLiteRepository  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH))
    args = parser.parse_args()
    repo = SQLiteRepository(args.db)
    repo.init_db()
    violations = []
    for row in repo.all_payload_rows():
        violations.extend(_check_row(row))
    result = {"status": "passed" if not violations else "failed", "violations": violations}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    if violations:
        raise SystemExit(1)


def _check_row(row: dict[str, Any]) -> list[dict[str, str]]:
    payload = row["payload"]
    label = f"{row['table']}:{row['object_id']}"
    violations: list[dict[str, str]] = []
    if row["type"] == "portfolio":
        total = payload["cash_weight"] + sum(payload["holdings_weight"].values())
        if abs(total - 1.0) > 0.0001:
            violations.append({"label": label, "path": "$.holdings_weight", "reason": "portfolio_weight_sum_not_one"})
    if row["type"] == "decision":
        total = sum(action["target_weight"] for action in payload["decision_actions"])
        if total > 1.0001:
            violations.append({"label": label, "path": "$.decision_actions", "reason": "decision_target_weight_above_one"})
    return violations


if __name__ == "__main__":
    main()

