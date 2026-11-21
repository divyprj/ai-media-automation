"""Unit tests for SQLite database connection, models, and repository."""

import os
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pytest

from src.contracts.enums import Platform, PostStatus, SourceType
from src.contracts.schemas import (
    AuditLogEntry,
    DiscoveredItem,
    GeneratedContent,
    PublishJob,
)
from src.database.connection import create_connection, get_db_connection
from src.database.models import init_db
from src.database.repository import Repository


class TestDatabaseConnection:
    """Test SQLite connection pragmas, WAL mode, and row factory behavior."""

    def test_file_database_pragmas(self, tmp_path):
        db_file = str(tmp_path / "test_pragmas.db")
        conn = create_connection(db_file)
        try:
            # WAL mode
            journal_mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
            assert journal_mode.lower() == "wal"

            # synchronous = NORMAL (1)
            synchronous = conn.execute("PRAGMA synchronous;").fetchone()[0]
            assert synchronous == 1

            # busy_timeout = 5000
            busy_timeout = conn.execute("PRAGMA busy_timeout;").fetchone()[0]
            assert busy_timeout == 5000

            # foreign_keys = ON (1)
            foreign_keys = conn.execute("PRAGMA foreign_keys;").fetchone()[0]
            assert foreign_keys == 1
        finally:
            conn.close()

    def test_memory_database_pragmas(self):
        conn = create_connection(":memory:")
        try:
            synchronous = conn.execute("PRAGMA synchronous;").fetchone()[0]
            assert synchronous == 1

            busy_timeout = conn.execute("PRAGMA busy_timeout;").fetchone()[0]
            assert busy_timeout == 5000

            foreign_keys = conn.execute("PRAGMA foreign_keys;").fetchone()[0]
            assert foreign_keys == 1
        finally:
            conn.close()

    def test_row_factory_access(self):
        with get_db_connection(":memory:") as conn:
            conn.execute("CREATE TABLE test_row (id INT, label TEXT);")
            conn.execute("INSERT INTO test_row VALUES (1, 'Alpha');")
            row = conn.execute("SELECT * FROM test_row;").fetchone()

            # Dict / key access
            assert row["id"] == 1
            assert row["label"] == "Alpha"

            # Index access
            assert row[0] == 1
            assert row[1] == "Alpha"

            # Keys inspection
            assert list(row.keys()) == ["id", "label"]

    def test_context_manager_commit_and_rollback(self, tmp_path):
        db_file = str(tmp_path / "test_txn.db")

        # Verify auto-commit on clean exit
        with get_db_connection(db_file) as conn:
            conn.execute("CREATE TABLE txn_test (val INT);")
            conn.execute("INSERT INTO txn_test VALUES (100);")

        with get_db_connection(db_file) as conn:
            row = conn.execute("SELECT val FROM txn_test;").fetchone()
            assert row["val"] == 100

        # Verify rollback on exception
        with pytest.raises(RuntimeError):
            with get_db_connection(db_file) as conn:
                conn.execute("INSERT INTO txn_test VALUES (200);")
                raise RuntimeError("Forced failure")

        with get_db_connection(db_file) as conn:
            rows = conn.execute("SELECT val FROM txn_test;").fetchall()
            values = [r["val"] for r in rows]
            assert 200 not in values
            assert 100 in values


class TestDatabaseModels:
    """Test table and index DDL initialization."""

    def test_init_db_creates_all_tables_and_indexes(self):
        conn = create_connection(":memory:")
        try:
            init_db(conn)
            cursor = conn.execute(
                "SELECT name, type FROM sqlite_master WHERE type IN ('table', 'index');"
            )
            created = {row["name"] for row in cursor.fetchall()}

            expected_tables = {
                "feeds",
                "discovered_items",
                "generated_posts",
                "publish_queue",
                "audit_logs",
            }
            assert expected_tables.issubset(created)

            expected_indexes = {
                "idx_discovered_items_hash",
                "idx_publish_queue_status_sched",
                "idx_publish_queue_item",
                "idx_publish_queue_post_id",
                "idx_generated_posts_item",
                "idx_audit_logs_timestamp",
            }
            assert expected_indexes.issubset(created)
        finally:
            conn.close()


class TestRepository:
    """Test thread-safe Repository CRUD, constraints, and queue transitions."""

    @pytest.fixture
    def repo(self, tmp_path):
        db_path = str(tmp_path / "repo_test.db")
        repository = Repository(db_path)
        repository.init_db()
        yield repository
        repository.close()

    def test_save_and_get_discovered_item(self, repo):
        item = DiscoveredItem(
            id="item-test-1",
            source_type=SourceType.ARXIV,
            title="Reasoning via Distillation",
            summary="A comprehensive survey on distillation techniques.",
            source_url="https://arxiv.org/abs/2401.99999",
            raw_metadata={"category": "cs.AI", "pages": 12},
            content_hash="hash_distill_1",
            is_verified=True,
            verification_score=88.0,
            verification_notes="Verified via official source.",
        )
        saved = repo.save_discovered_item(item)
        assert saved is True

        retrieved = repo.get_discovered_item("item-test-1")
        assert retrieved is not None
        assert retrieved.id == item.id
        assert retrieved.title == item.title
        assert retrieved.source_type == SourceType.ARXIV
        assert retrieved.raw_metadata["category"] == "cs.AI"
        assert retrieved.is_verified is True
        assert retrieved.verification_score == 88.0

    def test_duplicate_content_hash_prevention(self, repo):
        item1 = DiscoveredItem(
            id="item-hash-1",
            source_type=SourceType.GITHUB,
            title="Project A",
            summary="Summary A",
            source_url="https://github.com/repo/a",
            content_hash="unique_hash_123",
        )
        assert repo.save_discovered_item(item1) is True

        # Same content hash, different id
        item2 = DiscoveredItem(
            id="item-hash-2",
            source_type=SourceType.GITHUB,
            title="Project A Duplicate",
            summary="Summary A Duplicate",
            source_url="https://github.com/repo/a",
            content_hash="unique_hash_123",
        )
        # Must return False without crashing
        assert repo.save_discovered_item(item2) is False

    def test_duplicate_primary_key_prevention(self, repo):
        item1 = DiscoveredItem(
            id="item-pk-1",
            source_type=SourceType.BLOG,
            title="Blog Post",
            summary="Summary",
            source_url="https://openai.com/blog/test1",
            content_hash="hash_pk_1",
        )
        assert repo.save_discovered_item(item1) is True

        # Same primary key, different content hash
        item2 = DiscoveredItem(
            id="item-pk-1",
            source_type=SourceType.BLOG,
            title="Blog Post Different",
            summary="Summary",
            source_url="https://openai.com/blog/test2",
            content_hash="hash_pk_2",
        )
        assert repo.save_discovered_item(item2) is False

    def test_get_nonexistent_item_returns_none(self, repo):
        assert repo.get_discovered_item("nonexistent-id") is None

    def test_get_unprocessed_items_and_filtering(self, repo):
        item1 = DiscoveredItem(
            id="unprocessed-1",
            source_type=SourceType.ARXIV,
            title="Paper 1",
            summary="Abstract 1",
            source_url="https://arxiv.org/1",
            content_hash="hash_unproc_1",
        )
        item2 = DiscoveredItem(
            id="unprocessed-2",
            source_type=SourceType.ARXIV,
            title="Paper 2",
            summary="Abstract 2",
            source_url="https://arxiv.org/2",
            content_hash="hash_unproc_2",
        )
        repo.save_discovered_item(item1)
        repo.save_discovered_item(item2)

        unprocessed = repo.get_unprocessed_items()
        assert len(unprocessed) == 2

        # Enqueue job for item1
        content = GeneratedContent(
            platform=Platform.X,
            text="Paper 1 announced.",
            character_count=18,
            attribution_url="https://arxiv.org/1",
        )
        job = PublishJob(
            job_id="job-unproc-1",
            item_id="unprocessed-1",
            platform=Platform.X,
            content=content,
        )
        repo.enqueue_publish_job(job)

        # Now only item2 should be in unprocessed items
        unprocessed_after = repo.get_unprocessed_items()
        assert len(unprocessed_after) == 1
        assert unprocessed_after[0].id == "unprocessed-2"

    def test_get_unprocessed_items_platform_filter(self, repo):
        item = DiscoveredItem(
            id="item-multiplatform-1",
            source_type=SourceType.ARXIV,
            title="Multi-Platform Discovery",
            summary="New breakthrough architecture.",
            source_url="https://arxiv.org/abs/2402.12345",
            content_hash="hash_multiplatform_123",
        )
        repo.save_discovered_item(item)

        # Enqueue job for Platform.X
        content_x = GeneratedContent(
            platform=Platform.X,
            text="Breakthrough architecture for X.",
            character_count=32,
            attribution_url="https://arxiv.org/abs/2402.12345",
        )
        job_x = PublishJob(
            job_id="job-x-multi",
            item_id="item-multiplatform-1",
            platform=Platform.X,
            content=content_x,
            status=PostStatus.QUEUED,
        )
        repo.enqueue_publish_job(job_x)

        # Query unprocessed for LinkedIn: must still return the item
        unprocessed_linkedin = repo.get_unprocessed_items(platform=Platform.LINKEDIN)
        assert any(it.id == "item-multiplatform-1" for it in unprocessed_linkedin)

        # Query unprocessed for X: must exclude the item
        unprocessed_x = repo.get_unprocessed_items(platform=Platform.X)
        assert not any(it.id == "item-multiplatform-1" for it in unprocessed_x)

        # Default query (no platform): excludes items queued for any platform
        unprocessed_default = repo.get_unprocessed_items()
        assert not any(it.id == "item-multiplatform-1" for it in unprocessed_default)

    def test_foreign_key_enforcement_on_enqueue(self, repo):
        content = GeneratedContent(
            platform=Platform.X,
            text="Non-existent item announcement.",
            character_count=31,
            attribution_url="https://unknown.com",
        )
        job = PublishJob(
            job_id="job-fk-fail",
            item_id="does-not-exist",
            platform=Platform.X,
            content=content,
        )
        # Attempting to enqueue job referencing non-existent item_id must violate foreign key
        with pytest.raises(sqlite3.IntegrityError):
            repo.enqueue_publish_job(job)

    def test_enqueue_and_get_pending_jobs(self, repo):
        item = DiscoveredItem(
            id="item-pending-1",
            source_type=SourceType.HUGGINGFACE,
            title="Model Hub Update",
            summary="New checkpoint available.",
            source_url="https://huggingface.co/models",
            content_hash="hash_hf_model",
        )
        repo.save_discovered_item(item)

        content = GeneratedContent(
            platform=Platform.X,
            text="Checkpoint now available on HF Hub.",
            character_count=35,
            has_em_dash=False,
            attribution_url="https://huggingface.co/models",
        )
        job = PublishJob(
            job_id="job-pending-1",
            item_id="item-pending-1",
            platform=Platform.X,
            content=content,
            status=PostStatus.QUEUED,
        )
        job_id = repo.enqueue_publish_job(job)
        assert job_id == "job-pending-1"

        pending_jobs = repo.get_pending_jobs()
        assert len(pending_jobs) == 1
        retrieved_job = pending_jobs[0]
        assert retrieved_job.job_id == "job-pending-1"
        assert retrieved_job.platform == Platform.X
        assert retrieved_job.content.text == "Checkpoint now available on HF Hub."
        assert retrieved_job.status == PostStatus.QUEUED

    def test_get_pending_jobs_with_multiple_drafts_no_cartesian_product(self, repo):
        item = DiscoveredItem(
            id="item-regen-test",
            source_type=SourceType.BLOG,
            title="Reasoning Paper Release",
            summary="Discussion on new reasoning model.",
            source_url="https://example.com/reasoning",
            content_hash="hash_regen_123",
        )
        repo.save_discovered_item(item)

        # Enqueue draft 1 for item on Platform.X, then reject it
        c1 = GeneratedContent(
            platform=Platform.X,
            text="Draft 1 (bad draft with issues)",
            character_count=30,
            attribution_url="https://example.com/reasoning",
        )
        job1 = PublishJob(
            job_id="job-regen-1",
            item_id="item-regen-test",
            platform=Platform.X,
            content=c1,
            status=PostStatus.QUEUED,
        )
        repo.enqueue_publish_job(job1)
        repo.update_job_status("job-regen-1", PostStatus.REJECTED)

        # Enqueue draft 2 for item on Platform.X (pending / QUEUED)
        c2 = GeneratedContent(
            platform=Platform.X,
            text="Draft 2 (good polished draft)",
            character_count=30,
            attribution_url="https://example.com/reasoning",
        )
        job2 = PublishJob(
            job_id="job-regen-2",
            item_id="item-regen-test",
            platform=Platform.X,
            content=c2,
            status=PostStatus.QUEUED,
        )
        repo.enqueue_publish_job(job2)

        # Verify get_pending_jobs returns exactly 1 pending job with draft 2 content
        pending_jobs = repo.get_pending_jobs()
        assert len(pending_jobs) == 1
        assert pending_jobs[0].job_id == "job-regen-2"
        assert pending_jobs[0].content.text == "Draft 2 (good polished draft)"
        assert pending_jobs[0].status == PostStatus.QUEUED

    def test_update_job_status(self, repo):
        item = DiscoveredItem(
            id="item-status-1",
            source_type=SourceType.BLOG,
            title="Lab Update",
            summary="New research report.",
            source_url="https://research.google",
            content_hash="hash_google_res",
        )
        repo.save_discovered_item(item)

        content = GeneratedContent(
            platform=Platform.LINKEDIN,
            text="Research report overview.",
            character_count=24,
            attribution_url="https://research.google",
        )
        job = PublishJob(
            job_id="job-status-1",
            item_id="item-status-1",
            platform=Platform.LINKEDIN,
            content=content,
            status=PostStatus.QUEUED,
        )
        repo.enqueue_publish_job(job)

        # Update to PUBLISHED
        updated = repo.update_job_status("job-status-1", PostStatus.PUBLISHED)
        assert updated is True

        # Since it is now PUBLISHED, get_pending_jobs should not include it
        assert len(repo.get_pending_jobs()) == 0

        # Non-existent job update returns False
        assert repo.update_job_status("nonexistent-job", PostStatus.FAILED) is False

    def test_record_audit_log(self, repo):
        entry = AuditLogEntry(
            id="audit-log-1",
            event_type="SYSTEM_STARTUP",
            details={"version": "0.1.0", "mode": "zero_cost"},
        )
        repo.record_audit_log(entry)

        with get_db_connection(repo.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM audit_logs WHERE id = 'audit-log-1';"
            ).fetchone()
            assert row is not None
            assert row["event_type"] == "SYSTEM_STARTUP"
            assert "0.1.0" in row["details"]

    def test_get_system_status(self, repo):
        # Create an item and multiple jobs with different statuses
        item = DiscoveredItem(
            id="item-telemetry-1",
            source_type=SourceType.GITHUB,
            title="Telemetry Item",
            summary="Summary",
            source_url="https://github.com/test",
            content_hash="hash_telemetry_1",
        )
        repo.save_discovered_item(item)

        content = GeneratedContent(
            platform=Platform.X,
            text="Telemetry post.",
            character_count=15,
            attribution_url="https://github.com/test",
        )
        job1 = PublishJob(
            job_id="job-t1",
            item_id="item-telemetry-1",
            platform=Platform.X,
            content=content,
            status=PostStatus.QUEUED,
        )
        repo.enqueue_publish_job(job1)

        status = repo.get_system_status()
        assert status.active_workers == 1
        assert status.queue_counts.get("queued") == 1


class TestRepositoryConcurrency:
    """Test multi-threaded concurrent access to ensure thread safety and WAL concurrency."""

    def test_concurrent_writes_and_reads(self, tmp_path):
        db_path = str(tmp_path / "concurrent_test.db")
        repo = Repository(db_path)
        repo.init_db()

        num_threads = 10
        items_per_thread = 5

        def worker_task(thread_idx: int):
            for i in range(items_per_thread):
                item_id = f"item-t{thread_idx}-{i}"
                item = DiscoveredItem(
                    id=item_id,
                    source_type=SourceType.ARXIV,
                    title=f"Paper from thread {thread_idx} index {i}",
                    summary="Concurrent test summary",
                    source_url=f"https://arxiv.org/{thread_idx}/{i}",
                    content_hash=f"hash-{thread_idx}-{i}",
                )
                saved = repo.save_discovered_item(item)
                assert saved is True

                retrieved = repo.get_discovered_item(item_id)
                assert retrieved is not None
                assert retrieved.id == item_id

        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(worker_task, idx) for idx in range(num_threads)]
            for future in futures:
                future.result()

        # Verify all items were successfully persisted
        with get_db_connection(db_path) as conn:
            count = conn.execute("SELECT count(*) FROM discovered_items;").fetchone()[0]
            assert count == num_threads * items_per_thread

        repo.close()
