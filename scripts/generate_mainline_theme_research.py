from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from invest_system.local_env import load_local_env  # noqa: E402
from invest_system.repositories import DEFAULT_DB_PATH, SQLiteRepository  # noqa: E402
from invest_system.validators.module_contracts import validate_module_contract  # noqa: E402
from invest_system.validators.schema_validator import validate_or_raise  # noqa: E402


@dataclass(frozen=True)
class ThemeCluster:
    name: str
    reason: str
    ths_codes: tuple[str, ...]
    sw_codes: tuple[str, ...]


THEME_CLUSTERS = (
    ThemeCluster(
        name="AI infrastructure hardware chain",
        reason="electronics and communications strength is concentrated in PCB, CPO, F5G, optical fiber, and high-speed connection themes",
        ths_codes=("885959.TI", "886033.TI", "885998.TI", "886084.TI", "886073.TI"),
        sw_codes=("801080.SI", "801770.SI"),
    ),
    ThemeCluster(
        name="advanced electronics manufacturing chain",
        reason="advanced packaging, passive components, discrete devices, and display-related hardware show synchronized strength",
        ths_codes=("886009.TI", "884093.TI", "884090.TI", "885875.TI", "885809.TI"),
        sw_codes=("801080.SI",),
    ),
    ThemeCluster(
        name="strategic metal and copper-foil materials",
        reason="tungsten and PET copper foil show stronger short-cycle persistence than most concept groups",
        ths_codes=("884282.TI", "886020.TI"),
        sw_codes=("801050.SI",),
    ),
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--as-of", default=date.today().isoformat())
    parser.add_argument("--output")
    parser.add_argument("--no-append", action="store_true")
    args = parser.parse_args()

    load_local_env()
    result = generate_snapshot(as_of=date.fromisoformat(args.as_of))
    output_path = Path(args.output) if args.output else _default_output_path(result["basis_date"])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(output_path, result)

    inserted = None
    if not args.no_append:
        repo = SQLiteRepository(args.db)
        repo.init_db()
        inserted = repo.append_research_snapshot(result)

    print(
        json.dumps(
            {
                "status": "ok",
                "snapshot_id": result["snapshot_id"],
                "basis_date": result["basis_date"],
                "next_review_date": result["next_review_date"],
                "inserted": inserted,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


def generate_snapshot(as_of: date) -> dict[str, Any]:
    unavailable_reason = _tushare_unavailable_reason()
    if unavailable_reason:
        return _fallback_snapshot(as_of, unavailable_reason)

    try:
        import tushare as ts  # type: ignore[import-not-found]

        token = os.environ["TUSHARE_TOKEN"]
        ts.set_token(token)
        pro = ts.pro_api(token)
        basis_date, basis_gaps = _latest_complete_trading_day(pro, as_of)
        evidence = _collect_theme_evidence(pro, basis_date)
        snapshot = _snapshot_from_evidence(
            basis_date=basis_date,
            next_review_date=_next_review_date(pro, basis_date),
            data_gaps=[*basis_gaps, *evidence["data_gaps"]],
            clusters=evidence["clusters"],
            source_market_snapshot_id=None,
        )
    except Exception as exc:  # noqa: BLE001
        snapshot = _fallback_snapshot(as_of, f"tushare_runtime_failure:{type(exc).__name__}")

    validate_or_raise(snapshot["payload"], "theme_research_payload.schema.json")
    validate_or_raise(snapshot, "research.schema.json")
    validate_module_contract(snapshot)
    return snapshot


def _latest_complete_trading_day(pro: Any, as_of: date) -> tuple[str, list[str]]:
    start = (as_of - timedelta(days=30)).strftime("%Y%m%d")
    end = as_of.strftime("%Y%m%d")
    calendar = pro.trade_cal(exchange="SSE", start_date=start, end_date=end)
    if calendar is None or calendar.empty:
        raise RuntimeError("trade_calendar_unavailable")

    open_days = [
        str(row["cal_date"])
        for _, row in calendar.sort_values("cal_date", ascending=False).iterrows()
        if int(row.get("is_open", 0)) == 1
    ]
    for trade_date in open_days:
        if _has_complete_daily_records(pro, trade_date):
            basis_date = _format_trade_date(trade_date)
            gaps = []
            if trade_date != end:
                gaps.append(f"same_day_complete_data_unavailable:{end}")
            return basis_date, gaps
    raise RuntimeError("complete_daily_records_unavailable")


def _has_complete_daily_records(pro: Any, trade_date: str) -> bool:
    index_daily = pro.index_daily(ts_code="000001.SH", trade_date=trade_date)
    stock_daily = pro.daily(ts_code="600519.SH", trade_date=trade_date)
    return index_daily is not None and not index_daily.empty and stock_daily is not None and not stock_daily.empty


def _collect_theme_evidence(pro: Any, basis_date: str) -> dict[str, Any]:
    trade_date = basis_date.replace("-", "")
    start_date = _lookback_start(pro, trade_date, lookback_open_days=7)
    ths_names = _ths_names(pro)
    sw_names = _sw_names(pro)
    limit_industries = _limit_industries(pro, trade_date)

    clusters = []
    data_gaps = []
    for cluster in THEME_CLUSTERS:
        metrics, gaps = _cluster_metrics(pro, cluster, start_date, trade_date)
        data_gaps.extend(gaps)
        score = _strength_score(metrics)
        clusters.append(
            {
                "theme_id": _theme_id(cluster.name),
                "name": cluster.name,
                "sector": _theme_sector(cluster),
                "forming_reason": cluster.reason,
                "strength_score": score,
                "theme_state": _theme_state(score, _continuity(metrics)),
                "signal_type": _signal_types(metrics, score),
                "continuity": _continuity(metrics),
                "risks": _cluster_risks(cluster, metrics),
                "leading_indicators": [
                    *[ths_names.get(code, code) for code in cluster.ths_codes],
                    *[sw_names.get(code, code) for code in cluster.sw_codes],
                ],
                "research_first_queue": True,
                "metrics": metrics,
                "limit_industry_confirmation": _limit_confirmation(limit_industries, cluster),
            }
        )

    clusters.sort(key=lambda item: item["strength_score"], reverse=True)
    if not clusters:
        data_gaps.append("theme_cluster_evidence_empty")
    return {"clusters": clusters[:3], "data_gaps": _dedupe_strings(data_gaps)}


def _cluster_metrics(pro: Any, cluster: ThemeCluster, start_date: str, trade_date: str) -> tuple[dict[str, Any], list[str]]:
    gaps = []
    rows = []
    for code in cluster.ths_codes:
        data = _safe_ths_history(pro, code, start_date, trade_date)
        if not data:
            gaps.append(f"ths_history_missing:{code}")
        rows.extend(data)
    for code in cluster.sw_codes:
        data = _safe_sw_history(pro, code, start_date, trade_date)
        if not data:
            gaps.append(f"sw_history_missing:{code}")
        rows.extend(data)

    latest_rows = [row for row in rows if row["trade_date"] == trade_date]
    current_avg = _average([row["pct_change"] for row in latest_rows])
    turnover_avg = _average([row["turnover_rate"] for row in latest_rows if row["turnover_rate"] is not None])
    positive_ratio = _ratio([row["pct_change"] > 0 for row in rows])
    cum_values = _cumulative_values(rows)
    cumulative_avg = _average(cum_values)
    sample_count = len({row["code"] for row in rows})
    return (
        {
            "current_pct_avg": round(current_avg, 4),
            "lookback_cumulative_pct_avg": round(cumulative_avg, 4),
            "positive_observation_ratio": round(positive_ratio, 4),
            "turnover_rate_avg": round(turnover_avg, 4),
            "evidence_coverage_ratio": round(min(1.0, sample_count / max(1, len(cluster.ths_codes) + len(cluster.sw_codes))), 4),
            "theme_breadth_ratio": round(min(1.0, len(cluster.ths_codes) / 5), 4),
        },
        gaps,
    )


def _safe_ths_history(pro: Any, code: str, start_date: str, trade_date: str) -> list[dict[str, Any]]:
    try:
        data = pro.ths_daily(ts_code=code, start_date=start_date, end_date=trade_date)
    except Exception:  # noqa: BLE001
        return []
    if data is None or data.empty:
        return []
    return [
        {
            "code": code,
            "trade_date": str(row["trade_date"]),
            "pct_change": float(row.get("pct_change", 0) or 0),
            "turnover_rate": float(row.get("turnover_rate", 0) or 0),
            "close": float(row.get("close", 0) or 0),
            "pre_close": float(row.get("pre_close", 0) or 0),
        }
        for _, row in data.iterrows()
    ]


def _safe_sw_history(pro: Any, code: str, start_date: str, trade_date: str) -> list[dict[str, Any]]:
    try:
        data = pro.sw_daily(ts_code=code, start_date=start_date, end_date=trade_date)
    except Exception:  # noqa: BLE001
        return []
    if data is None or data.empty:
        return []
    return [
        {
            "code": code,
            "trade_date": str(row["trade_date"]),
            "pct_change": float(row.get("pct_change", 0) or 0),
            "turnover_rate": None,
            "close": float(row.get("close", 0) or 0),
            "pre_close": None,
        }
        for _, row in data.iterrows()
    ]


def _limit_industries(pro: Any, trade_date: str) -> set[str]:
    try:
        data = pro.limit_list_d(trade_date=trade_date)
    except Exception:  # noqa: BLE001
        return set()
    if data is None or data.empty or "industry" not in data:
        return set()
    if "limit" in data:
        data = data[data["limit"] == "U"]
    return {str(item) for item in data["industry"].dropna().unique()}


def _limit_confirmation(limit_industries: set[str], cluster: ThemeCluster) -> str:
    if not limit_industries:
        return "limit_industry_data_missing"
    mapping = {
        "AI infrastructure hardware chain": {"元件", "通信设备", "光学光电"},
        "advanced electronics manufacturing chain": {"元件", "光学光电", "军工电子", "专用设备"},
        "strategic metal and copper-foil materials": {"小金属", "贵金属", "工业金属"},
    }
    hits = sorted(mapping.get(cluster.name, set()) & limit_industries)
    return "confirmed:" + ",".join(hits) if hits else "not_confirmed_by_limit_industry"


def _ths_names(pro: Any) -> dict[str, str]:
    try:
        data = pro.ths_index()
    except Exception:  # noqa: BLE001
        return {}
    if data is None or data.empty:
        return {}
    return {str(row["ts_code"]): str(row.get("name", row["ts_code"])) for _, row in data.iterrows()}


def _sw_names(pro: Any) -> dict[str, str]:
    try:
        data = pro.index_classify(src="SW2021", level="L1")
    except Exception:  # noqa: BLE001
        return {}
    if data is None or data.empty:
        return {}
    return {str(row["index_code"]): str(row.get("industry_name", row["index_code"])) for _, row in data.iterrows()}


def _lookback_start(pro: Any, trade_date: str, lookback_open_days: int) -> str:
    end = datetime.strptime(trade_date, "%Y%m%d").date()
    start = (end - timedelta(days=30)).strftime("%Y%m%d")
    calendar = pro.trade_cal(exchange="SSE", start_date=start, end_date=trade_date)
    if calendar is None or calendar.empty:
        return (end - timedelta(days=10)).strftime("%Y%m%d")
    open_days = [
        str(row["cal_date"])
        for _, row in calendar.sort_values("cal_date", ascending=False).iterrows()
        if int(row.get("is_open", 0)) == 1
    ]
    selected = list(reversed(open_days[:lookback_open_days]))
    return selected[0] if selected else (end - timedelta(days=10)).strftime("%Y%m%d")


def _next_review_date(pro: Any, basis_date: str) -> str:
    day = date.fromisoformat(basis_date)
    start = (day + timedelta(days=1)).strftime("%Y%m%d")
    end = (day + timedelta(days=15)).strftime("%Y%m%d")
    try:
        calendar = pro.trade_cal(exchange="SSE", start_date=start, end_date=end)
    except Exception:  # noqa: BLE001
        return (day + timedelta(days=1)).isoformat()
    if calendar is None or calendar.empty:
        return (day + timedelta(days=1)).isoformat()
    for _, row in calendar.sort_values("cal_date").iterrows():
        if int(row.get("is_open", 0)) == 1:
            return _format_trade_date(str(row["cal_date"]))
    return (day + timedelta(days=1)).isoformat()


def _snapshot_from_evidence(
    *,
    basis_date: str,
    next_review_date: str,
    data_gaps: list[str],
    clusters: list[dict[str, Any]],
    source_market_snapshot_id: str | None,
) -> dict[str, Any]:
    generated_at = _utc_now()
    primary = clusters[0] if clusters else _fallback_cluster()
    key_facts = []
    reasoning = []
    risks = []
    for index, cluster in enumerate(clusters, start=1):
        key_facts.append(
            f"Mainline {index}: {cluster['name']} theme_state={cluster['theme_state']} auxiliary_strength_score={cluster['strength_score']}."
        )
        key_facts.append(
            "Leading indicators: "
            + "; ".join(cluster["leading_indicators"][:8])
            + ". Theme layer does not output single-security candidates."
        )
        reasoning.append(f"{cluster['name']} formation reason: {cluster['forming_reason']}.")
        reasoning.append(
            f"{cluster['name']} metrics: current_pct_avg={cluster['metrics']['current_pct_avg']}%, "
            f"lookback_cumulative_pct_avg={cluster['metrics']['lookback_cumulative_pct_avg']}%, "
            f"positive_observation_ratio={cluster['metrics']['positive_observation_ratio']}, "
            f"coverage_ratio={cluster['metrics']['evidence_coverage_ratio']}, "
            f"theme_breadth_ratio={cluster['metrics']['theme_breadth_ratio']}."
        )
        risks.extend(cluster["risks"])

    payload = {
        "theme_id": primary["theme_id"],
        "theme_name": primary["name"],
        "sector": primary["sector"],
        "theme_state": primary["theme_state"],
        "signal_type": primary["signal_type"],
        "leading_indicators": primary["leading_indicators"],
        "strength_score": primary["strength_score"],
    }
    final_data_gaps = _dedupe_strings(
        [
            *data_gaps,
            "intraday_and_after_close_realtime_confirmation_not_used",
        ]
    )
    confidence = _confidence(primary["strength_score"], final_data_gaps, len(clusters))
    snapshot = {
        "schema_version": "1.0",
        "snapshot_id": f"theme-research-{basis_date}-mainline-{generated_at.replace(':', '').replace('-', '')[:15]}",
        "basis_date": basis_date,
        "generated_at": generated_at,
        "module": "theme_research",
        "data_sources": [
            "tushare:trade_cal",
            "tushare:index_daily",
            "tushare:daily",
            "tushare:ths_index",
            "tushare:ths_daily",
            "tushare:ths_member",
            "tushare:sw_daily",
            "tushare:limit_list_d",
        ],
        "data_gaps": final_data_gaps,
        "conflicts": [],
        "executive_summary": (
            f"On {basis_date}, the primary research mainline is {primary['name']} "
            f"with theme_state={primary['theme_state']}."
        ),
        "key_facts": key_facts or ["No live theme evidence is available; fallback watchlist is blocked for review."],
        "reasoning": reasoning or ["Fallback research is not actionable because live evidence is unavailable."],
        "risks": _dedupe_strings(risks or ["Live source outage can invalidate this watchlist."]),
        "conclusion_strength": _conclusion_strength(confidence, final_data_gaps),
        "actionability": "research_first",
        "confidence": confidence,
        "invalidation_conditions": [
            "A newer complete trading day changes theme ranking or breadth.",
            "A downstream stock-layer gate blocks any single-security use.",
            "Theme state weakens in the next review.",
        ],
        "next_review_date": next_review_date,
        "must_not_do": [
            "Do not convert this research snapshot into broker execution.",
            "Do not create buy, add, reduce, or sell instructions from this theme snapshot.",
            "Do not derive single-security candidates from this theme snapshot.",
        ],
        "required_human_review": True,
        "status": "json_validated",
        "trace": {
            "fact_pack_id": f"mainline-theme-fact-pack-{basis_date}",
            "source_market_snapshot_id": source_market_snapshot_id,
        },
        "payload": payload,
    }
    return snapshot


def _fallback_snapshot(as_of: date, reason: str) -> dict[str, Any]:
    basis_date = as_of.isoformat()
    return _snapshot_from_evidence(
        basis_date=basis_date,
        next_review_date=(as_of + timedelta(days=1)).isoformat(),
        data_gaps=[
            reason,
            "mock_fallback_used:no live structured market data was available",
            "basis_date_unconfirmed_by_live_calendar",
        ],
        clusters=[_fallback_cluster()],
        source_market_snapshot_id=None,
    )


def _fallback_cluster() -> dict[str, Any]:
    return {
        "theme_id": "offline_mainline_watchlist",
        "name": "offline mainline watchlist",
        "sector": "unconfirmed market theme",
        "forming_reason": "live structured source is unavailable, so no current market mainline is confirmed",
        "strength_score": 50,
        "theme_state": "exhausted",
        "signal_type": ["risk_event"],
        "continuity": "blocked_by_data_gap",
        "risks": ["Current strength is not confirmed by live structured data."],
        "leading_indicators": ["live structured source unavailable"],
        "research_first_queue": True,
        "metrics": {
            "current_pct_avg": 0,
            "lookback_cumulative_pct_avg": 0,
            "positive_observation_ratio": 0,
            "turnover_rate_avg": 0,
            "evidence_coverage_ratio": 0,
            "theme_breadth_ratio": 0,
        },
        "limit_industry_confirmation": "not_available",
    }


def _strength_score(metrics: dict[str, Any]) -> float:
    score = (
        35
        + metrics["current_pct_avg"] * 3
        + metrics["lookback_cumulative_pct_avg"] * 0.7
        + metrics["positive_observation_ratio"] * 15
        + metrics["turnover_rate_avg"] * 1
        + metrics["evidence_coverage_ratio"] * 8
        + metrics["theme_breadth_ratio"] * 8
    )
    if metrics["lookback_cumulative_pct_avg"] > 8:
        score -= 5
    if metrics["theme_breadth_ratio"] < 0.5:
        score -= 3
    return round(max(0, min(100, score)), 2)


def _continuity(metrics: dict[str, Any]) -> str:
    if metrics["lookback_cumulative_pct_avg"] >= 6 and metrics["positive_observation_ratio"] >= 0.55:
        return "strong_continuation"
    if metrics["lookback_cumulative_pct_avg"] >= 2 or metrics["positive_observation_ratio"] >= 0.45:
        return "continuation_watch"
    return "single_day_surge_watch"


def _cluster_risks(cluster: ThemeCluster, metrics: dict[str, Any]) -> list[str]:
    risks = [
        f"{cluster.name}: concrete instruments must be reviewed only by the stock layer gates.",
        f"{cluster.name}: theme signal can reverse if next complete-day breadth weakens.",
    ]
    if metrics["positive_observation_ratio"] < 0.45:
        risks.append(f"{cluster.name}: recent positive observation ratio is not yet broad enough.")
    if metrics["lookback_cumulative_pct_avg"] > 8:
        risks.append(f"{cluster.name}: short-cycle crowding risk is elevated after a fast move.")
    return risks


def _theme_state(score: float, continuity: str) -> str:
    if score < 45:
        return "exhausted"
    if score < 58:
        return "emerging"
    if score >= 82 and continuity == "strong_continuation":
        return "dominant"
    if score >= 58:
        return "strengthening"
    return "weakening"


def _signal_types(metrics: dict[str, Any], score: float) -> list[str]:
    signals = ["momentum", "structural"]
    if metrics.get("turnover_rate_avg", 0) > 0:
        signals.append("liquidity")
    if score >= 82 or metrics.get("lookback_cumulative_pct_avg", 0) > 8:
        signals.append("risk_event")
    return list(dict.fromkeys(signals))


def _theme_id(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "theme"


def _theme_sector(cluster: ThemeCluster) -> str:
    if "AI" in cluster.name:
        return "technology infrastructure"
    if "electronics" in cluster.name:
        return "advanced electronics manufacturing"
    if "metal" in cluster.name:
        return "strategic materials"
    return "market structure"


def _confidence(score: float, data_gaps: list[str], cluster_count: int) -> float:
    base = min(0.86, max(0.45, score / 100))
    if cluster_count >= 3:
        base += 0.03
    base -= min(0.18, len(data_gaps) * 0.025)
    return round(max(0.25, min(0.9, base)), 4)


def _conclusion_strength(confidence: float, data_gaps: list[str]) -> str:
    if confidence >= 0.78 and len(data_gaps) <= 2:
        return "strong"
    if confidence >= 0.55:
        return "medium"
    return "weak"


def _cumulative_values(rows: list[dict[str, Any]]) -> list[float]:
    by_code: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_code.setdefault(row["code"], []).append(row)
    values = []
    for code_rows in by_code.values():
        ordered = sorted(code_rows, key=lambda item: item["trade_date"])
        first = ordered[0]
        last = ordered[-1]
        start = first["pre_close"] or first["close"]
        if start:
            values.append((last["close"] / start - 1) * 100)
    return values


def _average(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0


def _ratio(values: list[bool]) -> float:
    return sum(1 for value in values if value) / len(values) if values else 0


def _dedupe_strings(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _format_trade_date(trade_date: str) -> str:
    return f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]}"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _default_output_path(basis_date: str) -> Path:
    return Path("research/theme_research") / f"theme-research-{basis_date}-mainline.json"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as json_file:
        json.dump(payload, json_file, ensure_ascii=False, indent=2, sort_keys=True)
        json_file.write("\n")


def _tushare_unavailable_reason() -> str | None:
    if not os.environ.get("TUSHARE_TOKEN"):
        return "missing_TUSHARE_TOKEN"
    if importlib.util.find_spec("tushare") is None:
        return "python_package_missing:tushare"
    return None


if __name__ == "__main__":
    main()
