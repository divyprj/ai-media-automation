"""Audit logs and real-time system event telemetry routes."""

import json
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Query, Request

from src.database.connection import get_db_connection

router = APIRouter(prefix="/api", tags=["Audit Logs & Events"])


@router.get("/logs")
def get_audit_logs(
    request: Request,
    limit: int = Query(default=50, ge=1, le=500),
    event_type: Optional[str] = Query(default=None),
) -> List[Dict[str, Any]]:
    """Retrieve immutable audit log events and system execution telemetry."""
    repo = getattr(request.app.state, "repo", None)
    if not repo:
        return []

    query = "SELECT * FROM audit_logs WHERE 1=1"
    params: List[Any] = []

    if event_type:
        query += " AND event_type = ?"
        params.append(event_type.upper())

    query += " ORDER BY timestamp DESC LIMIT ?;"
    params.append(limit)

    with get_db_connection(repo.db_path) as conn:
        cursor = conn.execute(query, params)
        rows = cursor.fetchall()
        entries: List[Dict[str, Any]] = []
        for r in rows:
            details_obj = {}
            if r["details"]:
                try:
                    details_obj = json.loads(r["details"])
                except Exception:
                    details_obj = {"raw": r["details"]}

            entries.append(
                {
                    "id": r["id"],
                    "event_type": r["event_type"],
                    "timestamp": r["timestamp"],
                    "details": details_obj,
                }
            )
        return entries
