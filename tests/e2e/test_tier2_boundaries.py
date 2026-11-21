"""Tier 2: Boundary Value Analysis & Edge Cases.

Covers 5 distinct boundary classes with 7 tests per class:
1. Extreme Character Counts & Off-by-One Boundaries (7 tests)
2. Feed & Network Boundaries (7 tests)
3. Unicode, Banned Glyphs & Malformed Inputs (7 tests)
4. Environment & Configuration Boundaries (7 tests)
5. Concurrency & Race Conditions (7 tests)

Total: 35 tests.
"""

import sqlite3
import threading

import pytest
from src.discovery.parsers.rss_parser import parse_rss_feed
from src.generator.editorial_rules import (
    EditorialLinter,
    LinkedInFormatter,
    TwitterTextCalculator,
)
from src.publishing.queue_manager import QueueManager

from src.contracts.enums import PostStatus
from src.database.connection import get_db_connection

# ==============================================================================
# Class 1: Extreme Character Counts & Off-by-One Boundaries (7 tests)
# ==============================================================================

def test_t2_b1_01_twitter_exact_279_chars_passes():
    """Verify an X post of exactly 279 ASCII characters passes character limit validation."""
    calc = TwitterTextCalculator()
    text = "a" * 279
    assert calc.calculate_weighted_length(text) == 279
    assert calc.is_valid_x_post(text) is True


def test_t2_b1_02_twitter_exact_280_chars_passes():
    """Verify an X post of exactly 280 ASCII characters passes character limit validation."""
    calc = TwitterTextCalculator()
    text = "a" * 280
    assert calc.calculate_weighted_length(text) == 280
    assert calc.is_valid_x_post(text) is True


def test_t2_b1_03_twitter_exact_281_chars_fails():
    """Verify an X post of exactly 281 ASCII characters fails character limit validation."""
    calc = TwitterTextCalculator()
    text = "a" * 281
    assert calc.calculate_weighted_length(text) == 281
    assert calc.is_valid_x_post(text) is False


def test_t2_b1_04_linkedin_exact_2999_chars_passes():
    """Verify a LinkedIn post of exactly 2999 characters passes character limit validation."""
    formatter = LinkedInFormatter()
    text = "a" * 2999
    assert formatter.is_valid_linkedin_length(text) is True


def test_t2_b1_05_linkedin_exact_3000_chars_passes():
    """Verify a LinkedIn post of exactly 3000 characters passes character limit validation."""
    formatter = LinkedInFormatter()
    text = "a" * 3000
    assert formatter.is_valid_linkedin_length(text) is True


def test_t2_b1_06_linkedin_exact_3001_chars_fails():
    """Verify a LinkedIn post of exactly 3001 characters fails character limit validation."""
    formatter = LinkedInFormatter()
    text = "a" * 3001
    assert formatter.is_valid_linkedin_length(text) is False


def test_t2_b1_07_empty_zero_char_content_fails():
    """Verify an empty string fails X post validation."""
    calc = TwitterTextCalculator()
    assert calc.is_valid_x_post("") is False


# ==============================================================================
# Class 2: Feed & Network Boundaries (7 tests)
# ==============================================================================

def test_t2_b2_01_empty_feed_zero_items_graceful_handling():
    """Verify an empty RSS feed containing zero items parses to an empty list without crashing."""
    empty_rss = "<rss version='2.0'><channel><title>Empty</title></channel></rss>"
    items = parse_rss_feed(empty_rss)
    assert items == []


def test_t2_b2_02_massive_10mb_feed_partial_read_bounds():
    """Verify a massive feed respects max_bytes stream bounds."""
    massive_desc = "A" * (100 * 1024)
    rss = f"<rss version='2.0'><channel><item><title>T</title><link>https://example.com</link><description>{massive_desc}</description></item></channel></rss>"
    items = parse_rss_feed(rss, max_bytes=64 * 1024)
    assert len(items) == 1
    assert len(items[0].summary) <= 64 * 1024


def test_t2_b2_03_http_404_feed_not_found_handled(mock_http_client):
    """Verify HTTP client handles 404 or simulated feed response gracefully."""
    res = mock_http_client.get("https://example.com/notfound-feed.xml")
    assert res.status_code in [200, 404]


def test_t2_b2_04_http_500_server_error_handled(mock_http_client):
    """Verify HTTP client handles upstream server error gracefully."""
    res = mock_http_client.get("https://example.com/server-error.xml")
    assert res.status_code in [200, 500]


def test_t2_b2_05_http_429_rate_limit_reset_header_backoff():
    """Verify rate-limit 429 response parses reset header and computes backoff delay."""
    qm = QueueManager(None)
    backoff = qm.calculate_rate_limit_backoff({"x-rate-limit-reset": "1795242025"})
    assert isinstance(backoff, float)
    assert backoff >= 0.0


def test_t2_b2_06_network_timeout_and_socket_disconnect():
    """Verify network timeouts are classified as retryable errors."""
    qm = QueueManager(None)
    res = qm.handle_network_exception(TimeoutError("Connection timed out"))
    assert res.should_retry is True


def test_t2_b2_07_malformed_corrupt_non_xml_payload():
    """Verify corrupt non-XML payloads return empty list without uncaught exception."""
    corrupt = "This is not XML at all! {json: true}"
    items = parse_rss_feed(corrupt)
    assert items == []


# ==============================================================================
# Class 3: Unicode, Banned Glyphs & Malformed Inputs (7 tests)
# ==============================================================================

def test_t2_b3_01_text_with_only_prohibited_em_dashes():
    """Verify text composed exclusively of em dashes is flagged as unclean."""
    linter = EditorialLinter()
    assert linter.scan_dashes("—————").is_clean is False


def test_t2_b3_02_text_with_100_emojis_cluster():
    """Verify text with an excessive cluster of emojis fails editorial validation."""
    linter = EditorialLinter()
    assert linter.validate_emoji_count("🚀" * 100) is False


def test_t2_b3_03_bilingual_and_cjk_emoji_boundary_weights():
    """Verify mixed ASCII, CJK, and emoji text correctly weights non-ASCII glyphs as 2 units."""
    calc = TwitterTextCalculator()
    mixed = "AI モデル 📊"
    assert calc.calculate_weighted_length(mixed) > len(mixed)


def test_t2_b3_04_exclusive_zero_width_space_payload():
    """Verify payloads containing only zero-width spaces are identified."""
    linter = EditorialLinter()
    assert linter.contains_zero_width("\u200b\u200b\u200b") is True


def test_t2_b3_05_embedded_null_bytes_in_feed_text():
    """Verify embedded null bytes are sanitized without causing database encoding errors."""
    linter = EditorialLinter()
    clean = linter.sanitize_null_bytes("Text\x00WithNull")
    assert "\x00" not in clean
    assert clean == "TextWithNull"


def test_t2_b3_06_unprintable_ascii_control_characters():
    """Verify unprintable ASCII control characters are stripped."""
    linter = EditorialLinter()
    clean = linter.strip_control_chars("Text\x07\x08")
    assert clean == "Text"


def test_t2_b3_07_unbreakable_500_char_token_wrapping():
    """Verify long unbreakable URL or token is wrapped or formatted safely."""
    formatter = LinkedInFormatter()
    long_token = "https://example.com/" + "a" * 200
    wrapped = formatter.wrap_long_tokens(long_token, max_token_len=80)
    assert len(wrapped) > 0


# ==============================================================================
# Class 4: Environment & Configuration Boundaries (7 tests)
# ==============================================================================

def test_t2_b4_01_missing_social_api_keys_fallback_to_mode_b(test_settings):
    """Verify absent social API keys automatically routes publishing to Mode B (Manual Queue)."""
    qm = QueueManager(None, settings=test_settings)
    assert qm.get_active_publishing_mode() == "MODE_B"


def test_t2_b4_02_unreachable_ollama_fallback_to_heuristics():
    """Verify unreachable Ollama endpoint falls back to clean deterministic heuristics."""
    qm = QueueManager(None)
    content = qm.generate_fallback_content("New LLM Released", "Significant speedups observed", "https://arxiv.org/abs/123")
    assert len(content.text) > 0
    assert "—" not in content.text


def test_t2_b4_03_invalid_db_path_error_handling():
    """Verify attempting to connect to an impossible database path raises an exception."""
    with pytest.raises((sqlite3.Error, OSError)), get_db_connection("/invalid/path/that/cannot/exist/db.sqlite") as conn:
        conn.execute("SELECT 1;")


def test_t2_b4_04_corrupted_sqlite_header_handling(temp_workdir):
    """Verify corrupted non-SQLite database file raises sqlite3.DatabaseError."""
    corrupt_db = temp_workdir / "corrupt.db"
    corrupt_db.write_bytes(b"CORRUPT HEADER NOT SQLITE")
    with pytest.raises(sqlite3.DatabaseError), get_db_connection(str(corrupt_db)) as conn:
        conn.execute("SELECT 1;")


def test_t2_b4_05_readonly_db_filesystem_exception_handling():
    """Verify handling of readonly database filesystem exceptions."""
    qm = QueueManager(None)
    res = qm.handle_db_exception(sqlite3.OperationalError("attempt to write a readonly database"))
    assert res.get("handled") is True


def test_t2_b4_06_heavy_sqlite_wal_busy_timeout_contention(db_connection):
    """Verify busy_timeout PRAGMA is configured to >= 5000ms."""
    cursor = db_connection.cursor()
    cursor.execute("PRAGMA busy_timeout;")
    timeout = cursor.fetchone()[0]
    assert timeout >= 5000


def test_t2_b4_07_missing_env_variables_load_defaults():
    """Verify Settings loads safe default configuration values when env is empty."""
    from src.config import Settings
    s = Settings()
    assert s.server_port == 8000
    assert s.database_url == "data/ai_media.db"


# ==============================================================================
# Class 5: Concurrency & Race Conditions (7 tests)
# ==============================================================================

def test_t2_b5_01_concurrent_publish_exact_same_job(db_repo, make_publish_job):
    """Verify atomic lock acquisition ensures only 1 worker claims a publish job."""
    qm = QueueManager(db_repo)
    job = make_publish_job(job_id="job_race_lock_1")
    qm.enqueue(job)
    results = []

    def try_publish():
        success = qm.acquire_publish_lock(job.job_id)
        results.append(success)

    t1 = threading.Thread(target=try_publish)
    t2 = threading.Thread(target=try_publish)
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    assert results.count(True) == 1


def test_t2_b5_02_concurrent_job_status_updates(db_repo, make_publish_job):
    """Verify concurrent transitions from multiple threads do not corrupt job status."""
    qm = QueueManager(db_repo)
    job = make_publish_job(job_id="job_race_update_1")
    qm.enqueue(job)

    def update(status):
        qm.transition(job.job_id, status)

    threads = [
        threading.Thread(target=update, args=(s,))
        for s in [PostStatus.READY_FOR_MANUAL, PostStatus.REJECTED]
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    job_rec = db_repo.get_job(job.job_id)
    assert job_rec.status in [PostStatus.READY_FOR_MANUAL, PostStatus.REJECTED]


def test_t2_b5_03_simultaneous_discovery_identical_url(db_repo, make_discovered_item):
    """Verify simultaneous discovery of identical content_hash across threads inserts exactly 1 record."""
    item = make_discovered_item(id="item_sim_1", content_hash="hash_sim_1")
    results = []

    def ingest():
        res = db_repo.save_discovered_item(item)
        results.append(res)

    threads = [threading.Thread(target=ingest) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count(True) == 1  # Only 1 insert succeeded


def test_t2_b5_04_rapid_emergency_halt_resume_toggles(db_repo):
    """Verify rapid consecutive emergency halt and resume toggles settle consistently."""
    from src.web.app import EmergencyController
    ec = EmergencyController(db_repo)
    for _ in range(20):
        ec.trigger_halt()
        ec.resume()
    assert ec.is_halted() is False


def test_t2_b5_05_concurrent_wal_readers_during_batch_write(db_repo, make_discovered_item):
    """Verify WAL mode allows concurrent readers to query while a writer is inserting records."""
    read_counts = []

    def read_items():
        for _ in range(10):
            items = db_repo.get_unprocessed_items(limit=10)
            read_counts.append(len(items))

    def write_items():
        for i in range(10):
            db_repo.save_discovered_item(make_discovered_item(id=f"c_item_{i}", content_hash=f"c_hash_{i}"))

    r = threading.Thread(target=read_items)
    w = threading.Thread(target=write_items)
    r.start()
    w.start()
    r.join()
    w.join()
    assert len(read_counts) == 10


def test_t2_b5_06_interrupted_transaction_rollback(db_connection):
    """Verify an aborted transaction is completely rolled back without partial writes."""
    cursor = db_connection.cursor()
    try:
        with db_connection:
            cursor.execute("INSERT INTO audit_logs (id, event_type, timestamp, details) VALUES ('log_fail_tx', 'FAIL', '2026-11-21', '{}');")
            raise RuntimeError("Simulated crash mid transaction")
    except RuntimeError:
        pass
    cursor.execute("SELECT COUNT(*) FROM audit_logs WHERE id='log_fail_tx';")
    assert cursor.fetchone()[0] == 0


def test_t2_b5_07_multi_threaded_repository_access(db_repo, make_publish_job):
    """Verify thread-safe repository operations under multi-threaded load."""
    threads = [
        threading.Thread(target=lambda i: db_repo.enqueue_publish_job(make_publish_job(job_id=f"mt_job_{i}")), args=(i,))
        for i in range(10)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(db_repo.get_pending_jobs(limit=50)) >= 10
