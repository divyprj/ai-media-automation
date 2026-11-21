"""Central Local Web Dashboard FastAPI application with real-time WebSockets and scheduler."""

from contextlib import asynccontextmanager
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import threading
import time
from typing import Any, AsyncGenerator, Dict, Optional
import uuid

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from src.config import Settings, get_settings
from src.contracts.schemas import AuditLogEntry
from src.database.connection import get_db_connection
from src.database.repository import Repository
from src.publishing.circuit_breaker import CircuitBreaker
from src.publishing.queue_manager import QueueManager
from src.scheduler.engine import SchedulerEngine
from src.web.routes.items import router as items_router
from src.web.routes.logs import router as logs_router
from src.web.routes.queue import router as queue_router
from src.web.routes.register import router as register_router
from src.web.routes.status import router as status_router
from src.web.websocket import ConnectionManager

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent / "static"


def utc_now() -> datetime:
    """Return the current UTC timestamp."""
    return datetime.now(timezone.utc)


class EmergencyController:
    """Thread-safe emergency automation shutoff controller backed by SQLite and memory."""

    _halt_event: bool = False
    _lock = threading.RLock()

    def __init__(self, repo: Optional[Repository] = None):
        self.repo = repo
        self._circuit_breaker = CircuitBreaker(repo=repo) if repo else None

    def is_halted(self) -> bool:
        """Check whether emergency halt is active in SQLite state or memory."""
        if self._circuit_breaker:
            return self._circuit_breaker.is_halted()

        if self.repo:
            try:
                with get_db_connection(self.repo.db_path) as conn:
                    cursor = conn.execute(
                        "SELECT details FROM audit_logs WHERE event_type = 'EMERGENCY_HALT' ORDER BY timestamp DESC LIMIT 1;"
                    )
                    row = cursor.fetchone()
                    if row:
                        d = json.loads(row["details"])
                        return bool(d.get("halted", False))
            except Exception:
                pass

        return EmergencyController._halt_event

    def trigger_halt(self, reason: str = "Manual emergency halt triggered") -> None:
        """Immediately trigger emergency shutdown across memory and persistent SQLite."""
        with EmergencyController._lock:
            EmergencyController._halt_event = True
            if self._circuit_breaker:
                self._circuit_breaker.trigger_emergency_stop(reason=reason)
            elif self.repo:
                try:
                    self.repo.record_audit_log(
                        AuditLogEntry(
                            id=f"log_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}",
                            event_type="EMERGENCY_HALT",
                            timestamp=utc_now(),
                            details={"halted": True, "reason": reason},
                        )
                    )
                except Exception:
                    pass

    def resume(self) -> None:
        """Clear emergency halt and restore normal automated operations."""
        with EmergencyController._lock:
            EmergencyController._halt_event = False
            if self._circuit_breaker:
                self._circuit_breaker.resume_operations()
            elif self.repo:
                try:
                    self.repo.record_audit_log(
                        AuditLogEntry(
                            id=f"log_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}",
                            event_type="EMERGENCY_HALT",
                            timestamp=utc_now(),
                            details={"halted": False, "reason": "Operations resumed"},
                        )
                    )
                except Exception:
                    pass

    def can_poll_feeds(self) -> bool:
        """Return True if background feed discovery is allowed to run."""
        return not self.is_halted()

    def can_publish_jobs(self) -> bool:
        """Return True if queue publishing dispatchers are allowed to run."""
        return not self.is_halted()


def create_app(
    settings: Optional[Settings] = None,
    repo: Optional[Repository] = None,
    scheduler: Optional[SchedulerEngine] = None,
) -> FastAPI:
    """Create and configure the production FastAPI dashboard application."""
    app_settings = settings or get_settings()
    app_repo = repo or Repository(app_settings.database_url)
    ec = EmergencyController(app_repo)
    ws_manager = ConnectionManager()
    queue_mgr = QueueManager(app_repo, app_settings)

    if scheduler is None:
        scheduler_engine = SchedulerEngine(
            repo=app_repo,
            settings=app_settings,
            emergency_controller=ec,
            queue_manager=queue_mgr,
            broadcast_callback=ws_manager.broadcast,
        )
    else:
        scheduler_engine = scheduler
        if scheduler_engine.broadcast_callback is None:
            scheduler_engine.broadcast_callback = ws_manager.broadcast

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        # Startup: ensure tables exist and start scheduler
        try:
            app_repo.init_db()
        except Exception as db_err:
            logger.debug("Database initialization during startup: %s", db_err)

        await scheduler_engine.start()
        logger.info("FastAPI Local Dashboard & Background Scheduler started successfully.")
        try:
            yield
        finally:
            # Shutdown: stop scheduler gracefully
            await scheduler_engine.stop()
            logger.info("FastAPI Local Dashboard & Background Scheduler shut down gracefully.")

    app = FastAPI(
        title="Divyansh Prajapati AI Social Intelligence Control Center",
        description="Autonomous AI media and social intelligence dashboard operating with ₹0 budget",
        version="1.0.0",
        lifespan=lifespan,
    )

    # Attach shared resources to app.state
    app.state.settings = app_settings
    app.state.repo = app_repo
    app.state.emergency_controller = ec
    app.state.scheduler = scheduler_engine
    app.state.ws_manager = ws_manager
    app.state.queue_manager = queue_mgr
    app.state.start_time = time.time()
    app.state.system_mode = "AUTONOMOUS"

    # CORS middleware for local browser dashboard
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register API Routers
    app.include_router(status_router)
    app.include_router(items_router)
    app.include_router(queue_router)
    app.include_router(register_router)
    app.include_router(logs_router)

    # Ensure static directory exists
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # Root endpoint serving Single-Page Dashboard
    @app.get("/", response_class=HTMLResponse)
    def read_root() -> Any:
        index_file = STATIC_DIR / "index.html"
        if index_file.exists():
            return FileResponse(str(index_file))
        return HTMLResponse(
            "<!DOCTYPE html><html><head><title>AI Social Intelligence</title></head>"
            "<body><h1>Divyansh Prajapati AI Social Intelligence Control Center</h1>"
            "<p>Dashboard static files initializing...</p></body></html>"
        )

    # Real-time WebSocket Endpoint
    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        await ws_manager.connect(websocket)
        try:
            # Send initial greeting and health status
            await websocket.send_json(
                {
                    "type": "connection_established",
                    "healthy": True,
                    "timestamp": utc_now().isoformat(),
                }
            )
            while True:
                msg = await websocket.receive_text()
                # Acknowledge incoming messages
                await websocket.send_json(
                    {
                        "type": "ack",
                        "received": msg,
                        "timestamp": utc_now().isoformat(),
                    }
                )
        except WebSocketDisconnect:
            await ws_manager.disconnect(websocket)
        except Exception as ws_err:
            logger.debug("WebSocket error: %s", ws_err)
            await ws_manager.disconnect(websocket)

    return app


# Module-level instance for direct ASGI startup
app = create_app()
