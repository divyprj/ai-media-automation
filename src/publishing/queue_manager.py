"""Thread-safe, idempotent SQLite WAL publishing queue manager with crash recovery."""

from datetime import datetime, timezone
import hashlib
import json
import sqlite3
import threading
from typing import Any, Dict, List, Optional
import urllib.parse
import uuid

from pydantic import ConfigDict

from src.config import Settings, get_settings
from src.contracts.enums import Platform, PostStatus, SourceType
from src.contracts.schemas import DiscoveredItem, GeneratedContent, PublishJob
from src.database.connection import get_db_connection
from src.database.repository import Repository
from src.publishing.circuit_breaker import CircuitBreaker
from src.publishing.safety_filter import SafetyFilter


PERSONAL_PROFILE = {
    "name": "Divyansh Prajapati",
    "handle": "@divyprjai",
}

ALLOWED_TRANSITIONS = {
    "pending": {"queued", "awaiting_approval", "rejected"},
    "verified": {"queued", "awaiting_approval", "ready_for_manual", "rejected"},
    "queued": {"publishing", "published", "ready_for_manual", "awaiting_approval", "rejected"},
    "awaiting_approval": {"queued", "approved", "ready_for_manual", "rejected"},
    "approved": {"queued", "publishing", "published", "ready_for_manual", "rejected"},
    "ready_for_manual": {"published", "rejected", "queued"},
    "publishing": {"published", "failed", "queued"},
    "failed": {"queued", "rejected"},
    "rejected": {"queued"},
    "published": set(),
}


class ExtendedPublishJob(PublishJob):
    """Extended PublishJob preserving database metadata such as error_message."""

    error_message: Optional[str] = None
    model_config = ConfigDict(populate_by_name=True, extra="allow")


class RetryDecision:
    """Decision indicating whether an operation should be retried."""

    def __init__(self, should_retry: bool, retry_after: float = 0.0, reason: Optional[str] = None):
        self.should_retry = should_retry
        self.retry_after = retry_after
        self.reason = reason


class QueueManager:
    """Thread-safe queue manager backed by SQLite WAL with idempotency and crash recovery."""

    def __init__(
        self,
        repo: Optional[Repository] = None,
        settings: Optional[Settings] = None,
        circuit_breaker: Optional[CircuitBreaker] = None,
    ):
        self.repo = repo
        self.settings = settings or get_settings()
        self._lock = threading.RLock()
        self.circuit_breaker = circuit_breaker or (CircuitBreaker(repo) if repo else None)
        self.safety_filter = SafetyFilter()

    # -------------------------------------------------------------------------
    # Idempotency & Hash Calculations
    # -------------------------------------------------------------------------
    def compute_idempotency_hash(
        self, source_url: str, platform: str, format_type: str, content_text: str
    ) -> str:
        """Compute SHA-256 idempotency hash using formula SHA256(source_url + platform + format + text)."""
        key = f"{source_url}:{platform}:{format_type}:{content_text}"
        return hashlib.sha256(key.encode("utf-8")).hexdigest()

    def compute_payload_hash(
        self, platform: str, text: str, visual_path: Optional[str] = None
    ) -> str:
        """Compute SHA-256 payload hash (platform + text + visual_path)."""
        key = f"{platform}:{text}:{visual_path or ''}"
        return hashlib.sha256(key.encode("utf-8")).hexdigest()

    # -------------------------------------------------------------------------
    # Enqueue Operations
    # -------------------------------------------------------------------------
    def enqueue(self, job: PublishJob) -> bool:
        """Enqueue a PublishJob with strict duplicate prevention across process restarts."""
        if self.repo is None:
            return True

        with self._lock:
            try:
                with get_db_connection(self.repo.db_path) as conn:
                    # 1. Primary Key duplicate check on publish_queue
                    cur = conn.execute("SELECT COUNT(*) FROM publish_queue WHERE job_id = ?;", (job.job_id,))
                    if cur.fetchone()[0] > 0:
                        return False

                # Delegate to repository to insert post & queue entry atomically
                self.repo.enqueue_publish_job(job)
                return True
            except sqlite3.IntegrityError:
                return False
            except Exception:
                return False

    def enqueue_item(
        self,
        content: GeneratedContent,
        scheduled_for: Optional[datetime] = None,
        item_id: Optional[str] = None,
    ) -> PublishJob:
        """Higher-level enqueue interface evaluating safety and generating a PublishJob."""
        # 1. Evaluate safety if not already flagged
        if not content.is_sensitive:
            self.safety_filter.evaluate(content)

        status = PostStatus.AWAITING_APPROVAL if content.is_sensitive else PostStatus.QUEUED

        # 2. Derive deterministic job_id from payload hash
        payload_hash = self.compute_payload_hash(content.platform.value, content.text, content.visual_path)
        job_id = f"job_{payload_hash[:16]}"
        ref_item_id = item_id or f"item_{job_id}"

        job = ExtendedPublishJob(
            job_id=job_id,
            item_id=ref_item_id,
            platform=content.platform,
            content=content,
            status=status,
            scheduled_for=scheduled_for,
            created_at=datetime.now(timezone.utc),
            retry_count=0,
        )

        if self.repo:
            # Ensure discovered_item exists for FK integrity
            existing_item = self.repo.get_discovered_item(ref_item_id)
            if not existing_item:
                disc_item = DiscoveredItem(
                    id=ref_item_id,
                    source_type=SourceType.BLOG,
                    title=content.text[:60],
                    summary=content.text,
                    source_url=content.attribution_url or "https://example.com",
                    content_hash=payload_hash,
                    is_verified=True,
                    verification_score=100.0,
                )
                self.repo.save_discovered_item(disc_item)

            self.enqueue(job)

        return job

    # -------------------------------------------------------------------------
    # State Machine Transitions
    # -------------------------------------------------------------------------
    def transition(self, job_id: str, new_status: PostStatus | str) -> bool:
        """Atomically transition job status verifying allowed transition graph."""
        status_val = new_status.value if hasattr(new_status, "value") else str(new_status).lower()

        if self.repo is None:
            return True

        with self._lock:
            with get_db_connection(self.repo.db_path) as conn:
                cur = conn.execute("SELECT status FROM publish_queue WHERE job_id = ?;", (job_id,))
                row = cur.fetchone()
                if not row:
                    return False

                current_status = row["status"].lower()
                allowed = ALLOWED_TRANSITIONS.get(current_status, set())
                if status_val not in allowed:
                    return False

                # If halted, block transitions to publishing
                if status_val == "publishing" and self.circuit_breaker and self.circuit_breaker.is_halted():
                    return False

                now_iso = datetime.now(timezone.utc).isoformat()
                upd = conn.execute(
                    "UPDATE publish_queue SET status = ?, updated_at = ? WHERE job_id = ?;",
                    (status_val, now_iso, job_id),
                )
                return upd.rowcount > 0

    def update_status(
        self,
        job_id: str,
        new_status: PostStatus | str,
        error_message: Optional[str] = None,
    ) -> Optional[PublishJob]:
        """Update job status and return the refreshed PublishJob."""
        status_val = new_status.value if hasattr(new_status, "value") else str(new_status).lower()

        if self.repo is None:
            return None

        with self._lock:
            with get_db_connection(self.repo.db_path) as conn:
                now_iso = datetime.now(timezone.utc).isoformat()
                conn.execute(
                    "UPDATE publish_queue SET status = ?, error_message = ?, updated_at = ? WHERE job_id = ?;",
                    (status_val, error_message, now_iso, job_id),
                )

            return self.get_job(job_id)

    # -------------------------------------------------------------------------
    # Concurrency Lock & Failure Recording
    # -------------------------------------------------------------------------
    def acquire_publish_lock(self, job_id: str) -> bool:
        """Atomically claim a job for publishing using compare-and-swap SQL."""
        if self.circuit_breaker and self.circuit_breaker.is_halted():
            return False

        if self.repo is None:
            return True

        with self._lock:
            with get_db_connection(self.repo.db_path) as conn:
                cursor = conn.execute(
                    """
                    UPDATE publish_queue
                    SET status = 'publishing', updated_at = datetime('now')
                    WHERE job_id = ?
                      AND status IN ('queued', 'approved', 'ready_for_manual')
                      AND status != 'publishing';
                    """,
                    (job_id,),
                )
                return cursor.rowcount > 0

    def record_failure(self, job_id: str, error_message: str) -> None:
        """Increment retry count and record failure error message."""
        if self.repo:
            with self._lock:
                with get_db_connection(self.repo.db_path) as conn:
                    conn.execute(
                        """
                        UPDATE publish_queue
                        SET retry_count = retry_count + 1,
                            error_message = ?,
                            updated_at = datetime('now')
                        WHERE job_id = ?;
                        """,
                        (error_message, job_id),
                    )

    # -------------------------------------------------------------------------
    # Crash Recovery Mechanism
    # -------------------------------------------------------------------------
    def sweep_stale_jobs(self, stale_minutes: int = 5) -> int:
        """Recover stale jobs stuck in 'publishing' state back to 'queued' with incremented retry count."""
        if self.repo is None:
            return 0

        with self._lock:
            with get_db_connection(self.repo.db_path) as conn:
                cursor = conn.execute(
                    """
                    UPDATE publish_queue
                    SET status = 'queued',
                        retry_count = retry_count + 1,
                        updated_at = datetime('now'),
                        error_message = 'Reset to queued by crash recovery sweep'
                    WHERE status = 'publishing'
                      AND (datetime(updated_at) < datetime('now', ?) OR updated_at < datetime('now', ?));
                    """,
                    (f"-{stale_minutes} minutes", f"-{stale_minutes} minutes"),
                )
                return cursor.rowcount

    def recover_stuck_jobs(self, timeout_seconds: int = 300) -> int:
        """Alias for sweep_stale_jobs using seconds threshold."""
        minutes = max(1, timeout_seconds // 60)
        return self.sweep_stale_jobs(stale_minutes=minutes)

    # -------------------------------------------------------------------------
    # Query & Telemetry
    # -------------------------------------------------------------------------
    def get_job(self, job_id: str) -> Optional[PublishJob]:
        """Fetch a PublishJob by job_id with attached content."""
        if self.repo is None:
            return None

        with get_db_connection(self.repo.db_path) as conn:
            cur = conn.execute(
                """
                SELECT q.job_id, q.item_id, q.platform, q.status, q.scheduled_for,
                       q.created_at, q.retry_count, q.error_message,
                       p.text, p.character_count, p.has_em_dash, p.visual_path,
                       p.attribution_url, p.is_sensitive
                FROM publish_queue q
                LEFT JOIN generated_posts p ON q.post_id = p.id
                WHERE q.job_id = ?;
                """,
                (job_id,),
            )
            row = cur.fetchone()
            if not row:
                return None

            content = GeneratedContent(
                platform=Platform(row["platform"]),
                text=row["text"] or "",
                character_count=row["character_count"] or 0,
                has_em_dash=bool(row["has_em_dash"]),
                visual_path=row["visual_path"],
                attribution_url=row["attribution_url"] or "",
                is_sensitive=bool(row["is_sensitive"]),
            )

            try:
                post_status = PostStatus(row["status"])
            except ValueError:
                post_status = PostStatus.QUEUED

            return ExtendedPublishJob(
                job_id=row["job_id"],
                item_id=row["item_id"],
                platform=Platform(row["platform"]),
                content=content,
                status=post_status,
                scheduled_for=datetime.fromisoformat(row["scheduled_for"]) if row["scheduled_for"] else None,
                created_at=datetime.fromisoformat(row["created_at"]),
                retry_count=row["retry_count"],
                error_message=row["error_message"],
            )

    def get_next_pending_job(self, platform: Optional[Platform] = None) -> Optional[PublishJob]:
        """Fetch the next job ready for execution, adhering to circuit breaker state."""
        if self.circuit_breaker and self.circuit_breaker.is_halted():
            return None

        if self.repo is None:
            return None

        with get_db_connection(self.repo.db_path) as conn:
            query = """
                SELECT q.job_id, q.item_id, q.platform, q.status, q.scheduled_for,
                       q.created_at, q.retry_count, q.error_message,
                       p.text, p.character_count, p.has_em_dash, p.visual_path,
                       p.attribution_url, p.is_sensitive
                FROM publish_queue q
                LEFT JOIN generated_posts p ON q.post_id = p.id
                WHERE q.status IN ('queued', 'approved')
                  AND (q.scheduled_for IS NULL OR q.scheduled_for <= datetime('now'))
            """
            params: List[Any] = []
            if platform:
                query += " AND q.platform = ?"
                params.append(platform.value)

            query += " ORDER BY q.created_at ASC LIMIT 1;"
            cur = conn.execute(query, params)
            row = cur.fetchone()
            if not row:
                return None

            content = GeneratedContent(
                platform=Platform(row["platform"]),
                text=row["text"] or "",
                character_count=row["character_count"] or 0,
                has_em_dash=bool(row["has_em_dash"]),
                visual_path=row["visual_path"],
                attribution_url=row["attribution_url"] or "",
                is_sensitive=bool(row["is_sensitive"]),
            )
            try:
                post_status = PostStatus(row["status"])
            except ValueError:
                post_status = PostStatus.QUEUED

            return ExtendedPublishJob(
                job_id=row["job_id"],
                item_id=row["item_id"],
                platform=Platform(row["platform"]),
                content=content,
                status=post_status,
                scheduled_for=datetime.fromisoformat(row["scheduled_for"]) if row["scheduled_for"] else None,
                created_at=datetime.fromisoformat(row["created_at"]),
                retry_count=row["retry_count"],
                error_message=row["error_message"],
            )

    def get_queue_summary(self) -> Dict[str, int]:
        """Return counts of jobs broken down by lifecycle status."""
        if self.repo is None:
            return {}

        with get_db_connection(self.repo.db_path) as conn:
            cur = conn.execute("SELECT status, COUNT(*) as cnt FROM publish_queue GROUP BY status;")
            return {row["status"]: row["cnt"] for row in cur.fetchall()}

    def get_active_publishing_mode(self) -> str:
        """Return MODE_A if official API credentials exist, else MODE_B (Manual Queue)."""
        if self.settings and getattr(self.settings, "x_api_key", None):
            return "MODE_A"
        return "MODE_B"

    # -------------------------------------------------------------------------
    # Formatting & Utility Helpers
    # -------------------------------------------------------------------------
    def generate_web_intent_url(self, text: str, url: str) -> str:
        """Generate official X tweet web intent URL."""
        params = {"text": text, "url": url}
        return f"https://twitter.com/intent/tweet?{urllib.parse.urlencode(params)}"

    def generate_fallback_content(self, headline: str, summary: str, url: str) -> GeneratedContent:
        """Generate compliant 0-em-dash fallback content under API/LLM outage."""
        clean_headline = headline.replace("—", ": ").replace("--", "-").replace("–", "-").strip()
        clean_summary = summary.replace("—", ": ").replace("--", "-").replace("–", "-").strip()
        text = f"{clean_headline}: {clean_summary} - Analysis by {PERSONAL_PROFILE['handle']}: {url}"
        text = text.replace("—", ": ")[:280]

        return GeneratedContent(
            platform=Platform.X,
            text=text,
            character_count=len(text),
            has_em_dash=False,
            attribution_url=url,
            is_sensitive=False,
        )

    def create_job_from_text(self, job_id: str, text: str, is_sensitive: bool = False) -> PublishJob:
        """Test convenience helper creating a job from raw text."""
        content = GeneratedContent(
            platform=Platform.X,
            text=text,
            character_count=len(text),
            has_em_dash=False,
            attribution_url="https://example.com",
            is_sensitive=is_sensitive,
        )
        status = PostStatus.AWAITING_APPROVAL if is_sensitive else PostStatus.QUEUED
        job = ExtendedPublishJob(
            job_id=job_id,
            item_id=f"item_{job_id}",
            platform=Platform.X,
            content=content,
            status=status,
        )
        if self.repo:
            item = DiscoveredItem(
                id=f"item_{job_id}",
                source_type=SourceType.BLOG,
                title=text[:50],
                summary=text,
                source_url="https://example.com",
                content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            )
            self.repo.save_discovered_item(item)
            self.enqueue(job)
        return job

    def calculate_rate_limit_backoff(self, headers: dict) -> float:
        """Parse x-rate-limit-reset header and compute backoff seconds."""
        reset_val = headers.get("x-rate-limit-reset", "0")
        try:
            target_time = float(reset_val)
            diff = target_time - datetime.now().timestamp()
            return max(0.0, diff)
        except (ValueError, TypeError):
            return 0.0

    def handle_network_exception(self, exc: Exception) -> RetryDecision:
        """Classify network errors as retryable."""
        return RetryDecision(should_retry=True, reason=str(exc))

    def handle_db_exception(self, exc: Exception) -> Dict[str, Any]:
        """Gracefully handle database operational exceptions."""
        return {"handled": True, "error": str(exc)}
