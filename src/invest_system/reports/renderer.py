from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from invest_system.repositories import SQLiteRepository
from invest_system.validators.policies import assert_no_sensitive_content
from invest_system.validators.schema_validator import validate_or_raise


DEFAULT_REPORT_DIR = Path("temp/reports")
REPORT_FORMATS = ("markdown", "html", "pdf")


def generate_report(
    repo: SQLiteRepository,
    *,
    as_of: str | None = None,
    output_dir: str | Path = DEFAULT_REPORT_DIR,
    formats: list[str] | None = None,
) -> dict[str, Any]:
    repo.init_db()
    selected_formats = _normalize_formats(formats)
    report_model = _build_report_model(repo, as_of)
    assert_no_sensitive_content(report_model)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    slug = _report_slug(as_of, report_model)

    written_files = []
    if report_model["status"] == "ok":
        for report_format in selected_formats:
            path = output_path / f"{slug}.{_extension(report_format)}"
            content = _render_format(report_model, report_format)
            if report_format == "pdf":
                path.write_bytes(content)
            else:
                path.write_text(content, encoding="utf-8")
            written_files.append(
                {
                    "format": report_format,
                    "path": _safe_path(path),
                    "size_bytes": path.stat().st_size,
                }
            )

    manifest = {
        "schema_version": "1.0",
        "status": report_model["status"],
        "as_of": as_of,
        "generated_at": _utc_now(),
        "source_ids": report_model["source_ids"],
        "formats": selected_formats,
        "files": written_files,
    }
    validate_or_raise(manifest, "report_manifest.schema.json")
    return manifest


def _build_report_model(repo: SQLiteRepository, as_of: str | None) -> dict[str, Any]:
    state = repo.replay_state(as_of)
    market = state.get("market")
    decision = state.get("decision")
    portfolio = state.get("portfolio")
    research_items = _latest_research_by_module(repo, as_of)
    status = "ok" if any([market, decision, portfolio, research_items]) else "empty"
    source_ids = {
        "market_snapshot_id": market.get("snapshot_id") if market else None,
        "decision_id": decision.get("decision_id") if decision else None,
        "portfolio_id": portfolio.get("portfolio_id") if portfolio else None,
        "research_snapshot_ids": [item["snapshot_id"] for item in research_items],
    }
    return {
        "status": status,
        "as_of": as_of,
        "market": market,
        "research_items": research_items,
        "decision": decision,
        "portfolio": portfolio,
        "trace": state.get("trace", {}),
        "source_ids": source_ids,
    }


def _latest_research_by_module(repo: SQLiteRepository, as_of: str | None) -> list[dict[str, Any]]:
    latest_by_module: dict[str, dict[str, Any]] = {}
    for event in repo.timeline(as_of):
        if event["type"] != "research":
            continue
        payload = event["payload"]
        module = payload.get("module", "unknown")
        latest_by_module[module] = payload
    return list(latest_by_module.values())


def _render_format(report_model: dict[str, Any], report_format: str) -> str | bytes:
    if report_format == "markdown":
        return _render_markdown(report_model)
    if report_format == "html":
        return _render_html(report_model)
    if report_format == "pdf":
        return _render_pdf(report_model)
    raise ValueError(f"unsupported report format: {report_format}")


def _render_markdown(report_model: dict[str, Any]) -> str:
    lines = [
        "# MyInvest Research Report",
        "",
        "## Executive Summary",
        _executive_summary(report_model),
        "",
        "## Market State",
        *_market_lines(report_model.get("market")),
        "",
        "## Research Insights",
        *_research_lines(report_model["research_items"]),
        "",
        "## Decision Log",
        *_decision_lines(report_model.get("decision")),
        "",
        "## Portfolio State",
        *_portfolio_lines(report_model.get("portfolio")),
        "",
        "## Risk Section",
        *_risk_lines(report_model),
        "",
        "## Replay Trace",
        *_trace_lines(report_model),
        "",
    ]
    return "\n".join(lines)


def _render_html(report_model: dict[str, Any]) -> str:
    sections = [
        _html_section("Executive Summary", [_executive_summary(report_model)]),
        _html_section("Market State", _market_lines(report_model.get("market"))),
        _html_section("Research Insights", _research_lines(report_model["research_items"])),
        _html_section("Decision Log", _decision_lines(report_model.get("decision"))),
        _html_section("Portfolio State", _portfolio_lines(report_model.get("portfolio"))),
        _html_section("Risk Section", _risk_lines(report_model)),
        _html_section("Replay Trace", _trace_lines(report_model)),
    ]
    return (
        "<!doctype html>\n"
        "<html lang=\"en\">\n"
        "<head><meta charset=\"utf-8\"><title>MyInvest Research Report</title>"
        "<style>body{font-family:Arial,sans-serif;max-width:960px;margin:32px auto;line-height:1.5;}"
        "h1,h2{color:#111827;}li{margin:4px 0;}code{background:#f3f4f6;padding:1px 4px;}</style>"
        "</head>\n<body>\n<h1>MyInvest Research Report</h1>\n"
        + "\n".join(sections)
        + "\n</body>\n</html>\n"
    )


def _render_pdf(report_model: dict[str, Any]) -> bytes:
    markdown = _render_markdown(report_model)
    text_lines = [_ascii_pdf_line(line) for line in markdown.splitlines() if line.strip()][:42]
    return _minimal_pdf(text_lines)


def _executive_summary(report_model: dict[str, Any]) -> str:
    market = report_model.get("market")
    decision = report_model.get("decision")
    portfolio = report_model.get("portfolio")
    if not any([market, decision, portfolio, report_model["research_items"]]):
        return "No replay state is available for the selected as-of point."
    parts = []
    if market:
        parts.append(market["executive_summary"])
    if decision:
        parts.append(f"Decision record {decision['decision_id']} is included.")
    if portfolio:
        parts.append(f"Portfolio snapshot {portfolio['portfolio_id']} is included.")
    return " ".join(parts)


def _market_lines(market: dict[str, Any] | None) -> list[str]:
    if market is None:
        return ["- Market snapshot: unavailable"]
    payload = market["payload"]
    return [
        f"- Snapshot: `{market['snapshot_id']}`",
        f"- Market score: {payload['market_score']}",
        f"- Risk level: {payload['risk_level']}",
        f"- Equity range: {_ratio(payload['equity_min'])} to {_ratio(payload['equity_max'])}",
        f"- Confidence: {_ratio(market['confidence'])}",
        f"- Data sources: {', '.join(market['data_sources'])}",
        f"- Data gaps: {_list_or_none(market['data_gaps'])}",
        f"- Conflicts: {_list_or_none(market['conflicts'])}",
    ]


def _research_lines(research_items: list[dict[str, Any]]) -> list[str]:
    if not research_items:
        return ["- Research snapshots: unavailable"]
    lines = []
    for item in research_items:
        lines.append(
            f"- `{item['module']}` / `{item['snapshot_id']}`: "
            f"{item['executive_summary']} Confidence {_ratio(item['confidence'])}."
        )
        if item.get("key_facts"):
            lines.append(f"  - Key fact: {item['key_facts'][0]}")
    return lines


def _decision_lines(decision: dict[str, Any] | None) -> list[str]:
    if decision is None:
        return ["- Decision record: unavailable"]
    lines = [f"- Decision: `{decision['decision_id']}`", f"- Status: {decision['status']}"]
    for action in decision["decision_actions"]:
        lines.append(
            f"- {action['symbol']}: {action['action']} "
            f"current {_ratio(action['current_weight'])}, target {_ratio(action['target_weight'])}, "
            f"delta {action['delta_weight_pp']} pp"
        )
    return lines


def _portfolio_lines(portfolio: dict[str, Any] | None) -> list[str]:
    if portfolio is None:
        return ["- Portfolio snapshot: unavailable"]
    lines = [
        f"- Portfolio: `{portfolio['portfolio_id']}`",
        f"- Cash weight: {_ratio(portfolio['cash_weight'])}",
        f"- PnL ratio: {_ratio(portfolio['pnl_ratio'])}",
        f"- Turnover: {_ratio(portfolio['turnover'])}",
    ]
    for symbol, weight in portfolio["holdings_weight"].items():
        lines.append(f"- Holding {symbol}: {_ratio(weight)}")
    return lines


def _risk_lines(report_model: dict[str, Any]) -> list[str]:
    risks: list[str] = []
    for payload in [report_model.get("market"), *report_model["research_items"], report_model.get("decision")]:
        if not payload:
            continue
        risks.extend(payload.get("risks", []))
        risks.extend(payload.get("risk_notes", []))
        risks.extend([f"Data gap: {item}" for item in payload.get("data_gaps", [])])
    if not risks:
        return ["- No explicit risk items were recorded."]
    return [f"- {item}" for item in risks]


def _trace_lines(report_model: dict[str, Any]) -> list[str]:
    source_ids = report_model["source_ids"]
    return [
        f"- Market snapshot: `{source_ids['market_snapshot_id']}`",
        f"- Decision: `{source_ids['decision_id']}`",
        f"- Portfolio: `{source_ids['portfolio_id']}`",
        f"- Research snapshots: {_list_or_none(source_ids['research_snapshot_ids'])}",
    ]


def _html_section(title: str, lines: list[str]) -> str:
    items = "\n".join(f"<li>{html.escape(_strip_markdown_bullet(line))}</li>" for line in lines)
    return f"<section><h2>{html.escape(title)}</h2><ul>{items}</ul></section>"


def _minimal_pdf(lines: list[str]) -> bytes:
    escaped_lines = [_pdf_escape(line) for line in lines]
    text_ops = ["BT", "/F1 10 Tf", "50 780 Td"]
    for index, line in enumerate(escaped_lines):
        if index:
            text_ops.append("0 -16 Td")
        text_ops.append(f"({line}) Tj")
    text_ops.append("ET")
    stream = "\n".join(text_ops).encode("latin-1", errors="replace")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    chunks = [b"%PDF-1.4\n"]
    offsets = [0]
    for object_id, body in enumerate(objects, start=1):
        offsets.append(sum(len(chunk) for chunk in chunks))
        chunks.append(f"{object_id} 0 obj\n".encode("ascii") + body + b"\nendobj\n")
    xref_offset = sum(len(chunk) for chunk in chunks)
    chunks.append(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode("ascii"))
    for offset in offsets[1:]:
        chunks.append(f"{offset:010d} 00000 n \n".encode("ascii"))
    chunks.append(
        (
            "trailer\n"
            f"<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            "startxref\n"
            f"{xref_offset}\n"
            "%%EOF\n"
        ).encode("ascii")
    )
    return b"".join(chunks)


def _normalize_formats(formats: list[str] | None) -> list[str]:
    if not formats:
        return ["markdown", "html"]
    if "all" in formats:
        return list(REPORT_FORMATS)
    invalid = [item for item in formats if item not in REPORT_FORMATS]
    if invalid:
        raise ValueError(f"unsupported report formats: {invalid}")
    return list(dict.fromkeys(formats))


def _extension(report_format: str) -> str:
    if report_format == "markdown":
        return "md"
    return report_format


def _report_slug(as_of: str | None, report_model: dict[str, Any]) -> str:
    value = as_of or report_model["source_ids"]["portfolio_id"] or "latest"
    return "report-" + re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-")


def _safe_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return path.name


def _ratio(value: float | int) -> str:
    return f"{float(value) * 100:.2f}%"


def _list_or_none(values: list[Any]) -> str:
    return ", ".join(str(item) for item in values) if values else "none"


def _strip_markdown_bullet(line: str) -> str:
    return line.lstrip("- ").replace("`", "")


def _ascii_pdf_line(line: str) -> str:
    return line.replace("`", "").encode("latin-1", errors="replace").decode("latin-1")


def _pdf_escape(line: str) -> str:
    return line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
