"""Core domain schemas and contract data models."""

from datetime import datetime, timezone
from typing import Any, Dict, Optional
from pydantic import BaseModel, ConfigDict, Field

from src.contracts.enums import Platform, PostStatus, SourceType


def utc_now() -> datetime:
    """Return the current UTC timestamp."""
    return datetime.now(timezone.utc)


class DiscoveredItem(BaseModel):
    """An AI breakthrough, research paper, or tool discovered from monitored feeds."""

    id: str = Field(description="Unique identifier for the item (e.g. SHA-256 or UUID)")
    source_type: SourceType = Field(description="Category of the source feed")
    title: str = Field(description="Title or headline of the discovery")
    summary: str = Field(description="Cleaned text summary or abstract")
    source_url: str = Field(description="Canonical original URL of the source")
    raw_metadata: Dict[str, Any] = Field(
        default_factory=dict, description="Raw feed metadata, authors, tags"
    )
    discovered_at: datetime = Field(
        default_factory=utc_now, description="Timestamp when item was ingested"
    )
    content_hash: str = Field(
        description="Deterministic hash for multi-layer deduplication"
    )
    is_verified: bool = Field(
        default=False, description="Whether the item passed factual verification"
    )
    verification_score: float = Field(
        default=0.0, description="0.0 - 100.0 factual verification score"
    )
    verification_notes: Optional[str] = Field(
        default=None, description="Detailed verification notes and checks"
    )

    model_config = ConfigDict(populate_by_name=True)


class GeneratedContent(BaseModel):
    """Publication-ready content adapted for a target social platform."""

    platform: Platform = Field(description="Target platform (X or LinkedIn)")
    text: str = Field(description="Editorial body text adhering to platform limits")
    character_count: int = Field(description="Calculated character or weighted count")
    has_em_dash: bool = Field(
        default=False, description="Flag indicating em dash presence (must be False)"
    )
    visual_path: Optional[str] = Field(
        default=None, description="File path to accompanying visual/infographic"
    )
    attribution_url: str = Field(
        description="Source reference URL for verification and attribution"
    )
    is_sensitive: bool = Field(
        default=False, description="Whether content covers sensitive/controversial topics"
    )

    model_config = ConfigDict(populate_by_name=True)


class PublishJob(BaseModel):
    """An entry in the publication queue awaiting execution or manual workflow."""

    job_id: str = Field(description="Unique job identifier")
    item_id: str = Field(description="Referenced discovered item id")
    platform: Platform = Field(description="Target social platform")
    content: GeneratedContent = Field(description="Generated editorial content payload")
    status: PostStatus = Field(
        default=PostStatus.QUEUED, description="Lifecycle status of this job"
    )
    scheduled_for: Optional[datetime] = Field(
        default=None, description="Scheduled release time (if deferred)"
    )
    created_at: datetime = Field(
        default_factory=utc_now, description="Creation timestamp"
    )
    retry_count: int = Field(
        default=0, description="Number of attempted publish executions"
    )

    model_config = ConfigDict(populate_by_name=True)


class SystemStatus(BaseModel):
    """Global system health, emergency shutoff status, and queue telemetry."""

    is_paused: bool = Field(
        default=False, description="Whether automation loops are temporarily paused"
    )
    emergency_shutoff: bool = Field(
        default=False, description="Emergency stop flag halting all publishing"
    )
    active_workers: int = Field(
        default=0, description="Number of active background ingestion/publishing workers"
    )
    last_poll_time: Optional[datetime] = Field(
        default=None, description="Timestamp of the most recent feed poll"
    )
    queue_counts: Dict[str, int] = Field(
        default_factory=dict, description="Job counts broken down by PostStatus"
    )

    model_config = ConfigDict(populate_by_name=True)


class AuditLogEntry(BaseModel):
    """Immutable record of system events, publishing actions, and safety alerts."""

    id: str = Field(description="Unique log entry identifier")
    event_type: str = Field(description="Category of the event (e.g. INGEST, APPROVE)")
    timestamp: datetime = Field(
        default_factory=utc_now, description="Event occurrence timestamp"
    )
    details: Dict[str, Any] = Field(
        default_factory=dict, description="Structured event payload"
    )

    model_config = ConfigDict(populate_by_name=True)
