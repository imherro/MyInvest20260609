from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from invest_system.repositories import DEFAULT_DB_PATH, SQLiteRepository  # noqa: E402
from invest_system.workflow import run_daily_auto_research  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--basis-date", default=date.today().isoformat())
    parser.add_argument(
        "--source",
        default="auto",
        choices=["auto", "mock", "tushare", "baostock", "yfinance", "fred"],
    )
    parser.add_argument("--allow-network", action="store_true")
    args = parser.parse_args()

    result = run_daily_auto_research(
        SQLiteRepository(args.db),
        basis_date=args.basis_date,
        source=args.source,
        allow_network=args.allow_network,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    if result["status"] != "ok":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
