from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from invest_system.repositories import DEFAULT_DB_PATH, SQLiteRepository  # noqa: E402
from invest_system.validators.policies import SENSITIVE_FIELD_NAMES  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH))
    args = parser.parse_args()
    payloads = _payloads(args.path, args.db)
    violations = []
    for label, payload in payloads:
        violations.extend(_scan(label, payload))
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


def _scan(label: str, value: Any, path: str = "$") -> list[dict[str, str]]:
    violations: list[dict[str, str]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key.lower() in SENSITIVE_FIELD_NAMES:
                violations.append({"label": label, "path": f"{path}.{key}", "reason": "sensitive_field"})
            violations.extend(_scan(label, child, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            violations.extend(_scan(label, child, f"{path}[{index}]"))
    elif isinstance(value, str) and ":\\" in value:
        violations.append({"label": label, "path": path, "reason": "local_absolute_path"})
    return violations


if __name__ == "__main__":
    main()

