from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from invest_system.validators.policies import (
    assert_decision_policy,
    assert_portfolio_policy,
    assert_research_policy,
)
from invest_system.validators.schema_validator import validate_or_raise


DEFAULT_DB_PATH = Path("data/local/invest_system.sqlite")

SNAPSHOT_TABLES = {
    "market_snapshot": ("snapshot_id", "market"),
    "research_snapshot": ("snapshot_id", "research"),
    "decision_record": ("decision_id", "decision"),
    "portfolio_snapshot": ("portfolio_id", "portfolio"),
}


class SQLiteRepository:
    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH) -> None:
        self.db_path = Path(db_path)

    def init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS market_snapshot (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    snapshot_id TEXT NOT NULL,
                    basis_date TEXT NOT NULL,
                    module TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL CHECK (json_valid(payload_json)),
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS research_snapshot (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    snapshot_id TEXT NOT NULL,
                    basis_date TEXT NOT NULL,
                    module TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL CHECK (json_valid(payload_json)),
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS decision_record (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    decision_id TEXT NOT NULL,
                    basis_date TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL CHECK (json_valid(payload_json)),
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS portfolio_snapshot (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    portfolio_id TEXT NOT NULL,
                    basis_date TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL CHECK (json_valid(payload_json)),
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS event_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL CHECK (event_type IN ('market', 'research', 'decision', 'portfolio')),
                    object_id TEXT NOT NULL,
                    basis_date TEXT NOT NULL,
                    payload_json TEXT NOT NULL CHECK (json_valid(payload_json)),
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_market_snapshot_created_at
                    ON market_snapshot(created_at);
                CREATE INDEX IF NOT EXISTS idx_research_snapshot_created_at
                    ON research_snapshot(created_at);
                CREATE INDEX IF NOT EXISTS idx_decision_record_created_at
                    ON decision_record(created_at);
                CREATE INDEX IF NOT EXISTS idx_portfolio_snapshot_created_at
                    ON portfolio_snapshot(created_at);
                CREATE INDEX IF NOT EXISTS idx_event_log_created_at
                    ON event_log(created_at);
                """
            )
            self._install_append_only_triggers(conn)
            conn.commit()

    def append_market_snapshot(self, payload: dict[str, Any]) -> dict[str, Any]:
        validate_or_raise(payload, "market_snapshot.schema.json")
        assert_research_policy(payload)
        return self._insert_snapshot(
            table="market_snapshot",
            id_column="snapshot_id",
            object_id=payload["snapshot_id"],
            basis_date=payload["basis_date"],
            status=payload["status"],
            payload=payload,
            module=payload["module"],
            event_type="market",
        )

    def append_research_snapshot(self, payload: dict[str, Any]) -> dict[str, Any]:
        validate_or_raise(payload, "research.schema.json")
        assert_research_policy(payload)
        return self._insert_snapshot(
            table="research_snapshot",
            id_column="snapshot_id",
            object_id=payload["snapshot_id"],
            basis_date=payload["basis_date"],
            status=payload["status"],
            payload=payload,
            module=payload["module"],
            event_type="research",
        )

    def append_decision_record(self, payload: dict[str, Any]) -> dict[str, Any]:
        validate_or_raise(payload, "decision.schema.json")
        assert_decision_policy(payload)
        return self._insert_snapshot(
            table="decision_record",
            id_column="decision_id",
            object_id=payload["decision_id"],
            basis_date=payload["basis_date"],
            status=payload["status"],
            payload=payload,
            event_type="decision",
        )

    def append_portfolio_snapshot(self, payload: dict[str, Any]) -> dict[str, Any]:
        validate_or_raise(payload, "portfolio.schema.json")
        assert_portfolio_policy(payload)
        return self._insert_snapshot(
            table="portfolio_snapshot",
            id_column="portfolio_id",
            object_id=payload["portfolio_id"],
            basis_date=payload["basis_date"],
            status=payload["status"],
            payload=payload,
            event_type="portfolio",
        )

    def latest_market(self) -> dict[str, Any] | None:
        return self._latest_payload("market_snapshot")

    def latest_research(self) -> dict[str, Any] | None:
        return self._latest_payload("research_snapshot")

    def latest_decision(self) -> dict[str, Any] | None:
        return self._latest_payload("decision_record")

    def latest_portfolio(self) -> dict[str, Any] | None:
        return self._latest_payload("portfolio_snapshot")

    def timeline(self, as_of: str | None = None) -> list[dict[str, Any]]:
        where = ""
        params: tuple[str, ...] = ()
        if as_of:
            where = "WHERE created_at <= ?"
            params = (as_of,)
        with closing(self._connect()) as conn:
            rows = conn.execute(
                f"""
                SELECT event_type, object_id, basis_date, payload_json, created_at
                FROM event_log
                {where}
                ORDER BY created_at ASC, id ASC
                """,
                params,
            ).fetchall()
        return [
            {
                "timestamp": row["created_at"],
                "type": row["event_type"],
                "object_id": row["object_id"],
                "basis_date": row["basis_date"],
                "payload": json.loads(row["payload_json"]),
            }
            for row in rows
        ]

    def replay_state(self, as_of: str | None = None) -> dict[str, Any]:
        state = {
            "as_of": as_of,
            "market": self._latest_payload("market_snapshot", as_of),
            "research": self._latest_payload("research_snapshot", as_of),
            "decision": self._latest_payload("decision_record", as_of),
            "portfolio": self._latest_payload("portfolio_snapshot", as_of),
        }
        state["trace"] = self._build_trace(state)
        return state

    def table_counts(self) -> dict[str, int]:
        with closing(self._connect()) as conn:
            return {
                table: conn.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()["count"]
                for table in [*SNAPSHOT_TABLES.keys(), "event_log"]
            }

    def all_payload_rows(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        with closing(self._connect()) as conn:
            for table, (id_column, event_type) in SNAPSHOT_TABLES.items():
                for row in conn.execute(
                    f"SELECT {id_column} AS object_id, payload_json, created_at FROM {table} ORDER BY id ASC"
                ):
                    rows.append(
                        {
                            "table": table,
                            "type": event_type,
                            "object_id": row["object_id"],
                            "payload": json.loads(row["payload_json"]),
                            "created_at": row["created_at"],
                        }
                    )
        return rows

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _insert_snapshot(
        self,
        *,
        table: str,
        id_column: str,
        object_id: str,
        basis_date: str,
        status: str,
        payload: dict[str, Any],
        event_type: str,
        module: str | None = None,
    ) -> dict[str, Any]:
        created_at = _utc_now()
        payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        with closing(self._connect()) as conn:
            if module is None:
                conn.execute(
                    f"""
                    INSERT INTO {table} ({id_column}, basis_date, status, payload_json, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (object_id, basis_date, status, payload_json, created_at),
                )
            else:
                conn.execute(
                    f"""
                    INSERT INTO {table} ({id_column}, basis_date, module, status, payload_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (object_id, basis_date, module, status, payload_json, created_at),
                )
            conn.execute(
                """
                INSERT INTO event_log (event_type, object_id, basis_date, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (event_type, object_id, basis_date, payload_json, created_at),
            )
            conn.commit()
        return {"object_id": object_id, "created_at": created_at, "type": event_type}

    def _latest_payload(self, table: str, as_of: str | None = None) -> dict[str, Any] | None:
        where = ""
        params: tuple[str, ...] = ()
        if as_of:
            where = "WHERE created_at <= ?"
            params = (as_of,)
        with closing(self._connect()) as conn:
            row = conn.execute(
                f"""
                SELECT payload_json
                FROM {table}
                {where}
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                """,
                params,
            ).fetchone()
        if row is None:
            return None
        return json.loads(row["payload_json"])

    def _payload_by_object_id(self, table: str, id_column: str, object_id: str) -> dict[str, Any] | None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                f"""
                SELECT payload_json
                FROM {table}
                WHERE {id_column} = ?
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                """,
                (object_id,),
            ).fetchone()
        if row is None:
            return None
        return json.loads(row["payload_json"])

    def _build_trace(self, state: dict[str, Any]) -> dict[str, Any]:
        portfolio = state.get("portfolio")
        decision = state.get("decision")
        trace: dict[str, Any] = {
            "source_market_snapshot_id": None,
            "source_research_snapshot_ids": [],
            "source_decision_id": None,
        }
        if portfolio:
            trace["source_decision_id"] = portfolio.get("source_decision_id")
            if trace["source_decision_id"]:
                decision = self._payload_by_object_id(
                    "decision_record", "decision_id", trace["source_decision_id"]
                )
        if decision:
            decision_trace = decision.get("trace", {})
            trace["source_market_snapshot_id"] = decision_trace.get("source_market_snapshot_id")
            trace["source_research_snapshot_ids"] = decision_trace.get("source_research_snapshot_ids", [])
        return trace

    def _install_append_only_triggers(self, conn: sqlite3.Connection) -> None:
        for table in [*SNAPSHOT_TABLES.keys(), "event_log"]:
            conn.executescript(
                f"""
                CREATE TRIGGER IF NOT EXISTS prevent_{table}_update
                BEFORE UPDATE ON {table}
                BEGIN
                    SELECT RAISE(ABORT, 'append-only table cannot be updated');
                END;

                CREATE TRIGGER IF NOT EXISTS prevent_{table}_delete
                BEFORE DELETE ON {table}
                BEGIN
                    SELECT RAISE(ABORT, 'append-only table cannot be deleted');
                END;
                """
            )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
