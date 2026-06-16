from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse

from invest_system.comparison import compute_comparison_history, compute_comparison_state
from invest_system.entry import build_home_state
from invest_system.guidance import compute_guidance_state
from invest_system.macro import compute_macro_history, compute_macro_state, compute_model_consensus
from invest_system.repositories import DEFAULT_DB_PATH, SQLiteRepository
from invest_system.risk import compute_risk_history, compute_risk_state
from invest_system.self_check import system_status
from invest_system.web.dashboard import build_dashboard_state
from invest_system.web.portal import build_portal_state, build_usability_state, render_portal_page


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
                    "/guidance/state",
                    "/usability/state",
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
                    "/app",
                    "/home_human",
                    "/guidance/view",
                    "/dashboard",
                    "/overview",
                    "/market/view",
                    "/risk/view",
                    "/macro/view",
                    "/comparison/view",
                    "/portfolio/view",
                    "/research/view",
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

    @app.get("/app", response_class=HTMLResponse)
    def app_home_page(as_of: str | None = Query(default=None)) -> HTMLResponse:
        return HTMLResponse(render_portal_page(build_portal_state(repo, as_of), "home"))

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

    @app.get("/portfolio/view", response_class=HTMLResponse)
    def portfolio_view_page(as_of: str | None = Query(default=None)) -> HTMLResponse:
        return HTMLResponse(render_portal_page(build_portal_state(repo, as_of), "portfolio"))

    @app.get("/research/view", response_class=HTMLResponse)
    def research_view_page(as_of: str | None = Query(default=None)) -> HTMLResponse:
        return HTMLResponse(render_portal_page(build_portal_state(repo, as_of), "research"))

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
