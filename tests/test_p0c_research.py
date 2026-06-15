from __future__ import annotations

import json
import subprocess
import sys

from invest_system.golden import seed_multiday_repository
from invest_system.repositories import SQLiteRepository
from invest_system.research import generate_p0c_research
from invest_system.validators.schema_validator import validate_or_raise


def test_generate_p0c_research_appends_structured_snapshots(tmp_path) -> None:
    db_path = tmp_path / "p0c.sqlite"
    repo = SQLiteRepository(db_path)
    seed_multiday_repository(repo)

    result = generate_p0c_research(repo, "2026-06-15")

    assert result["status"] == "ok"
    assert len(result["inserted"]) == 5
    rows = repo.all_payload_rows()
    modules = {row["payload"]["module"] for row in rows if row["type"] == "research"}
    assert {"etf_valuation", "stock_valuation", "theme_research", "leader_ranking", "review_score"} <= modules
    latest = repo.latest_research()
    assert latest["module"] == "review_score"
    assert latest["payload"]["total_score"] >= 0
    assert repo.table_counts()["event_log"] == 23


def test_p0c_payload_schemas_are_valid(tmp_path) -> None:
    db_path = tmp_path / "p0c.sqlite"
    repo = SQLiteRepository(db_path)
    seed_multiday_repository(repo)
    generate_p0c_research(repo, "2026-06-15")
    schema_by_module = {
        "etf_valuation": "etf_valuation_payload.schema.json",
        "stock_valuation": "stock_valuation_payload.schema.json",
        "theme_research": "theme_research_payload.schema.json",
        "leader_ranking": "leader_ranking_payload.schema.json",
        "review_score": "review_score_payload.schema.json",
    }

    for row in repo.all_payload_rows():
        payload = row["payload"]
        module = payload.get("module")
        if module in schema_by_module:
            validate_or_raise(payload["payload"], schema_by_module[module])


def test_generate_p0c_research_cli_outputs_json(tmp_path) -> None:
    db_path = tmp_path / "p0c_cli.sqlite"
    seed_multiday_repository(SQLiteRepository(db_path))

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/generate_p0c_research.py",
            "--db",
            str(db_path),
            "--basis-date",
            "2026-06-15",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(completed.stdout)

    assert payload["status"] == "ok"
    assert len(payload["inserted"]) == 5

