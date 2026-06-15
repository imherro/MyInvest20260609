from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from invest_system.adapters.baostock_adapter import collect_baostock
from invest_system.adapters.fred_adapter import collect_fred
from invest_system.adapters.mock_adapter import collect_mock
from invest_system.adapters.tushare_adapter import collect_tushare
from invest_system.adapters.yfinance_adapter import collect_yfinance
from invest_system.repositories import SQLiteRepository
from invest_system.validators.schema_validator import validate_or_raise


DEFAULT_SYMBOLS = ("510300.SH", "159915.SZ", "002920.SZ", "511360.SH")
DEFAULT_INDICES = ("000300.SH", "000905.SH")
SOURCE_ORDER = ("tushare", "baostock", "yfinance", "fred")


def collect_market_data_bundle(
    *,
    basis_date: str,
    source: str = "auto",
    allow_network: bool = False,
    symbols: list[str] | None = None,
    indices: list[str] | None = None,
) -> dict[str, Any]:
    request = {
        "basis_date": basis_date,
        "symbols": symbols or list(DEFAULT_SYMBOLS),
        "indices": indices or list(DEFAULT_INDICES),
        "allow_network": allow_network,
    }
    selected = _selected_sources(source)
    results = [_collect_source(name, request) for name in selected]
    if _requires_mock_fallback(results):
        results.append(collect_mock(request))

    bundle = _bundle_from_results(basis_date=basis_date, requested_source=source, results=results)
    validate_or_raise(bundle, "market_data_bundle.schema.json")
    return bundle


def append_market_snapshot_from_adapters(
    repo: SQLiteRepository,
    *,
    basis_date: str,
    source: str = "auto",
    allow_network: bool = False,
    symbols: list[str] | None = None,
    indices: list[str] | None = None,
) -> dict[str, Any]:
    repo.init_db()
    bundle = collect_market_data_bundle(
        basis_date=basis_date,
        source=source,
        allow_network=allow_network,
        symbols=symbols,
        indices=indices,
    )
    market_snapshot = build_market_snapshot_from_bundle(bundle)
    inserted = repo.append_market_snapshot(market_snapshot)
    return {
        "status": "ok",
        "inserted": inserted,
        "bundle": bundle,
        "market_snapshot_id": market_snapshot["snapshot_id"],
    }


def build_market_snapshot_from_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    validate_or_raise(bundle, "market_data_bundle.schema.json")
    market_score = _market_score(bundle)
    crowding_penalty = _crowding_penalty(bundle)
    quality = bundle["quality"]["completeness_score"]
    risk_level = "high" if quality < 0.45 or crowding_penalty >= 35 else "medium" if crowding_penalty >= 15 else "low"
    equity_min = 0.35 if risk_level == "high" else 0.45 if risk_level == "medium" else 0.5
    equity_max = 0.55 if risk_level == "high" else 0.65 if risk_level == "medium" else 0.7
    data_sources = [f"adapter:{source_name}" for source_name in bundle["successful_sources"]]
    if not data_sources:
        data_sources = ["adapter:unavailable"]

    snapshot = {
        "schema_version": "1.0",
        "snapshot_id": f"market-{bundle['basis_date']}-{bundle['mode']}-adapter",
        "basis_date": bundle["basis_date"],
        "generated_at": _utc_now(),
        "module": "market_position",
        "data_sources": data_sources,
        "data_gaps": bundle["data_gaps"],
        "conflicts": bundle["conflicts"],
        "executive_summary": "Read-only market data is normalized into a market position snapshot.",
        "key_facts": [
            f"Successful source count: {len(bundle['successful_sources'])}.",
            f"Symbol records: {len(bundle['symbols'])}.",
            f"Index records: {len(bundle['indices'])}.",
        ],
        "reasoning": [
            "Adapter data is read-only and converted into the existing market_snapshot schema.",
            "Mock fallback is retained when live data sources are unavailable.",
        ],
        "risks": [
            "External source outage can reduce confidence.",
            "Conflicting source values must be reviewed before production use.",
        ],
        "conclusion_strength": "medium" if quality >= 0.55 else "weak",
        "actionability": "observe",
        "confidence": round(max(0.2, min(0.9, quality)), 4),
        "invalidation_conditions": ["A newer market data bundle supersedes this snapshot."],
        "next_review_date": bundle["basis_date"],
        "must_not_do": ["Do not treat read-only market data as a broker execution instruction."],
        "required_human_review": True,
        "status": "json_validated",
        "trace": {
            "fact_pack_id": bundle["bundle_id"],
            "source_market_snapshot_id": None,
        },
        "payload": {
            "market_score": market_score,
            "equity_min": equity_min,
            "equity_max": equity_max,
            "risk_level": risk_level,
            "reason": _market_reasons(bundle, market_score),
            "crowding_penalty": crowding_penalty,
        },
    }
    validate_or_raise(snapshot, "market_snapshot.schema.json")
    return snapshot


def build_p0c_price_data_from_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    validate_or_raise(bundle, "market_data_bundle.schema.json")
    symbol_rows = {row["symbol"]: row for row in bundle["symbols"]}
    etf_row = symbol_rows.get("510300.SH") or _first_symbol_row(bundle)
    stock_row = symbol_rows.get("002920.SZ") or _first_symbol_row(bundle)
    theme_symbols = [row["symbol"] for row in bundle["symbols"][:3]] or ["510300.SH", "159915.SZ", "002920.SZ"]
    average_return = _average_return(bundle)
    return_signal = _bounded(0.5 + average_return * 12, 0.05, 0.95)
    breadth_signal = _bounded(_positive_ratio(bundle), 0.05, 0.95)
    liquidity_signal = _bounded(_average_turnover(bundle) * 25, 0.05, 0.95)
    theme_name = "adapter_market_breadth"

    return {
        "etfs": {
            etf_row["symbol"]: {
                "price": etf_row["last_price"],
                "fair_value_mid": round(etf_row["last_price"] * 1.06, 4),
                "tracking_target": "CSI300",
                "volatility": _volatility_proxy(etf_row["daily_return"]),
            }
        },
        "stocks": {
            stock_row["symbol"]: {
                "price": stock_row["last_price"],
                "fair_value_mid": round(stock_row["last_price"] * 1.08, 4),
                "method": "adapter_relative_valuation",
                "volatility": _volatility_proxy(stock_row["daily_return"]),
            }
        },
        "themes": [
            {
                "theme": theme_name,
                "symbols": theme_symbols,
                "related_etfs": [etf_row["symbol"]],
                "return_signal": round(return_signal, 4),
                "breadth_signal": round(breadth_signal, 4),
                "liquidity_signal": round(liquidity_signal, 4),
            }
        ],
        "leaders": {
            theme_name: [
                {
                    "symbol": row["symbol"],
                    "momentum": round(_bounded(0.5 + row["daily_return"] * 15, 0.05, 0.95), 4),
                    "liquidity": round(_bounded(row["turnover_ratio"] * 30, 0.05, 0.95), 4),
                    "valuation": round(_bounded(0.62 - row["daily_return"] * 3, 0.05, 0.95), 4),
                }
                for row in bundle["symbols"][:3]
            ]
        },
    }


def _selected_sources(source: str) -> list[str]:
    if source == "auto":
        return list(SOURCE_ORDER)
    if source == "mock":
        return ["mock"]
    if source in SOURCE_ORDER:
        return [source]
    raise ValueError(f"unsupported market data source: {source}")


def _collect_source(name: str, request: dict[str, Any]) -> dict[str, Any]:
    if name == "mock":
        return collect_mock(request)
    if name == "tushare":
        return collect_tushare(request)
    if name == "baostock":
        return collect_baostock(request)
    if name == "yfinance":
        return collect_yfinance(request)
    if name == "fred":
        return collect_fred(request)
    raise ValueError(f"unsupported market data source: {name}")


def _requires_mock_fallback(results: list[dict[str, Any]]) -> bool:
    if any(result["source"] == "mock" and result["status"] == "ok" for result in results):
        return False
    symbols = sum(len(result.get("symbols", [])) for result in results if result["status"] == "ok")
    indices = sum(len(result.get("indices", [])) for result in results if result["status"] == "ok")
    return symbols == 0 and indices == 0


def _bundle_from_results(
    *,
    basis_date: str,
    requested_source: str,
    results: list[dict[str, Any]],
) -> dict[str, Any]:
    successful = [result["source"] for result in results if result["status"] == "ok"]
    data_gaps = [f"{result['source']}:{gap}" for result in results for gap in result.get("data_gaps", [])]
    conflicts = [f"{result['source']}:{conflict}" for result in results for conflict in result.get("conflicts", [])]
    indices = _dedupe_market_rows("symbol", [row for result in results for row in result.get("indices", [])])
    symbols = _dedupe_market_rows("symbol", [row for result in results for row in result.get("symbols", [])])
    macro = _dedupe_market_rows("indicator", [row for result in results for row in result.get("macro", [])])
    attempted = [result["source"] for result in results]
    mode = requested_source
    if len(successful) > 1 and requested_source != "mock":
        mode = "mixed"
    if requested_source == "auto" and successful == ["mock"]:
        mode = "mock"

    expected_records = max(1, len(DEFAULT_SYMBOLS) + len(DEFAULT_INDICES))
    completeness = min(1.0, (len(indices) + len(symbols)) / expected_records)
    if successful:
        completeness = max(completeness, 0.35)
    if data_gaps and "mock" in successful:
        completeness = min(completeness, 0.7)

    return {
        "schema_version": "1.0",
        "bundle_id": f"market-data-bundle-{basis_date}-{mode}",
        "basis_date": basis_date,
        "generated_at": _utc_now(),
        "mode": mode,
        "read_only": True,
        "attempted_sources": attempted,
        "successful_sources": successful,
        "data_gaps": data_gaps,
        "conflicts": conflicts,
        "source_results": [
            {
                "source": result["source"],
                "status": result["status"],
                "read_only": True,
                "record_count": len(result.get("indices", []))
                + len(result.get("symbols", []))
                + len(result.get("macro", [])),
                "data_gap": result.get("data_gaps", [None])[0] if result.get("data_gaps") else None,
            }
            for result in results
        ],
        "indices": indices,
        "symbols": symbols,
        "macro": macro,
        "quality": {
            "completeness_score": round(completeness, 4),
            "conflict_score": 0 if conflicts else 1,
            "freshness_score": 1,
        },
    }


def _dedupe_market_rows(key: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for row in rows:
        value = row[key]
        if value in seen:
            continue
        seen.add(value)
        deduped.append(row)
    return deduped


def _market_score(bundle: dict[str, Any]) -> float:
    average_return = _average_return(bundle)
    quality = bundle["quality"]["completeness_score"]
    score = 50 + average_return * 800 + (quality - 0.5) * 20
    if bundle["conflicts"]:
        score -= 8
    return round(_bounded(score, 0, 100), 4)


def _crowding_penalty(bundle: dict[str, Any]) -> float:
    return round(_bounded(abs(_average_return(bundle)) * 500 + len(bundle["conflicts"]) * 10, 0, 100), 4)


def _market_reasons(bundle: dict[str, Any], market_score: float) -> list[str]:
    reasons = [f"Market score is {market_score} from read-only adapter data."]
    if "mock" in bundle["successful_sources"]:
        reasons.append("Mock fallback is active for unavailable live sources.")
    if bundle["data_gaps"]:
        reasons.append("Data gaps are recorded in the snapshot for review.")
    return reasons


def _average_return(bundle: dict[str, Any]) -> float:
    rows = bundle["indices"] + bundle["symbols"]
    if not rows:
        return 0
    return sum(row["daily_return"] for row in rows) / len(rows)


def _positive_ratio(bundle: dict[str, Any]) -> float:
    rows = bundle["indices"] + bundle["symbols"]
    if not rows:
        return 0.5
    return sum(1 for row in rows if row["daily_return"] >= 0) / len(rows)


def _average_turnover(bundle: dict[str, Any]) -> float:
    rows = bundle["symbols"]
    if not rows:
        return 0.02
    return sum(row["turnover_ratio"] for row in rows) / len(rows)


def _first_symbol_row(bundle: dict[str, Any]) -> dict[str, Any]:
    if bundle["symbols"]:
        return bundle["symbols"][0]
    return {
        "symbol": "510300.SH",
        "last_price": 3.82,
        "daily_return": 0.003,
        "turnover_ratio": 0.02,
        "source": "adapter:default",
    }


def _volatility_proxy(daily_return: float) -> float:
    return round(_bounded(0.16 + abs(daily_return) * 12, 0.12, 0.35), 4)


def _bounded(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
