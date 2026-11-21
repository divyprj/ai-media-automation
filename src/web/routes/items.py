"""News discovery stream endpoints with source, verification score, and category filters."""

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Query, Request

from src.contracts.schemas import DiscoveredItem
from src.database.connection import get_db_connection

router = APIRouter(prefix="/api", tags=["News Discovery Stream"])


@router.get("/items")
@router.get("/discovery")
def get_discovered_items(
    request: Request,
    limit: int = Query(default=50, ge=1, le=500),
    source_type: Optional[str] = Query(default=None),
    is_verified: Optional[bool] = Query(default=None),
    min_score: Optional[float] = Query(default=None),
) -> List[Dict[str, Any]]:
    """Retrieve discovered AI items matching query criteria."""
    repo = getattr(request.app.state, "repo", None)
    if not repo:
        return []

    query = "SELECT * FROM discovered_items WHERE 1=1"
    params: List[Any] = []

    if source_type:
        query += " AND source_type = ?"
        params.append(source_type.lower())

    if is_verified is not None:
        query += " AND is_verified = ?"
        params.append(1 if is_verified else 0)

    if min_score is not None:
        query += " AND verification_score >= ?"
        params.append(float(min_score))

    query += " ORDER BY discovered_at DESC LIMIT ?;"
    params.append(limit)

    with get_db_connection(repo.db_path) as conn:
        cursor = conn.execute(query, params)
        rows = cursor.fetchall()
        items = []
        for r in rows:
            disc_item = repo._row_to_discovered_item(r)
            items.append(disc_item.model_dump())
        return items


@router.post("/items/trigger-discovery")
async def trigger_discovery_now(request: Request) -> Dict[str, Any]:
    """Manually trigger a background news discovery polling cycle."""
    scheduler = getattr(request.app.state, "scheduler", None)
    if not scheduler:
        return {"status": "error", "message": "Scheduler not configured"}

    result = await scheduler.run_discovery_cycle()
    return result
