from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, Query
from fastapi.responses import HTMLResponse

from invest_system.adapters import append_market_snapshot_from_adapters
from invest_system.comparison import compute_comparison_history, compute_comparison_state
from invest_system.collectors import import_qmt_positions_from_qmt
from invest_system.decision import build_decision_explain, build_decision_proposal
from invest_system.entry import build_home_state
from invest_system.guidance import compute_guidance_state
from invest_system.macro import compute_macro_history, compute_macro_state, compute_model_consensus
from invest_system.repositories import DEFAULT_DB_PATH, SQLiteRepository
from invest_system.research.importer import append_research_import, validate_research_import
from invest_system.risk import compute_risk_history, compute_risk_state
from invest_system.self_check import system_status
from invest_system.shadow import run_auto_shadow_portfolio
from invest_system.web.dashboard import (
    build_actual_vs_shadow_state,
    build_dashboard_state,
    build_portfolio_history_state,
)
from invest_system.web.portal import (
    build_portal_state,
    build_research_valuation_prompt_state,
    build_research_valuation_review_state,
    build_usability_state,
    render_portal_page,
)
from invest_system.workflow import build_daily_workflow_state


def create_app(db_path: str | Path = DEFAULT_DB_PATH) -> FastAPI:
    repo = SQLiteRepository(db_path)
    repo.init_db()
    app = FastAPI(
        title="MyInvest JSON API",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.get("/")
    def api_index() -> dict[str, Any]:
        return {
            "status": "ok",
            "data": {
                "service": "MyInvest JSON API",
                "json_only": True,
                "primary_human_entry": "/app",
                "endpoints": [
                    "/home",
                    "/entry/home_state",
                    "/workflow/daily/state",
                    "/guidance/state",
                    "/usability/state",
                    "POST /market/refresh",
                    "POST /portfolio/qmt/refresh",
                    "POST /research/import/validate",
                    "POST /research/import",
                    "/research/valuation-review",
                    "/research/valuation-prompts",
                    "/decision/proposal",
                    "/decision/explain",
                    "/research/latest",
                    "/market/latest",
                    "/target-pool/latest",
                    "/decision/latest",
                    "/portfolio/state",
                    "/portfolio/history",
                    "/portfolio/actual-vs-shadow",
                    "/timeline/replay",
                    "/comparison/state",
                    "/comparison/history",
                    "/macro/state",
                    "/macro/history",
                    "/model/consensus",
                    "/risk/state",
                    "/risk/history",
                    "/system/dashboard_state",
                    "/system/status",
                ],
                "view_endpoints": [
                    "/app",
                    "/home_human",
                    "/workflow/daily/view",
                    "/guidance/view",
                    "/dashboard",
                    "/overview",
                    "/market/view",
                    "/risk/view",
                    "/macro/view",
                    "/comparison/view",
                    "/decision/view",
                    "/portfolio/view",
                    "/research/view",
                    "/research/import/view",
                    "/report/view",
                    "/system/view",
                    "/usability/view",
                ],
            },
        }

    @app.get("/home")
    def home_endpoint(as_of: str | None = Query(default=None)) -> dict[str, Any]:
        return {"status": "ok", "data": build_home_state(repo, as_of)}

    @app.get("/entry/home_state")
    def entry_home_state_endpoint(as_of: str | None = Query(default=None)) -> dict[str, Any]:
        return {"status": "ok", "data": build_home_state(repo, as_of)}

    @app.get("/workflow/daily/state")
    def daily_workflow_state_endpoint(as_of: str | None = Query(default=None)) -> dict[str, Any]:
        return {"status": "ok", "data": build_daily_workflow_state(repo, as_of)}

    @app.get("/home_human", response_class=HTMLResponse)
    def home_human_page(as_of: str | None = Query(default=None)) -> HTMLResponse:
        return HTMLResponse(render_portal_page(build_portal_state(repo, as_of), "entry"))

    @app.get("/guidance/state")
    def guidance_state_endpoint(as_of: str | None = Query(default=None)) -> dict[str, Any]:
        return {"status": "ok", "data": compute_guidance_state(repo, as_of)}

    @app.get("/guidance/view", response_class=HTMLResponse)
    def guidance_view_page(as_of: str | None = Query(default=None)) -> HTMLResponse:
        return HTMLResponse(render_portal_page(build_portal_state(repo, as_of), "guidance"))

    @app.get("/usability/state")
    def usability_state_endpoint(as_of: str | None = Query(default=None)) -> dict[str, Any]:
        return build_usability_state(repo, as_of)

    @app.post("/research/import/validate")
    def research_import_validate_endpoint(payload: Any = Body(...)) -> dict[str, Any]:
        validation = validate_research_import(repo, payload)
        status = "ok" if validation["status"] in {"pass", "warn"} else "failed"
        return {"status": status, "data": validation}

    @app.post("/research/import")
    def research_import_endpoint(payload: Any = Body(...)) -> dict[str, Any]:
        result = append_research_import(repo, payload)
        if result["status"] == "ok":
            result["data"]["auto_shadow"] = run_auto_shadow_portfolio(
                repo,
                trigger="research_import",
                as_of=payload.get("basis_date") if isinstance(payload, dict) else None,
            )
        return result

    @app.post("/market/refresh")
    def market_refresh_endpoint(
        basis_date: str | None = Query(default=None),
        source: str = Query(default="auto"),
        allow_network: bool = Query(default=True),
    ) -> dict[str, Any]:
        latest_market = repo.latest_market()
        refresh_date = basis_date or (latest_market["basis_date"] if latest_market else None)
        if refresh_date is None:
            return {
                "status": "failed",
                "data": {
                    "reason": "missing_basis_date",
                    "message": "没有可复用的市场基准日，请指定 basis_date。",
                },
            }
        try:
            result = append_market_snapshot_from_adapters(
                repo,
                basis_date=refresh_date,
                source=source,
                allow_network=allow_network,
            )
        except ValueError as exc:
            return {
                "status": "failed",
                "data": {
                    "reason": "invalid_market_refresh_request",
                    "message": str(exc),
                },
            }
        except Exception:
            return {
                "status": "failed",
                "data": {
                    "reason": "market_refresh_failed",
                    "message": "市场快照刷新失败，请检查本地数据源配置后重试。",
                },
            }
        result["auto_shadow"] = run_auto_shadow_portfolio(
            repo,
            trigger="market_refresh",
            as_of=refresh_date,
            market_returns=_market_returns_from_bundle(result["bundle"]),
            benchmark_returns=_benchmark_returns_from_bundle(result["bundle"]),
        )
        return {"status": "ok", "data": result}

    @app.get("/research/latest")
    def research_latest() -> dict[str, Any]:
        payload = repo.latest_research()
        return _json_result(payload)

    @app.get("/research/valuation-review")
    def research_valuation_review_endpoint(as_of: str | None = Query(default=None)) -> dict[str, Any]:
        return build_research_valuation_review_state(repo, as_of)

    @app.get("/research/valuation-prompts")
    def research_valuation_prompts_endpoint(as_of: str | None = Query(default=None)) -> dict[str, Any]:
        return build_research_valuation_prompt_state(repo, as_of)

    @app.get("/market/latest")
    def market_latest() -> dict[str, Any]:
        payload = repo.latest_market()
        return _json_result(payload)

    @app.get("/target-pool/latest")
    def target_pool_latest() -> dict[str, Any]:
        payload = repo.latest_target_pool()
        return _json_result(payload)

    @app.get("/decision/latest")
    def decision_latest() -> dict[str, Any]:
        payload = repo.latest_decision()
        return _json_result(payload)

    @app.get("/decision/proposal")
    def decision_proposal_endpoint(as_of: str | None = Query(default=None)) -> dict[str, Any]:
        return {"status": "ok", "data": build_decision_proposal(repo, as_of)}

    @app.get("/decision/explain")
    def decision_explain_endpoint(as_of: str | None = Query(default=None)) -> dict[str, Any]:
        return build_decision_explain(repo, as_of)

    @app.get("/portfolio/state")
    def portfolio_state() -> dict[str, Any]:
        payload = repo.latest_portfolio()
        return _json_result(payload)

    @app.get("/portfolio/history")
    def portfolio_history_endpoint(as_of: str | None = Query(default=None)) -> dict[str, Any]:
        return build_portfolio_history_state(repo, as_of)

    @app.get("/portfolio/actual-vs-shadow")
    def portfolio_actual_vs_shadow_endpoint(as_of: str | None = Query(default=None)) -> dict[str, Any]:
        return build_actual_vs_shadow_state(repo, as_of)

    @app.post("/portfolio/qmt/refresh")
    def portfolio_qmt_refresh_endpoint(basis_date: str = Query(...)) -> dict[str, Any]:
        result = import_qmt_positions_from_qmt(repo, basis_date)
        return {"status": "ok" if result["status"] == "ok" else "blocked", "data": result}

    @app.get("/timeline/replay")
    def timeline_replay(as_of: str | None = Query(default=None)) -> dict[str, Any]:
        return {
            "status": "ok",
            "data": {
                "state": repo.replay_state(as_of),
                "events": repo.timeline(as_of),
            },
        }

    @app.get("/risk/state")
    def risk_state_endpoint(as_of: str | None = Query(default=None)) -> dict[str, Any]:
        return {"status": "ok", "data": compute_risk_state(repo, as_of)}

    @app.get("/risk/history")
    def risk_history_endpoint() -> dict[str, Any]:
        return compute_risk_history(repo)

    @app.get("/comparison/state")
    def comparison_state_endpoint(as_of: str | None = Query(default=None)) -> dict[str, Any]:
        return {"status": "ok", "data": compute_comparison_state(repo, as_of)}

    @app.get("/comparison/history")
    def comparison_history_endpoint() -> dict[str, Any]:
        return compute_comparison_history(repo)

    @app.get("/macro/state")
    def macro_state_endpoint(as_of: str | None = Query(default=None)) -> dict[str, Any]:
        return {"status": "ok", "data": compute_macro_state(repo, as_of)}

    @app.get("/macro/history")
    def macro_history_endpoint() -> dict[str, Any]:
        return compute_macro_history(repo)

    @app.get("/model/consensus")
    def model_consensus_endpoint(as_of: str | None = Query(default=None)) -> dict[str, Any]:
        return {"status": "ok", "data": compute_model_consensus(repo, as_of)}

    @app.get("/system/status")
    def system_status_endpoint(as_of: str | None = Query(default=None)) -> dict[str, Any]:
        return system_status(repo.db_path, as_of)

    @app.get("/system/dashboard_state")
    def dashboard_state_endpoint(as_of: str | None = Query(default=None)) -> dict[str, Any]:
        return build_dashboard_state(repo, as_of)

    @app.get("/app", response_class=HTMLResponse)
    def app_home_page(as_of: str | None = Query(default=None)) -> HTMLResponse:
        return HTMLResponse(render_portal_page(build_portal_state(repo, as_of), "home"))

    @app.get("/workflow/daily/view", response_class=HTMLResponse)
    def daily_workflow_view_page(as_of: str | None = Query(default=None)) -> HTMLResponse:
        return HTMLResponse(render_portal_page(build_portal_state(repo, as_of), "daily"))

    @app.get("/dashboard", response_class=HTMLResponse)
    def dashboard_page(as_of: str | None = Query(default=None)) -> HTMLResponse:
        return HTMLResponse(render_portal_page(build_portal_state(repo, as_of), "dashboard"))

    @app.get("/overview", response_class=HTMLResponse)
    def overview_page(as_of: str | None = Query(default=None)) -> HTMLResponse:
        return HTMLResponse(render_portal_page(build_portal_state(repo, as_of), "overview"))

    @app.get("/market/view", response_class=HTMLResponse)
    def market_view_page(as_of: str | None = Query(default=None)) -> HTMLResponse:
        return HTMLResponse(render_portal_page(build_portal_state(repo, as_of), "market"))

    @app.get("/risk/view", response_class=HTMLResponse)
    def risk_view_page(as_of: str | None = Query(default=None)) -> HTMLResponse:
        return HTMLResponse(render_portal_page(build_portal_state(repo, as_of), "risk"))

    @app.get("/macro/view", response_class=HTMLResponse)
    def macro_view_page(as_of: str | None = Query(default=None)) -> HTMLResponse:
        return HTMLResponse(render_portal_page(build_portal_state(repo, as_of), "macro"))

    @app.get("/comparison/view", response_class=HTMLResponse)
    def comparison_view_page(as_of: str | None = Query(default=None)) -> HTMLResponse:
        return HTMLResponse(render_portal_page(build_portal_state(repo, as_of), "comparison"))

    @app.get("/decision/view", response_class=HTMLResponse)
    def decision_view_page(as_of: str | None = Query(default=None)) -> HTMLResponse:
        return HTMLResponse(render_portal_page(build_portal_state(repo, as_of), "decision"))

    @app.get("/portfolio/view", response_class=HTMLResponse)
    def portfolio_view_page(as_of: str | None = Query(default=None)) -> HTMLResponse:
        return HTMLResponse(render_portal_page(build_portal_state(repo, as_of), "portfolio"))

    @app.get("/research/view", response_class=HTMLResponse)
    def research_view_page(as_of: str | None = Query(default=None)) -> HTMLResponse:
        return HTMLResponse(render_portal_page(build_portal_state(repo, as_of), "research"))

    @app.get("/research/import/view", response_class=HTMLResponse)
    def research_import_view_page(as_of: str | None = Query(default=None)) -> HTMLResponse:
        return HTMLResponse(render_portal_page(build_portal_state(repo, as_of), "research_import"))

    @app.get("/report/view", response_class=HTMLResponse)
    def report_view_page(as_of: str | None = Query(default=None)) -> HTMLResponse:
        return HTMLResponse(render_portal_page(build_portal_state(repo, as_of), "report"))

    @app.get("/system/view", response_class=HTMLResponse)
    def system_view_page(as_of: str | None = Query(default=None)) -> HTMLResponse:
        return HTMLResponse(render_portal_page(build_portal_state(repo, as_of), "system"))

    @app.get("/usability/view", response_class=HTMLResponse)
    def usability_view_page(as_of: str | None = Query(default=None)) -> HTMLResponse:
        return HTMLResponse(render_portal_page(build_portal_state(repo, as_of), "usability"))

    return app


app = create_app()


def _json_result(payload: dict[str, Any] | None) -> dict[str, Any]:
    if payload is None:
        return {"status": "empty", "data": None}
    return {"status": "ok", "data": payload}


def _market_returns_from_bundle(bundle: dict[str, Any]) -> dict[str, float]:
    returns: dict[str, float] = {}
    for item in bundle.get("symbols", []):
        symbol = item.get("symbol")
        if symbol:
            returns[symbol] = float(item.get("daily_return", 0))
    return returns


def _benchmark_returns_from_bundle(bundle: dict[str, Any]) -> dict[str, float]:
    returns: dict[str, float] = {}
    for item in bundle.get("indices", []):
        name = item.get("name") or item.get("symbol")
        if name:
            returns[str(name)] = float(item.get("daily_return", 0))
    return returns
