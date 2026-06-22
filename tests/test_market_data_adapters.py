from __future__ import annotations

import json
import re
import subprocess
import sys

from invest_system.adapters import (
    append_market_snapshot_from_adapters,
    build_market_snapshot_from_bundle,
    build_p0c_price_data_from_bundle,
    collect_market_data_bundle,
)
from invest_system.adapters import market_data
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
    assert "adapter:mock" in latest["data_sources"]
    assert "derived:market_research_v1" in latest["data_sources"]
    assert latest["actionability"] == "observe"
    assert latest["payload"]["headline_index"]["name"] == "上证指数"
    assert latest["payload"]["headline_index"]["last_price"] == 3387.42
    assert "momentum" in latest["payload"]["signal_type"]
    assert repo.table_counts()["market_snapshot"] == 1
    assert repo.table_counts()["event_log"] == 1


def test_auto_market_data_uses_mock_fallback_when_network_disabled() -> None:
    bundle = collect_market_data_bundle(
        basis_date="2026-06-15",
        source="auto",
        allow_network=False,
    )

    assert "mock" in bundle["successful_sources"]
    assert any(row["symbol"] == "000001.SH" for row in bundle["indices"])
    assert bundle["data_gaps"]
    assert all(result["read_only"] for result in bundle["source_results"])
    snapshot = build_market_snapshot_from_bundle(bundle)
    assert snapshot["status"] == "json_validated"
    assert "adapter:mock" in snapshot["data_sources"]
    assert snapshot["payload"]["headline_index"]["name"] == "上证指数"


def test_market_data_gaps_summarize_identifiers_without_codes() -> None:
    bundle = market_data._bundle_from_results(
        basis_date="2026-06-22",
        requested_source="auto",
        results=[
            {
                "source": "tushare",
                "status": "ok",
                "indices": [],
                "symbols": [],
                "macro": [],
                "conflicts": [],
                "data_gaps": [
                    "missing_symbol:510300.SH",
                    "missing_symbol:159915.SZ",
                    "missing_index:000001.SH",
                ],
            }
        ],
    )

    text = json.dumps(bundle, ensure_ascii=False)
    assert not re.search(r"\b(?:[036]\d{5}|[15]\d{5})\.(?:SH|SZ)\b", text)
    assert "tushare:missing_symbol_records:2" in bundle["data_gaps"]
    assert "tushare:missing_index_records:1" in bundle["data_gaps"]
    assert bundle["source_results"][0]["data_gap"] == "tushare:missing_index_records:1"


def test_market_data_collection_loads_local_env(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(market_data, "load_local_env", lambda: calls.append("loaded"))

    collect_market_data_bundle(basis_date="2026-06-15", source="mock")

    assert calls == ["loaded"]


def test_market_snapshot_contains_research_coverage_and_data_gaps() -> None:
    bundle = collect_market_data_bundle(basis_date="2026-06-15", source="mock")
    snapshot = build_market_snapshot_from_bundle(bundle)
    joined_facts = " ".join(snapshot["key_facts"])

    for expected in [
        "Index trend",
        "Market breadth",
        "Liquidity",
        "Risk appetite",
        "Main-line strength",
        "Valuation and crowding",
        "Macro/policy environment",
        "Equity risk boundary",
    ]:
        assert expected in joined_facts
    assert "derived:market_research_v1" in snapshot["data_sources"]
    assert any("valuation_metrics_limited" in gap for gap in snapshot["data_gaps"])
    assert snapshot["actionability"] == "observe"


def test_market_data_bundle_builds_p0c_price_data_shape() -> None:
    bundle = collect_market_data_bundle(basis_date="2026-06-15", source="mock")
    price_data = build_p0c_price_data_from_bundle(bundle)

    assert price_data["etfs"]
    assert price_data["stocks"]
    assert price_data["themes"][0]["leading_indicators"]
    assert "symbols" not in price_data["themes"][0]
    assert "leaders" not in price_data


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
    assert len(payload["p0c_research"]["inserted"]) == 4
    repo = SQLiteRepository(db_path)
    assert repo.table_counts()["market_snapshot"] == 1
    assert repo.table_counts()["research_snapshot"] == 4
