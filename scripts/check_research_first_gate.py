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
    parser.add_argument("--path")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH))
    args = parser.parse_args()
    payloads = _payloads(args.path, args.db)
    violations = []
    for label, payload in payloads:
        violations.extend(_check_payload(label, payload))
    result = {"status": "passed" if not violations else "failed", "violations": violations}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    if violations:
        raise SystemExit(1)


def _payloads(path: str | None, db_path: str) -> list[tuple[str, Any]]:
    if path:
        with Path(path).open("r", encoding="utf-8-sig") as json_file:
            return [(path, json.load(json_file))]
    repo = SQLiteRepository(db_path)
    repo.init_db()
    return [(f"{row['table']}:{row['object_id']}", row["payload"]) for row in repo.all_payload_rows()]


def _check_payload(label: str, payload: Any) -> list[dict[str, str]]:
    violations: list[dict[str, str]] = []
    if not isinstance(payload, dict):
        return violations
    if "decision_actions" in payload:
        for index, action in enumerate(payload["decision_actions"]):
            gates = action.get("gates", {})
            if gates.get("research_first") is True:
                if action.get("target_weight") != 0:
                    violations.append({"label": label, "path": f"$.decision_actions[{index}]", "reason": "research_first_weight_not_zero"})
                if action.get("action") not in {"research_first", "hold", "no_action"}:
                    violations.append({"label": label, "path": f"$.decision_actions[{index}]", "reason": "research_first_actionable"})
    inner = payload.get("payload", {})
    if isinstance(inner, dict):
        research_first = {
            item.get("symbol")
            for item in inner.get("research_first_list", [])
            if isinstance(item, dict)
        }
        action_candidates = {
            item.get("symbol")
            for item in inner.get("action_candidates", [])
            if isinstance(item, dict)
        }
        overlap = sorted(symbol for symbol in research_first & action_candidates if symbol)
        for symbol in overlap:
            violations.append({"label": label, "path": "$.payload.action_candidates", "reason": f"research_first_candidate:{symbol}"})
    return violations


if __name__ == "__main__":
    main()

