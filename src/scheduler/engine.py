"""Background async scheduler engine for periodic news discovery and publishing queue management."""

import asyncio
from datetime import datetime, timezone
import logging
from typing import Any, Awaitable, Callable, Dict, Optional
import uuid

from pydantic import BaseModel, Field

from src.config import Settings, get_settings
from src.contracts.schemas import AuditLogEntry
from src.database.repository import Repository
from src.publishing.queue_manager import QueueManager

logger = logging.getLogger(__name__)


def utc_now() -> datetime:
    """Return the current UTC timestamp."""
    return datetime.now(timezone.utc)


class SchedulerConfig(BaseModel):
    """Configuration options for the background scheduler engine."""

    discovery_interval: float = Field(
        default=60.0, description="Interval in seconds between discovery polling cycles"
    )
    queue_interval: float = Field(
        default=15.0, description="Interval in seconds between queue processing sweeps"
    )
    stuck_job_timeout: int = Field(
        default=300, description="Timeout in seconds before considering a publishing job stuck"
    )


class SchedulerEngine:
    """Asyncio background orchestration engine managing feed ingestion and queue recovery."""

    def __init__(
        self,
        repo: Optional[Repository] = None,
        settings: Optional[Settings] = None,
        emergency_controller: Optional[Any] = None,
        queue_manager: Optional[QueueManager] = None,
        config: Optional[SchedulerConfig] = None,
        broadcast_callback: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None,
    ):
        self.repo = repo
        self.settings = settings or get_settings()
        self.emergency_controller = emergency_controller
        self.queue_manager = queue_manager or (QueueManager(repo, self.settings) if repo else None)
        self.config = config or SchedulerConfig()
        self.broadcast_callback = broadcast_callback

        self.is_running: bool = False
        self.is_paused: bool = False
        self.last_poll_time: Optional[datetime] = None
        self.last_queue_time: Optional[datetime] = None
        self.poll_count: int = 0
        self.queue_cycle_count: int = 0
        self.error_count: int = 0

        self._discovery_task: Optional[asyncio.Task] = None
        self._queue_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()

    # -------------------------------------------------------------------------
    # State & Health Checks
    # -------------------------------------------------------------------------
    def is_halted(self) -> bool:
        """Check whether emergency shutoff is active."""
        if self.emergency_controller and hasattr(self.emergency_controller, "is_halted"):
            return bool(self.emergency_controller.is_halted())
        return False

    def can_poll_feeds(self) -> bool:
        """Return True if background feed discovery is allowed to run."""
        return self.is_running and not self.is_paused and not self.is_halted()

    def can_publish_jobs(self) -> bool:
        """Return True if queue processing and dispatching is allowed to run."""
        return self.is_running and not self.is_paused and not self.is_halted()

    def pause(self) -> None:
        """Pause automated background task execution."""
        self.is_paused = True
        logger.info("Scheduler execution paused.")

    def resume(self) -> None:
        """Resume automated background task execution."""
        self.is_paused = False
        logger.info("Scheduler execution resumed.")

    def trigger_emergency_stop(self, reason: str = "Emergency shutoff activated") -> None:
        """Immediately trigger emergency halt across scheduler and controller."""
        self.is_paused = True
        if self.emergency_controller and hasattr(self.emergency_controller, "trigger_halt"):
            self.emergency_controller.trigger_halt(reason=reason)
        logger.warning("Emergency stop triggered on scheduler: %s", reason)

    # -------------------------------------------------------------------------
    # Lifecycle Management
    # -------------------------------------------------------------------------
    async def start(self) -> None:
        """Start background scheduler tasks within the active event loop."""
        async with self._lock:
            if self.is_running:
                return

            self.is_running = True
            logger.info("Starting background scheduler tasks...")
            self._discovery_task = asyncio.create_task(
                self._discovery_loop(), name="scheduler_discovery_loop"
            )
            self._queue_task = asyncio.create_task(
                self._queue_loop(), name="scheduler_queue_loop"
            )

    async def stop(self) -> None:
        """Gracefully stop and cancel background scheduler tasks."""
        async with self._lock:
            if not self.is_running:
                return

            self.is_running = False
            logger.info("Stopping background scheduler tasks...")

            tasks = [t for t in [self._discovery_task, self._queue_task] if t is not None]
            for task in tasks:
                if not task.done():
                    task.cancel()

            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

            self._discovery_task = None
            self._queue_task = None
            logger.info("Background scheduler successfully stopped.")

    # -------------------------------------------------------------------------
    # Single Cycle Executions
    # -------------------------------------------------------------------------
    async def run_discovery_cycle(self) -> Dict[str, Any]:
        """Execute a single news discovery cycle with safety and broadcast checks."""
        if not self.can_poll_feeds():
            reason = "halted" if self.is_halted() else ("paused" if self.is_paused else "stopped")
            return {"status": "skipped", "reason": reason}

        try:
            self.poll_count += 1
            now = utc_now()
            self.last_poll_time = now

            # Record audit log if repo available
            if self.repo:
                try:
                    self.repo.record_audit_log(
                        AuditLogEntry(
                            id=f"log_{int(now.timestamp() * 1000)}_{uuid.uuid4().hex[:8]}",
                            event_type="DISCOVERY_POLL",
                            timestamp=now,
                            details={"poll_cycle": self.poll_count, "status": "completed"},
                        )
                    )
                except Exception as log_err:
                    logger.debug("Failed recording discovery audit log: %s", log_err)

            # Broadcast WebSocket notification
            if self.broadcast_callback:
                try:
                    await self.broadcast_callback(
                        {
                            "type": "discovery_cycle",
                            "poll_count": self.poll_count,
                            "timestamp": now.isoformat(),
                        }
                    )
                except Exception as ws_err:
                    logger.debug("Broadcast callback error in discovery cycle: %s", ws_err)

            return {
                "status": "completed",
                "poll_count": self.poll_count,
                "timestamp": now.isoformat(),
            }
        except Exception as exc:
            self.error_count += 1
            logger.error("Error in scheduler discovery cycle: %s", exc)
            return {"status": "error", "error": str(exc)}

    async def run_queue_cycle(self) -> Dict[str, Any]:
        """Execute a single queue recovery and sweep cycle."""
        if not self.can_publish_jobs():
            reason = "halted" if self.is_halted() else ("paused" if self.is_paused else "stopped")
            return {"status": "skipped", "reason": reason}

        try:
            self.queue_cycle_count += 1
            now = utc_now()
            self.last_queue_time = now
            recovered = 0

            # Recover stuck jobs if queue_manager is present
            if self.queue_manager and hasattr(self.queue_manager, "recover_stuck_jobs"):
                recovered = self.queue_manager.recover_stuck_jobs(
                    timeout_seconds=self.config.stuck_job_timeout
                )

            # Broadcast WebSocket notification
            if self.broadcast_callback:
                try:
                    await self.broadcast_callback(
                        {
                            "type": "queue_cycle",
                            "cycle_count": self.queue_cycle_count,
                            "recovered_jobs": recovered,
                            "timestamp": now.isoformat(),
                        }
                    )
                except Exception as ws_err:
                    logger.debug("Broadcast callback error in queue cycle: %s", ws_err)

            return {
                "status": "completed",
                "cycle_count": self.queue_cycle_count,
                "recovered_jobs": recovered,
                "timestamp": now.isoformat(),
            }
        except Exception as exc:
            self.error_count += 1
            logger.error("Error in scheduler queue cycle: %s", exc)
            return {"status": "error", "error": str(exc)}

    # -------------------------------------------------------------------------
    # Background Task Loops
    # -------------------------------------------------------------------------
    async def _discovery_loop(self) -> None:
        """Internal discovery loop running periodically until stopped."""
        logger.info("Discovery loop started with interval: %.1fs", self.config.discovery_interval)
        while self.is_running:
            try:
                await self.run_discovery_cycle()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self.error_count += 1
                logger.error("Unexpected discovery loop error: %s", exc)

            try:
                await asyncio.sleep(self.config.discovery_interval)
            except asyncio.CancelledError:
                break

    async def _queue_loop(self) -> None:
        """Internal queue processing loop running periodically until stopped."""
        logger.info("Queue sweep loop started with interval: %.1fs", self.config.queue_interval)
        while self.is_running:
            try:
                await self.run_queue_cycle()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self.error_count += 1
                logger.error("Unexpected queue loop error: %s", exc)

            try:
                await asyncio.sleep(self.config.queue_interval)
            except asyncio.CancelledError:
                break
