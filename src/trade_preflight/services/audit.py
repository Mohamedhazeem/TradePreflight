"""SQLite-backed audit persistence.

All access goes through Hermes' ``plugin_db("trade-preflight")`` helper, which
opens the profile-scoped ``data.db`` in WAL mode and survives plugin updates.

The audit log is append/update only: ``pre_tool_call`` writes the decision and
``post_tool_call`` upgrades an allowed row to its execution outcome.
"""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

from .. import PLUGIN_NAME

__all__ = [
    "AuditStore",
    "default_audit_store",
    "EXECUTION_ALLOWED",
    "EXECUTION_BLOCKED",
    "EXECUTION_FAILED",
    "EXECUTION_OUTCOME_UNKNOWN",
    "EXECUTION_SUCCEEDED",
]

EXECUTION_BLOCKED = "EXECUTION_BLOCKED"
EXECUTION_ALLOWED = "EXECUTION_ALLOWED"
EXECUTION_SUCCEEDED = "EXECUTION_SUCCEEDED"
EXECUTION_FAILED = "EXECUTION_FAILED"
EXECUTION_OUTCOME_UNKNOWN = "EXECUTION_OUTCOME_UNKNOWN"

_DECISIONS = frozenset(
    {
        EXECUTION_BLOCKED,
        EXECUTION_ALLOWED,
        EXECUTION_SUCCEEDED,
        EXECUTION_FAILED,
        EXECUTION_OUTCOME_UNKNOWN,
    }
)
_SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _default_connection_factory() -> sqlite3.Connection:
    try:
        from plugins.plugin_storage import plugin_db
    except ImportError as exc:  # outside a Hermes runtime
        raise RuntimeError("Hermes plugin storage is unavailable") from exc

    return plugin_db(PLUGIN_NAME)


class AuditStore:
    """Thin repository around ``audit_log`` / schema initialization."""

    def __init__(
        self,
        connection_factory: Callable[[], sqlite3.Connection] | None = None,
    ) -> None:
        self._connection_factory = connection_factory or _default_connection_factory
        self._lock = threading.Lock()
        self._ready = False

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = self._connection_factory()
        try:
            connection.row_factory = sqlite3.Row
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        """Create the schema once per store instance (idempotent SQL)."""
        with self._lock:
            if self._ready:
                return
            schema = _SCHEMA_PATH.read_text(encoding="utf-8")
            with self._connect() as connection:
                connection.executescript(schema)
            self._ready = True

    def record_decision(
        self,
        *,
        tool_call_id: str,
        tool_name: str,
        order_json: str,
        decision: str,
        reason: str,
        policy_hash: str,
    ) -> None:
        """Insert or replace the pre-execution decision for a tool call."""
        if decision not in _DECISIONS:
            raise ValueError(f"invalid audit decision: {decision!r}")
        if not tool_call_id:
            raise ValueError("tool_call_id is required for audit correlation")

        self.initialize()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO audit_log (
                    tool_call_id, timestamp, tool_name, order_json,
                    decision, reason, policy_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(tool_call_id) DO UPDATE SET
                    timestamp   = excluded.timestamp,
                    tool_name   = excluded.tool_name,
                    order_json  = excluded.order_json,
                    decision    = excluded.decision,
                    reason      = excluded.reason,
                    policy_hash = excluded.policy_hash
                """,
                (
                    tool_call_id,
                    _utc_now(),
                    tool_name,
                    order_json,
                    decision,
                    reason,
                    policy_hash,
                ),
            )

    def record_outcome(
        self,
        *,
        tool_call_id: str,
        decision: str,
        reason: str,
    ) -> bool:
        """Upgrade an ``EXECUTION_ALLOWED`` row to its final outcome.

        Returns ``True`` when an allowed row was updated. Blocked or unknown
        rows are never rewritten by the post-execution observer.
        """
        if decision not in (EXECUTION_SUCCEEDED, EXECUTION_FAILED, EXECUTION_OUTCOME_UNKNOWN):
            raise ValueError(f"invalid outcome decision: {decision!r}")
        if not tool_call_id:
            raise ValueError("tool_call_id is required for audit correlation")

        self.initialize()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE audit_log
                   SET decision = ?, reason = ?
                 WHERE tool_call_id = ? AND decision = ?
                """,
                (decision, reason, tool_call_id, EXECUTION_ALLOWED),
            )
            return cursor.rowcount > 0

    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        """Return newest audit rows first."""
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise ValueError("limit must be an integer")
        if not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")

        self.initialize()
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT tool_call_id, timestamp, tool_name, order_json,
                       decision, reason, policy_hash
                  FROM audit_log
                 ORDER BY timestamp DESC, rowid DESC
                 LIMIT ?
                """,
                (limit,),
            ).fetchall()

        return [dict(row) for row in rows]


_DEFAULT_STORE_LOCK = threading.Lock()
_DEFAULT_STORE: AuditStore | None = None


def default_audit_store() -> AuditStore:
    """Process-wide store used by the hooks and the ``trade_audit`` tool."""
    global _DEFAULT_STORE
    with _DEFAULT_STORE_LOCK:
        if _DEFAULT_STORE is None:
            _DEFAULT_STORE = AuditStore()
        return _DEFAULT_STORE
