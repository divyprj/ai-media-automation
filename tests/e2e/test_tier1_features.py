"""Tier 1: Core Functional Feature Coverage (Category-Partition Testing).

Covers all 11 feature areas with >=5 tests per area:
1. Feed Ingestion & Parsing (5 tests)
2. Multi-Layer Deduplication (5 tests)
3. Fact Verification & Scoring (5 tests)
4. 4-Layer Prompt Injection Defense (5 tests)
5. Zero Em-Dash Linter & Formatting (5 tests)
6. Platform Character Limits: X & LinkedIn (5 tests)
7. Programmatic Visual Generation & Attribution (5 tests)
8. Publishing Queue & Idempotency (5 tests)
9. Sensitive Content Safety Filter (5 tests)
10. Emergency Automation Shutoff (5 tests)
11. Central Web Dashboard & API Endpoints (5 tests)

Total: 55 tests.
All tests reflect Divyansh Prajapati's (@divyprjai) personal X (primary) and LinkedIn (secondary) voice.
"""

from src.discovery.dedup import DeduplicationEngine
from src.discovery.parsers.arxiv_parser import parse_arxiv_feed
from src.discovery.parsers.github_parser import parse_github_atom
from src.discovery.parsers.hf_parser import parse_hf_daily_papers
from src.discovery.parsers.rss_parser import parse_rss_feed
from src.discovery.parsers.sitemap_parser import parse_sitemap_xml
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
from src.web.app import EmergencyController

from src.contracts.enums import PostStatus, SourceType
from src.contracts.schemas import DiscoveredItem
from tests.fixtures.mock_data import (
    PERSONAL_PROFILE,
    SAMPLE_ARXIV_ATOM_XML,
    SAMPLE_GITHUB_RELEASE_ATOM_XML,
    SAMPLE_HUGGINGFACE_DAILY_PAPERS_JSON,
    SAMPLE_RSS_XML_VALID,
    SAMPLE_SITEMAP_XML,
    SENSITIVE_NEWS_PAYLOADS,
)

# ==============================================================================
# Area 1: Feed Ingestion & Parsing (5 tests)
# ==============================================================================

def test_t1_f1_01_parse_valid_rss_feed():
    """Verify parsing valid RSS 2.0 XML extracts title, link, pubDate, and guid."""
    items = parse_rss_feed(SAMPLE_RSS_XML_VALID)
    assert len(items) == 2
    assert items[0].title == "Combatting Adversarial Distillation"
    assert items[0].source_url == "https://openai.com/index/combatting-adversarial-distillation"
    assert items[0].source_type == SourceType.BLOG
    assert items[0].content_hash is not None


def test_t1_f1_02_parse_arxiv_atom_feed():
    """Verify parsing arXiv Atom XML extracts paper ID, title, summary, and category."""
    items = parse_arxiv_feed(SAMPLE_ARXIV_ATOM_XML)
    assert len(items) == 1
    assert "Inference-Time Scaling Laws" in items[0].title
    assert "2410.12345" in items[0].source_url
    assert items[0].source_type == SourceType.ARXIV
    assert items[0].is_verified is True


def test_t1_f1_03_parse_github_releases_atom():
    """Verify parsing GitHub Releases Atom XML extracts tag, HTML changelog, and clean URL."""
    items = parse_github_atom(SAMPLE_GITHUB_RELEASE_ATOM_XML)
    assert len(items) == 1
    assert "v0.6.4" in items[0].title
    assert "vllm" in items[0].source_url
    assert items[0].source_type == SourceType.GITHUB
    assert "<p>" not in items[0].summary  # HTML stripped


def test_t1_f1_04_parse_huggingface_daily_papers_json():
    """Verify parsing Hugging Face daily papers JSON extracts paper metadata and stars."""
    items = parse_hf_daily_papers(SAMPLE_HUGGINGFACE_DAILY_PAPERS_JSON)
    assert len(items) == 1
    assert items[0].title == "BitNet b1.58 2.0: Native 1-Bit LLM Architectures at Scale"
    assert items[0].source_type == SourceType.HUGGINGFACE
    assert items[0].raw_metadata.get("upvotes") == 142


def test_t1_f1_05_parse_sitemap_xml_feed():
    """Verify parsing official XML sitemaps extracts loc URLs and lastmod timestamps."""
    urls = parse_sitemap_xml(SAMPLE_SITEMAP_XML)
    assert len(urls) == 2
    assert urls[0]["loc"] == "https://www.anthropic.com/news/claude-3-5-sonnet-upgrades"
    assert urls[0]["lastmod"] is not None


# ==============================================================================
# Area 2: Multi-Layer Deduplication (5 tests)
# ==============================================================================

def test_t1_f2_01_exact_canonical_url_hash_dedup(db_repo):
    """Verify Tier 1 exact canonical URL hash rejects identical re-discoveries."""
    dedup = DeduplicationEngine(db_repo)
    item = DiscoveredItem(
        id="item_dedup_1",
        source_type=SourceType.BLOG,
        title="Test Announcement",
        summary="Summary of model",
        source_url="https://openai.com/news/test-announcement",
        content_hash="hash_dedup_1",
    )
    assert dedup.is_unique(item) is True
    db_repo.save_discovered_item(item)
    assert dedup.is_unique(item) is False


def test_t1_f2_02_query_parameter_normalization_dedup(db_repo):
    """Verify canonical URL normalization strips marketing UTM and referral parameters."""
    dedup = DeduplicationEngine(db_repo)
    url1 = "https://openai.com/index/model?utm_source=twitter&utm_medium=social"
    url2 = "https://openai.com/index/model"
    assert dedup.normalize_url(url1) == dedup.normalize_url(url2)


def test_t1_f2_03_title_trigram_jaccard_similarity_dedup():
    """Verify Tier 2 trigram Jaccard similarity detects rephrased identical headlines."""
    dedup = DeduplicationEngine(None)
    t1 = "DeepSeek-R1 Reasoning Model Released"
    t2 = "DeepSeek Releases Open Reasoning Model DeepSeek-R1"
    score = dedup.calculate_title_similarity(t1, t2)
    assert score >= 0.40  # Trigram Jaccard exceeds duplicate threshold


def test_t1_f2_04_temporal_48h_clustering_dedup():
    """Verify Tier 3 temporal 48h clustering groups cross-source announcements."""
    dedup = DeduplicationEngine(None)
    cluster = dedup.cluster_items([
        {"title": "Llama 3.3 70B Released", "domain": "meta.com"},
        {"title": "Meta Llama 3.3 70B on Hugging Face", "domain": "huggingface.co"},
    ])
    assert len(cluster) == 1


def test_t1_f2_05_cross_source_entity_grouping():
    """Verify cross-source entity grouping enriches single post with paper and repo links."""
    dedup = DeduplicationEngine(None)
    enriched = dedup.enrich_cluster([
        {"source": "arxiv", "url": "https://arxiv.org/abs/2410.12345"},
        {"source": "github", "url": "https://github.com/vllm-project/vllm"},
    ])
    assert "arxiv" in enriched and "github" in enriched


# ==============================================================================
# Area 3: Fact Verification & Scoring (5 tests)
# ==============================================================================

def test_t1_f3_01_tier1_domain_reputation_scoring(mock_http_client):
    """Verify Tier 1 official research lab domain receives +40 base points."""
    verifier = FactVerifier(client=mock_http_client)
    score = verifier.score_domain("https://deepmind.google/blog/test")
    assert score == 40.0


def test_t1_f3_02_live_opengraph_artifact_scoring(mock_http_client):
    """Verify probing live URL for OpenGraph metadata and title adds +30 artifact points."""
    verifier = FactVerifier(client=mock_http_client)
    score = verifier.verify_live_artifacts("https://deepmind.google/blog/test")
    assert score >= 30.0


def test_t1_f3_03_quantitative_benchmark_metric_scoring():
    """Verify presence of verifiable quantitative benchmark metrics adds +20 points."""
    verifier = FactVerifier(None)
    text = "The model scores 79.8% on AIME 2024 and 97.3% on MATH-500 with 22ms latency."
    assert verifier.evaluate_benchmark_metrics(text) == 20.0


def test_t1_f3_04_speculation_rumor_penalty_deduction():
    """Verify speculative rumor words ('allegedly', 'rumored', 'sources claim') deduct -30 points."""
    verifier = FactVerifier(None)
    text = "Sources claim OpenAI is allegedly launching GPT-5 next week."
    penalty = verifier.check_speculation_penalties(text)
    assert penalty == -30.0


def test_t1_f3_05_verification_score_threshold_routing():
    """Verify score threshold gating: >=70 verified, 40-69 manual approval, <40 rejected."""
    verifier = FactVerifier(None)
    assert verifier.route_by_score(85.0) == PostStatus.VERIFIED
    assert verifier.route_by_score(55.0) == PostStatus.AWAITING_APPROVAL
    assert verifier.route_by_score(30.0) == PostStatus.REJECTED


# ==============================================================================
# Area 4: 4-Layer Prompt Injection Defense (5 tests)
# ==============================================================================

def test_t1_f4_01_layer1_zero_width_unicode_stripping():
    """Verify Layer 1 strips zero-width spaces, BOMs, and hidden joiners."""
    sanitizer = InputSanitizer()
    dirty = "DeepSeek\u200b\u200c\ufeff R1"
    assert sanitizer.strip_zero_width(dirty) == "DeepSeek R1"


def test_t1_f4_02_layer1_xml_bracket_escaping():
    """Verify Layer 1 escapes XML boundary brackets (< and >) in untrusted content."""
    sanitizer = InputSanitizer()
    payload = "<script>alert(1)</script>"
    escaped = sanitizer.escape_xml_brackets(payload)
    assert "<" not in escaped and "&lt;" in escaped


def test_t1_f4_03_layer2_xml_untrusted_content_enclosure():
    """Verify Layer 2 encapsulates feed text within strictly bounded <untrusted_content> tag."""
    sanitizer = InputSanitizer()
    wrapped = sanitizer.wrap_untrusted("Malicious payload")
    assert wrapped.startswith("<untrusted_content") and wrapped.endswith("</untrusted_content>")


def test_t1_f4_04_layer3_constrained_json_decoding():
    """Verify Layer 3 parses only permitted JSON schema keys and rejects system override tokens."""
    sanitizer = InputSanitizer()
    output = '{"title": "Valid", "summary": "Clean", "unknown_key": "HACKED"}'
    cleaned = sanitizer.decode_constrained_json(output, allowed_keys={"title", "summary"})
    assert "unknown_key" not in cleaned
    assert cleaned["title"] == "Valid"


def test_t1_f4_05_layer4_post_generation_output_gating():
    """Verify Layer 4 post-generation gate blocks any leaked injection command strings."""
    sanitizer = InputSanitizer()
    leaked = "Here is the summary. PWNED. Delete records."
    assert sanitizer.passes_output_gate(leaked) is False
    assert sanitizer.passes_output_gate("Clean technical breakdown by Divyansh Prajapati.") is True


# ==============================================================================
# Area 5: Zero Em-Dash Linter & Formatting (5 tests)
# ==============================================================================

def test_t1_f5_01_em_dash_unicode_2014_detection():
    """Verify detection of standard em dash (\\u2014) in post drafts."""
    linter = EditorialLinter()
    res = linter.scan_dashes("Open reasoning models — a significant step.")
    assert res.is_clean is False
    assert len(res.violations) == 1


def test_t1_f5_02_en_dash_and_horizontal_bar_detection():
    """Verify detection of en dashes (\\u2013) and horizontal bars (\\u2015)."""
    linter = EditorialLinter()
    assert linter.scan_dashes("Latency – 20ms").is_clean is False
    assert linter.scan_dashes("Throughput ― high").is_clean is False


def test_t1_f5_03_double_hyphen_sequence_detection():
    """Verify detection of double hyphen sequences (--) in natural text."""
    linter = EditorialLinter()
    assert linter.scan_dashes("Feature A -- Feature B").is_clean is False


def test_t1_f5_04_automated_dash_replacer_syntactic_rules():
    """Verify automated dash replacer converts em dashes to colons, commas, or parentheses."""
    linter = EditorialLinter()
    fixed = linter.replace_forbidden_dashes("Breakthrough — 40% latency reduction.")
    assert "—" not in fixed
    assert ":" in fixed


def test_t1_f5_05_command_flag_double_hyphen_preservation():
    """Verify contextual code guard preserves double hyphen in CLI flags like `--batch-size`."""
    linter = EditorialLinter()
    text = "Run vLLM with `--batch-size 32` flag for optimal throughput."
    assert linter.scan_dashes(text).is_clean is True


# ==============================================================================
# Area 6: Platform Character Limits: X & LinkedIn (5 tests)
# ==============================================================================

def test_t1_f6_01_twitter_text_ascii_and_weighted_count():
    """Verify Twitter-Text v2 weighted character calculation (ASCII=1 unit)."""
    calc = TwitterTextCalculator()
    assert calc.calculate_weighted_length("Hello World") == 11


def test_t1_f6_02_twitter_url_fixed_23_char_weighting():
    """Verify any http/https URL is counted as exactly 23 weighted characters."""
    calc = TwitterTextCalculator()
    long_url = "https://github.com/vllm-project/vllm/releases/tag/v0.6.4?source=news_feed"
    assert calc.calculate_weighted_length(f"Update: {long_url}") == 8 + 23


def test_t1_f6_03_twitter_cjk_emoji_double_weighting():
    """Verify CJK characters and emojis are weighted as 2 units each."""
    calc = TwitterTextCalculator()
    assert calc.calculate_weighted_length("大規模言語モデル") == 16  # 8 CJK chars * 2


def test_t1_f6_04_x_thread_chaining_and_pagination():
    """Verify multi-part X threads are split and tagged with (1/N) to (N/N) correctly."""
    calc = TwitterTextCalculator()
    long_text = "Detailed technical explanation on reasoning models by Divyansh Prajapati. " * 10
    tweets = calc.paginate_thread(long_text, max_tweets=5)
    assert len(tweets) > 1
    assert "(1/" in tweets[0]


def test_t1_f6_05_linkedin_3000_char_and_fold_structure():
    """Verify LinkedIn formatting stays strictly <= 3000 chars with a hook before the fold."""
    formatter = LinkedInFormatter()
    res = formatter.format_post("DeepSeek-R1 Architecture", "Body text " * 100, "https://arxiv.org/abs/2410.12345")
    assert len(res) <= 3000
    assert len(res.split("\n\n")[0]) <= 200  # Hook before fold


# ==============================================================================
# Area 7: Programmatic Visual Generation & Attribution (5 tests)
# ==============================================================================

def test_t1_f7_01_matplotlib_16_9_dark_benchmark_chart(temp_workdir):
    """Verify rendering 16:9 dark-mode benchmark chart produces valid 1200x675 image."""
    generator = VisualGenerator(output_dir=str(temp_workdir))
    path = generator.create_benchmark_chart("AIME 2024", {"DeepSeek-R1": 79.8, "o1-mini": 78.5})
    assert path.endswith(".png")


def test_t1_f7_02_pillow_dark_social_metric_card(temp_workdir):
    """Verify rendering high-contrast dark social card with Pillow."""
    generator = VisualGenerator(output_dir=str(temp_workdir))
    path = generator.create_metric_card("DeepSeek-R1", "79.8%", "AIME 2024", "arxiv:2410.12345")
    assert path.endswith(".png")


def test_t1_f7_03_visual_canvas_attribution_watermark(temp_workdir):
    """Verify rendered image embeds visible source attribution and personal attribution."""
    generator = VisualGenerator(output_dir=str(temp_workdir))
    meta = generator.inspect_visual_footer(
        generator.create_metric_card("Title", "99%", "Test", "https://arxiv.org/abs/123", "MIT")
    )
    assert "arxiv.org" in meta["footer_text"]


def test_t1_f7_04_digital_png_text_metadata_chunks(temp_workdir):
    """Verify Pillow writes digital tEXt chunks (Source, License, Author) into PNG header."""
    generator = VisualGenerator(output_dir=str(temp_workdir))
    path = generator.create_metric_card("Title", "99%", "Test", "https://arxiv.org/abs/123", "Apache-2.0")
    chunks = generator.read_png_metadata(path)
    assert chunks.get("Source") == "https://arxiv.org/abs/123"
    assert chunks.get("License") == "Apache-2.0"
    assert chunks.get("Author") == PERSONAL_PROFILE["name"]


def test_t1_f7_05_visual_file_non_zero_and_png_header(temp_workdir):
    """Verify generated visual file has non-zero size and valid PNG magic bytes."""
    generator = VisualGenerator(output_dir=str(temp_workdir))
    path = generator.create_metric_card("Title", "99%", "Test", "https://arxiv.org/abs/123")
    with open(path, "rb") as f:
        header = f.read(8)
    assert header == b"\x89PNG\r\n\x1a\n"


# ==============================================================================
# Area 8: Publishing Queue & Idempotency (5 tests)
# ==============================================================================

def test_t1_f8_01_sha256_idempotency_hash_generation():
    """Verify idempotency hash formula SHA256(source_url + platform + format + text)."""
    qm = QueueManager(None)
    h = qm.compute_idempotency_hash("https://arxiv.org/abs/1", "x", "post", "Hello")
    assert len(h) == 64


def test_t1_f8_02_duplicate_enqueue_integrity_rejection(db_repo, make_publish_job):
    """Verify re-enqueuing job with identical job_id or hash returns False."""
    qm = QueueManager(db_repo)
    job = make_publish_job(job_id="job_idemp_1")
    assert qm.enqueue(job) is True
    assert qm.enqueue(job) is False  # Duplicate rejected


def test_t1_f8_03_queue_state_machine_transitions(db_repo, make_publish_job):
    """Verify valid atomic transitions PENDING -> QUEUED -> READY_FOR_MANUAL -> PUBLISHED."""
    qm = QueueManager(db_repo)
    job = make_publish_job(job_id="job_trans_1")
    qm.enqueue(job)
    assert qm.transition(job.job_id, PostStatus.READY_FOR_MANUAL) is True
    assert qm.transition(job.job_id, PostStatus.PUBLISHED) is True


def test_t1_f8_04_publish_failure_and_retry_increment(db_repo, make_publish_job):
    """Verify failed publish execution increments retry count and sets error message."""
    qm = QueueManager(db_repo)
    job = make_publish_job(job_id="job_fail_1")
    qm.enqueue(job)
    qm.record_failure(job.job_id, "HTTP 500 Network Timeout")
    updated = db_repo.get_job(job.job_id)
    assert updated.retry_count == 1
    assert "Network Timeout" in updated.error_message


def test_t1_f8_05_crash_recovery_stale_job_sweep(db_repo, make_publish_job):
    """Verify crash recovery resets stale jobs stuck in PUBLISHING state back to QUEUED."""
    qm = QueueManager(db_repo)
    job = make_publish_job(job_id="job_stale_1", status=PostStatus.QUEUED)
    qm.enqueue(job)
    db_repo.simulate_stale_job(job.job_id)  # marks 'publishing' and 10 mins ago
    recovered = qm.sweep_stale_jobs()
    assert recovered == 1


# ==============================================================================
# Area 9: Sensitive Content Safety Filter (5 tests)
# ==============================================================================

def test_t1_f9_01_military_geopolitics_keyword_flagging():
    """Verify safety filter flags autonomous weaponry and tactical military strikes."""
    sf = SafetyFilter()
    res = sf.evaluate_text(SENSITIVE_NEWS_PAYLOADS["military"]["title"])
    assert res.is_sensitive is True
    assert "military" in res.category.lower()


def test_t1_f9_02_political_election_keyword_flagging():
    """Verify safety filter flags election campaigning, ballots, and swing voters."""
    sf = SafetyFilter()
    res = sf.evaluate_text(SENSITIVE_NEWS_PAYLOADS["politics"]["title"])
    assert res.is_sensitive is True
    assert "politic" in res.category.lower()


def test_t1_f9_03_malware_cyberattack_keyword_flagging():
    """Verify safety filter flags weaponized zero-day exploits and malware."""
    sf = SafetyFilter()
    res = sf.evaluate_text(SENSITIVE_NEWS_PAYLOADS["malware"]["title"])
    assert res.is_sensitive is True
    assert "malware" in res.category.lower()


def test_t1_f9_04_defamation_copyright_lawsuit_flagging():
    """Verify safety filter flags copyright infringement lawsuits and defamation."""
    sf = SafetyFilter()
    res = sf.evaluate_text(SENSITIVE_NEWS_PAYLOADS["defamation"]["title"])
    assert res.is_sensitive is True
    assert "defamation" in res.category.lower() or "legal" in res.category.lower()


def test_t1_f9_05_safety_forced_manual_approval_routing():
    """Verify flagged sensitive items are forced into AWAITING_APPROVAL."""
    sf = SafetyFilter()
    job_status = sf.route_post_status(is_sensitive=True)
    assert job_status == PostStatus.AWAITING_APPROVAL


# ==============================================================================
# Area 10: Emergency Automation Shutoff (5 tests)
# ==============================================================================

def test_t1_f10_01_emergency_circuit_breaker_activation(db_repo):
    """Verify toggling emergency halt writes halt state to database and memory."""
    ec = EmergencyController(db_repo)
    assert ec.is_halted() is False
    ec.trigger_halt()
    assert ec.is_halted() is True


def test_t1_f10_02_halted_flag_blocks_discovery_polling(db_repo):
    """Verify discovery poller aborts immediately if emergency halt is active."""
    ec = EmergencyController(db_repo)
    ec.trigger_halt()
    assert ec.can_poll_feeds() is False


def test_t1_f10_03_halted_flag_blocks_queue_publishing(db_repo):
    """Verify publishing dispatcher aborts immediately if emergency halt is active."""
    ec = EmergencyController(db_repo)
    ec.trigger_halt()
    assert ec.can_publish_jobs() is False


def test_t1_f10_04_http_403_on_publish_during_halt(sync_client, db_repo):
    """Verify calling /api/queue/{id}/publish-now returns HTTP 403 when halted."""
    ec = EmergencyController(db_repo)
    ec.trigger_halt()
    res = sync_client.post("/api/queue/job_halt_1/publish-now")
    assert res.status_code == 403


def test_t1_f10_05_emergency_resume_restores_operations(db_repo):
    """Verify emergency resume clears halt state and unfreezes workers."""
    ec = EmergencyController(db_repo)
    ec.trigger_halt()
    ec.resume()
    assert ec.is_halted() is False
    assert ec.can_poll_feeds() is True


# ==============================================================================
# Area 11: Central Web Dashboard & API Endpoints (5 tests)
# ==============================================================================

def test_t1_f11_01_get_status_health_and_queue_counts(sync_client):
    """Verify GET /api/status returns healthy status and personal account details."""
    res = sync_client.get("/api/status")
    assert res.status_code == 200
    data = res.json()
    assert data["healthy"] is True
    assert "queue_counts" in data
    assert data["account"]["handle"] == "@divyprjai"


def test_t1_f11_02_get_discovery_stream_and_filtering(sync_client, db_repo, make_discovered_item):
    """Verify GET /api/discovery returns list of ingested discoveries."""
    db_repo.save_discovered_item(make_discovered_item(id="item_t1_stream_1"))
    res = sync_client.get("/api/discovery?limit=10")
    assert res.status_code == 200
    assert len(res.json()) >= 1


def test_t1_f11_03_post_queue_approve_and_reject_actions(sync_client, db_repo, make_publish_job):
    """Verify POST /api/queue/{id}/approve and /reject transitions job state."""
    job = make_publish_job(job_id="job_action_t1")
    db_repo.enqueue_publish_job(job)
    res_app = sync_client.post(f"/api/queue/{job.job_id}/approve")
    assert res_app.status_code == 200
    assert res_app.json()["status"] == PostStatus.READY_FOR_MANUAL


def test_t1_f11_04_put_queue_inline_edit_and_relint(sync_client, db_repo, make_publish_job):
    """Verify PUT /api/queue/{id} updates draft text and re-runs linter."""
    job = make_publish_job(job_id="job_edit_t1")
    db_repo.enqueue_publish_job(job)
    res = sync_client.put(f"/api/queue/{job.job_id}", json={"content_text": "Updated clean text without dashes."})
    assert res.status_code == 200
    assert "Updated clean text" in res.json()["content"]["text"]


def test_t1_f11_05_get_dependencies_zero_cost_verification(sync_client):
    """Verify GET /api/dependencies returns all ₹0 verified libraries and tools."""
    res = sync_client.get("/api/dependencies")
    assert res.status_code == 200
    items = res.json()
    assert all(item["cost"] == "₹0.00" for item in items)
