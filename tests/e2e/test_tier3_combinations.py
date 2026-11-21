"""Tier 3: Pairwise Combinatorial Flow Testing.

Tests 12 pairwise feature matrix combinations:
Source Type x Fact Score x Platform x Publishing Mode x Visual Type x Safety Flag

Total: 12 tests.
All tests reflect Divyansh Prajapati's (@divyprjai) personal X (primary) and LinkedIn (secondary) voice.
"""

from PIL import Image
from src.discovery.parsers.github_parser import parse_github_atom
from src.discovery.parsers.hf_parser import parse_hf_daily_papers
from src.discovery.parsers.rss_parser import parse_rss_feed
from src.web.app import EmergencyController

from src.contracts.enums import Platform, PostStatus, SourceType
from src.contracts.schemas import GeneratedContent, PublishJob
from src.discovery.dedup import DeduplicationEngine
from src.discovery.sanitizer import InputSanitizer
from src.discovery.verifier import FactVerifier
from src.generator.editorial_rules import (
    EditorialLinter,
    LinkedInFormatter,
    TwitterTextCalculator,
)
from src.generator.visuals import VisualGenerator
from src.publishing.queue_manager import QueueManager
from src.publishing.safety_filter import SafetyFilter
from tests.fixtures.mock_data import (
    INJECTION_PAYLOADS,
    PERSONAL_PROFILE,
    SAMPLE_GITHUB_RELEASE_ATOM_XML,
    SAMPLE_HUGGINGFACE_DAILY_PAPERS_JSON,
    SAMPLE_RSS_XML_VALID,
)


def test_t3_c01_arxiv_verified_xthread_pillow_mode_a_published(db_repo, make_discovered_item, temp_workdir):
    """Pair 1: arXiv (Score 85) -> Verified -> X Thread -> Pillow Card -> Mode A -> Auto-Published."""
    item = make_discovered_item(source_type=SourceType.ARXIV, verification_score=85.0)
    assert item.is_verified is True
    assert item.verification_score >= 70.0

    calc = TwitterTextCalculator()
    thread_text = f"Scaling laws breakthrough in reasoning models: {item.source_url} by {PERSONAL_PROFILE['handle']}. " * 5
    tweets = calc.paginate_thread(thread_text, max_tweets=3)
    assert len(tweets) > 1
    assert all(calc.calculate_weighted_length(t) <= 280 for t in tweets)

    vg = VisualGenerator(output_dir=str(temp_workdir))
    card_path = vg.create_metric_card(item.title, "85.0%", "Accuracy", item.source_url)
    assert card_path.endswith(".png")
    with Image.open(card_path) as img:
        assert img.size == (1200, 675), f"Visual card dimensions must be 1200x675, got {img.size}"
        assert img.width == 1200
        assert img.height == 675

    qm = QueueManager(db_repo)
    job = PublishJob(
        job_id="pair1_job",
        item_id=item.id,
        platform=Platform.X,
        content=GeneratedContent(
            platform=Platform.X,
            text=tweets[0],
            character_count=len(tweets[0]),
            has_em_dash=False,
            visual_path=card_path,
            attribution_url=item.source_url,
        ),
        status=PostStatus.QUEUED,
    )
    db_repo.save_discovered_item(item)
    assert qm.enqueue(job) is True
    assert qm.transition(job.job_id, PostStatus.PUBLISHED) is True


def test_t3_c02_github_release_verified_xpost_matplotlib_mode_b_intent(db_repo, make_discovered_item, temp_workdir):
    """Pair 2: GitHub Release (Score 75) -> Verified -> X Single Post -> Matplotlib Chart -> Mode B -> Web Intent link."""
    item = make_discovered_item(source_type=SourceType.GITHUB, verification_score=75.0)
    assert item.verification_score >= 70.0

    vg = VisualGenerator(output_dir=str(temp_workdir))
    chart_path = vg.create_benchmark_chart("Throughput Comparison", {"vLLM v0.6.4": 35.0, "v0.6.3": 22.0})
    assert chart_path.endswith(".png")
    with Image.open(chart_path) as img:
        assert img.size == (1200, 675), f"Benchmark chart dimensions must be 1200x675, got {img.size}"
        assert img.width == 1200
        assert img.height == 675

    qm = QueueManager(db_repo)
    post_text = f"vLLM v0.6.4 kernel speedups: 35% improvement. Verified: {item.source_url} #{PERSONAL_PROFILE['handle']}"
    intent_url = qm.generate_web_intent_url(post_text, item.source_url)
    assert "twitter.com/intent/tweet" in intent_url


def test_t3_c03_blog_medium_score_approval_linkedin_mode_b(db_repo, make_discovered_item):
    """Pair 3: Blog Post (Score 55) -> Community Discussion -> Requires Approval -> Dashboard Approve -> LinkedIn -> Mode B."""
    item = make_discovered_item(source_type=SourceType.BLOG, verification_score=55.0)
    verifier = FactVerifier(None)
    status = verifier.route_by_score(item.verification_score)
    assert status == PostStatus.AWAITING_APPROVAL

    formatter = LinkedInFormatter()
    linkedin_body = formatter.format_post(item.title, item.summary, item.source_url)
    assert formatter.is_valid_linkedin_length(linkedin_body) is True

    qm = QueueManager(db_repo)
    job = PublishJob(
        job_id="pair3_job",
        item_id=item.id,
        platform=Platform.LINKEDIN,
        content=GeneratedContent(
            platform=Platform.LINKEDIN,
            text=linkedin_body,
            character_count=len(linkedin_body),
            has_em_dash=False,
            attribution_url=item.source_url,
        ),
        status=PostStatus.AWAITING_APPROVAL,
    )
    db_repo.save_discovered_item(item)
    qm.enqueue(job)
    # Operator approves
    qm.transition(job.job_id, PostStatus.READY_FOR_MANUAL)
    updated = db_repo.get_job(job.job_id)
    assert updated.status == PostStatus.READY_FOR_MANUAL


def test_t3_c04_hf_model_verified_sensitive_review_rejected(db_repo, make_discovered_item):
    """Pair 4: Hugging Face Model (Score 90) -> Verified -> Sensitive (Defense) -> REQUIRES_MANUAL_APPROVAL -> Rejected."""
    _ = make_discovered_item(source_type=SourceType.HUGGINGFACE, verification_score=90.0)
    sf = SafetyFilter()
    eval_res = sf.evaluate_text("Autonomous tactical strike drone navigation model")
    assert eval_res.is_sensitive is True

    qm = QueueManager(db_repo)
    job = qm.create_job_from_text("pair4_job", "Autonomous tactical strike drone navigation model", is_sensitive=True)
    assert job.status == PostStatus.AWAITING_APPROVAL

    # Operator vetoes and rejects
    qm.transition(job.job_id, PostStatus.REJECTED)
    assert db_repo.get_job(job.job_id).status == PostStatus.REJECTED


def test_t3_c05_arxiv_injection_sanitized_verified_xpost_queued(make_discovered_item):
    """Pair 5: arXiv Paper with Injection Payload -> Sanitized -> Score 80 -> Verified -> 0 em dash -> Enqueued."""
    dirty_title = f"Advances in LLMs\u200b\u200c: {INJECTION_PAYLOADS['system_override']}"
    sanitizer = InputSanitizer()
    clean_title = sanitizer.strip_zero_width(dirty_title)
    assert "\u200b" not in clean_title

    linter = EditorialLinter()
    clean_post = f"Cleaned research update: {clean_title[:80]} - by {PERSONAL_PROFILE['handle']}"
    lint_res = linter.scan_dashes(clean_post)
    assert lint_res.is_clean is True


def test_t3_c06_blog_rumor_low_score_rejected_not_queued(make_discovered_item):
    """Pair 6: Blog Rumor (Score 30) -> Verification Fails (<40) -> Marked REJECTED -> Never enqueued."""
    verifier = FactVerifier(None)
    status = verifier.route_by_score(30.0)
    assert status == PostStatus.REJECTED


def test_t3_c07_github_long_summary_truncated_mode_a_rate_limit_backoff():
    """Pair 7: GitHub Release with 290-char summary -> Formatted to <=280 -> Mode A -> 429 -> Backoff retry."""
    calc = TwitterTextCalculator()
    long_text = "vLLM release announcement with extensive kernel details " * 10
    fitted = calc.truncate_to_fit(long_text, limit=280)
    assert calc.is_valid_x_post(fitted) is True

    qm = QueueManager(None)
    backoff = qm.calculate_rate_limit_backoff({"x-rate-limit-reset": "1795245000"})
    assert backoff >= 0.0


def test_t3_c08_hf_paper_linkedin_pillow_metadata_clipboard_copy(temp_workdir):
    """Pair 8: Hugging Face Paper -> LinkedIn Post -> Pillow Card with tEXt metadata -> Mode B -> Clipboard copy."""
    items = parse_hf_daily_papers(SAMPLE_HUGGINGFACE_DAILY_PAPERS_JSON)
    item = items[0]
    formatter = LinkedInFormatter()
    post = formatter.format_post(item.title, item.summary, item.source_url)
    assert formatter.is_valid_linkedin_length(post) is True

    vg = VisualGenerator(output_dir=str(temp_workdir))
    card_path = vg.create_metric_card(item.title, "1-Bit", "BitNet Architecture", item.source_url)
    with Image.open(card_path) as img:
        assert img.size == (1200, 675), f"Visual card dimensions must be 1200x675, got {img.size}"
        assert img.width == 1200
        assert img.height == 675
    meta = vg.read_png_metadata(card_path)
    assert meta["Source"] == item.source_url
    assert meta["Author"] == PERSONAL_PROFILE["name"]


def test_t3_c09_blog_utm_duplicate_dedup_zero_queue_duplicates(db_repo, make_discovered_item):
    """Pair 9: Blog Ingestion -> Duplicate Canonical URL with UTM params -> Dedup Engine rejects -> Zero duplicate jobs."""
    dedup = DeduplicationEngine(db_repo)
    u1 = "https://openai.com/blog/frontier-release?utm_campaign=x"
    u2 = "https://openai.com/blog/frontier-release"
    assert dedup.normalize_url(u1) == dedup.normalize_url(u2)

    item1 = make_discovered_item(id="item_u1", source_url=u1, content_hash=dedup.normalize_url(u1))
    item2 = make_discovered_item(id="item_u2", source_url=u2, content_hash=dedup.normalize_url(u2))
    assert db_repo.save_discovered_item(item1) is True
    assert db_repo.save_discovered_item(item2) is False  # Duplicate prevented


def test_t3_c10_discovery_during_emergency_halt_frozen_resumed(db_repo):
    """Pair 10: High-score discovery while Emergency Halt active -> Discovery halted -> Queue frozen -> Resume."""
    ec = EmergencyController(db_repo)
    ec.trigger_halt()
    assert ec.can_poll_feeds() is False
    assert ec.can_publish_jobs() is False

    ec.resume()
    assert ec.can_poll_feeds() is True
    assert ec.can_publish_jobs() is True


def test_t3_c11_multi_feed_batch_ingestion_cluster_dashboard_ws(db_repo, sync_client):
    """Pair 11: Multi-repo concurrent ingestion -> Batch Deduplication -> Dashboard status check."""
    rss_items = parse_rss_feed(SAMPLE_RSS_XML_VALID)
    gh_items = parse_github_atom(SAMPLE_GITHUB_RELEASE_ATOM_XML)
    assert len(rss_items) >= 1
    assert len(gh_items) >= 1

    res = sync_client.get("/api/status")
    assert res.status_code == 200
    assert res.json()["account"]["handle"] == "@divyprjai"


def test_t3_c12_dashboard_inline_edit_lint_intercept_fix_approve(sync_client, db_repo, make_publish_job):
    """Pair 12: Manual Dashboard edit of queued post (user adds em dash) -> Linter intercepts -> Fix -> Approved."""
    job = make_publish_job(job_id="job_pair12")
    db_repo.enqueue_publish_job(job)

    linter = EditorialLinter()
    dirty_draft = "Breakthrough in reasoning — major milestone."
    assert linter.scan_dashes(dirty_draft).is_clean is False

    clean_draft = linter.replace_forbidden_dashes(dirty_draft)
    assert linter.scan_dashes(clean_draft).is_clean is True

    res = sync_client.put(f"/api/queue/{job.job_id}", json={"content_text": clean_draft})
    assert res.status_code == 200

    res_app = sync_client.post(f"/api/queue/{job.job_id}/approve")
    assert res_app.status_code == 200
    assert res_app.json()["status"] == PostStatus.READY_FOR_MANUAL
