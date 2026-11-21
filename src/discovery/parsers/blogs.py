"""RSS and XML sitemap parser for AI research lab announcements and industry blogs.

Supports:
- OpenAI, Google DeepMind, Microsoft Research, AWS ML, Hugging Face, Meta AI
- XML sitemaps for labs without native RSS (Anthropic, Mistral)
- Stream truncation (max_bytes) handling and malformed XML recovery
- LaTeX MathJax stripping and unescaped ampersand pre-cleaning
"""

import hashlib
import html
import logging
import re
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional
import httpx

from src.contracts.enums import SourceType
from src.contracts.schemas import DiscoveredItem
from src.discovery.dedup import DeduplicationEngine

logger = logging.getLogger(__name__)

LAB_FEEDS = {
    "openai": "https://openai.com/news/rss.xml",
    "deepmind": "https://deepmind.google/blog/rss.xml",
    "microsoft": "https://www.microsoft.com/en-us/research/feed/",
    "aws": "https://aws.amazon.com/blogs/machine-learning/feed/",
    "huggingface": "https://huggingface.co/blog/feed.xml",
    "meta": "https://engineering.fb.com/category/ai-research/feed/",
}

LAB_SITEMAPS = {
    "anthropic": "https://www.anthropic.com/sitemap.xml",
    "mistral": "https://mistral.ai/sitemap-0.xml",
}


def clean_blog_title(title: str) -> str:
    """Clean blog headline stripping LaTeX math delimiters, HTML tags, and excessive spaces."""
    if not title:
        return ""
    # Strip HTML tags
    clean = re.sub(r"<[^>]+>", "", title)
    # Strip LaTeX $...$ or $$...$$
    clean = re.sub(r"\$\$?([^\$]+)\$\$?", r"\1", clean)
    # Strip backslashes from common LaTeX symbols (e.g. \alpha -> alpha, \log -> log)
    clean = re.sub(r"\\([a-zA-Z]+)", r"\1", clean)
    # Unescape HTML entities
    clean = html.unescape(clean)
    # Normalize whitespace
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean


def parse_rss_feed(xml_text: str, max_bytes: Optional[int] = None) -> List[DiscoveredItem]:
    """Parse RSS 2.0 or Atom XML feed string into DiscoveredItem models.

    Handles max_bytes partial reading, unescaped ampersands, and LaTeX math.
    """
    if not xml_text or not xml_text.strip():
        return []

    # Handle max_bytes constraint if partial stream is passed
    if max_bytes and len(xml_text.encode("utf-8")) > max_bytes:
        xml_text = xml_text[:max_bytes]
        if "<feed" in xml_text or "<entry" in xml_text:
            if "<entry" in xml_text and "</entry>" not in xml_text:
                if "<summary" in xml_text and "</summary>" not in xml_text:
                    xml_text += "</summary>"
                elif "<content" in xml_text and "</content>" not in xml_text:
                    xml_text += "</content>"
                xml_text += "</entry></feed>"
            elif "</entry>" in xml_text:
                last_entry_end = xml_text.rfind("</entry>")
                xml_text = xml_text[:last_entry_end + 8] + "</feed>"
            else:
                return []
        elif "<item>" in xml_text and "</item>" not in xml_text:
            if "<description>" in xml_text and "</description>" not in xml_text:
                xml_text += "</description>"
            xml_text += "</item></channel></rss>"
        elif "</item>" in xml_text:
            last_item_end = xml_text.rfind("</item>")
            xml_text = xml_text[:last_item_end + 7] + "</channel></rss>"
        else:
            return []

    # Pre-clean unescaped ampersands in titles and bodies
    cleaned_xml = re.sub(r"&(?!(amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);)", "&amp;", xml_text)

    try:
        root = ET.fromstring(cleaned_xml)
    except (ET.ParseError, ValueError) as err:
        logger.warning("Failed to parse RSS XML: %s", err)
        return []

    items: List[DiscoveredItem] = []
    tag_clean = root.tag.split("}")[-1] if "}" in root.tag else root.tag

    if tag_clean == "rss" or tag_clean == "RDF":
        channel = root.find("channel")
        if channel is None:
            channel = root

        for item_elem in channel.findall("item"):
            title_elem = item_elem.find("title")
            link_elem = item_elem.find("link")
            desc_elem = item_elem.find("description")
            guid_elem = item_elem.find("guid")
            pub_elem = item_elem.find("pubDate")

            raw_title = title_elem.text if title_elem is not None and title_elem.text else ""
            clean_title = clean_blog_title(raw_title)

            raw_url = link_elem.text.strip() if link_elem is not None and link_elem.text else ""
            raw_summary = desc_elem.text if desc_elem is not None and desc_elem.text else ""
            clean_summary = html.unescape(re.sub(r"<[^>]+>", " ", raw_summary))
            clean_summary = re.sub(r"\s+", " ", clean_summary).strip()

            if max_bytes and len(clean_summary) > max_bytes:
                clean_summary = clean_summary[:max_bytes]

            guid_text = guid_elem.text.strip() if guid_elem is not None and guid_elem.text else None
            pub_text = pub_elem.text.strip() if pub_elem is not None and pub_elem.text else None

            dedup = DeduplicationEngine()
            content_hash = (
                dedup.calculate_canonical_hash(raw_url)
                if raw_url
                else hashlib.sha256(clean_title.encode("utf-8")).hexdigest()
            )
            item_id = f"rss_{content_hash[:16]}"

            items.append(
                DiscoveredItem(
                    id=item_id,
                    source_type=SourceType.BLOG,
                    title=clean_title,
                    summary=clean_summary,
                    source_url=raw_url,
                    content_hash=content_hash,
                    raw_metadata={
                        "guid": guid_text,
                        "pub_date": pub_text,
                    },
                    is_verified=False,
                    verification_score=0.0,
                    verification_notes="Discovered via lab/industry RSS feed, pending verification.",
                )
            )

    elif tag_clean == "feed":
        # Atom feed
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        for entry in root.findall("atom:entry", ns):
            title_elem = entry.find("atom:title", ns)
            link_elem = entry.find("atom:link", ns)
            summary_elem = entry.find("atom:summary", ns)
            if summary_elem is None:
                summary_elem = entry.find("atom:content", ns)
            id_elem = entry.find("atom:id", ns)
            updated_elem = entry.find("atom:updated", ns)

            raw_title = title_elem.text if title_elem is not None and title_elem.text else ""
            clean_title = clean_blog_title(raw_title)

            raw_url = link_elem.attrib.get("href", "").strip() if link_elem is not None else ""
            raw_summary = summary_elem.text if summary_elem is not None and summary_elem.text else ""
            clean_summary = html.unescape(re.sub(r"<[^>]+>", " ", raw_summary))
            clean_summary = re.sub(r"\s+", " ", clean_summary).strip()

            if max_bytes and len(clean_summary) > max_bytes:
                clean_summary = clean_summary[:max_bytes]

            atom_id = id_elem.text.strip() if id_elem is not None and id_elem.text else None
            updated = updated_elem.text.strip() if updated_elem is not None and updated_elem.text else None

            dedup = DeduplicationEngine()
            content_hash = (
                dedup.calculate_canonical_hash(raw_url)
                if raw_url
                else hashlib.sha256(clean_title.encode("utf-8")).hexdigest()
            )
            item_id = f"atom_{content_hash[:16]}"

            items.append(
                DiscoveredItem(
                    id=item_id,
                    source_type=SourceType.BLOG,
                    title=clean_title,
                    summary=clean_summary,
                    source_url=raw_url,
                    content_hash=content_hash,
                    raw_metadata={
                        "atom_id": atom_id,
                        "updated": updated,
                    },
                    is_verified=False,
                    verification_score=0.0,
                    verification_notes="Discovered via Atom feed, pending verification.",
                )
            )

    return items


def parse_sitemap_xml(xml_text: str) -> List[Dict[str, Any]]:
    """Parse XML sitemap payload extracting loc URLs and lastmod timestamps."""
    if not xml_text or not xml_text.strip():
        return []

    try:
        root = ET.fromstring(xml_text)
    except (ET.ParseError, ValueError) as err:
        logger.warning("Failed to parse sitemap XML: %s", err)
        return []

    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    results: List[Dict[str, Any]] = []

    # Handle urlset (<urlset><url>...</url></urlset>)
    for url_elem in root.findall("sm:url", ns):
        loc_elem = url_elem.find("sm:loc", ns)
        lastmod_elem = url_elem.find("sm:lastmod", ns)
        if loc_elem is not None and loc_elem.text:
            results.append({
                "loc": loc_elem.text.strip(),
                "lastmod": lastmod_elem.text.strip() if lastmod_elem is not None and lastmod_elem.text else None,
            })

    # Also handle sitemap index (<sitemapindex><sitemap><loc>...)
    if not results:
        for sm_elem in root.findall("sm:sitemap", ns):
            loc_elem = sm_elem.find("sm:loc", ns)
            lastmod_elem = sm_elem.find("sm:lastmod", ns)
            if loc_elem is not None and loc_elem.text:
                results.append({
                    "loc": loc_elem.text.strip(),
                    "lastmod": lastmod_elem.text.strip() if lastmod_elem is not None and lastmod_elem.text else None,
                })

    return results


def fetch_blog_feed(
    url: str,
    max_bytes: Optional[int] = None,
    client: Optional[httpx.Client] = None,
) -> List[DiscoveredItem]:
    """Fetch and parse an RSS or Atom blog feed over HTTP."""
    close_client = False
    if client is None:
        client = httpx.Client(timeout=5.0)
        close_client = True

    try:
        resp = client.get(url)
        resp.raise_for_status()
        return parse_rss_feed(resp.text, max_bytes=max_bytes)
    except (httpx.HTTPError, OSError) as exc:
        logger.warning("Failed to fetch blog feed from %s: %s", url, exc)
        return []
    finally:
        if close_client:
            client.close()


def fetch_sitemap_news(
    sitemap_url: str,
    path_filter: str = "/news/",
    client: Optional[httpx.Client] = None,
) -> List[Dict[str, Any]]:
    """Fetch sitemap XML and filter entries matching a news path prefix."""
    close_client = False
    if client is None:
        client = httpx.Client(timeout=5.0)
        close_client = True

    try:
        resp = client.get(sitemap_url)
        resp.raise_for_status()
        entries = parse_sitemap_xml(resp.text)
        return [e for e in entries if path_filter in e["loc"]]
    except (httpx.HTTPError, OSError) as exc:
        logger.warning("Failed to fetch sitemap from %s: %s", sitemap_url, exc)
        return []
    finally:
        if close_client:
            client.close()
