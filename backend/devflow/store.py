from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

from devflow.models import AgentState, Event, utc_now


class SQLiteStore:
    """Small durable store for the local MVP.

    Production maps the same repository interface to PostgreSQL and Redis.
    """

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _init_schema(self) -> None:
        with self._lock, self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    request TEXT NOT NULL,
                    state_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_tasks_tenant_updated
                    ON tasks(tenant_id, updated_at DESC);

                CREATE TABLE IF NOT EXISTS events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    node TEXT,
                    message TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(task_id) REFERENCES tasks(task_id)
                );
                CREATE INDEX IF NOT EXISTS idx_events_task_id
                    ON events(task_id, event_id);

                CREATE TABLE IF NOT EXISTS idempotency (
                    idempotency_key TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    step_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    result_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )

    def create_task(self, state: AgentState) -> None:
        now = utc_now()
        state["created_at"] = now
        state["updated_at"] = now
        with self._lock, self._connect() as connection:
            connection.execute(
                """INSERT INTO tasks
                (task_id, tenant_id, user_id, status, request, state_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    state["task_id"],
                    state["tenant_id"],
                    state["user_id"],
                    state["status"],
                    state["request"],
                    json.dumps(state, ensure_ascii=False),
                    now,
                    now,
                ),
            )

    def save_state(self, state: AgentState) -> None:
        state["updated_at"] = utc_now()
        with self._lock, self._connect() as connection:
            connection.execute(
                """UPDATE tasks SET status=?, state_json=?, updated_at=?
                WHERE task_id=? AND tenant_id=?""",
                (
                    state["status"],
                    json.dumps(state, ensure_ascii=False),
                    state["updated_at"],
                    state["task_id"],
                    state["tenant_id"],
                ),
            )

    def get_state(self, task_id: str, tenant_id: str = "demo-tenant") -> AgentState | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT state_json FROM tasks WHERE task_id=? AND tenant_id=?",
                (task_id, tenant_id),
            ).fetchone()
        return json.loads(row["state_json"]) if row else None

    def list_states(self, tenant_id: str = "demo-tenant", limit: int = 50) -> list[AgentState]:
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT state_json FROM tasks WHERE tenant_id=?
                ORDER BY updated_at DESC LIMIT ?""",
                (tenant_id, limit),
            ).fetchall()
        return [json.loads(row["state_json"]) for row in rows]

    def add_event(self, event: Event) -> int:
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """INSERT INTO events
                (task_id, event_type, node, message, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    event.task_id,
                    event.event_type,
                    event.node,
                    event.message,
                    json.dumps(event.payload, ensure_ascii=False),
                    event.created_at,
                ),
            )
            return int(cursor.lastrowid)

    def list_events(self, task_id: str, after_id: int = 0) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT * FROM events WHERE task_id=? AND event_id>?
                ORDER BY event_id ASC""",
                (task_id, after_id),
            ).fetchall()
        return [
            {
                "event_id": row["event_id"],
                "task_id": row["task_id"],
                "event_type": row["event_type"],
                "node": row["node"],
                "message": row["message"],
                "payload": json.loads(row["payload_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def get_idempotent_result(self, key: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT status, result_json FROM idempotency WHERE idempotency_key=?",
                (key,),
            ).fetchone()
        if not row or row["status"] != "succeeded" or not row["result_json"]:
            return None
        return json.loads(row["result_json"])

    def reserve_idempotency(self, key: str, task_id: str, step_id: str) -> bool:
        now = utc_now()
        try:
            with self._lock, self._connect() as connection:
                connection.execute(
                    """INSERT INTO idempotency
                    (idempotency_key, task_id, step_id, status, created_at, updated_at)
                    VALUES (?, ?, ?, 'pending', ?, ?)""",
                    (key, task_id, step_id, now, now),
                )
            return True
        except sqlite3.IntegrityError:
            return False

    def complete_idempotency(self, key: str, result: dict[str, Any]) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """UPDATE idempotency SET status='succeeded', result_json=?, updated_at=?
                WHERE idempotency_key=?""",
                (json.dumps(result, ensure_ascii=False), utc_now(), key),
            )

    def count_idempotency(self, task_id: str, step_id: str | None = None) -> int:
        query = "SELECT COUNT(*) AS count FROM idempotency WHERE task_id=?"
        params: tuple[Any, ...] = (task_id,)
        if step_id is not None:
            query += " AND step_id=?"
            params = (task_id, step_id)
        with self._connect() as connection:
            row = connection.execute(query, params).fetchone()
        return int(row["count"])
