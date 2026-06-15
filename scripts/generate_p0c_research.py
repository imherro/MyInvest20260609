from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from invest_system.repositories import DEFAULT_DB_PATH, SQLiteRepository  # noqa: E402
from invest_system.research import generate_p0c_research  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--basis-date", required=True)
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH))
    args = parser.parse_args()
    result = generate_p0c_research(SQLiteRepository(args.db), args.basis_date)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()

