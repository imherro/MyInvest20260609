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
    assert len(result["inserted"]) == 4
    rows = repo.all_payload_rows()
    modules = {row["payload"]["module"] for row in rows if row["type"] == "research"}
    assert {"etf_valuation", "stock_valuation", "theme_research", "review_score"} <= modules
    assert "leader_ranking" not in modules
    latest = repo.latest_research()
    assert latest["module"] == "review_score"
    assert latest["payload"]["total_score"] >= 0
    assert repo.table_counts()["event_log"] == 22


def test_p0c_payload_schemas_are_valid(tmp_path) -> None:
    db_path = tmp_path / "p0c.sqlite"
    repo = SQLiteRepository(db_path)
    seed_multiday_repository(repo)
    generate_p0c_research(repo, "2026-06-15")
    schema_by_module = {
        "etf_valuation": "etf_valuation_payload.schema.json",
        "stock_valuation": "stock_valuation_payload.schema.json",
        "theme_research": "theme_research_payload.schema.json",
        "review_score": "review_score_payload.schema.json",
    }

    for row in repo.all_payload_rows():
        payload = row["payload"]
        module = payload.get("module")
        if module in schema_by_module:
            validate_or_raise(payload["payload"], schema_by_module[module])


def test_p0c_valuation_payloads_are_ratio_only(tmp_path) -> None:
    db_path = tmp_path / "p0c_ratio_only.sqlite"
    repo = SQLiteRepository(db_path)
    seed_multiday_repository(repo)
    generate_p0c_research(repo, "2026-06-15")

    valuation_payloads = [
        row["payload"]["payload"]
        for row in repo.all_payload_rows()
        if row["payload"].get("module") in {"etf_valuation", "stock_valuation"}
    ]

    assert valuation_payloads
    for payload in valuation_payloads:
        assert "price" not in payload
        assert "fair_value_range" not in payload
        if "research_first_status" in payload:
            assert payload["research_first_status"] == "BLOCKED"
            assert payload["gates"]["profile"] == "missing"
            assert payload["gates"]["liquidity"] == "missing"
            assert "signal_type" in payload
        else:
            assert "observed_to_fair_value_ratio" in payload
            assert "fair_value_band_pct" in payload


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
    assert len(payload["inserted"]) == 4
