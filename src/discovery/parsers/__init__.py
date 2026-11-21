"""Feed fetchers and parsers for arXiv, GitHub, Hugging Face, and AI Lab blogs."""

import sys
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

# Register compatibility aliases into sys.modules so existing test runners
# referencing *_parser submodule paths resolve directly to these modules.
from src.discovery.parsers import arxiv as _arxiv_mod
from src.discovery.parsers import blogs as _blogs_mod
from src.discovery.parsers import github as _github_mod
from src.discovery.parsers import huggingface as _hf_mod

sys.modules.setdefault("src.discovery.parsers.arxiv_parser", _arxiv_mod)
sys.modules.setdefault("src.discovery.parsers.github_parser", _github_mod)
sys.modules.setdefault("src.discovery.parsers.hf_parser", _hf_mod)
sys.modules.setdefault("src.discovery.parsers.rss_parser", _blogs_mod)
sys.modules.setdefault("src.discovery.parsers.sitemap_parser", _blogs_mod)

__all__ = [
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
