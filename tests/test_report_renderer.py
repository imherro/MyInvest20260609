from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from invest_system.adapters import append_market_snapshot_from_adapters, build_p0c_price_data_from_bundle
from invest_system.golden import seed_multiday_repository
from invest_system.reports import generate_report
from invest_system.repositories import SQLiteRepository
from invest_system.research import generate_p0c_research
from invest_system.validators.schema_validator import validate_or_raise


def test_generate_report_writes_markdown_and_html_from_replay_state(tmp_path) -> None:
    db_path = tmp_path / "report.sqlite"
    output_dir = tmp_path / "reports"
    repo = SQLiteRepository(db_path)
    seed_multiday_repository(repo)
    market_data = append_market_snapshot_from_adapters(repo, basis_date="2026-06-15", source="mock")
    generate_p0c_research(repo, "2026-06-15", price_data=build_p0c_price_data_from_bundle(market_data["bundle"]))

    manifest = generate_report(repo, as_of="2026-06-15", output_dir=output_dir, formats=["markdown", "html"])

    assert manifest["status"] == "ok"
    validate_or_raise(manifest, "report_manifest.schema.json")
    assert {item["format"] for item in manifest["files"]} == {"markdown", "html"}
    markdown_path = output_dir / "report-2026-06-15.md"
    html_path = output_dir / "report-2026-06-15.html"
    assert markdown_path.exists()
    assert html_path.exists()
    markdown = markdown_path.read_text(encoding="utf-8")
    html = html_path.read_text(encoding="utf-8")
    assert "Executive Summary" in markdown
    assert "Market State" in markdown
    assert "Decision Log" in markdown
    assert "Portfolio State" in markdown
    assert "<h2>Risk Section</h2>" in html


def test_generate_report_cli_outputs_json_manifest(tmp_path) -> None:
    db_path = tmp_path / "report_cli.sqlite"
    output_dir = tmp_path / "reports"
    seed_multiday_repository(SQLiteRepository(db_path))

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/generate_report.py",
            "--db",
            str(db_path),
            "--as-of",
            "2026-06-14",
            "--output-dir",
            str(output_dir),
            "--format",
            "all",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    manifest = json.loads(completed.stdout)

    assert manifest["status"] == "ok"
    assert {item["format"] for item in manifest["files"]} == {"markdown", "html", "pdf"}
    assert (output_dir / "report-2026-06-14.md").exists()
    assert (output_dir / "report-2026-06-14.html").exists()
    assert (output_dir / "report-2026-06-14.pdf").read_bytes().startswith(b"%PDF-1.4")


def test_empty_report_returns_json_without_files(tmp_path) -> None:
    repo = SQLiteRepository(tmp_path / "empty.sqlite")
    manifest = generate_report(repo, as_of="2026-06-15", output_dir=tmp_path / "reports")

    assert manifest["status"] == "empty"
    assert manifest["files"] == []
