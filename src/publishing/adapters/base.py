"""Base publisher adapter abstract class and publishing result schemas."""

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field

from src.contracts.schemas import PublishJob


def utc_now() -> datetime:
    """Return the current UTC timestamp."""
    return datetime.now(timezone.utc)


class PublishResult(BaseModel):
    """Standardized result of a social publishing execution."""

    success: bool = Field(description="Whether the publication succeeded")
    post_id: Optional[str] = Field(default=None, description="External platform post/tweet ID")
    post_url: Optional[str] = Field(default=None, description="Direct URL to published post or intent")
    error: Optional[str] = Field(default=None, description="Error message if publishing failed")
    mode: str = Field(description="Publishing mode: 'MODE_A' (API) or 'MODE_B' (Manual Queue)")
    rate_limit_reset: Optional[float] = Field(default=None, description="Seconds until rate limit reset")
    timestamp: datetime = Field(default_factory=utc_now, description="Execution timestamp")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Platform-specific metadata")


class BasePublisherAdapter(ABC):
    """Abstract base class for all social publishing adapters."""

    @abstractmethod
    def publish(self, job: PublishJob) -> PublishResult:
        """Execute publication of a queued job to the target platform."""
        pass

    @abstractmethod
    def can_publish(self) -> bool:
        """Check if adapter has valid credentials and operational status to publish."""
        pass

    def get_mode(self) -> str:
        """Return the operational mode of this adapter."""
        return "MODE_A"
