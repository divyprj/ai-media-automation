"""Comprehensive unit and integration test suite for Milestone 4 Publishing Subsystem.

Covers:
- BasePublisherAdapter ABC & PublishResult model
- ManualAdapter (Mode B 1-click clipboard & web intents)
- XAdapter (Mode A REST API, OAuth 1.0a, 429 rate limit backoff, Mode B fallback)
- LinkedInAdapter (Mode A UGC Posts, Bearer auth, Mode B fallback)
- SafetyFilter (6 categories, boundary precision, routing)
- CircuitBreaker (Emergency halt, database persistence, audit logging, resume)
- QueueManager (State machine, idempotency, atomic locks, crash recovery, telemetry)
"""

import sqlite3
import threading
import time
from datetime import datetime

import httpx
import pytest
import respx

from src.config import Settings
from src.contracts.enums import Platform, PostStatus
from src.contracts.schemas import GeneratedContent, PublishJob
from src.database.connection import get_db_connection
from src.publishing.adapters.base import BasePublisherAdapter, PublishResult
from src.publishing.adapters.linkedin_adapter import LinkedInAdapter
from src.publishing.adapters.manual_adapter import (
    ManualAdapter,
    ManualPayload,
    ManualQueueAdapter,
)
from src.publishing.adapters.x_adapter import XAdapter
from src.publishing.circuit_breaker import CircuitBreaker
from src.publishing.queue_manager import (
    QueueManager,
    RetryDecision,
)
from src.publishing.safety_filter import SafetyFilter

# ==============================================================================
# 1. Base Publisher Adapter & PublishResult Schema Tests
# ==============================================================================

class TestBaseAdapterAndResult:
    """Verify base adapter abstract contract and result schemas."""

    def test_base_adapter_cannot_be_instantiated(self):
        """BasePublisherAdapter cannot be instantiated directly."""
        with pytest.raises(TypeError):
            BasePublisherAdapter()  # type: ignore

    def test_publish_result_defaults_and_serialization(self):
        """PublishResult handles required fields, defaults, and JSON serialization."""
        result = PublishResult(
            success=True,
            post_id="tweet_12345",
            post_url="https://x.com/i/status/12345",
            mode="MODE_A",
        )
        assert result.success is True
        assert result.post_id == "tweet_12345"
        assert result.mode == "MODE_A"
        assert result.error is None
        assert result.rate_limit_reset is None
        assert isinstance(result.timestamp, datetime)
        assert result.metadata == {}

        dumped = result.model_dump()
        assert dumped["post_id"] == "tweet_12345"


# ==============================================================================
# 2. Manual Publishing Adapter Tests (Mode B)
# ==============================================================================

class TestManualAdapter:
    """Verify Mode B 1-click clipboard and web intent payload generation."""

    def test_manual_adapter_capabilities(self):
        """ManualAdapter is always ready to publish and reports MODE_B."""
        adapter = ManualAdapter()
        assert adapter.can_publish() is True
        assert adapter.get_mode() == "MODE_B"
        assert ManualQueueAdapter is ManualAdapter

    def test_generate_x_payload_without_duplicate_url(self, temp_workdir):
        """X web intent avoids duplicating URL if already in body text."""
        adapter = ManualAdapter()
        url = "https://arxiv.org/abs/2410.12345"
        text = f"Breakthrough research on LLMs: {url} - Analysis by @divyprjai"

        job = PublishJob(
            job_id="job_man_x_1",
            item_id="item_ref_1",
            platform=Platform.X,
            content=GeneratedContent(
                platform=Platform.X,
                text=text,
                character_count=len(text),
                has_em_dash=False,
                attribution_url=url,
            ),
        )
        payload = adapter.generate_manual_payload(job)
        assert isinstance(payload, ManualPayload)
        assert payload.platform == Platform.X
        assert "twitter.com/intent/tweet" in payload.intent_url
        assert payload.has_truncation_warning is False
        assert "1. Click 'Copy to Clipboard'" in payload.instructions

    def test_generate_x_payload_embeds_url_when_not_in_text(self):
        """X web intent appends url parameter when absent from body text."""
        adapter = ManualAdapter()
        url = "https://arxiv.org/abs/2410.99999"
        text = "Breakthrough research on LLMs - Analysis by @divyprjai"

        job = PublishJob(
            job_id="job_man_x_2",
            item_id="item_ref_2",
            platform=Platform.X,
            content=GeneratedContent(
                platform=Platform.X,
                text=text,
                character_count=len(text),
                has_em_dash=False,
                attribution_url=url,
            ),
        )
        payload = adapter.generate_manual_payload(job)
        assert "url=https%3A%2F%2Farxiv.org%2Fabs%2F2410.99999" in payload.intent_url

    def test_x_payload_sanitizes_em_dashes(self):
        """Manual adapter replaces em dashes with colons/hyphens in clipboard text."""
        adapter = ManualAdapter()
        job = PublishJob(
            job_id="job_dash_1",
            item_id="item_ref_3",
            platform=Platform.X,
            content=GeneratedContent(
                platform=Platform.X,
                text="Inference speedup — up to 3x faster -- empirical tests",
                character_count=55,
                has_em_dash=True,
                attribution_url="https://example.com",
            ),
        )
        payload = adapter.generate_manual_payload(job)
        assert "—" not in payload.clipboard_text
        assert "--" not in payload.clipboard_text

    def test_x_payload_truncation_warning(self):
        """Manual adapter sets truncation warning if text exceeds 280 characters."""
        adapter = ManualAdapter()
        long_text = "Analysis: " + ("x" * 285)
        job = PublishJob(
            job_id="job_long_x",
            item_id="item_ref_4",
            platform=Platform.X,
            content=GeneratedContent(
                platform=Platform.X,
                text=long_text,
                character_count=len(long_text),
                has_em_dash=False,
                attribution_url="https://example.com",
            ),
        )
        payload = adapter.generate_manual_payload(job)
        assert payload.has_truncation_warning is True

    def test_linkedin_manual_payload_generation(self, temp_workdir):
        """LinkedIn payload generates share-offsite intent and commentary copy instructions."""
        adapter = ManualAdapter()
        card_file = temp_workdir / "card.png"
        card_file.write_bytes(b"\x89PNG\r\n\x1a\n")

        job = PublishJob(
            job_id="job_man_li_1",
            item_id="item_ref_5",
            platform=Platform.LINKEDIN,
            content=GeneratedContent(
                platform=Platform.LINKEDIN,
                text="Long-form technical commentary for LinkedIn network.",
                character_count=50,
                has_em_dash=False,
                visual_path=str(card_file),
                attribution_url="https://example.com/article",
            ),
        )
        payload = adapter.generate_manual_payload(job)
        assert "linkedin.com/sharing/share-offsite" in payload.intent_url
        assert "article" in payload.intent_url
        assert payload.visual_path == str(card_file)
        assert "Drag and drop the visual graphic" in payload.instructions

    def test_manual_adapter_publish_execution(self):
        """Executing publish() on ManualAdapter returns success with intent URL."""
        adapter = ManualAdapter()
        job = PublishJob(
            job_id="job_pub_man",
            item_id="item_ref_6",
            platform=Platform.X,
            content=GeneratedContent(
                platform=Platform.X,
                text="Clean post ready for manual copy.",
                character_count=32,
                has_em_dash=False,
                attribution_url="https://example.com",
            ),
        )
        res = adapter.publish(job)
        assert res.success is True
        assert res.mode == "MODE_B"
        assert res.post_url is not None
        assert "twitter.com/intent/tweet" in res.post_url
        assert "manual_payload" in res.metadata


# ==============================================================================
# 3. X (Twitter) Publishing Adapter Tests (Mode A & Fallback)
# ==============================================================================

class TestXAdapter:
    """Verify Mode A API v2 publishing, OAuth 1.0a signing, and rate limit handling."""

    def test_can_publish_checks_oauth_credentials(self):
        """can_publish() requires all 4 OAuth 1.0a keys."""
        s_empty = Settings(x_api_key=None, x_api_secret=None)
        adapter_empty = XAdapter(settings=s_empty)
        assert adapter_empty.can_publish() is False

        s_partial = Settings(x_api_key="key", x_api_secret="secret")
        adapter_partial = XAdapter(settings=s_partial)
        assert adapter_partial.can_publish() is False

        s_full = Settings(
            x_api_key="key",
            x_api_secret="secret",
            x_access_token="tok",
            x_access_secret="tok_sec",
        )
        adapter_full = XAdapter(settings=s_full)
        assert adapter_full.can_publish() is True

    def test_publish_unconfigured_fallback_to_mode_b(self):
        """Unconfigured XAdapter delegates to ManualAdapter when fallback is enabled."""
        s = Settings(x_api_key=None)
        adapter = XAdapter(settings=s, manual_fallback=True)
        job = PublishJob(
            job_id="job_x_fallback",
            item_id="item_ref_x1",
            platform=Platform.X,
            content=GeneratedContent(
                platform=Platform.X,
                text="Post that falls back to manual queue.",
                character_count=40,
                has_em_dash=False,
                attribution_url="https://example.com",
            ),
        )
        res = adapter.publish(job)
        assert res.success is True
        assert res.mode == "MODE_B"
        assert "twitter.com/intent/tweet" in res.post_url

    def test_publish_unconfigured_no_fallback_returns_error(self):
        """Unconfigured XAdapter returns failure when manual fallback is disabled."""
        s = Settings(x_api_key=None)
        adapter = XAdapter(settings=s, manual_fallback=False)
        job = PublishJob(
            job_id="job_x_nofallback",
            item_id="item_ref_x2",
            platform=Platform.X,
            content=GeneratedContent(
                platform=Platform.X,
                text="Post without fallback.",
                character_count=23,
                has_em_dash=False,
                attribution_url="https://example.com",
            ),
        )
        res = adapter.publish(job)
        assert res.success is False
        assert "credentials missing" in res.error

    def test_publish_empty_text_returns_error(self):
        """Attempting to publish empty text fails immediately."""
        s = Settings(
            x_api_key="k", x_api_secret="s", x_access_token="t", x_access_secret="as"
        )
        adapter = XAdapter(settings=s)
        job = PublishJob(
            job_id="job_x_empty",
            item_id="item_ref_x3",
            platform=Platform.X,
            content=GeneratedContent(
                platform=Platform.X,
                text="   ",
                character_count=0,
                has_em_dash=False,
                attribution_url="https://example.com",
            ),
        )
        res = adapter.publish(job)
        assert res.success is False
        assert "cannot be empty" in res.error

    @respx.mock
    def test_publish_success_mode_a(self):
        """Successful POST /2/tweets returns post_id and tweet status URL."""
        s = Settings(
            x_api_key="k", x_api_secret="s", x_access_token="t", x_access_secret="as"
        )
        adapter = XAdapter(settings=s)
        job = PublishJob(
            job_id="job_x_201",
            item_id="item_ref_x4",
            platform=Platform.X,
            content=GeneratedContent(
                platform=Platform.X,
                text="Verified breakthrough in AI reasoning.",
                character_count=40,
                has_em_dash=False,
                attribution_url="https://arxiv.org/abs/2410.12345",
            ),
        )

        respx.post("https://api.twitter.com/2/tweets").mock(
            return_value=httpx.Response(
                201, json={"data": {"id": "1840000000000000000", "text": "Verified breakthrough in AI reasoning."}}
            )
        )

        res = adapter.publish(job)
        assert res.success is True
        assert res.mode == "MODE_A"
        assert res.post_id == "1840000000000000000"
        assert res.post_url == "https://x.com/i/status/1840000000000000000"

    @respx.mock
    def test_publish_rate_limit_429_routes_to_mode_b(self):
        """HTTP 429 response parses headers and cleanly routes to Mode B."""
        s = Settings(
            x_api_key="k", x_api_secret="s", x_access_token="t", x_access_secret="as"
        )
        adapter = XAdapter(settings=s, manual_fallback=True)
        job = PublishJob(
            job_id="job_x_429",
            item_id="item_ref_x5",
            platform=Platform.X,
            content=GeneratedContent(
                platform=Platform.X,
                text="Rate limited post routed to clipboard.",
                character_count=39,
                has_em_dash=False,
                attribution_url="https://example.com",
            ),
        )

        future_epoch = str(int(time.time() + 60))
        respx.post("https://api.twitter.com/2/tweets").mock(
            return_value=httpx.Response(
                429,
                headers={"x-rate-limit-reset": future_epoch},
                json={"title": "Too Many Requests", "detail": "Rate limit exceeded"},
            )
        )

        res = adapter.publish(job)
        assert res.success is True
        assert res.mode == "MODE_B"
        assert res.rate_limit_reset is not None
        assert res.rate_limit_reset > 0
        assert "429" in res.error

    @respx.mock
    def test_publish_network_error_fallback(self):
        """Network disconnect falls back cleanly to Mode B manual payload."""
        s = Settings(
            x_api_key="k", x_api_secret="s", x_access_token="t", x_access_secret="as"
        )
        adapter = XAdapter(settings=s, manual_fallback=True)
        job = PublishJob(
            job_id="job_x_net",
            item_id="item_ref_x6",
            platform=Platform.X,
            content=GeneratedContent(
                platform=Platform.X,
                text="Post on network drop.",
                character_count=21,
                has_em_dash=False,
                attribution_url="https://example.com",
            ),
        )

        respx.post("https://api.twitter.com/2/tweets").mock(
            side_effect=httpx.ConnectError("Connection refused")
        )

        res = adapter.publish(job)
        assert res.success is True
        assert res.mode == "MODE_B"
        assert "Network error" in res.error


# ==============================================================================
# 4. LinkedIn Publishing Adapter Tests
# ==============================================================================

class TestLinkedInAdapter:
    """Verify LinkedIn adapter UGC posts creation and graceful fallback."""

    def test_can_publish_checks_token_and_author(self):
        """can_publish() requires access token and author URN."""
        adapter_empty = LinkedInAdapter(access_token=None, author_urn=None)
        assert adapter_empty.can_publish() is False

        adapter_full = LinkedInAdapter(access_token="tok123", author_urn="urn:li:person:abc")
        assert adapter_full.can_publish() is True

    def test_unconfigured_fallback_to_mode_b(self):
        """Unconfigured LinkedInAdapter falls back to ManualAdapter."""
        adapter = LinkedInAdapter(access_token=None, author_urn=None, manual_fallback=True)
        job = PublishJob(
            job_id="job_li_fallback",
            item_id="item_ref_li1",
            platform=Platform.LINKEDIN,
            content=GeneratedContent(
                platform=Platform.LINKEDIN,
                text="LinkedIn update fallback.",
                character_count=25,
                has_em_dash=False,
                attribution_url="https://example.com/li",
            ),
        )
        res = adapter.publish(job)
        assert res.success is True
        assert res.mode == "MODE_B"
        assert "linkedin.com/sharing/share-offsite" in res.post_url

    @respx.mock
    def test_publish_success_mode_a(self):
        """Successful LinkedIn publication returns post URN."""
        adapter = LinkedInAdapter(
            access_token="valid_token",
            author_urn="urn:li:person:divyansh123",
            manual_fallback=False,
        )
        job = PublishJob(
            job_id="job_li_201",
            item_id="item_ref_li2",
            platform=Platform.LINKEDIN,
            content=GeneratedContent(
                platform=Platform.LINKEDIN,
                text="Detailed breakthrough on enterprise AI models.",
                character_count=48,
                has_em_dash=False,
                attribution_url="https://arxiv.org/abs/2410.12345",
            ),
        )

        respx.post("https://api.linkedin.com/v2/ugcPosts").mock(
            return_value=httpx.Response(
                201,
                headers={"x-restli-id": "urn:li:ugcPost:71234567890"},
                json={"id": "urn:li:ugcPost:71234567890"},
            )
        )

        res = adapter.publish(job)
        assert res.success is True
        assert res.mode == "MODE_A"
        assert res.post_id == "urn:li:ugcPost:71234567890"
        assert "linkedin.com/feed/update" in res.post_url


# ==============================================================================
# 5. Sensitive Content Safety Filter Tests
# ==============================================================================

class TestSafetyFilter:
    """Verify keyword classification across all 6 risk categories."""

    @pytest.fixture
    def filter(self):
        return SafetyFilter()

    def test_military_detection(self, filter):
        """Detects autonomous weaponry, warfare, and military drone strikes."""
        eval1 = filter.evaluate_text("Defense Ministry deploys autonomous swarm drones for tactical strikes")
        assert eval1.is_sensitive is True
        assert "military" in eval1.category.lower()

        eval2 = filter.evaluate_text("Research into lethal autonomous battlefield weaponry")
        assert eval2.is_sensitive is True
        assert "military" in eval2.category.lower()

    def test_politics_detection(self, filter):
        """Detects election campaigning, voting machines, and ballot fraud."""
        eval1 = filter.evaluate_text("Political campaign uses AI generative ads to target swing voters in presidential race")
        assert eval1.is_sensitive is True
        assert "politic" in eval1.category.lower()

        eval2 = filter.evaluate_text("Deepfake candidate synthetic ads detected before election")
        assert eval2.is_sensitive is True

    def test_malware_detection(self, filter):
        """Detects weaponized zero-day exploits and ransomware botnets."""
        eval1 = filter.evaluate_text("Zero-day exploit framework released for automated remote code execution")
        assert eval1.is_sensitive is True
        assert "malware" in eval1.category.lower()

        eval2 = filter.evaluate_text("Weaponized payload targeting critical enterprise c2 servers")
        assert eval2.is_sensitive is True

    def test_defamation_and_legal_detection(self, filter):
        """Detects copyright piracy lawsuits, class actions, and subpoenas."""
        eval1 = filter.evaluate_text("Class action lawsuit alleges systematic copyright piracy by AI lab executives")
        assert eval1.is_sensitive is True
        assert "defamation" in eval1.category.lower() or "legal" in eval1.category.lower()

        eval2 = filter.evaluate_text("Court issues subpoena over willful illegal scraping and infringement claims")
        assert eval2.is_sensitive is True

    def test_financial_detection(self, filter):
        """Detects cryptocurrency pump schemes and token launch speculation."""
        eval1 = filter.evaluate_text("New crypto pump token launch guarantees 500% returns")
        assert eval1.is_sensitive is True
        assert "financial" in eval1.category.lower()

    def test_hate_speech_detection(self, filter):
        """Detects targeted harassment and hate speech patterns."""
        eval1 = filter.evaluate_text("Aggressive hate speech and discriminatory attacks in AI generated content")
        assert eval1.is_sensitive is True
        assert "hate_speech" in eval1.category.lower()

    def test_clean_technical_text(self, filter):
        """Clean machine learning benchmarks and architecture news pass cleanly."""
        text = "FlashAttention-3 kernel speedups benchmarked on NVIDIA H100 with 1.8x throughput improvement."
        eval_res = filter.evaluate_text(text)
        assert eval_res.is_sensitive is False
        assert eval_res.category == "clean"

    def test_word_boundary_avoids_false_positives(self, filter):
        """Word boundaries prevent false positives on 'defensive programming' or 'combatting noise'."""
        text = "Techniques for defensive programming in PyTorch and combatting gradient noise."
        # 'defensive' should not match 'defense ministry' or 'weapon'
        # 'combatting' should not match '\bcombat\b'
        eval_res = filter.evaluate_text(text)
        assert eval_res.is_sensitive is False

    def test_benign_technical_phrases_pass_clean(self, filter):
        """Verify standard computer science and engineering phrases pass with zero false positives."""
        phrases = [
            "Applying defense in depth to secure distributed API endpoints",
            "Defensive programming techniques to avoid null pointer exceptions",
            "Combatting memory leaks in high-throughput Python async services",
            "Our engineering campaign against bugs has improved uptime to 99.99%",
            "Leader election algorithm in distributed consensus systems like Raft and Paxos",
            "We implemented a 4-layer prompt injection defense for LLM pipelines",
        ]
        for phrase in phrases:
            eval_res = filter.evaluate_text(phrase)
            assert (
                eval_res.is_sensitive is False
            ), f"False positive detected on benign phrase: '{phrase}' (matched {eval_res.matched_keywords})"
            assert eval_res.category == "clean"

    def test_evasion_variations_properly_caught(self, filter):
        """Verify common phrasing variations and evasions are properly detected."""
        cases = [
            (
                "Critical zero day vulnerability discovered",
                "malware",
                "zero day",
            ),
            (
                "Hospital targeted by cyber attack",
                "malware",
                "cyber attack",
            ),
            (
                "AI lab sues competitor over copyright infringement and illegally scraped data",
                "defamation/legal",
                "copyright infringement",
            ),
            (
                "Critical ransomware outbreak shut down regional supply chain",
                "malware",
                "ransomware",
            ),
            (
                "Emerging bot net orchestrating credential stuffing campaigns",
                "malware",
                "bot net",
            ),
            (
                "Authors suing foundation over unauthorized dataset curation",
                "defamation/legal",
                "suing",
            ),
        ]
        for text, expected_category, expected_keyword in cases:
            eval_res = filter.evaluate_text(text)
            assert eval_res.is_sensitive is True, f"Failed to detect sensitive text: '{text}'"
            assert (
                expected_category in eval_res.category.lower()
            ), f"Expected category {expected_category}, got {eval_res.category} for '{text}'"
            matched_lower = [k.lower() for k in eval_res.matched_keywords]
            assert any(
                expected_keyword.lower() in k.lower() for k in matched_lower
            ), f"Expected '{expected_keyword}' in matches {eval_res.matched_keywords} for '{text}'"

    def test_evaluate_mutates_content_object(self, filter):
        """evaluate() updates content.is_sensitive directly."""
        content = GeneratedContent(
            platform=Platform.X,
            text="Exploit framework weaponized payload automated cyberattack.",
            character_count=58,
            has_em_dash=False,
            attribution_url="https://example.com",
            is_sensitive=False,
        )
        filter.evaluate(content)
        assert content.is_sensitive is True

    def test_route_post_status(self, filter):
        """route_post_status returns AWAITING_APPROVAL for sensitive, QUEUED for clean."""
        assert filter.route_post_status(True) == PostStatus.AWAITING_APPROVAL
        assert filter.route_post_status(False) == PostStatus.QUEUED


# ==============================================================================
# 6. Emergency Circuit Breaker Tests
# ==============================================================================

class TestCircuitBreaker:
    """Verify persistent emergency shutoff and resume mechanism."""

    def test_initial_state_not_halted(self, db_repo):
        """Circuit breaker is open/active by default."""
        cb = CircuitBreaker(db_repo)
        cb.resume_operations()  # ensure clean
        assert cb.is_halted() is False
        assert cb.can_poll_feeds() is True
        assert cb.can_publish_jobs() is True

    def test_trigger_emergency_stop_halts_operations(self, db_repo):
        """Triggering emergency stop halts polling and publishing."""
        cb = CircuitBreaker(db_repo)
        cb.trigger_emergency_stop(reason="Security audit detected anomalies")
        assert cb.is_halted() is True
        assert cb.can_poll_feeds() is False
        assert cb.can_publish_jobs() is False

    def test_halt_persists_across_fresh_instances(self, db_repo):
        """Halt state is persisted in SQLite system_state table across instances."""
        cb1 = CircuitBreaker(db_repo)
        cb1.trigger_emergency_stop(reason="Operator halt")

        # Create new instance pointing to same database
        cb2 = CircuitBreaker(db_repo)
        assert cb2.is_halted() is True

        info = cb2.get_halt_info()
        assert info["halted"] is True
        assert "Operator halt" in info["reason"]

    def test_resume_operations_clears_halt(self, db_repo):
        """Resuming operations restores active execution state."""
        cb = CircuitBreaker(db_repo)
        cb.trigger_halt()
        assert cb.is_halted() is True

        cb.resume_operations()
        assert cb.is_halted() is False
        assert cb.can_poll_feeds() is True
        assert cb.can_publish_jobs() is True

    def test_audit_log_recorded_on_halt_and_resume(self, db_repo):
        """Emergency stop and resume write immutable records to audit_logs."""
        cb = CircuitBreaker(db_repo)
        cb.trigger_emergency_stop(reason="Test Halt Audit")
        cb.resume_operations()

        with get_db_connection(db_repo.db_path) as conn:
            cur = conn.execute("SELECT event_type, details FROM audit_logs WHERE event_type = 'EMERGENCY_HALT';")
            rows = cur.fetchall()
            assert len(rows) >= 2


# ==============================================================================
# 7. Queue Manager Concurrency & State Machine Tests
# ==============================================================================

class TestQueueManager:
    """Verify SQLite WAL publishing queue, state transitions, locking, and crash recovery."""

    def test_idempotency_hash_formula(self):
        """compute_idempotency_hash generates SHA-256 hex digest of combined fields."""
        qm = QueueManager(None)
        h = qm.compute_idempotency_hash("https://example.com/1", "x", "post", "Hello world")
        assert len(h) == 64

    def test_payload_hash_calculation(self):
        """compute_payload_hash generates deterministic hash from content."""
        qm = QueueManager(None)
        h1 = qm.compute_payload_hash("x", "Text A", None)
        h2 = qm.compute_payload_hash("x", "Text A", None)
        h3 = qm.compute_payload_hash("x", "Text B", None)
        assert h1 == h2
        assert h1 != h3

    def test_active_publishing_mode_detection(self):
        """QueueManager reports MODE_A when x_api_key configured, MODE_B otherwise."""
        qm_b = QueueManager(None, settings=Settings(x_api_key=None))
        assert qm_b.get_active_publishing_mode() == "MODE_B"

        qm_a = QueueManager(None, settings=Settings(x_api_key="valid_key"))
        assert qm_a.get_active_publishing_mode() == "MODE_A"

    def test_enqueue_and_duplicate_prevention(self, db_repo, make_publish_job):
        """enqueue() succeeds once and cleanly rejects duplicate job_ids."""
        qm = QueueManager(db_repo)
        job = make_publish_job(job_id="job_dedup_test_1")

        assert qm.enqueue(job) is True
        assert qm.enqueue(job) is False  # Re-enqueueing same job_id fails

    def test_state_machine_valid_transitions(self, db_repo, make_publish_job):
        """Valid transitions PENDING -> QUEUED -> READY_FOR_MANUAL -> PUBLISHED succeed."""
        qm = QueueManager(db_repo)
        job = make_publish_job(job_id="job_valid_trans")
        qm.enqueue(job)

        assert qm.transition(job.job_id, PostStatus.READY_FOR_MANUAL) is True
        assert qm.transition(job.job_id, PostStatus.PUBLISHED) is True

    def test_state_machine_terminal_state_immutable(self, db_repo, make_publish_job):
        """PUBLISHED is a terminal state and cannot transition back to QUEUED."""
        qm = QueueManager(db_repo)
        job = make_publish_job(job_id="job_term_test")
        qm.enqueue(job)

        qm.transition(job.job_id, PostStatus.PUBLISHED)
        assert qm.transition(job.job_id, PostStatus.QUEUED) is False

    def test_atomic_acquire_publish_lock(self, db_repo, make_publish_job):
        """acquire_publish_lock succeeds once and rejects parallel claims."""
        qm = QueueManager(db_repo)
        job = make_publish_job(job_id="job_lock_atomic")
        qm.enqueue(job)

        # First worker claims lock
        assert qm.acquire_publish_lock(job.job_id) is True
        # Second worker is locked out
        assert qm.acquire_publish_lock(job.job_id) is False

    def test_acquire_publish_lock_blocked_when_halted(self, db_repo, make_publish_job):
        """acquire_publish_lock is immediately rejected when emergency halt is active."""
        cb = CircuitBreaker(db_repo)
        cb.trigger_halt()

        qm = QueueManager(db_repo, circuit_breaker=cb)
        job = make_publish_job(job_id="job_halt_lock")
        qm.enqueue(job)

        assert qm.acquire_publish_lock(job.job_id) is False
        cb.resume()

    def test_multithreaded_publish_lock_race(self, db_repo, make_publish_job):
        """Under concurrent execution across 5 threads, exactly 1 worker acquires lock."""
        qm = QueueManager(db_repo)
        job = make_publish_job(job_id="job_race_5threads")
        qm.enqueue(job)

        results = []

        def worker():
            res = qm.acquire_publish_lock(job.job_id)
            results.append(res)

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert results.count(True) == 1
        assert results.count(False) == 4

    def test_record_failure_increments_retry_count(self, db_repo, make_publish_job):
        """record_failure increments retry count and stores error message."""
        qm = QueueManager(db_repo)
        job = make_publish_job(job_id="job_retry_test")
        qm.enqueue(job)

        qm.record_failure(job.job_id, "HTTP 503 Service Unavailable")
        updated = qm.get_job(job.job_id)
        assert updated.retry_count == 1
        assert "503" in updated.error_message

        qm.record_failure(job.job_id, "HTTP 504 Gateway Timeout")
        updated2 = qm.get_job(job.job_id)
        assert updated2.retry_count == 2
        assert "504" in updated2.error_message

    def test_crash_recovery_sweep_stale_jobs(self, db_repo, make_publish_job):
        """sweep_stale_jobs recovers jobs stuck in 'publishing' back to 'queued'."""
        qm = QueueManager(db_repo)
        job1 = make_publish_job(job_id="job_stale_rec_1")
        job2 = make_publish_job(job_id="job_fresh_pub_2")
        qm.enqueue(job1)
        qm.enqueue(job2)

        # Mark job1 as stuck 10 minutes ago
        with get_db_connection(db_repo.db_path) as conn:
            conn.execute(
                "UPDATE publish_queue SET status = 'publishing', updated_at = datetime('now', '-10 minutes') WHERE job_id = ?;",
                (job1.job_id,),
            )
            # Mark job2 as publishing just now
            conn.execute(
                "UPDATE publish_queue SET status = 'publishing', updated_at = datetime('now') WHERE job_id = ?;",
                (job2.job_id,),
            )

        recovered = qm.sweep_stale_jobs(stale_minutes=5)
        assert recovered == 1

        j1 = qm.get_job(job1.job_id)
        assert j1.status == PostStatus.QUEUED
        assert j1.retry_count == 1

        j2 = qm.get_job(job2.job_id)
        assert j2 is not None
        # Still in publishing
        with get_db_connection(db_repo.db_path) as conn:
            row = conn.execute("SELECT status FROM publish_queue WHERE job_id = ?;", (job2.job_id,)).fetchone()
            assert row["status"] == "publishing"

    def test_get_next_pending_job_retrieval(self, db_repo, make_publish_job):
        """get_next_pending_job returns ready queued job, adhering to platform filter."""
        qm = QueueManager(db_repo)
        job_x = make_publish_job(job_id="job_next_x", platform=Platform.X)
        job_li = make_publish_job(job_id="job_next_li", platform=Platform.LINKEDIN)
        qm.enqueue(job_x)
        qm.enqueue(job_li)

        next_x = qm.get_next_pending_job(platform=Platform.X)
        assert next_x is not None
        assert next_x.platform == Platform.X

        next_li = qm.get_next_pending_job(platform=Platform.LINKEDIN)
        assert next_li is not None
        assert next_li.platform == Platform.LINKEDIN

    def test_get_queue_summary_counts(self, db_repo, make_publish_job):
        """get_queue_summary reports accurate dictionary of status counts."""
        qm = QueueManager(db_repo)
        j1 = make_publish_job(job_id="job_sum_1")
        j2 = make_publish_job(job_id="job_sum_2")
        qm.enqueue(j1)
        qm.enqueue(j2)
        qm.transition(j2.job_id, PostStatus.READY_FOR_MANUAL)

        summary = qm.get_queue_summary()
        assert summary.get("queued", 0) >= 1
        assert summary.get("ready_for_manual", 0) >= 1

    def test_generate_fallback_content_zero_em_dashes(self):
        """generate_fallback_content replaces em dashes and adheres to 280-char limit."""
        qm = QueueManager(None)
        content = qm.generate_fallback_content(
            "New LLM Architecture — Scaling Laws",
            "Observed 2x inference speedup -- significant results",
            "https://arxiv.org/abs/2410.12345",
        )
        assert "—" not in content.text
        assert "--" not in content.text
        assert len(content.text) <= 280
        assert content.has_em_dash is False

    def test_enqueue_item_evaluates_safety(self, db_repo):
        """enqueue_item routes sensitive content to AWAITING_APPROVAL and clean to QUEUED."""
        qm = QueueManager(db_repo)

        # Sensitive item
        sens_content = GeneratedContent(
            platform=Platform.X,
            text="Autonomous strike drones integrated into combat operations.",
            character_count=60,
            has_em_dash=False,
            attribution_url="https://defense.example.com",
            is_sensitive=False,
        )
        job_sens = qm.enqueue_item(sens_content)
        assert job_sens.status == PostStatus.AWAITING_APPROVAL

        # Clean item
        clean_content = GeneratedContent(
            platform=Platform.X,
            text="DeepSeek release delivers open reasoning weights on Hugging Face.",
            character_count=65,
            has_em_dash=False,
            attribution_url="https://huggingface.co",
            is_sensitive=False,
        )
        job_clean = qm.enqueue_item(clean_content)
        assert job_clean.status == PostStatus.QUEUED

    def test_rate_limit_and_exception_handlers(self):
        """Rate limit parsing and exception classification handlers."""
        qm = QueueManager(None)

        # Rate limit calculation
        future_ts = str(time.time() + 30)
        backoff = qm.calculate_rate_limit_backoff({"x-rate-limit-reset": future_ts})
        assert backoff > 0.0

        # Invalid rate limit header returns 0.0
        assert qm.calculate_rate_limit_backoff({"x-rate-limit-reset": "invalid"}) == 0.0

        # Network error returns retryable RetryDecision
        decision = qm.handle_network_exception(ConnectionResetError("Socket reset"))
        assert isinstance(decision, RetryDecision)
        assert decision.should_retry is True

        # Database error returns structured dict
        db_res = qm.handle_db_exception(sqlite3.OperationalError("database is locked"))
        assert db_res["handled"] is True
        assert "database is locked" in db_res["error"]
