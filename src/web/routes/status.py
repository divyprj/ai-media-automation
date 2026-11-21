"""System status, automation pause/resume, and emergency circuit breaker routes."""

from datetime import datetime, timezone
import time
from typing import Any, Dict
from fastapi import APIRouter, Request

from src.contracts.enums import PostStatus
from src.publishing.queue_manager import PERSONAL_PROFILE

router = APIRouter(prefix="/api", tags=["Status & Automation Control"])


def utc_now() -> datetime:
    """Return the current UTC timestamp."""
    return datetime.now(timezone.utc)


@router.get("/status")
def get_system_status(request: Request) -> Dict[str, Any]:
    """Retrieve real-time system health, worker states, queue metrics, and automation mode."""
    repo = getattr(request.app.state, "repo", None)
    ec = getattr(request.app.state, "emergency_controller", None)
    scheduler = getattr(request.app.state, "scheduler", None)
    start_time = getattr(request.app.state, "start_time", time.time())
    mode = getattr(request.app.state, "system_mode", "AUTONOMOUS")

    is_halted = ec.is_halted() if ec and hasattr(ec, "is_halted") else False
    is_paused = scheduler.is_paused if scheduler else False

    # Extract queue status breakdown
    counts: Dict[str, int] = {
        PostStatus.QUEUED.value: 0,
        PostStatus.AWAITING_APPROVAL.value: 0,
        PostStatus.READY_FOR_MANUAL.value: 0,
        PostStatus.PUBLISHED.value: 0,
        PostStatus.REJECTED.value: 0,
    }

    last_poll_iso = None
    if repo:
        try:
            status_obj = repo.get_system_status()
            for k, v in status_obj.queue_counts.items():
                counts[k] = v
            if status_obj.last_poll_time:
                last_poll_iso = status_obj.last_poll_time.isoformat()
        except Exception:
            pass

    if scheduler and scheduler.last_poll_time:
        last_poll_iso = scheduler.last_poll_time.isoformat()

    uptime = round(time.time() - start_time, 2)
    active_workers = 1 if (not is_halted and not is_paused) else 0

    return {
        "healthy": True,
        "is_paused": is_paused,
        "paused": is_paused,
        "emergency_shutoff": is_halted,
        "emergency_halt": is_halted,
        "mode": mode,
        "active_workers": active_workers,
        "queue_counts": counts,
        "uptime": uptime,
        "last_poll_time": last_poll_iso,
        "account": PERSONAL_PROFILE,
    }


@router.post("/status/pause")
async def pause_system(request: Request) -> Dict[str, Any]:
    """Pause background feed polling and automatic publishing dispatchers."""
    scheduler = getattr(request.app.state, "scheduler", None)
    if scheduler:
        scheduler.pause()

    now_iso = utc_now().isoformat()
    ws_manager = getattr(request.app.state, "ws_manager", None)
    if ws_manager:
        await ws_manager.broadcast(
            {"type": "status_change", "is_paused": True, "paused": True, "timestamp": now_iso}
        )

    return {
        "is_paused": True,
        "paused": True,
        "status": "paused",
        "timestamp": now_iso,
    }


@router.post("/status/resume")
async def resume_system(request: Request) -> Dict[str, Any]:
    """Resume background feed polling and automatic publishing dispatchers."""
    scheduler = getattr(request.app.state, "scheduler", None)
    if scheduler:
        scheduler.resume()

    now_iso = utc_now().isoformat()
    ws_manager = getattr(request.app.state, "ws_manager", None)
    if ws_manager:
        await ws_manager.broadcast(
            {"type": "status_change", "is_paused": False, "paused": False, "timestamp": now_iso}
        )

    return {
        "is_paused": False,
        "paused": False,
        "status": "resumed",
        "timestamp": now_iso,
    }


@router.post("/status/emergency-shutoff")
@router.post("/system/emergency-stop")
async def emergency_shutoff(request: Request) -> Dict[str, Any]:
    """Immediately trigger emergency circuit breaker, freezing all background loops."""
    ec = getattr(request.app.state, "emergency_controller", None)
    if ec and hasattr(ec, "trigger_halt"):
        ec.trigger_halt(reason="Emergency shutoff triggered via API")

    scheduler = getattr(request.app.state, "scheduler", None)
    if scheduler:
        scheduler.pause()

    now_iso = utc_now().isoformat()
    ws_manager = getattr(request.app.state, "ws_manager", None)
    if ws_manager:
        await ws_manager.broadcast(
            {
                "type": "status_change",
                "emergency_shutoff": True,
                "emergency_halt": True,
                "timestamp": now_iso,
            }
        )

    return {
        "emergency_shutoff": True,
        "emergency_halt": True,
        "timestamp": now_iso,
    }


@router.post("/system/emergency-resume")
async def emergency_resume(request: Request) -> Dict[str, Any]:
    """Resume normal operations after emergency shutoff."""
    ec = getattr(request.app.state, "emergency_controller", None)
    if ec and hasattr(ec, "resume"):
        ec.resume()

    scheduler = getattr(request.app.state, "scheduler", None)
    if scheduler:
        scheduler.resume()

    now_iso = utc_now().isoformat()
    ws_manager = getattr(request.app.state, "ws_manager", None)
    if ws_manager:
        await ws_manager.broadcast(
            {
                "type": "status_change",
                "emergency_shutoff": False,
                "emergency_halt": False,
                "timestamp": now_iso,
            }
        )

    return {
        "emergency_shutoff": False,
        "emergency_halt": False,
        "timestamp": now_iso,
    }


@router.post("/system/toggle-mode")
async def toggle_mode(request: Request, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Toggle system operating mode between AUTONOMOUS and MANUAL."""
    mode = payload.get("mode", "AUTONOMOUS")
    request.app.state.system_mode = mode

    ws_manager = getattr(request.app.state, "ws_manager", None)
    if ws_manager:
        await ws_manager.broadcast(
            {"type": "mode_change", "mode": mode, "timestamp": utc_now().isoformat()}
        )

    return {"current_mode": mode}
