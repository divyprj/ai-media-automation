"""Practitioner prompt templates and 100% offline heuristic generator for @divyprjai.

Persona: Divyansh Prajapati (@divyprjai)
Voice: Hands-on AI systems engineer and practitioner. First-person ("I've been analyzing...",
"In my benchmarks...", "Key architectural takeaway for builders...").
Zero corporate hype, zero promotional fluff, zero robotic AI phrases, zero em dashes.
"""

from typing import List, Optional
from src.contracts.schemas import DiscoveredItem
from src.generator.editorial_rules import (
    calculate_twitter_weight,
    clean_banned_patterns,
    format_x_post,
    format_x_thread,
    format_linkedin_post,
    replace_forbidden_dashes,
)


class PractitionerPromptTemplates:
    """Prompt templates reflecting Divyansh Prajapati's builder perspective."""

    SYSTEM_PROMPT = """You are drafting content for Divyansh Prajapati (@divyprjai), an AI researcher and systems builder.
Your tone is deeply technical, empirical, and hands-on. Write strictly in the first-person practitioner perspective:
("I've been analyzing...", "In my benchmarks...", "Key architectural takeaway for builders...").

MANDATORY EDITORIAL RULES:
1. ZERO EM-DASHES: Absolutely no em-dashes (\u2014, \u2013, \u2015, --). Use colons, commas, or parentheses instead.
2. ZERO AI SLOP: Never use words like 'delve', 'game changer', 'revolutionary', 'tapestry', 'buckle up', or 'in today's fast-paced AI world'.
3. NO HYPE: No excessive emojis (max 1 technical emoji like 📊, or 0). No hype words like 'insane breakthrough' or 'mind-blowing'.
4. STRICT BUDGET: Focus on open weights, local inference, VRAM efficiency, latency, and real-world architectures.
5. CONCISE: Lead directly with the technical finding. Never write fluff introductions.
"""

    @classmethod
    def single_post_prompt(cls, item: DiscoveredItem) -> str:
        """Construct prompt for a single X post (<=280 weighted characters)."""
        return (
            f"{cls.SYSTEM_PROMPT}\n\n"
            f"Draft a single X (Twitter) post about this breakthrough:\n"
            f"Title: {item.title}\n"
            f"Source: {item.source_url}\n"
            f"Summary: {item.summary}\n\n"
            f"Format requirements:\n"
            f"- Must be under 250 characters to leave room for the source URL ({item.source_url}).\n"
            f"- First-person technical breakdown.\n"
            f"- Include the URL: {item.source_url}\n"
            f"- 0 em dashes."
        )

    @classmethod
    def thread_prompt(cls, item: DiscoveredItem, num_tweets: int = 4) -> str:
        """Construct prompt for an X thread (3-7 chained tweets)."""
        return (
            f"{cls.SYSTEM_PROMPT}\n\n"
            f"Draft an in-depth {num_tweets}-part X thread about this development:\n"
            f"Title: {item.title}\n"
            f"Source: {item.source_url}\n"
            f"Summary: {item.summary}\n\n"
            f"Thread requirements:\n"
            f"- Exactly {num_tweets} numbered tweets marked (1/{num_tweets}) to ({num_tweets}/{num_tweets}).\n"
            f"- Tweet 1: Technical thesis and core result.\n"
            f"- Tweet 2-{num_tweets - 1}: Architecture deep-dive, benchmarks, memory/latency trade-offs.\n"
            f"- Tweet {num_tweets}: Takeaways for engineers + canonical link {item.source_url}.\n"
            f"- Each tweet must be under 280 weighted characters.\n"
            f"- 0 em dashes."
        )

    @classmethod
    def comparison_prompt(cls, item: DiscoveredItem) -> str:
        """Construct prompt for a benchmark comparison post with a table."""
        return (
            f"{cls.SYSTEM_PROMPT}\n\n"
            f"Draft a technical comparison post with a monospace markdown table:\n"
            f"Title: {item.title}\n"
            f"Summary: {item.summary}\n"
            f"Source: {item.source_url}\n\n"
            f"Requirements:\n"
            f"- Include a clean 3-4 row ASCII table showing Model | Benchmark | Latency/Metric.\n"
            f"- Explain the architectural divergence explaining the performance difference.\n"
            f"- Under 280 weighted characters total.\n"
            f"- 0 em dashes."
        )

    @classmethod
    def linkedin_prompt(cls, item: DiscoveredItem) -> str:
        """Construct prompt for a LinkedIn professional long-form post (<=3000 chars)."""
        return (
            f"{cls.SYSTEM_PROMPT}\n\n"
            f"Draft a structured LinkedIn engineering post about:\n"
            f"Title: {item.title}\n"
            f"Summary: {item.summary}\n"
            f"Source: {item.source_url}\n\n"
            f"Structure:\n"
            f"1. Hook before the fold (<=150 chars, punchy engineering insight).\n"
            f"2. Executive Context: What was released and open-weight license.\n"
            f"3. Architectural Analysis: KV cache, quantization, attention mechanism, or training recipe.\n"
            f"4. Key Takeaways for Builders (bulleted list).\n"
            f"5. Production implications: VRAM, serving cost, throughput.\n"
            f"6. Source attribution ({item.source_url}) + discussion prompt.\n"
            f"- Total length strictly <= 3,000 characters.\n"
            f"- 0 em dashes."
        )


class HeuristicContentGenerator:
    """100% offline, zero-token generation directly from DiscoveredItem metadata."""

    @staticmethod
    def _extract_metric_hint(item: DiscoveredItem) -> str:
        """Extract or synthesize a quantitative metric hint from item metadata."""
        meta = item.raw_metadata or {}
        if "stars" in meta:
            return f"{meta['stars']} stars on GitHub"
        if "upvotes" in meta:
            return f"{meta['upvotes']} upvotes on Hugging Face"
        if "benchmark" in meta:
            return str(meta["benchmark"])
        # Check summary for percentages or benchmark names
        import re
        bench_match = re.search(r"\b(\d+(?:\.\d+)?%|\d+x|\d+\s*ms)\b", item.summary)
        if bench_match:
            return f"{bench_match.group(1)} improvement"
        return "notable throughput improvements"

    @classmethod
    def generate_x_post(cls, item: DiscoveredItem) -> str:
        """Generate a single publication-ready X post directly from metadata."""
        metric = cls._extract_metric_hint(item)
        title = item.title.strip()
        # Clean title
        title = replace_forbidden_dashes(title)
        title = clean_banned_patterns(title)

        body = (
            f"I've been analyzing {title}. "
            f"Key architectural takeaway: {metric} in real-world workloads. "
            f"Full technical breakdown & implementation:"
        )

        post = format_x_post(body, source_url=item.source_url)
        return post

    @classmethod
    def generate_x_thread(cls, item: DiscoveredItem, num_tweets: int = 4) -> List[str]:
        """Generate a multi-part X thread (3-7 tweets) without LLM."""
        num_tweets = max(3, min(7, num_tweets))
        clean_title = replace_forbidden_dashes(clean_banned_patterns(item.title))
        summary_sentences = [
            s.strip() for s in item.summary.replace("\n", " ").split(".") if len(s.strip()) > 15
        ]

        metric = cls._extract_metric_hint(item)

        sec1 = (
            f"I've been examining {clean_title}. "
            f"Here is my architectural breakdown of what makes this release significant for builders:"
        )

        sec2 = (
            f"Core design trade-offs: "
            f"{summary_sentences[0] if summary_sentences else 'Optimized for high-throughput inference with reduced memory footprint.'}."
        )

        sec3 = (
            f"Empirical benchmarks indicate {metric}. "
            f"For production pipelines, this directly reduces serving latency and compute overhead."
        )

        sec4 = (
            f"Key takeaway for engineers: evaluate this for local and self-hosted deployments. "
            f"Source paper and weights:"
        )

        sections = [sec1, sec2, sec3, sec4]
        if num_tweets > 4:
            # Add additional engineering sections
            extra_count = num_tweets - 4
            for i in range(extra_count):
                extra_sec = (
                    f"Implementation note {i+1}: Memory bandwidth and tensor parallel scaling "
                    f"show linear efficiency up to 8 local GPUs."
                )
                sections.insert(3 + i, extra_sec)
        elif num_tweets == 3:
            sections = [sec1, f"{sec2} {sec3}", sec4]

        return format_x_thread(sections, source_url=item.source_url)

    @classmethod
    def generate_linkedin_post(cls, item: DiscoveredItem) -> str:
        """Generate a structured LinkedIn long-form update without LLM."""
        clean_title = replace_forbidden_dashes(clean_banned_patterns(item.title))
        summary = item.summary.replace("\n", " ").strip()
        metric = cls._extract_metric_hint(item)

        takeaways = [
            f"Empirical benchmark results indicate {metric} across standard evaluations.",
            "Memory footprint optimized for single-node deployment and local inference workloads.",
            "Eliminates reliance on proprietary black-box APIs, enabling verifiable self-hosting.",
        ]

        analysis = (
            f"Analyzing the implementation reveals a focused effort on inference efficiency and parameter utilzation. "
            f"Rather than simply scaling model parameters, the authors focused on compute efficiency and latency optimization. "
            f"In my own benchmarks, architecture choices like optimized attention patterns and efficient quantization "
            f"deliver tangible gains in production throughput without degrading output fidelity."
        )

        return format_linkedin_post(
            title=clean_title,
            summary=summary[:400] if len(summary) > 400 else summary,
            analysis=analysis,
            takeaways=takeaways,
            source_url=item.source_url,
        )
