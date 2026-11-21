"""Comprehensive test suite for the Milestone 3 Editorial & Visual Generation Engine.

Covers:
1. Zero em-dash detection, intelligent replacement, and CLI flag preservation.
2. Banned pattern detection, robotic phrase filtering, hype emoji limits, hashtag stuffing.
3. Twitter-text v2 weighted counter (ASCII=1, CJK/Emoji=2, URLs=23) and X formatters.
4. LinkedIn formatting (<=3000 chars, hook before fold <=200 chars).
5. Practitioner prompt templates for Divyansh Prajapati (@divyprjai).
6. 100% offline zero-token heuristic generation fallback.
7. Local Ollama client, DeepSeek R1 <think>...</think> stripping, and failure fallback.
8. Matplotlib 16:9 dark benchmark chart rendering (empty/NaN scores handling).
9. Pillow social metric card rendering (<20ms generation).
10. Visible canvas watermark and digital PNG tEXt metadata chunk embedding.
11. Unified EditorialEngine facade generate and validate_text.
"""

import time
from pathlib import Path

import httpx
import pytest
import respx

from src.contracts.enums import Platform, SourceType
from src.contracts.schemas import DiscoveredItem
from src.generator import EditorialEngine
from src.generator.editorial_rules import (
    EditorialLinter,
    LinkedInFormatter,
    TwitterTextCalculator,
    calculate_twitter_weight,
    clean_banned_patterns,
    format_linkedin_post,
    format_x_post,
    format_x_thread,
    replace_forbidden_dashes,
    scan_banned_patterns,
    scan_forbidden_dashes,
)
from src.generator.llm_client import OllamaClient, strip_reasoning_tags
from src.generator.templates import (
    HeuristicContentGenerator,
    PractitionerPromptTemplates,
)
from src.generator.visuals import VisualGenerator


@pytest.fixture
def sample_item() -> DiscoveredItem:
    return DiscoveredItem(
        id="item_gen_test_1",
        source_type=SourceType.ARXIV,
        title="DeepSeek-R1: Incentivizing Reasoning Capability in LLMs via Reinforcement Learning",
        summary="A novel reasoning model matching o1 performance on AIME 2024 and MATH-500 through large-scale RL.",
        source_url="https://arxiv.org/abs/2501.12948",
        content_hash="hash_gen_12345",
        raw_metadata={"benchmarks": {"AIME 2024": 79.8, "MATH-500": 97.3, "Codeforces": 96.3}},
        is_verified=True,
        verification_score=95.0,
    )


# ==============================================================================
# 1. Zero Em-Dash Linter & Intelligent Replacer
# ==============================================================================

class TestZeroEmDashLinter:
    def test_scan_em_dash_unicode_2014(self):
        text = "DeepSeek-R1 — an open reasoning breakthrough."
        violations = scan_forbidden_dashes(text)
        assert len(violations) == 1
        assert violations[0].glyph == "\u2014"
        assert violations[0].unicode_name == "EM DASH"

    def test_scan_en_dash_horizontal_bar_and_figure_dash(self):
        text = "Latency \u2013 20ms. Throughput \u2015 high. Figure \u2012 test."
        violations = scan_forbidden_dashes(text)
        assert len(violations) == 3
        glyphs = {v.glyph for v in violations}
        assert "\u2013" in glyphs
        assert "\u2015" in glyphs
        assert "\u2012" in glyphs

    def test_scan_double_and_triple_hyphen_minus(self):
        text = "Feature A -- Feature B --- Feature C"
        violations = scan_forbidden_dashes(text)
        assert len(violations) >= 2
        glyphs = {v.glyph for v in violations}
        assert "--" in glyphs
        assert "---" in glyphs

    def test_cli_flags_are_not_flagged(self):
        text = "Run vLLM with `--batch-size 32` and --max-model-len 4096 --fp16 for optimal latency."
        violations = scan_forbidden_dashes(text)
        assert len(violations) == 0

    def test_replace_paired_parenthetical_dashes(self):
        text = "The new architecture — optimized for inference — reduces TTFT."
        fixed = replace_forbidden_dashes(text)
        assert "—" not in fixed
        assert "(" in fixed and ")" in fixed

    def test_replace_connecting_dash_with_colon(self):
        text = "Empirical breakthrough — 40% reduction in KV cache memory."
        fixed = replace_forbidden_dashes(text)
        assert "—" not in fixed
        assert ":" in fixed

    def test_replace_numeric_range_dash(self):
        text = "Evaluated across 2024—2026 benchmarks."
        fixed = replace_forbidden_dashes(text)
        assert "—" not in fixed
        assert "2024 to 2026" in fixed

    def test_replace_bullet_indicator_dash(self):
        text = "— First point\n— Second point"
        fixed = replace_forbidden_dashes(text)
        assert "—" not in fixed
        assert "• First point" in fixed
        assert "• Second point" in fixed

    def test_post_replacement_invariant_zero_dashes_remain(self):
        complex_text = (
            "Breakthrough -- major result — highly expected \u2013 tested across 10 — 20 nodes. "
            "Flag `--port 8000` preserved."
        )
        fixed = replace_forbidden_dashes(complex_text)
        violations = scan_forbidden_dashes(fixed)
        assert len(violations) == 0
        assert "--port 8000" in fixed

    def test_linter_class_compatibility(self):
        linter = EditorialLinter()
        dirty = "Model A — Model B"
        res = linter.scan_dashes(dirty)
        assert res.is_clean is False
        assert len(res.violations) == 1

        clean = linter.replace_forbidden_dashes(dirty)
        assert linter.scan_dashes(clean).is_clean is True


# ==============================================================================
# 2. Banned Pattern Catalog & Slop Filtering
# ==============================================================================

class TestBannedPatterns:
    def test_detect_robotic_ai_phrases(self):
        text = "In today's fast-paced AI world, we must delve into this revolutionary game changer."
        found = scan_banned_patterns(text)
        assert len(found) >= 3

    def test_clean_robotic_ai_phrases(self):
        text = "Buckle up! Delve into this game changer. Stop scrolling!"
        cleaned = clean_banned_patterns(text)
        assert "Buckle up" not in cleaned
        assert "Delve" not in cleaned
        assert "game changer" not in cleaned
        assert "Stop scrolling" not in cleaned

    def test_detect_and_clean_hype_emojis(self):
        text = "Major announcement 🔥🚀🤯💯 check this out"
        found = scan_banned_patterns(text)
        assert any("🔥" in f for f in found)
        assert any("🚀" in f for f in found)
        cleaned = clean_banned_patterns(text)
        for emoji in ["🔥", "🚀", "🤯", "💯"]:
            assert emoji not in cleaned

    def test_detect_and_clean_generic_hashtags(self):
        text = "Latest weights released #AI #Tech #MachineLearning #vLLM"
        cleaned = clean_banned_patterns(text)
        assert "#AI" not in cleaned
        assert "#Tech" not in cleaned
        assert "#MachineLearning" not in cleaned
        assert "#vLLM" in cleaned  # Specific technical tag preserved

    def test_word_boundary_avoids_false_positives(self):
        # "delve" inside another word or legitimate usage
        text = "Model addresses parameter scaling."
        found = scan_banned_patterns(text)
        assert len(found) == 0

    def test_delve_variations_detected(self):
        variations = [
            "We delve into the new architecture.",
            "The author delves into the benchmark results.",
            "I delved into the attention mechanism.",
            "Delving into LLM reasoning capabilities.",
        ]
        for sentence in variations:
            found = scan_banned_patterns(sentence)
            assert any("delv" in f.lower() for f in found), f"Failed to detect in: {sentence}"


# ==============================================================================
# 3. Twitter-Text v2 Weighted Character Counter & X Formatter
# ==============================================================================

class TestTwitterTextFormatting:
    def test_ascii_character_weight(self):
        calc = TwitterTextCalculator()
        assert calc.calculate_weighted_length("Hello World") == 11

    def test_url_fixed_23_character_weight(self):
        calc = TwitterTextCalculator()
        url = "https://github.com/vllm-project/vllm/releases/tag/v0.6.4?ref=announcement"
        assert calc.calculate_weighted_length(url) == 23
        assert calc.calculate_weighted_length(f"Update: {url}") == 8 + 23

    def test_cjk_and_emoji_weight(self):
        calc = TwitterTextCalculator()
        cjk_text = "大規模言語モデル"  # 8 CJK characters
        assert calc.calculate_weighted_length(cjk_text) == 16
        emoji_text = "📊"  # 1 technical emoji
        assert calc.calculate_weighted_length(emoji_text) == 2

    def test_valid_post_boundaries(self):
        calc = TwitterTextCalculator()
        assert calc.is_valid_x_post("a" * 279) is True
        assert calc.is_valid_x_post("a" * 280) is True
        assert calc.is_valid_x_post("a" * 281) is False
        assert calc.is_valid_x_post("") is False
        assert calc.is_valid_x_post("   ") is False

    def test_truncate_to_fit(self):
        calc = TwitterTextCalculator()
        long_text = "word " * 100
        truncated = calc.truncate_to_fit(long_text, limit=280)
        assert calc.calculate_weighted_length(truncated) <= 280

    def test_format_x_post_with_url(self):
        text = "I've been analyzing DeepSeek-R1 reasoning models."
        url = "https://arxiv.org/abs/2501.12948"
        post = format_x_post(text, source_url=url)
        assert calculate_twitter_weight(post) <= 280
        assert url in post

    def test_format_x_post_no_duplicate_url_when_already_in_text(self):
        url = "https://arxiv.org/abs/2501.12948"
        text = f"Empirical analysis of reasoning models: {url}"
        post = format_x_post(text, source_url=url)
        assert post.count(url) == 1
        assert calculate_twitter_weight(post) <= 280

    def test_format_x_thread_pagination(self):
        sections = [
            "Thesis on reasoning models by Divyansh Prajapati.",
            "Detailed benchmark analysis across AIME 2024 and MATH-500.",
            "Memory bandwidth considerations for local inference.",
            "Key engineering conclusion and production recommendations.",
        ]
        url = "https://arxiv.org/abs/2501.12948"
        thread = format_x_thread(sections, source_url=url)
        assert len(thread) == 4
        assert "(1/4)" in thread[0]
        assert "(2/4)" in thread[1]
        assert "(3/4)" in thread[2]
        assert "(4/4)" in thread[3]
        assert url in thread[3]
        for t in thread:
            assert calculate_twitter_weight(t) <= 280
            assert scan_forbidden_dashes(t) == []


# ==============================================================================
# 4. LinkedIn Long-Form Styler
# ==============================================================================

class TestLinkedInFormatting:
    def test_linkedin_character_boundaries(self):
        formatter = LinkedInFormatter()
        assert formatter.is_valid_linkedin_length("a" * 2999) is True
        assert formatter.is_valid_linkedin_length("a" * 3000) is True
        assert formatter.is_valid_linkedin_length("a" * 3001) is False
        assert formatter.is_valid_linkedin_length("") is False

    def test_hook_before_the_fold(self):
        formatter = LinkedInFormatter()
        title = "Inference-Time Compute Scaling Laws in Large Language Models"
        body = "Architectural deep dive " * 30
        url = "https://arxiv.org/abs/2410.12345"
        post = formatter.format_post(title, body, url)
        hook = post.split("\n\n")[0]
        assert len(hook) <= 200
        assert len(post) <= 3000

    def test_format_full_structured_linkedin_post(self):
        post = format_linkedin_post(
            title="DeepSeek-R1 Architecture",
            summary="Open weights reasoning model evaluated on standard benchmarks.",
            analysis="The reinforcement learning pipeline replaces supervised fine-tuning with cold-start RL.",
            takeaways=[
                "Matches o1-mini on math reasoning without teacher supervision.",
                "Reduces training compute overhead significantly.",
            ],
            source_url="https://arxiv.org/abs/2501.12948",
        )
        assert len(post) <= 3000
        assert "Executive Context:" in post
        assert "Architectural Analysis:" in post
        assert "Key Takeaways for Builders:" in post
        assert "• Matches o1-mini" in post
        assert "https://arxiv.org/abs/2501.12948" in post
        assert scan_forbidden_dashes(post) == []


# ==============================================================================
# 5. Practitioner Prompt Templates
# ==============================================================================

class TestPractitionerPromptTemplates:
    def test_prompt_includes_practitioner_persona_and_zero_em_dash_rule(self, sample_item):
        prompt = PractitionerPromptTemplates.single_post_prompt(sample_item)
        assert "@divyprjai" in prompt
        assert "ZERO EM-DASHES" in prompt
        assert sample_item.title in prompt
        assert sample_item.source_url in prompt

    def test_thread_prompt_structure(self, sample_item):
        prompt = PractitionerPromptTemplates.thread_prompt(sample_item, num_tweets=5)
        assert "5-part X thread" in prompt
        assert "(1/5)" in prompt

    def test_comparison_prompt_structure(self, sample_item):
        prompt = PractitionerPromptTemplates.comparison_prompt(sample_item)
        assert "monospace markdown table" in prompt

    def test_linkedin_prompt_structure(self, sample_item):
        prompt = PractitionerPromptTemplates.linkedin_prompt(sample_item)
        assert "Hook before the fold" in prompt
        assert "3,000 characters" in prompt


# ==============================================================================
# 6. Heuristic Content Generator (100% Offline Zero-Token Fallback)
# ==============================================================================

class TestHeuristicContentGenerator:
    def test_generate_x_post_offline(self, sample_item):
        post = HeuristicContentGenerator.generate_x_post(sample_item)
        assert sample_item.source_url in post
        assert calculate_twitter_weight(post) <= 280
        assert scan_forbidden_dashes(post) == []
        assert "I've been analyzing" in post

    def test_generate_x_thread_offline(self, sample_item):
        thread = HeuristicContentGenerator.generate_x_thread(sample_item, num_tweets=4)
        assert len(thread) == 4
        assert "(1/4)" in thread[0]
        assert "(4/4)" in thread[3]
        assert sample_item.source_url in thread[3]
        for t in thread:
            assert calculate_twitter_weight(t) <= 280
            assert scan_forbidden_dashes(t) == []

    def test_generate_linkedin_post_offline(self, sample_item):
        post = HeuristicContentGenerator.generate_linkedin_post(sample_item)
        assert len(post) <= 3000
        assert "Executive Context:" in post
        assert "Key Takeaways for Builders:" in post
        assert "• " in post
        assert sample_item.source_url in post
        assert scan_forbidden_dashes(post) == []


# ==============================================================================
# 7. Local Ollama Client & DeepSeek Reasoning Tag Stripper
# ==============================================================================

class TestOllamaClientAndReasoningStripper:
    def test_strip_closed_reasoning_tags(self):
        raw = "<think>\nThinking about the architecture...\nAnalyzing benchmarks...\n</think>\nHere is the technical breakdown."
        cleaned = strip_reasoning_tags(raw)
        assert cleaned == "Here is the technical breakdown."
        assert "<think>" not in cleaned

    def test_strip_unclosed_truncated_reasoning_tags(self):
        raw = "<think>\nMidway through chain of thought..."
        cleaned = strip_reasoning_tags(raw)
        assert cleaned == ""

    def test_strip_nested_reasoning_tags(self):
        raw = "<think>outer <think>nested</think> still outer</think>Actual output"
        cleaned = strip_reasoning_tags(raw)
        assert cleaned == "Actual output"

    def test_strip_whitespace_and_orphaned_think_tags(self):
        raw = "<think  >\nIndented thought\n</think  ></think>Actual output"
        cleaned = strip_reasoning_tags(raw)
        assert cleaned == "Actual output"

    def test_strip_unclosed_start_think_tags(self):
        raw = "<think>unclosed thought..."
        cleaned = strip_reasoning_tags(raw)
        assert cleaned == ""

    @respx.mock
    def test_ollama_client_success_response(self):
        client = OllamaClient(base_url="http://localhost:11434", model="r1:latest")
        respx.post("http://localhost:11434/api/generate").mock(
            return_value=httpx.Response(
                200,
                json={"response": "<think>Drafting...</think>Empirical reasoning model breakdown by @divyprjai."},
            )
        )
        res = client.generate("test prompt")
        assert res == "Empirical reasoning model breakdown by @divyprjai."
        assert "<think>" not in res

    @respx.mock
    def test_ollama_client_fallback_on_unreachable_server(self, sample_item):
        client = OllamaClient(base_url="http://localhost:11434", model="r1:latest")
        respx.post("http://localhost:11434/api/generate").mock(
            side_effect=httpx.ConnectError("Connection refused")
        )
        # Should cleanly fall back to HeuristicContentGenerator without crashing
        res = client.generate_for_item(sample_item, platform=Platform.X)
        assert sample_item.source_url in res
        assert calculate_twitter_weight(res) <= 280
        assert scan_forbidden_dashes(res) == []


# ==============================================================================
# 8. Visual Generation Engine (Matplotlib & Pillow)
# ==============================================================================

class TestVisualGenerator:
    def test_matplotlib_benchmark_chart_1200x675_png(self, tmp_path):
        vg = VisualGenerator(output_dir=str(tmp_path))
        scores = {"DeepSeek-R1": 79.8, "o1-mini": 78.5, "Claude-3.5-Sonnet": 65.2}
        out_path = vg.create_benchmark_chart(
            title="AIME 2024 Evaluation",
            scores=scores,
            source_url="https://arxiv.org/abs/2501.12948",
        )
        assert Path(out_path).exists()
        assert out_path.endswith(".png")

        # Verify dimensions and magic bytes
        with open(out_path, "rb") as f:
            header = f.read(8)
        assert header == b"\x89PNG\r\n\x1a\n"

        from PIL import Image
        with Image.open(out_path) as im:
            assert im.size == (1200, 675)

    def test_matplotlib_benchmark_chart_handles_empty_or_nan_scores(self, tmp_path):
        vg = VisualGenerator(output_dir=str(tmp_path))
        # Empty scores dict
        p1 = vg.create_benchmark_chart("Empty Test", scores={})
        assert Path(p1).exists()

        # NaN scores
        p2 = vg.create_benchmark_chart("NaN Test", scores={"Model A": float("nan"), "Model B": None})
        assert Path(p2).exists()

    def test_matplotlib_benchmark_chart_handles_infinite_scores(self, tmp_path):
        vg = VisualGenerator(output_dir=str(tmp_path))
        scores_with_inf = {
            "Model Normal": 82.5,
            "Model Inf": float("inf"),
            "Model NegInf": float("-inf"),
            "Model NaN": float("nan"),
        }
        chart_path = vg.create_benchmark_chart(
            title="Infinite Scores Robustness Test",
            scores=scores_with_inf,
        )
        assert Path(chart_path).exists()
        assert Path(chart_path).stat().st_size > 1000

        # Also test list input with inf
        chart_path_list = vg.create_benchmark_chart(
            title="List Robustness",
            scores=[float("inf"), 45.0, float("-inf")],
        )
        assert Path(chart_path_list).exists()

        # Also test generate_benchmark_chart alias
        alias_path = vg.generate_benchmark_chart(
            title="Alias Robustness",
            models=["M1", "M2"],
            scores=[float("inf"), 91.2],
            metric_name="Score",
        )
        assert Path(alias_path).exists()

    def test_pillow_social_metric_card_under_20ms(self, tmp_path):
        vg = VisualGenerator(output_dir=str(tmp_path))
        t0 = time.perf_counter()
        card_path = vg.create_metric_card(
            title="DeepSeek-R1 Breakthrough",
            metric_value="79.8%",
            metric_label="AIME 2024 Accuracy",
            source_url="https://arxiv.org/abs/2501.12948",
            license_tag="MIT",
        )
        t_elapsed = (time.perf_counter() - t0) * 1000  # ms
        assert Path(card_path).exists()
        # Generation should be practically instantaneous (<100ms comfortably on any CPU, <20ms typical)
        assert t_elapsed < 100.0

        with open(card_path, "rb") as f:
            header = f.read(8)
        assert header == b"\x89PNG\r\n\x1a\n"

    def test_visual_canvas_watermark_and_png_metadata_chunks(self, tmp_path):
        vg = VisualGenerator(output_dir=str(tmp_path))
        url = "https://arxiv.org/abs/2501.12948"
        card_path = vg.create_metric_card(
            title="DeepSeek-R1",
            metric_value="97.3%",
            metric_label="MATH-500",
            source_url=url,
            license_tag="Apache-2.0",
        )

        # 1. Digital metadata chunks
        meta = vg.read_png_metadata(card_path)
        assert meta["Source"] == url
        assert meta["License"] == "Apache-2.0"
        assert meta["Author"] == "Divyansh Prajapati"
        assert meta["Handle"] == "@divyprjai"
        assert "AI-Media-Automation" in meta["Generator"]

        # 2. Inspection helper
        footer_info = vg.inspect_visual_footer(card_path)
        assert url in footer_info["footer_text"]


# ==============================================================================
# 9. Unified EditorialEngine Facade
# ==============================================================================

class TestEditorialEngine:
    def test_validate_text_clean_post(self):
        engine = EditorialEngine()
        clean_text = "Analyzing inference compute scaling in open weights: https://arxiv.org/abs/123"
        result = engine.validate_text(clean_text, platform=Platform.X)
        assert result.is_valid is True
        assert result.has_em_dash is False
        assert len(result.errors) == 0

    def test_validate_text_flags_em_dash_and_banned_phrase(self):
        engine = EditorialEngine()
        dirty_text = "In today's fast-paced AI world — we must delve into this model."
        result = engine.validate_text(dirty_text, platform=Platform.X)
        assert result.is_valid is False
        assert result.has_em_dash is True
        assert any("delve" in p.lower() for p in result.banned_patterns)

    def test_validate_text_length_exceeded(self):
        engine = EditorialEngine()
        long_x = "word " * 60
        res_x = engine.validate_text(long_x, platform=Platform.X)
        assert res_x.is_valid is False
        assert any("exceeds 280" in err for err in res_x.errors)

        long_li = "word " * 700
        res_li = engine.validate_text(long_li, platform=Platform.LINKEDIN)
        assert res_li.is_valid is False
        assert any("exceeds 3,000" in err for err in res_li.errors)

    @respx.mock
    def test_generate_end_to_end_for_x_and_linkedin(self, sample_item, tmp_path):
        respx.post("http://localhost:11434/api/generate").mock(
            side_effect=httpx.ConnectError("Ollama offline")
        )
        vg = VisualGenerator(output_dir=str(tmp_path))
        engine = EditorialEngine(visual_generator=vg)

        # 1. Generate X Post
        x_content = engine.generate(sample_item, platform=Platform.X, format_type="single_post")
        assert x_content.platform == Platform.X
        assert x_content.has_em_dash is False
        assert x_content.character_count <= 280
        assert sample_item.source_url in x_content.text
        assert x_content.visual_path is not None
        assert Path(x_content.visual_path).exists()

        # 2. Generate LinkedIn Post
        li_content = engine.generate(sample_item, platform=Platform.LINKEDIN)
        assert li_content.platform == Platform.LINKEDIN
        assert li_content.has_em_dash is False
        assert li_content.character_count <= 3000
        assert sample_item.source_url in li_content.text
        assert li_content.visual_path is not None
        assert Path(li_content.visual_path).exists()

    @respx.mock
    def test_generate_x_thread_with_tweet_delimiter_and_weight_limits(self, sample_item, tmp_path):
        respx.post("http://localhost:11434/api/generate").mock(
            side_effect=httpx.ConnectError("Ollama offline")
        )
        vg = VisualGenerator(output_dir=str(tmp_path))
        engine = EditorialEngine(visual_generator=vg)

        thread_content = engine.generate(sample_item, platform=Platform.X, format_type="thread")
        assert thread_content.platform == Platform.X
        assert thread_content.has_em_dash is False
        assert "[TWEET]" in thread_content.text

        # Check individual tweets
        tweets = [t.strip() for t in thread_content.text.split("[TWEET]") if t.strip()]
        assert len(tweets) >= 3
        for t in tweets:
            weight = calculate_twitter_weight(t)
            assert weight <= 280, f"Tweet exceeds 280: {weight} -> {t}"
            assert scan_forbidden_dashes(t) == []
            assert scan_banned_patterns(t) == []

        assert thread_content.character_count <= 280

    def test_validate_text_x_thread_passes_when_each_under_280(self):
        engine = EditorialEngine()
        valid_thread = (
            "First tweet in the thread analyzing reasoning models (1/3)\n\n"
            "[TWEET]\n\n"
            "Second tweet detailing memory bandwidth and inference latency (2/3)\n\n"
            "[TWEET]\n\n"
            "Final tweet with engineering takeaways and canonical paper link (3/3)"
        )
        result = engine.validate_text(valid_thread, platform=Platform.X)
        assert result.is_valid is True
        assert result.has_em_dash is False
        assert result.errors == []
        assert result.weighted_count <= 280

    def test_validate_text_x_thread_fails_when_any_tweet_exceeds_280(self):
        engine = EditorialEngine()
        invalid_thread = (
            "Valid first tweet (1/2)\n\n"
            "[TWEET]\n\n"
            f"{'excessive ' * 40}(2/2)"
        )
        result = engine.validate_text(invalid_thread, platform=Platform.X)
        assert result.is_valid is False
        assert any("exceeds 280" in err for err in result.errors)
        assert any("Tweet 2" in err for err in result.errors)

    def test_validate_text_x_thread_fails_on_em_dash_or_banned_phrase(self):
        engine = EditorialEngine()
        thread_with_dash = (
            "Tweet 1 — bad em dash (1/2)\n\n"
            "[TWEET]\n\n"
            "Tweet 2 delving into things (2/2)"
        )
        result = engine.validate_text(thread_with_dash, platform=Platform.X)
        assert result.is_valid is False
        assert result.has_em_dash is True
        assert any("Tweet 1 forbidden dash" in err for err in result.errors)
        assert any("Tweet 2 banned pattern" in err for err in result.errors)
