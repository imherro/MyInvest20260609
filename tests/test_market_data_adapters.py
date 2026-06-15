from __future__ import annotations

import json
import subprocess
import sys

from invest_system.adapters import (
    append_market_snapshot_from_adapters,
    build_market_snapshot_from_bundle,
    build_p0c_price_data_from_bundle,
    collect_market_data_bundle,
)
from invest_system.repositories import SQLiteRepository
from invest_system.validators.schema_validator import validate_or_raise


def test_mock_market_data_bundle_appends_market_snapshot(tmp_path) -> None:
    repo = SQLiteRepository(tmp_path / "market.sqlite")
    result = append_market_snapshot_from_adapters(
        repo,
        basis_date="2026-06-15",
        source="mock",
    )

    assert result["status"] == "ok"
    validate_or_raise(result["bundle"], "market_data_bundle.schema.json")
    latest = repo.latest_market()
    assert latest["snapshot_id"] == "market-2026-06-15-mock-adapter"
    assert latest["data_sources"] == ["adapter:mock"]
    assert latest["actionability"] == "observe"
    assert repo.table_counts()["market_snapshot"] == 1
    assert repo.table_counts()["event_log"] == 1


def test_auto_market_data_uses_mock_fallback_when_network_disabled() -> None:
    bundle = collect_market_data_bundle(
        basis_date="2026-06-15",
        source="auto",
        allow_network=False,
    )

    assert "mock" in bundle["successful_sources"]
    assert bundle["data_gaps"]
    assert all(result["read_only"] for result in bundle["source_results"])
    snapshot = build_market_snapshot_from_bundle(bundle)
    assert snapshot["status"] == "json_validated"
    assert "adapter:mock" in snapshot["data_sources"]


def test_market_data_bundle_builds_p0c_price_data_shape() -> None:
    bundle = collect_market_data_bundle(basis_date="2026-06-15", source="mock")
    price_data = build_p0c_price_data_from_bundle(bundle)

    assert price_data["etfs"]
    assert price_data["stocks"]
    assert price_data["themes"][0]["symbols"]
    assert price_data["leaders"]


def test_collect_market_data_cli_outputs_json_and_can_run_p0c(tmp_path) -> None:
    db_path = tmp_path / "collect.sqlite"
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/collect_market_data.py",
            "--db",
            str(db_path),
            "--basis-date",
            "2026-06-15",
            "--source",
            "mock",
            "--run-p0c",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(completed.stdout)

    assert payload["status"] == "ok"
    assert payload["market_snapshot_id"] == "market-2026-06-15-mock-adapter"
    assert len(payload["p0c_research"]["inserted"]) == 5
    repo = SQLiteRepository(db_path)
    assert repo.table_counts()["market_snapshot"] == 1
    assert repo.table_counts()["research_snapshot"] == 5
