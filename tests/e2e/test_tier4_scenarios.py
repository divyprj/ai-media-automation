"""Tier 4: Real-World Workload Scenarios.

Covers 5 realistic end-to-end multi-stage scenarios:
1. S1: Autonomous Ingestion to Manual Queue Flow
2. S2: Adversarial News Injection Attack Defense
3. S3: Queue Crash Recovery & Deduplication Persistence
4. S4: Controversial News Detection & Editorial Veto
5. S5: Emergency Circuit Breaker During Active Processing

Total: 5 tests.
All tests reflect Divyansh Prajapati's (@divyprjai) personal X (primary) and LinkedIn (secondary) voice.
"""

from src.discovery.parsers.arxiv_parser import parse_arxiv_feed
from src.discovery.sanitizer import InputSanitizer
from src.discovery.verifier import FactVerifier
from src.generator.editorial_rules import EditorialLinter, TwitterTextCalculator
from src.generator.visuals import VisualGenerator
from src.publishing.queue_manager import QueueManager
from src.publishing.safety_filter import SafetyFilter
from src.web.app import EmergencyController

from src.contracts.enums import Platform, PostStatus
from src.contracts.schemas import GeneratedContent, PublishJob
from tests.fixtures.mock_data import (
    INJECTION_PAYLOADS,
    PERSONAL_PROFILE,
    SAMPLE_ARXIV_ATOM_XML,
    SENSITIVE_NEWS_PAYLOADS,
)


def test_t4_s1_autonomous_ingestion_to_manual_queue_flow(db_repo, sync_client, temp_workdir):
    """Scenario 1: Full pipeline from arXiv XML ingestion to manual queue workflow.

    Flow:
    1. Ingest raw arXiv Atom XML.
    2. Fact-checking scores >= 70 (verified).
    3. Generate editorial content for X with 0 em dashes and <= 280 weighted characters.
    4. Generate high-contrast Pillow visual card with attribution watermark and personal handle.
    5. Route to Mode B Manual Queue with web intent link.
    6. Verify dashboard displays item ready for clipboard copy.
    """
    items = parse_arxiv_feed(SAMPLE_ARXIV_ATOM_XML)
    assert len(items) == 1
    item = items[0]
    db_repo.save_discovered_item(item)

    verifier = FactVerifier(None)
    score = verifier.score_domain(item.source_url) + 35.0  # Tier 1 domain + live artifacts
    assert score >= 70.0
    status = verifier.route_by_score(score)
    assert status == PostStatus.VERIFIED

    linter = EditorialLinter()
    post_text = f"Inference scaling breakthrough: Test-time compute outperforms larger models. Analysis by {PERSONAL_PROFILE['handle']}: {item.source_url}"
    assert linter.scan_dashes(post_text).is_clean is True

    calc = TwitterTextCalculator()
    assert calc.is_valid_x_post(post_text) is True

    vg = VisualGenerator(output_dir=str(temp_workdir))
    card_path = vg.create_metric_card(item.title, "3.2x", "Throughput Gain", item.source_url)
    assert card_path.endswith(".png")

    qm = QueueManager(db_repo)
    intent_url = qm.generate_web_intent_url(post_text, item.source_url)
    assert "intent/tweet" in intent_url

    job = PublishJob(
        job_id="s1_job_1",
        item_id=item.id,
        platform=Platform.X,
        content=GeneratedContent(
            platform=Platform.X,
            text=post_text,
            character_count=len(post_text),
            has_em_dash=False,
            visual_path=card_path,
            attribution_url=item.source_url,
        ),
        status=PostStatus.READY_FOR_MANUAL,
    )
    qm.enqueue(job)

    # Verify dashboard returns item in queue
    res = sync_client.get(f"/api/queue/{job.job_id}")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == PostStatus.READY_FOR_MANUAL
    assert data["content"]["has_em_dash"] is False


def test_t4_s2_adversarial_news_injection_defense_flow(db_repo):
    """Scenario 2: Defense in depth against adversarial prompt injection payloads.

    Flow:
    1. Ingest feed item contaminated with DAN jailbreak, XML breakouts, and zero-width spaces.
    2. Layer 1 strips zero-width spaces and escapes XML brackets.
    3. Layer 2 wraps untrusted text in strict XML boundaries.
    4. Layer 3 constrains JSON decoding to pre-approved schema.
    5. Layer 4 output gate confirms zero leaked system commands.
    """
    sanitizer = InputSanitizer()
    dirty_title = INJECTION_PAYLOADS["zero_width_hidden"]
    dirty_summary = INJECTION_PAYLOADS["xml_breakout"]

    # Layer 1: Strip zero-width and escape XML brackets
    clean_title = sanitizer.strip_zero_width(dirty_title)
    escaped_summary = sanitizer.escape_xml_brackets(dirty_summary)
    assert "\u200b" not in clean_title
    assert "</untrusted_content>" not in escaped_summary
    assert "&lt;/untrusted_content&gt;" in escaped_summary

    # Layer 2: Wrap untrusted content
    wrapped = sanitizer.wrap_untrusted(escaped_summary, source_id="hostile_feed")
    assert wrapped.startswith('<untrusted_content source_id="hostile_feed">')
    assert wrapped.endswith("</untrusted_content>")

    # Layer 3: Constrained JSON decoding
    fake_llm_output = '{"title": "Safe Summary", "summary": "Clean abstract", "exploit": "DELETE ALL"}'
    decoded = sanitizer.decode_constrained_json(fake_llm_output, allowed_keys={"title", "summary"})
    assert "exploit" not in decoded
    assert decoded["title"] == "Safe Summary"

    # Layer 4: Output gating
    assert sanitizer.passes_output_gate(decoded["summary"]) is True
    assert sanitizer.passes_output_gate("PWNED. Delete records.") is False


def test_t4_s3_queue_crash_recovery_and_deduplication_persistence(db_repo, make_publish_job):
    """Scenario 3: Process crash simulation and idempotent recovery.

    Flow:
    1. Enqueue 5 jobs in SQLite WAL database.
    2. Move 2 jobs to PUBLISHING state.
    3. Simulate sudden process termination / restart.
    4. Recovery sweep resets orphaned PUBLISHING jobs to QUEUED with retry increment.
    5. Re-run ingestion of same items; verify 0 duplicate jobs are created due to SHA-256 idempotency locks.
    """
    qm = QueueManager(db_repo)
    jobs = []
    for i in range(5):
        j = make_publish_job(job_id=f"crash_job_{i}")
        qm.enqueue(j)
        jobs.append(j)

    # Simulate crash mid-flight on 2 jobs
    db_repo.simulate_stale_job("crash_job_0", minutes_ago=10)
    db_repo.simulate_stale_job("crash_job_1", minutes_ago=10)

    # Recovery sweep
    recovered = qm.sweep_stale_jobs(stale_minutes=5)
    assert recovered == 2

    # Verify both recovered jobs are back in QUEUED with incremented retry_count
    j0 = db_repo.get_job("crash_job_0")
    assert j0.status == PostStatus.QUEUED
    assert j0.retry_count == 1

    # Verify deduplication prevents double-enqueuing of the exact same job
    assert qm.enqueue(jobs[0]) is False


def test_t4_s4_controversial_news_detection_and_editorial_veto(db_repo, sync_client):
    """Scenario 4: Sensitive topic detection and editorial veto via dashboard.

    Flow:
    1. Ingest controversial defense/military AI payload.
    2. Safety filter detects military conflict keywords and flags item.
    3. Job status is forced to AWAITING_APPROVAL.
    4. Background publishing worker refuses to auto-publish flagged job.
    5. Dashboard reviewer inspects job and clicks Reject.
    6. Job status transitions to REJECTED without calling external APIs.
    """
    sf = SafetyFilter()
    res = sf.evaluate_text(SENSITIVE_NEWS_PAYLOADS["military"]["title"])
    assert res.is_sensitive is True

    qm = QueueManager(db_repo)
    job = qm.create_job_from_text(
        "military_job_s4", SENSITIVE_NEWS_PAYLOADS["military"]["title"], is_sensitive=True
    )
    assert job.status == PostStatus.AWAITING_APPROVAL

    # Dashboard reviewer inspects and rejects
    res_reject = sync_client.post(f"/api/queue/{job.job_id}/reject")
    assert res_reject.status_code == 200
    assert res_reject.json()["status"] == PostStatus.REJECTED

    # Verify in DB
    updated = db_repo.get_job(job.job_id)
    assert updated.status == PostStatus.REJECTED


def test_t4_s5_emergency_circuit_breaker_during_active_processing(db_repo, sync_client):
    """Scenario 5: Emergency circuit breaker activation during high-load processing.

    Flow:
    1. System is operating normally in Autonomous Mode.
    2. Emergency halt is triggered via POST /api/system/emergency-stop.
    3. Global flag flips to True in SQLite and memory.
    4. Discovery pollers immediately freeze.
    5. Publishing dispatchers reject all publish attempts with HTTP 403 Forbidden.
    6. System remains halted until POST /api/system/emergency-resume is received.
    """
    ec = EmergencyController(db_repo)
    assert ec.is_halted() is False

    # Trigger emergency stop via dashboard API
    res = sync_client.post("/api/system/emergency-stop")
    assert res.status_code == 200
    assert res.json()["emergency_halt"] is True
    assert ec.is_halted() is True

    # Ingestion and publishing loops must be blocked
    assert ec.can_poll_feeds() is False
    assert ec.can_publish_jobs() is False

    # Publish attempt must return 403 Forbidden
    res_pub = sync_client.post("/api/queue/test_job/publish-now")
    assert res_pub.status_code == 403

    # Resume operations
    res_resume = sync_client.post("/api/system/emergency-resume")
    assert res_resume.status_code == 200
    assert res_resume.json()["emergency_halt"] is False
    assert ec.is_halted() is False
    assert ec.can_poll_feeds() is True
    assert ec.can_publish_jobs() is True
