"""arXiv research paper feed fetcher and parser with rate-limiting and RSS fallback.

Implements:
- Thread-safe token bucket rate limiter (>= 3.5s interval between requests to export.arxiv.org)
- Robust XML parsing for arXiv Atom API feeds and static RSS feeds (rss.arxiv.org)
- LaTeX / MathJax stripping and title cleaning
- Seamless fallback from API to static RSS feeds on HTTP 429 or network errors
"""

import hashlib
import logging
import re
import threading
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import httpx

from src.contracts.enums import SourceType
from src.contracts.schemas import DiscoveredItem
from src.discovery.dedup import DeduplicationEngine

logger = logging.getLogger(__name__)

ARXIV_API_BASE = "https://export.arxiv.org/api/query"
DEFAULT_CATEGORIES = ["cs.AI", "cs.LG", "cs.CL", "stat.ML"]
ARXIV_RSS_TEMPLATE = "https://rss.arxiv.org/rss/{category}"


class ArxivRateLimiter:
    """Thread-safe rate limiter enforcing minimum delay between arXiv API calls."""

    def __init__(self, min_interval_seconds: float = 3.5):
        self.min_interval = min_interval_seconds
        self._last_request_time = 0.0
        self._lock = threading.Lock()

    def acquire(self) -> None:
        """Block until min_interval seconds have passed since previous call."""
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_request_time
            if elapsed < self.min_interval:
                time.sleep(self.min_interval - elapsed)
            self._last_request_time = time.monotonic()


_global_rate_limiter = ArxivRateLimiter(min_interval_seconds=3.5)


def clean_arxiv_title(title: str) -> str:
    """Clean arXiv title by stripping MathJax delimiters, newlines, and excessive whitespace."""
    if not title:
        return ""
    # Strip inline and display LaTeX delimiters: $...$ or $$...$$
    cleaned = re.sub(r"\$\$?([^\$]+)\$\$?", r"\1", title)
    # Strip backslashes from common symbols like \alpha, \mathcal{...}
    cleaned = re.sub(r"\\([a-zA-Z]+)", r"\1", cleaned)
    # Normalize whitespace and newlines
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def parse_arxiv_feed(xml_text: str) -> List[DiscoveredItem]:
    """Parse arXiv Atom XML or static RSS feed into standardized DiscoveredItem domain models.

    Gracefully handles malformed XML, unescaped ampersands, and empty feeds.
    """
    if not xml_text or not xml_text.strip():
        return []

    # Pre-clean unescaped ampersands
    cleaned_xml = re.sub(r"&(?!(amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);)", "&amp;", xml_text)

    try:
        root = ET.fromstring(cleaned_xml)
    except (ET.ParseError, ValueError) as err:
        logger.warning("Failed to parse arXiv XML: %s", err)
        return []

    items: List[DiscoveredItem] = []

    # Check if Atom feed (<feed xmlns="http://www.w3.org/2005/Atom">)
    tag_clean = root.tag.split("}")[-1] if "}" in root.tag else root.tag
    if tag_clean == "feed":
        ns = {
            "atom": "http://www.w3.org/2005/Atom",
            "arxiv": "http://arxiv.org/schemas/atom",
        }

        # Atom entries
        for entry in root.findall("atom:entry", ns):
            title_elem = entry.find("atom:title", ns)
            summary_elem = entry.find("atom:summary", ns)
            id_elem = entry.find("atom:id", ns)
            published_elem = entry.find("atom:published", ns)
            cat_elem = entry.find("arxiv:primary_category", ns)
            if cat_elem is None:
                cat_elem = entry.find("atom:category", ns)

            raw_title = title_elem.text if title_elem is not None and title_elem.text else ""
            title = clean_arxiv_title(raw_title)

            raw_summary = summary_elem.text if summary_elem is not None and summary_elem.text else ""
            summary = re.sub(r"\s+", " ", raw_summary).strip()

            raw_id = id_elem.text.strip() if id_elem is not None and id_elem.text else ""
            category = (
                cat_elem.attrib.get("term", "cs.AI")
                if cat_elem is not None and "term" in cat_elem.attrib
                else "cs.AI"
            )

            # Authors extraction
            authors = [
                a.find("atom:name", ns).text.strip()
                for a in entry.findall("atom:author", ns)
                if a.find("atom:name", ns) is not None and a.find("atom:name", ns).text
            ]

            # Links extraction
            pdf_url = None
            for link in entry.findall("atom:link", ns):
                if link.attrib.get("title") == "pdf" or link.attrib.get("type") == "application/pdf":
                    pdf_url = link.attrib.get("href")

            dedup = DeduplicationEngine()
            content_hash = (
                dedup.calculate_canonical_hash(raw_id)
                if raw_id
                else hashlib.sha256(title.encode("utf-8")).hexdigest()
            )
            item_id = f"arxiv_{content_hash[:16]}"

            raw_meta: Dict[str, Any] = {
                "category": category,
                "authors": authors,
                "arxiv_id": raw_id,
            }
            if pdf_url:
                raw_meta["pdf_url"] = pdf_url

            items.append(
                DiscoveredItem(
                    id=item_id,
                    source_type=SourceType.ARXIV,
                    title=title,
                    summary=summary,
                    source_url=raw_id,
                    content_hash=content_hash,
                    raw_metadata=raw_meta,
                    is_verified=True,
                    verification_score=85.0,
                    verification_notes="Verified via authoritative arXiv Atom feed.",
                )
            )

    elif tag_clean == "rss":
        # Static RSS feed fallback (<rss version="2.0"><channel><item>...)
        channel = root.find("channel")
        if channel is not None:
            for item_elem in channel.findall("item"):
                title_elem = item_elem.find("title")
                link_elem = item_elem.find("link")
                desc_elem = item_elem.find("description")

                raw_title = title_elem.text if title_elem is not None and title_elem.text else ""
                title = clean_arxiv_title(raw_title)

                raw_link = link_elem.text.strip() if link_elem is not None and link_elem.text else ""
                raw_desc = desc_elem.text if desc_elem is not None and desc_elem.text else ""
                summary = re.sub(r"\s+", " ", raw_desc).strip()

                dedup = DeduplicationEngine()
                content_hash = (
                    dedup.calculate_canonical_hash(raw_link)
                    if raw_link
                    else hashlib.sha256(title.encode("utf-8")).hexdigest()
                )
                item_id = f"arxiv_{content_hash[:16]}"

                items.append(
                    DiscoveredItem(
                        id=item_id,
                        source_type=SourceType.ARXIV,
                        title=title,
                        summary=summary,
                        source_url=raw_link,
                        content_hash=content_hash,
                        raw_metadata={"feed_type": "rss_fallback"},
                        is_verified=True,
                        verification_score=85.0,
                        verification_notes="Verified via authoritative arXiv RSS feed.",
                    )
                )

    return items


def fetch_arxiv_api(
    categories: Optional[List[str]] = None,
    max_results: int = 50,
    client: Optional[httpx.Client] = None,
    rate_limiter: Optional[ArxivRateLimiter] = None,
) -> List[DiscoveredItem]:
    """Fetch recent papers from the official arXiv Query API enforcing token bucket delay."""
    cats = categories or DEFAULT_CATEGORIES
    query_parts = [f"cat:{c}" for c in cats]
    search_query = " OR ".join(query_parts)

    params = {
        "search_query": search_query,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
        "max_results": str(max_results),
    }

    limiter = rate_limiter or _global_rate_limiter
    limiter.acquire()

    close_client = False
    if client is None:
        client = httpx.Client(timeout=5.0)
        close_client = True

    try:
        resp = client.get(ARXIV_API_BASE, params=params)
        if resp.status_code == 429:
            logger.warning("arXiv API rate limit exceeded (HTTP 429).")
            raise httpx.HTTPStatusError("Rate exceeded", request=resp.request, response=resp)
        resp.raise_for_status()
        return parse_arxiv_feed(resp.text)
    finally:
        if close_client:
            client.close()


def fetch_arxiv_rss(
    category: str = "cs.AI",
    client: Optional[httpx.Client] = None,
) -> List[DiscoveredItem]:
    """Fetch static CDN-cached RSS feed for a specific arXiv category."""
    url = ARXIV_RSS_TEMPLATE.format(category=category)
    close_client = False
    if client is None:
        client = httpx.Client(timeout=5.0)
        close_client = True

    try:
        resp = client.get(url)
        resp.raise_for_status()
        return parse_arxiv_feed(resp.text)
    except (httpx.HTTPError, OSError) as exc:
        logger.warning("Failed to fetch arXiv RSS for %s: %s", url, exc)
        return []
    finally:
        if close_client:
            client.close()


def fetch_arxiv_papers(
    categories: Optional[List[str]] = None,
    use_api: bool = True,
    client: Optional[httpx.Client] = None,
) -> List[DiscoveredItem]:
    """Fetch papers attempting API first, seamlessly falling back to static RSS feeds if blocked or failing."""
    cats = categories or DEFAULT_CATEGORIES
    if use_api:
        try:
            return fetch_arxiv_api(categories=cats, client=client)
        except Exception as exc:
            logger.warning("arXiv API query failed (%s), falling back to static category RSS feeds.", exc)

    # RSS Fallback
    all_items: List[DiscoveredItem] = []
    seen_hashes = set()
    for cat in cats:
        try:
            items = fetch_arxiv_rss(category=cat, client=client)
            for item in items:
                if item.content_hash not in seen_hashes:
                    seen_hashes.add(item.content_hash)
                    all_items.append(item)
        except Exception as exc:
            logger.warning("Failed to fetch arXiv RSS for category %s: %s", cat, exc)

    return all_items
