from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from invest_system.repositories import DEFAULT_DB_PATH, SQLiteRepository  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH))
    args = parser.parse_args()
    payload = _read_json(Path(args.input))
    repo = SQLiteRepository(args.db)
    repo.init_db()
    result = repo.append_decision_record(payload)
    print(json.dumps({"status": "ok", "inserted": result}, ensure_ascii=False, sort_keys=True))


def _read_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8-sig") as json_file:
        payload = json.load(json_file)
    if not isinstance(payload, dict):
        raise ValueError("input JSON must be an object")
    return payload


if __name__ == "__main__":
    main()
