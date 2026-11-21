"""System enumerations for platforms, post statuses, sources, and content types."""

from enum import Enum


class Platform(str, Enum):
    """Target social publishing platforms."""

    X = "x"
    LINKEDIN = "linkedin"


class PostStatus(str, Enum):
    """Lifecycle states of items and queued publish jobs."""

    DISCOVERED = "discovered"
    VERIFIED = "verified"
    QUEUED = "queued"
    AWAITING_APPROVAL = "awaiting_approval"
    READY_FOR_MANUAL = "ready_for_manual"
    PUBLISHED = "published"
    REJECTED = "rejected"
    FAILED = "failed"


class SourceType(str, Enum):
    """Monitored content feed and discovery source types."""

    ARXIV = "arxiv"
    GITHUB = "github"
    HUGGINGFACE = "huggingface"
    BLOG = "blog"


class ContentType(str, Enum):
    """Content editorial format types."""

    POST = "post"
    THREAD = "thread"
    SHOWCASE = "showcase"
