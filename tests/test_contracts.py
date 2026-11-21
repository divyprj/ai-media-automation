"""Unit tests for system enums and Pydantic contract schemas."""

from datetime import datetime, timezone
import pytest
from pydantic import ValidationError

from src.contracts.enums import ContentType, Platform, PostStatus, SourceType
from src.contracts.schemas import (
    AuditLogEntry,
    DiscoveredItem,
    GeneratedContent,
    PublishJob,
    SystemStatus,
)


class TestEnums:
    """Test enumeration definitions, string values, and membership."""

    def test_platform_values(self):
        assert Platform.X == "x"
        assert Platform.LINKEDIN == "linkedin"
        assert Platform("x") == Platform.X
        assert Platform("linkedin") == Platform.LINKEDIN

        with pytest.raises(ValueError):
            Platform("facebook")

    def test_post_status_values(self):
        expected_statuses = {
            "discovered",
            "verified",
            "queued",
            "awaiting_approval",
            "ready_for_manual",
            "published",
            "rejected",
            "failed",
        }
        actual_statuses = {status.value for status in PostStatus}
        assert actual_statuses == expected_statuses

    def test_source_type_values(self):
        expected_sources = {"arxiv", "github", "huggingface", "blog"}
        actual_sources = {source.value for source in SourceType}
        assert actual_sources == expected_sources

    def test_content_type_values(self):
        expected_types = {"post", "thread", "showcase"}
        actual_types = {t.value for t in ContentType}
        assert actual_types == expected_types


class TestDiscoveredItemSchema:
    """Test DiscoveredItem Pydantic schema validation and serialization."""

    def test_valid_item_creation(self):
        item = DiscoveredItem(
            id="item-001",
            source_type=SourceType.ARXIV,
            title="Attention Is All You Need",
            summary="Transformer architecture paper",
            source_url="https://arxiv.org/abs/1706.03762",
            content_hash="abc123hash",
        )
        assert item.id == "item-001"
        assert item.source_type == SourceType.ARXIV
        assert item.is_verified is False
        assert item.verification_score == 0.0
        assert item.verification_notes is None
        assert isinstance(item.discovered_at, datetime)
        assert item.raw_metadata == {}

    def test_item_with_full_metadata(self):
        now = datetime.now(timezone.utc)
        item = DiscoveredItem(
            id="item-002",
            source_type=SourceType.GITHUB,
            title="vLLM: High-throughput LLM serving",
            summary="Fast inference and serving engine for LLMs",
            source_url="https://github.com/vllm-project/vllm",
            raw_metadata={"stars": 25000, "release": "v0.6.0"},
            discovered_at=now,
            content_hash="vllm_hash_999",
            is_verified=True,
            verification_score=95.5,
            verification_notes="Verified via GitHub Releases API and official commit history.",
        )
        assert item.is_verified is True
        assert item.verification_score == 95.5
        assert item.raw_metadata["stars"] == 25000

    def test_item_json_serialization_roundtrip(self):
        item = DiscoveredItem(
            id="item-roundtrip",
            source_type=SourceType.HUGGINGFACE,
            title="DeepSeek-R1-Distill",
            summary="Open weights reasoning model",
            source_url="https://huggingface.co/deepseek-ai/DeepSeek-R1",
            content_hash="hf_deepseek_hash",
        )
        json_data = item.model_dump_json()
        deserialized = DiscoveredItem.model_validate_json(json_data)
        assert deserialized.id == item.id
        assert deserialized.source_type == item.source_type
        assert deserialized.content_hash == item.content_hash

    def test_missing_required_fields_raises_validation_error(self):
        with pytest.raises(ValidationError):
            DiscoveredItem(
                id="invalid-item",
                # missing source_type, title, summary, source_url, content_hash
            )


class TestGeneratedContentSchema:
    """Test GeneratedContent Pydantic schema validation."""

    def test_valid_generated_content(self):
        content = GeneratedContent(
            platform=Platform.X,
            text="DeepSeek releases new distilled reasoning models with open weights.",
            character_count=73,
            has_em_dash=False,
            attribution_url="https://huggingface.co/deepseek-ai",
        )
        assert content.platform == Platform.X
        assert content.character_count == 73
        assert content.has_em_dash is False
        assert content.visual_path is None
        assert content.is_sensitive is False

    def test_generated_content_with_visual_and_sensitivity(self):
        content = GeneratedContent(
            platform=Platform.LINKEDIN,
            text="Comprehensive breakdown of LLM inference architectures.",
            character_count=58,
            has_em_dash=False,
            visual_path="data/visuals/vllm_benchmark.png",
            attribution_url="https://github.com/vllm-project/vllm",
            is_sensitive=True,
        )
        assert content.visual_path == "data/visuals/vllm_benchmark.png"
        assert content.is_sensitive is True


class TestPublishJobSchema:
    """Test PublishJob Pydantic schema with nested GeneratedContent."""

    def test_valid_publish_job(self):
        content = GeneratedContent(
            platform=Platform.X,
            text="Announcing new open model release.",
            character_count=35,
            has_em_dash=False,
            attribution_url="https://arxiv.org/abs/2401.0001",
        )
        job = PublishJob(
            job_id="job-101",
            item_id="item-001",
            platform=Platform.X,
            content=content,
        )
        assert job.job_id == "job-101"
        assert job.item_id == "item-001"
        assert job.status == PostStatus.QUEUED
        assert job.retry_count == 0
        assert job.scheduled_for is None
        assert isinstance(job.created_at, datetime)

    def test_publish_job_json_roundtrip(self):
        content = GeneratedContent(
            platform=Platform.LINKEDIN,
            text="Analysis of open weights AI advancements.",
            character_count=42,
            attribution_url="https://arxiv.org",
        )
        job = PublishJob(
            job_id="job-202",
            item_id="item-002",
            platform=Platform.LINKEDIN,
            content=content,
            status=PostStatus.VERIFIED,
            retry_count=1,
        )
        json_str = job.model_dump_json()
        parsed = PublishJob.model_validate_json(json_str)
        assert parsed.job_id == "job-202"
        assert parsed.content.platform == Platform.LINKEDIN
        assert parsed.status == PostStatus.VERIFIED


class TestSystemStatusSchema:
    """Test SystemStatus schema defaults and state representations."""

    def test_default_system_status(self):
        status = SystemStatus()
        assert status.is_paused is False
        assert status.emergency_shutoff is False
        assert status.active_workers == 0
        assert status.last_poll_time is None
        assert status.queue_counts == {}

    def test_custom_system_status(self):
        now = datetime.now(timezone.utc)
        status = SystemStatus(
            is_paused=True,
            emergency_shutoff=True,
            active_workers=3,
            last_poll_time=now,
            queue_counts={"queued": 5, "published": 12, "rejected": 2},
        )
        assert status.is_paused is True
        assert status.emergency_shutoff is True
        assert status.active_workers == 3
        assert status.queue_counts["queued"] == 5


class TestAuditLogEntrySchema:
    """Test AuditLogEntry schema validation and serialization."""

    def test_valid_audit_log(self):
        entry = AuditLogEntry(
            id="audit-901",
            event_type="DISCOVERY_INGESTED",
            details={"source": "arxiv", "items_count": 14},
        )
        assert entry.id == "audit-901"
        assert entry.event_type == "DISCOVERY_INGESTED"
        assert entry.details["items_count"] == 14
        assert isinstance(entry.timestamp, datetime)

    def test_audit_log_entry_is_immutable(self):
        entry = AuditLogEntry(
            id="audit-immutable",
            event_type="SYSTEM_EVENT",
            details={},
        )
        with pytest.raises(ValidationError):
            entry.event_type = "MUTATED"
