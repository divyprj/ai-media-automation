"""Global emergency software circuit breaker backed by SQLite system_state and audit logs."""

from datetime import datetime, timezone
import json
import sqlite3
import threading
from typing import Any, Dict, Optional
import uuid

from src.contracts.schemas import AuditLogEntry
from src.database.connection import get_db_connection
from src.database.repository import Repository


class CircuitBreaker:
    """Persistent emergency shutoff controller halting background polling and publishing."""

    _memory_halt: bool = False
    _lock = threading.RLock()

    def __init__(self, repo: Optional[Repository] = None, db_path: Optional[str] = None):
        self.repo = repo
        self.db_path = repo.db_path if repo else db_path

    def _ensure_schema(self, conn: sqlite3.Connection) -> None:
        """Ensure system_state table exists."""
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS system_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )

    def is_halted(self) -> bool:
        """Check whether emergency stop is currently active."""
        if not self.db_path:
            return CircuitBreaker._memory_halt

        try:
            with get_db_connection(self.db_path) as conn:
                self._ensure_schema(conn)
                cur = conn.execute(
                    "SELECT value FROM system_state WHERE key = 'emergency_halt';"
                )
                row = cur.fetchone()
                if row:
                    data = json.loads(row["value"])
                    return bool(data.get("halted", False))

                # Fallback to audit_logs check for test/conftest compatibility
                cur2 = conn.execute(
                    "SELECT details FROM audit_logs WHERE event_type = 'EMERGENCY_HALT' ORDER BY timestamp DESC LIMIT 1;"
                )
                row2 = cur2.fetchone()
                if row2:
                    d = json.loads(row2["details"])
                    return bool(d.get("halted", False))
        except Exception:
            pass

        return CircuitBreaker._memory_halt

    def can_poll_feeds(self) -> bool:
        """Return True if background feed discovery is allowed to run."""
        return not self.is_halted()

    def can_publish_jobs(self) -> bool:
        """Return True if queue publishing dispatchers are allowed to run."""
        return not self.is_halted()

    def trigger_emergency_stop(self, reason: str = "Manual emergency halt triggered") -> None:
        """Immediately trigger emergency shutdown across memory and persistent SQLite."""
        with CircuitBreaker._lock:
            CircuitBreaker._memory_halt = True

            now_iso = datetime.now(timezone.utc).isoformat()
            if self.db_path:
                try:
                    with get_db_connection(self.db_path) as conn:
                        self._ensure_schema(conn)
                        payload = json.dumps({"halted": True, "reason": reason, "updated_at": now_iso})
                        conn.execute(
                            """
                            INSERT INTO system_state (key, value, updated_at)
                            VALUES ('emergency_halt', ?, ?)
                            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at;
                            """,
                            (payload, now_iso),
                        )
                except Exception:
                    pass

            if self.repo:
                try:
                    self.repo.record_audit_log(
                        AuditLogEntry(
                            id=f"log_{int(datetime.now(timezone.utc).timestamp()*1000)}_{uuid.uuid4().hex[:8]}",
                            event_type="EMERGENCY_HALT",
                            details={"halted": True, "reason": reason},
                        )
                    )
                except Exception:
                    pass
            elif self.db_path:
                # Direct audit log write if repo object not provided
                try:
                    with get_db_connection(self.db_path) as conn:
                        conn.execute(
                            """
                            INSERT INTO audit_logs (id, event_type, timestamp, details)
                            VALUES (?, 'EMERGENCY_HALT', ?, ?);
                            """,
                            (
                                f"log_{int(datetime.now(timezone.utc).timestamp()*1000)}_{uuid.uuid4().hex[:8]}",
                                now_iso,
                                json.dumps({"halted": True, "reason": reason}),
                            ),
                        )
                except Exception:
                    pass

    def trigger_halt(self, reason: str = "Manual emergency halt triggered") -> None:
        """Alias for trigger_emergency_stop for backward and test compatibility."""
        self.trigger_emergency_stop(reason=reason)

    def resume_operations(self) -> None:
        """Clear emergency halt and restore normal automated operations."""
        with CircuitBreaker._lock:
            CircuitBreaker._memory_halt = False

            now_iso = datetime.now(timezone.utc).isoformat()
            if self.db_path:
                try:
                    with get_db_connection(self.db_path) as conn:
                        self._ensure_schema(conn)
                        payload = json.dumps({"halted": False, "reason": "Operations resumed", "updated_at": now_iso})
                        conn.execute(
                            """
                            INSERT INTO system_state (key, value, updated_at)
                            VALUES ('emergency_halt', ?, ?)
                            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at;
                            """,
                            (payload, now_iso),
                        )
                except Exception:
                    pass

            if self.repo:
                try:
                    self.repo.record_audit_log(
                        AuditLogEntry(
                            id=f"log_{int(datetime.now(timezone.utc).timestamp()*1000)}_{uuid.uuid4().hex[:8]}",
                            event_type="EMERGENCY_HALT",
                            details={"halted": False, "reason": "Operations resumed"},
                        )
                    )
                except Exception:
                    pass
            elif self.db_path:
                try:
                    with get_db_connection(self.db_path) as conn:
                        conn.execute(
                            """
                            INSERT INTO audit_logs (id, event_type, timestamp, details)
                            VALUES (?, 'EMERGENCY_HALT', ?, ?);
                            """,
                            (
                                f"log_{int(datetime.now(timezone.utc).timestamp()*1000)}_{uuid.uuid4().hex[:8]}",
                                now_iso,
                                json.dumps({"halted": False, "reason": "Operations resumed"}),
                            ),
                        )
                except Exception:
                    pass

    def resume(self) -> None:
        """Alias for resume_operations for backward and test compatibility."""
        self.resume_operations()

    def get_halt_info(self) -> Dict[str, Any]:
        """Return structured halt information."""
        if self.db_path:
            try:
                with get_db_connection(self.db_path) as conn:
                    self._ensure_schema(conn)
                    cur = conn.execute("SELECT value, updated_at FROM system_state WHERE key = 'emergency_halt';")
                    row = cur.fetchone()
                    if row:
                        val = json.loads(row["value"])
                        return {
                            "halted": bool(val.get("halted", False)),
                            "reason": val.get("reason", ""),
                            "updated_at": row["updated_at"],
                        }
            except Exception:
                pass

        return {
            "halted": CircuitBreaker._memory_halt,
            "reason": "In-memory state" if CircuitBreaker._memory_halt else "Active",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }


EmergencyController = CircuitBreaker
