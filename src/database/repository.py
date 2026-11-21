"""Thread-safe SQLite repository for discovery, content, publishing, and audit telemetry."""

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.config import get_settings
from src.contracts.enums import Platform, PostStatus, SourceType
from src.contracts.schemas import (
    AuditLogEntry,
    DiscoveredItem,
    GeneratedContent,
    PublishJob,
    SystemStatus,
)
from src.database.connection import create_connection, get_db_connection
from src.database.models import init_db


class Repository:
    """Thread-safe repository managing all persistent SQLite data operations."""

    def __init__(self, db_path: Optional[str] = None):
        """Initialize repository with target database path.

        If db_path is ':memory:', configures a shared in-memory database to allow
        cross-connection thread-safe testing without data loss.
        """
        self._lock = threading.RLock()
        self._anchor_conn: Optional[sqlite3.Connection] = None

        if db_path is None:
            self.db_path = get_settings().database_url
        elif db_path == ":memory:":
            # Use unique shared in-memory database URI with anchor connection
            self.db_path = f"file:mem_{uuid.uuid4().hex}?mode=memory&cache=shared"
            self._anchor_conn = create_connection(self.db_path)
        else:
            self.db_path = db_path

    def close(self) -> None:
        """Close anchor connection if shared in-memory database is active."""
        with self._lock:
            if self._anchor_conn is not None:
                self._anchor_conn.close()
                self._anchor_conn = None

    def init_db(self) -> None:
        """Initialize schema tables and indexes."""
        with self._lock:
            with get_db_connection(self.db_path) as conn:
                init_db(conn)

    def save_discovered_item(self, item: DiscoveredItem) -> bool:
        """Persist a discovered item.

        Returns:
            True if inserted successfully, False if content_hash or id already exists.
        """
        with self._lock:
            try:
                with get_db_connection(self.db_path) as conn:
                    conn.execute(
                        """
                        INSERT INTO discovered_items (
                            id, source_type, title, summary, source_url,
                            content_hash, raw_metadata, discovered_at,
                            is_verified, verification_score, verification_notes
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                        """,
                        (
                            item.id,
                            item.source_type.value,
                            item.title,
                            item.summary,
                            item.source_url,
                            item.content_hash,
                            json.dumps(item.raw_metadata),
                            item.discovered_at.isoformat(),
                            1 if item.is_verified else 0,
                            item.verification_score,
                            item.verification_notes,
                        ),
                    )
                return True
            except sqlite3.IntegrityError:
                return False

    def get_discovered_item(self, item_id: str) -> Optional[DiscoveredItem]:
        """Retrieve a discovered item by its id."""
        with get_db_connection(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT * FROM discovered_items WHERE id = ?;",
                (item_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None

            return self._row_to_discovered_item(row)

    def get_unprocessed_items(self, limit: int = 50) -> List[DiscoveredItem]:
        """Retrieve discovered items that have not yet been queued for publishing."""
        with get_db_connection(self.db_path) as conn:
            cursor = conn.execute(
                """
                SELECT * FROM discovered_items
                WHERE id NOT IN (SELECT item_id FROM publish_queue)
                ORDER BY discovered_at DESC
                LIMIT ?;
                """,
                (limit,),
            )
            rows = cursor.fetchall()
            return [self._row_to_discovered_item(r) for r in rows]

    def enqueue_publish_job(self, job: PublishJob) -> str:
        """Enqueue a new publish job and record the generated post content.

        Args:
            job: PublishJob containing content and metadata.

        Returns:
            The job_id of the enqueued job.

        Raises:
            sqlite3.IntegrityError: If foreign key validation fails (e.g. invalid item_id).
        """
        with self._lock:
            with get_db_connection(self.db_path) as conn:
                post_id = str(uuid.uuid4())
                created_iso = job.created_at.isoformat()

                # Insert generated post record
                conn.execute(
                    """
                    INSERT INTO generated_posts (
                        id, item_id, platform, text, character_count,
                        has_em_dash, visual_path, attribution_url, is_sensitive, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        post_id,
                        job.item_id,
                        job.platform.value,
                        job.content.text,
                        job.content.character_count,
                        1 if job.content.has_em_dash else 0,
                        job.content.visual_path,
                        job.content.attribution_url,
                        1 if job.content.is_sensitive else 0,
                        created_iso,
                    ),
                )

                # Insert into publish queue
                sched_iso = job.scheduled_for.isoformat() if job.scheduled_for else None
                conn.execute(
                    """
                    INSERT INTO publish_queue (
                        job_id, item_id, platform, status, scheduled_for,
                        created_at, updated_at, retry_count, error_message
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        job.job_id,
                        job.item_id,
                        job.platform.value,
                        job.status.value,
                        sched_iso,
                        created_iso,
                        created_iso,
                        job.retry_count,
                        None,
                    ),
                )

            return job.job_id

    def update_job_status(
        self,
        job_id: str,
        new_status: PostStatus,
        error_message: Optional[str] = None,
    ) -> bool:
        """Update lifecycle status and error details of a queued publish job."""
        with self._lock:
            with get_db_connection(self.db_path) as conn:
                now_iso = datetime.now(timezone.utc).isoformat()
                cursor = conn.execute(
                    """
                    UPDATE publish_queue
                    SET status = ?, error_message = ?, updated_at = ?
                    WHERE job_id = ?;
                    """,
                    (new_status.value, error_message, now_iso, job_id),
                )
                return cursor.rowcount > 0

    def get_pending_jobs(self, limit: int = 50) -> List[PublishJob]:
        """Retrieve pending publication jobs with full generated content payload."""
        with get_db_connection(self.db_path) as conn:
            cursor = conn.execute(
                """
                SELECT
                    q.job_id, q.item_id, q.platform, q.status, q.scheduled_for,
                    q.created_at, q.retry_count, q.error_message,
                    p.text, p.character_count, p.has_em_dash, p.visual_path,
                    p.attribution_url, p.is_sensitive
                FROM publish_queue q
                LEFT JOIN generated_posts p
                    ON q.item_id = p.item_id AND q.platform = p.platform
                WHERE q.status IN ('queued', 'verified', 'awaiting_approval', 'ready_for_manual')
                ORDER BY q.created_at ASC
                LIMIT ?;
                """,
                (limit,),
            )
            rows = cursor.fetchall()
            jobs: List[PublishJob] = []
            for r in rows:
                content = GeneratedContent(
                    platform=Platform(r["platform"]),
                    text=r["text"] or "",
                    character_count=r["character_count"] or 0,
                    has_em_dash=bool(r["has_em_dash"]),
                    visual_path=r["visual_path"],
                    attribution_url=r["attribution_url"] or "",
                    is_sensitive=bool(r["is_sensitive"]),
                )
                sched = (
                    datetime.fromisoformat(r["scheduled_for"])
                    if r["scheduled_for"]
                    else None
                )
                created = datetime.fromisoformat(r["created_at"])
                jobs.append(
                    PublishJob(
                        job_id=r["job_id"],
                        item_id=r["item_id"],
                        platform=Platform(r["platform"]),
                        content=content,
                        status=PostStatus(r["status"]),
                        scheduled_for=sched,
                        created_at=created,
                        retry_count=r["retry_count"],
                    )
                )
            return jobs

    def record_audit_log(self, entry: AuditLogEntry) -> None:
        """Record an immutable audit log event."""
        with self._lock:
            with get_db_connection(self.db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO audit_logs (id, event_type, timestamp, details)
                    VALUES (?, ?, ?, ?);
                    """,
                    (
                        entry.id,
                        entry.event_type,
                        entry.timestamp.isoformat(),
                        json.dumps(entry.details),
                    ),
                )

    def get_system_status(self) -> SystemStatus:
        """Compute real-time system status and queue counts from database state."""
        with get_db_connection(self.db_path) as conn:
            # Query queue status breakdown
            cursor = conn.execute(
                "SELECT status, COUNT(*) as cnt FROM publish_queue GROUP BY status;"
            )
            counts: Dict[str, int] = {row["status"]: row["cnt"] for row in cursor.fetchall()}

            # Check most recent discovery poll timestamp
            cursor = conn.execute(
                "SELECT discovered_at FROM discovered_items ORDER BY discovered_at DESC LIMIT 1;"
            )
            last_item = cursor.fetchone()
            last_poll = (
                datetime.fromisoformat(last_item["discovered_at"])
                if last_item
                else None
            )

            settings = get_settings()
            return SystemStatus(
                is_paused=False,
                emergency_shutoff=settings.enable_emergency_shutoff,
                active_workers=1,
                last_poll_time=last_poll,
                queue_counts=counts,
            )

    @staticmethod
    def _row_to_discovered_item(row: sqlite3.Row) -> DiscoveredItem:
        """Convert a database row to a DiscoveredItem domain model."""
        raw_meta = json.loads(row["raw_metadata"]) if row["raw_metadata"] else {}
        return DiscoveredItem(
            id=row["id"],
            source_type=SourceType(row["source_type"]),
            title=row["title"],
            summary=row["summary"],
            source_url=row["source_url"],
            raw_metadata=raw_meta,
            discovered_at=datetime.fromisoformat(row["discovered_at"]),
            content_hash=row["content_hash"],
            is_verified=bool(row["is_verified"]),
            verification_score=float(row["verification_score"]),
            verification_notes=row["verification_notes"],
        )
