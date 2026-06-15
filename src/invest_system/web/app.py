from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, Query

from invest_system.repositories import DEFAULT_DB_PATH, SQLiteRepository


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
                    "/decision/latest",
                    "/portfolio/state",
                    "/timeline/replay",
                ],
            },
        }

    @app.get("/research/latest")
    def research_latest() -> dict[str, Any]:
        payload = repo.latest_research()
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

    return app


app = create_app()


def _json_result(payload: dict[str, Any] | None) -> dict[str, Any]:
    if payload is None:
        return {"status": "empty", "data": None}
    return {"status": "ok", "data": payload}
