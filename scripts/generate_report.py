from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from invest_system.reports import generate_report  # noqa: E402
from invest_system.repositories import DEFAULT_DB_PATH, SQLiteRepository  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--as-of", default=None)
    parser.add_argument("--output-dir", default="temp/reports")
    parser.add_argument(
        "--format",
        action="append",
        dest="formats",
        choices=["markdown", "html", "pdf", "all"],
        default=None,
    )
    args = parser.parse_args()
    manifest = generate_report(
        SQLiteRepository(args.db),
        as_of=args.as_of,
        output_dir=args.output_dir,
        formats=args.formats,
    )
    print(json.dumps(manifest, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
