from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from invest_system.adapters.baostock_adapter import collect_baostock
from invest_system.adapters.fred_adapter import collect_fred
from invest_system.adapters.mock_adapter import collect_mock
from invest_system.adapters.tushare_adapter import collect_tushare
from invest_system.adapters.yfinance_adapter import collect_yfinance
from invest_system.local_env import load_local_env
from invest_system.repositories import SQLiteRepository
from invest_system.validators.schema_validator import validate_or_raise


DEFAULT_SYMBOLS = ("510300.SH", "159915.SZ", "002920.SZ", "511360.SH")
DEFAULT_INDICES = ("000001.SH", "000300.SH", "000905.SH")
SOURCE_ORDER = ("tushare", "baostock", "yfinance", "fred")


def collect_market_data_bundle(
    *,
    basis_date: str,
    source: str = "auto",
    allow_network: bool = False,
    symbols: list[str] | None = None,
    indices: list[str] | None = None,
) -> dict[str, Any]:
    load_local_env()
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
    signals = _market_signals(bundle, market_score, crowding_penalty)
    data_gaps = _dedupe_strings([*bundle["data_gaps"], *_market_research_data_gaps(bundle)])
    risk_level = _risk_level(quality, crowding_penalty, signals)
    equity_min, equity_max = _equity_research_boundary(risk_level, signals)
    data_sources = [f"adapter:{source_name}" for source_name in bundle["successful_sources"]]
    if not data_sources:
        data_sources = ["adapter:unavailable"]
    data_sources.append("derived:market_research_v1")

    snapshot = {
        "schema_version": "1.0",
        "snapshot_id": f"market-{bundle['basis_date']}-{bundle['mode']}-adapter",
        "basis_date": bundle["basis_date"],
        "generated_at": _utc_now(),
        "module": "market_position",
        "data_sources": data_sources,
        "data_gaps": data_gaps,
        "conflicts": bundle["conflicts"],
        "executive_summary": (
            f"A-share market state is {signals['trend_state']} with {signals['breadth_state']} breadth, "
            f"{signals['liquidity_state']} liquidity, and {signals['risk_appetite']} risk appetite. "
            "The result is a Research/Market snapshot only."
        ),
        "key_facts": [
            f"Basis date is {bundle['basis_date']} and only complete-day adapter records are used.",
            (
                "Index trend: "
                f"{signals['trend_state']}; average index daily return {signals['index_return_pct']}; "
                f"positive index ratio {signals['index_positive_pct']}."
            ),
            (
                "Market breadth: "
                f"{signals['breadth_state']}; positive normalized-record ratio {signals['breadth_pct']}."
            ),
            (
                "Liquidity: "
                f"{signals['liquidity_state']}; average turnover proxy {signals['turnover_pct']}."
            ),
            (
                "Risk appetite: "
                f"{signals['risk_appetite']}; average symbol daily return {signals['symbol_return_pct']}."
            ),
            (
                "Main-line strength: "
                f"{signals['main_line_strength']}; positive symbol ratio {signals['symbol_positive_pct']}."
            ),
            (
                "Valuation and crowding: "
                f"{signals['crowding_state']}; crowding penalty score {crowding_penalty}."
            ),
            f"Macro/policy environment: {signals['macro_policy_state']}.",
            (
                "Equity risk boundary: "
                f"{_format_pct(equity_min)} to {_format_pct(equity_max)}; "
                f"stance is {signals['equity_risk_stance']}."
            ),
        ],
        "reasoning": [
            "Trend, breadth, liquidity, risk appetite, and crowding are derived from ratios and scores.",
            "Missing live-source, macro, policy, or valuation inputs are recorded as data gaps and lower confidence.",
            "The equity boundary is a market-risk review band, not a buy, sell, add, reduce, or execution instruction.",
            "When breadth weakens, liquidity is thin, or crowding is elevated, the snapshot remains observe-only.",
        ],
        "risks": [
            "External source outage can reduce confidence.",
            "Conflicting source values must be reviewed before production use.",
            "No single-security conclusion is valid from this Research/Market layer alone.",
            "Policy or macro news not represented in structured adapters can invalidate the market state.",
        ],
        "conclusion_strength": _conclusion_strength(quality, data_gaps),
        "actionability": "observe",
        "confidence": _confidence(quality, data_gaps),
        "invalidation_conditions": ["A newer market data bundle supersedes this snapshot."],
        "next_review_date": bundle["basis_date"],
        "must_not_do": [
            "Do not treat read-only market data as a broker execution instruction.",
            "Do not produce single-security buy/add/reduce/sell guidance from this market snapshot.",
            "Do not raise equity risk without fresh data, ResearchFirst coverage, and human review.",
        ],
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
            "headline_index": _headline_index(bundle),
        },
    }
    validate_or_raise(snapshot, "market_snapshot.schema.json")
    return snapshot


def _headline_index(bundle: dict[str, Any]) -> dict[str, Any] | None:
    for row in bundle["indices"]:
        if row["symbol"] == "000001.SH":
            return _index_payload(row, "上证指数")
    for row in bundle["indices"]:
        name = str(row.get("name", ""))
        if "上证" in name or "Shanghai" in name or "SSE" in name:
            return _index_payload(row, name)
    return None


def _index_payload(row: dict[str, Any], fallback_name: str) -> dict[str, Any]:
    return {
        "symbol": row["symbol"],
        "name": row.get("name") or fallback_name,
        "last_price": row.get("last_price"),
        "daily_return": row["daily_return"],
        "source": row["source"],
    }


def _market_signals(bundle: dict[str, Any], market_score: float, crowding_penalty: float) -> dict[str, Any]:
    index_return = _average_daily_return(bundle["indices"])
    symbol_return = _average_daily_return(bundle["symbols"])
    combined_return = _average_return(bundle)
    index_positive = _positive_ratio_rows(bundle["indices"])
    symbol_positive = _positive_ratio_rows(bundle["symbols"])
    breadth = _positive_ratio(bundle)
    turnover = _average_turnover(bundle)
    return {
        "trend_state": _trend_state(index_return),
        "breadth_state": _breadth_state(breadth),
        "liquidity_state": _liquidity_state(turnover, bundle["symbols"]),
        "risk_appetite": _risk_appetite_state(combined_return, breadth),
        "main_line_strength": _main_line_strength(symbol_return, symbol_positive),
        "crowding_state": _crowding_state(crowding_penalty),
        "macro_policy_state": (
            "structured macro/policy input available"
            if bundle["macro"]
            else "limited by missing structured macro/policy input"
        ),
        "equity_risk_stance": _equity_risk_stance(market_score, breadth, crowding_penalty),
        "index_return_pct": _format_pct(index_return),
        "symbol_return_pct": _format_pct(symbol_return),
        "index_positive_pct": _format_pct(index_positive),
        "symbol_positive_pct": _format_pct(symbol_positive),
        "breadth_pct": _format_pct(breadth),
        "turnover_pct": _format_pct(turnover),
        "combined_return": combined_return,
        "breadth": breadth,
    }


def _market_research_data_gaps(bundle: dict[str, Any]) -> list[str]:
    gaps: list[str] = []
    if not bundle["indices"]:
        gaps.append("index_trend_missing:no index records were available")
    elif len(bundle["indices"]) < len(DEFAULT_INDICES):
        gaps.append("index_trend_partial:some requested index records were unavailable")
    if not bundle["symbols"]:
        gaps.append("market_breadth_missing:no symbol records were available")
    elif len(bundle["symbols"]) < len(DEFAULT_SYMBOLS):
        gaps.append("market_breadth_partial:some requested symbol records were unavailable")
    if not bundle["symbols"] or all(row["turnover_ratio"] == 0 for row in bundle["symbols"]):
        gaps.append("liquidity_proxy_missing:no usable turnover proxy was available")
    if not bundle["macro"]:
        gaps.append("macro_policy_limited:no structured macro or policy adapter record was available")
    gaps.append("valuation_metrics_limited:no valuation percentile data was available; crowding uses return and conflict proxies")
    if "mock" in bundle["successful_sources"]:
        gaps.append("mock_fallback_used:mock data contributed because live coverage was incomplete")
    return gaps


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


def _conclusion_strength(quality: float, data_gaps: list[str]) -> str:
    if quality >= 0.85 and not data_gaps:
        return "strong"
    if quality >= 0.55:
        return "medium"
    return "weak"


def _confidence(quality: float, data_gaps: list[str]) -> float:
    gap_penalty = min(0.35, len(data_gaps) * 0.03)
    return round(max(0.2, min(0.9, quality - gap_penalty)), 4)


def _risk_level(quality: float, crowding_penalty: float, signals: dict[str, Any]) -> str:
    if quality < 0.45 or crowding_penalty >= 35 or signals["breadth"] < 0.35:
        return "high"
    if crowding_penalty >= 15 or signals["breadth"] < 0.5 or signals["combined_return"] < -0.005:
        return "medium"
    return "low"


def _equity_research_boundary(risk_level: str, signals: dict[str, Any]) -> tuple[float, float]:
    if risk_level == "high":
        return 0.35, 0.55
    if risk_level == "medium":
        return 0.45, 0.65
    if signals["equity_risk_stance"] == "watch_before_increase":
        return 0.45, 0.65
    return 0.5, 0.7


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


def _dedupe_strings(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


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
    return _average_daily_return(rows)


def _average_daily_return(rows: list[dict[str, Any]]) -> float:
    if not rows:
        return 0
    return sum(row["daily_return"] for row in rows) / len(rows)


def _positive_ratio(bundle: dict[str, Any]) -> float:
    rows = bundle["indices"] + bundle["symbols"]
    return _positive_ratio_rows(rows)


def _positive_ratio_rows(rows: list[dict[str, Any]]) -> float:
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


def _format_pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def _trend_state(index_return: float) -> str:
    if index_return >= 0.005:
        return "uptrend"
    if index_return <= -0.005:
        return "downtrend"
    return "range_bound"


def _breadth_state(breadth: float) -> str:
    if breadth >= 0.65:
        return "broad"
    if breadth >= 0.45:
        return "mixed"
    return "narrow"


def _liquidity_state(turnover: float, rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "unknown"
    if turnover >= 0.025:
        return "active"
    if turnover >= 0.012:
        return "normal"
    return "thin"


def _risk_appetite_state(average_return: float, breadth: float) -> str:
    if average_return >= 0.003 and breadth >= 0.55:
        return "risk_on"
    if average_return <= -0.003 or breadth < 0.4:
        return "risk_off"
    return "neutral"


def _main_line_strength(symbol_return: float, positive_ratio: float) -> str:
    if symbol_return >= 0.004 and positive_ratio >= 0.6:
        return "strong"
    if symbol_return >= 0 and positive_ratio >= 0.4:
        return "medium"
    return "weak"


def _crowding_state(crowding_penalty: float) -> str:
    if crowding_penalty >= 35:
        return "elevated"
    if crowding_penalty >= 15:
        return "watch"
    return "contained"


def _equity_risk_stance(market_score: float, breadth: float, crowding_penalty: float) -> str:
    if market_score >= 60 and breadth >= 0.55 and crowding_penalty < 15:
        return "can_review_higher_risk"
    if market_score < 45 or breadth < 0.45 or crowding_penalty >= 35:
        return "defensive"
    return "watch_before_increase"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
