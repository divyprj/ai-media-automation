"""Discovery and Fact Verification Engine package for Autonomous AI Media Automation.

Exposes:
- Feed Parsers: arXiv, GitHub Atom, Hugging Face, Lab Blogs/RSS/Sitemaps
- Multi-layer Deduplication Engine (Canonical URL hash, Title trigram Jaccard, 48h clustering)
- 4-layer Prompt Injection Defense Sanitizer (Zero-width strip, XML escaping, sandboxing, output gate)
- Deterministic Fact Verification Engine (Domain reputation, OpenGraph probing, benchmark & artifact checks, rumor deduction)
"""

from src.discovery.dedup import DeduplicationEngine
from src.discovery.parsers.arxiv import (
    ArxivRateLimiter,
    clean_arxiv_title,
    fetch_arxiv_api,
    fetch_arxiv_papers,
    fetch_arxiv_rss,
    parse_arxiv_feed,
)
from src.discovery.parsers.blogs import (
    LAB_FEEDS,
    LAB_SITEMAPS,
    clean_blog_title,
    fetch_blog_feed,
    fetch_sitemap_news,
    parse_rss_feed,
    parse_sitemap_xml,
)
from src.discovery.parsers.github import (
    fetch_github_readme,
    fetch_github_releases,
    parse_github_atom,
    strip_html_tags,
)
from src.discovery.parsers.huggingface import (
    fetch_hf_daily_papers,
    fetch_hf_model_readme,
    fetch_hf_trending_models,
    parse_hf_daily_papers,
    parse_hf_models,
)
from src.discovery.sanitizer import InputSanitizer
from src.discovery.verifier import FactVerifier

__all__ = [
    "DeduplicationEngine",
    "InputSanitizer",
    "FactVerifier",
    "ArxivRateLimiter",
    "clean_arxiv_title",
    "clean_blog_title",
    "fetch_arxiv_api",
    "fetch_arxiv_papers",
    "fetch_arxiv_rss",
    "fetch_blog_feed",
    "fetch_github_readme",
    "fetch_github_releases",
    "fetch_hf_daily_papers",
    "fetch_hf_model_readme",
    "fetch_hf_trending_models",
    "fetch_sitemap_news",
    "parse_arxiv_feed",
    "parse_github_atom",
    "parse_hf_daily_papers",
    "parse_hf_models",
    "parse_rss_feed",
    "parse_sitemap_xml",
    "strip_html_tags",
    "LAB_FEEDS",
    "LAB_SITEMAPS",
]
