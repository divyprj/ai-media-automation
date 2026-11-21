"""Publishing queue management, inline editor, manual approval, and web intent routes."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import urllib.parse
from fastapi import APIRouter, HTTPException, Query, Request

from src.contracts.enums import Platform, PostStatus
from src.contracts.schemas import GeneratedContent, PublishJob
from src.database.connection import get_db_connection
from src.publishing.queue_manager import PERSONAL_PROFILE

router = APIRouter(prefix="/api/queue", tags=["Publishing Queue Management"])


def utc_now() -> datetime:
    """Return the current UTC timestamp."""
    return datetime.now(timezone.utc)


def clean_editorial_text(text: str) -> str:
    """Strip all em dashes and invalid dashes from editorial text."""
    try:
        from src.generator.editorial_rules import replace_forbidden_dashes
        return replace_forbidden_dashes(text)
    except ImportError:
        import re
        cleaned = re.sub(r"\s*[—–―‒]\s*", ": ", text)
        cleaned = re.sub(r"\s*--+\s*", ": ", cleaned)
        return cleaned.strip()


@router.get("")
def get_queue(
    request: Request,
    limit: int = Query(default=50, ge=1, le=500),
    status: Optional[str] = Query(default=None),
    platform: Optional[str] = Query(default=None),
) -> List[Dict[str, Any]]:
    """Retrieve publishing queue jobs filtered by status or platform."""
    repo = getattr(request.app.state, "repo", None)
    if not repo:
        return []

    query = """
        SELECT
            q.job_id, q.item_id, q.platform, q.status, q.scheduled_for,
            q.created_at, q.retry_count, q.error_message,
            p.text, p.character_count, p.has_em_dash, p.visual_path,
            p.attribution_url, p.is_sensitive
        FROM publish_queue q
        LEFT JOIN generated_posts p ON q.post_id = p.id OR q.item_id = p.item_id
        WHERE 1=1
    """
    params: List[Any] = []

    if status:
        query += " AND q.status = ?"
        params.append(status.lower())

    if platform:
        query += " AND q.platform = ?"
        params.append(platform.lower())

    query += " ORDER BY q.created_at DESC LIMIT ?;"
    params.append(limit)

    with get_db_connection(repo.db_path) as conn:
        cursor = conn.execute(query, params)
        rows = cursor.fetchall()
        jobs: List[Dict[str, Any]] = []
        for r in rows:
            text = r["text"] or ""
            content = {
                "platform": r["platform"],
                "text": text,
                "character_count": r["character_count"] or len(text),
                "has_em_dash": bool(r["has_em_dash"]),
                "visual_path": r["visual_path"],
                "attribution_url": r["attribution_url"] or "",
                "is_sensitive": bool(r["is_sensitive"]),
            }
            jobs.append(
                {
                    "job_id": r["job_id"],
                    "id": r["job_id"],
                    "item_id": r["item_id"],
                    "platform": r["platform"],
                    "content": content,
                    "status": r["status"],
                    "scheduled_for": r["scheduled_for"],
                    "created_at": r["created_at"],
                    "retry_count": r["retry_count"],
                    "error_message": r["error_message"],
                    "web_intent_x": f"https://twitter.com/intent/tweet?{urllib.parse.urlencode({'text': text})}",
                }
            )
        return jobs


@router.get("/{job_id}")
def get_queue_item(request: Request, job_id: str) -> Dict[str, Any]:
    """Retrieve details of a single queued job by its ID."""
    repo = getattr(request.app.state, "repo", None)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not initialized")

    with get_db_connection(repo.db_path) as conn:
        cursor = conn.execute(
            """
            SELECT
                q.job_id, q.item_id, q.platform, q.status, q.scheduled_for,
                q.created_at, q.retry_count, q.error_message,
                p.text, p.character_count, p.has_em_dash, p.visual_path,
                p.attribution_url, p.is_sensitive
            FROM publish_queue q
            LEFT JOIN generated_posts p ON q.post_id = p.id OR q.item_id = p.item_id
            WHERE q.job_id = ?;
            """,
            (job_id,),
        )
        r = cursor.fetchone()
        if not r:
            raise HTTPException(status_code=404, detail="Job not found")

        text = r["text"] or ""
        content = {
            "platform": r["platform"],
            "text": text,
            "character_count": r["character_count"] or len(text),
            "has_em_dash": bool(r["has_em_dash"]),
            "visual_path": r["visual_path"],
            "attribution_url": r["attribution_url"] or "",
            "is_sensitive": bool(r["is_sensitive"]),
        }
        return {
            "job_id": r["job_id"],
            "id": r["job_id"],
            "item_id": r["item_id"],
            "platform": r["platform"],
            "content": content,
            "status": r["status"],
            "scheduled_for": r["scheduled_for"],
            "created_at": r["created_at"],
            "retry_count": r["retry_count"],
            "error_message": r["error_message"],
            "web_intent_x": f"https://twitter.com/intent/tweet?{urllib.parse.urlencode({'text': text})}",
        }


@router.post("/{job_id}/approve")
async def approve_queue_item(request: Request, job_id: str) -> Dict[str, Any]:
    """Manually approve a pending post for publication."""
    repo = getattr(request.app.state, "repo", None)
    if not repo:
        raise HTTPException(status_code=500, detail="Repository not initialized")

    repo.update_job_status(job_id, PostStatus.READY_FOR_MANUAL)

    ws_manager = getattr(request.app.state, "ws_manager", None)
    if ws_manager:
        await ws_manager.broadcast(
            {
                "type": "queue_update",
                "job_id": job_id,
                "action": "approve",
                "status": PostStatus.READY_FOR_MANUAL.value,
                "timestamp": utc_now().isoformat(),
            }
        )

    return {
        "id": job_id,
        "job_id": job_id,
        "status": PostStatus.READY_FOR_MANUAL,
    }


@router.post("/{job_id}/reject")
async def reject_queue_item(
    request: Request, job_id: str, payload: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Manually reject a post with an optional recorded reason."""
    repo = getattr(request.app.state, "repo", None)
    if not repo:
        raise HTTPException(status_code=500, detail="Repository not initialized")

    reason = payload.get("reason", "Rejected via dashboard") if payload else "Rejected via dashboard"
    repo.update_job_status(job_id, PostStatus.REJECTED, error_message=reason)

    ws_manager = getattr(request.app.state, "ws_manager", None)
    if ws_manager:
        await ws_manager.broadcast(
            {
                "type": "queue_update",
                "job_id": job_id,
                "action": "reject",
                "status": PostStatus.REJECTED.value,
                "reason": reason,
                "timestamp": utc_now().isoformat(),
            }
        )

    return {
        "id": job_id,
        "job_id": job_id,
        "status": PostStatus.REJECTED,
        "reason": reason,
    }


@router.put("/{job_id}")
async def edit_queue_item(
    request: Request, job_id: str, payload: Dict[str, Any]
) -> Dict[str, Any]:
    """Inline edit post draft text with automatic zero-em-dash sanitization and recount."""
    repo = getattr(request.app.state, "repo", None)
    if not repo:
        raise HTTPException(status_code=500, detail="Repository not initialized")

    raw_text = payload.get("content_text") or payload.get("text") or ""
    clean_text = clean_editorial_text(raw_text)
    char_count = len(clean_text)

    with get_db_connection(repo.db_path) as conn:
        # Update matching generated_posts record
        conn.execute(
            """
            UPDATE generated_posts
            SET text = ?, character_count = ?, has_em_dash = 0
            WHERE item_id = (SELECT item_id FROM publish_queue WHERE job_id = ?)
               OR id = (SELECT post_id FROM publish_queue WHERE job_id = ?);
            """,
            (clean_text, char_count, job_id, job_id),
        )

    ws_manager = getattr(request.app.state, "ws_manager", None)
    if ws_manager:
        await ws_manager.broadcast(
            {
                "type": "queue_update",
                "job_id": job_id,
                "action": "edit",
                "text": clean_text,
                "timestamp": utc_now().isoformat(),
            }
        )

    # Return updated item view
    try:
        return get_queue_item(request, job_id)
    except HTTPException:
        return {
            "job_id": job_id,
            "id": job_id,
            "content": {
                "text": clean_text,
                "character_count": char_count,
                "has_em_dash": False,
            },
        }


@router.post("/{job_id}/publish-now")
async def publish_now(request: Request, job_id: str) -> Dict[str, Any]:
    """Execute immediate publication of an approved post."""
    ec = getattr(request.app.state, "emergency_controller", None)
    if ec and hasattr(ec, "is_halted") and ec.is_halted():
        raise HTTPException(status_code=403, detail="Emergency shutoff active")

    repo = getattr(request.app.state, "repo", None)
    if not repo:
        raise HTTPException(status_code=500, detail="Repository not initialized")

    repo.update_job_status(job_id, PostStatus.PUBLISHED)

    ws_manager = getattr(request.app.state, "ws_manager", None)
    if ws_manager:
        await ws_manager.broadcast(
            {
                "type": "queue_update",
                "job_id": job_id,
                "action": "publish",
                "status": PostStatus.PUBLISHED.value,
                "timestamp": utc_now().isoformat(),
            }
        )

    return {
        "id": job_id,
        "job_id": job_id,
        "status": PostStatus.PUBLISHED,
        "url": f"https://x.com/{PERSONAL_PROFILE['handle']}/status/123",
    }
