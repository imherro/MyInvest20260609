from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse

from invest_system.comparison import compute_comparison_history, compute_comparison_state
from invest_system.macro import compute_macro_history, compute_macro_state, compute_model_consensus
from invest_system.repositories import DEFAULT_DB_PATH, SQLiteRepository
from invest_system.risk import compute_risk_history, compute_risk_state
from invest_system.self_check import system_status
from invest_system.web.dashboard import build_dashboard_state, render_dashboard_page


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
                "endpoints": [
                    "/research/latest",
                    "/market/latest",
                    "/target-pool/latest",
                    "/decision/latest",
                    "/portfolio/state",
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
                    "/dashboard",
                    "/overview",
                    "/portfolio/view",
                    "/research/view",
                    "/report/view",
                ],
            },
        }

    @app.get("/research/latest")
    def research_latest() -> dict[str, Any]:
        payload = repo.latest_research()
        return _json_result(payload)

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

    @app.get("/portfolio/state")
    def portfolio_state() -> dict[str, Any]:
        payload = repo.latest_portfolio()
        return _json_result(payload)

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

    @app.get("/dashboard", response_class=HTMLResponse)
    def dashboard_page(as_of: str | None = Query(default=None)) -> HTMLResponse:
        return HTMLResponse(render_dashboard_page(build_dashboard_state(repo, as_of), "dashboard"))

    @app.get("/overview", response_class=HTMLResponse)
    def overview_page(as_of: str | None = Query(default=None)) -> HTMLResponse:
        return HTMLResponse(render_dashboard_page(build_dashboard_state(repo, as_of), "overview"))

    @app.get("/portfolio/view", response_class=HTMLResponse)
    def portfolio_view_page(as_of: str | None = Query(default=None)) -> HTMLResponse:
        return HTMLResponse(render_dashboard_page(build_dashboard_state(repo, as_of), "portfolio"))

    @app.get("/research/view", response_class=HTMLResponse)
    def research_view_page(as_of: str | None = Query(default=None)) -> HTMLResponse:
        return HTMLResponse(render_dashboard_page(build_dashboard_state(repo, as_of), "research"))

    @app.get("/report/view", response_class=HTMLResponse)
    def report_view_page(as_of: str | None = Query(default=None)) -> HTMLResponse:
        return HTMLResponse(render_dashboard_page(build_dashboard_state(repo, as_of), "report"))

    return app


app = create_app()


def _json_result(payload: dict[str, Any] | None) -> dict[str, Any]:
    if payload is None:
        return {"status": "empty", "data": None}
    return {"status": "ok", "data": payload}
