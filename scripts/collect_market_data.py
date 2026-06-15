from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from invest_system.adapters import append_market_snapshot_from_adapters, build_p0c_price_data_from_bundle  # noqa: E402
from invest_system.repositories import DEFAULT_DB_PATH, SQLiteRepository  # noqa: E402
from invest_system.research import generate_p0c_research  # noqa: E402


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
    parser.add_argument("--symbol", action="append", dest="symbols")
    parser.add_argument("--index", action="append", dest="indices")
    parser.add_argument("--run-p0c", action="store_true")
    args = parser.parse_args()

    repo = SQLiteRepository(args.db)
    result = append_market_snapshot_from_adapters(
        repo,
        basis_date=args.basis_date,
        source=args.source,
        allow_network=args.allow_network,
        symbols=args.symbols,
        indices=args.indices,
    )
    if args.run_p0c:
        price_data = build_p0c_price_data_from_bundle(result["bundle"])
        result["p0c_research"] = generate_p0c_research(repo, args.basis_date, price_data=price_data)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
