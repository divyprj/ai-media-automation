"""GitHub Releases Atom feed fetcher and raw README parser.

Bypasses GitHub REST API 60 req/hr rate limits by parsing unauthenticated public
Atom feeds (`https://github.com/<owner>/<repo>/releases.atom`) and raw content
(`https://raw.githubusercontent.com/<owner>/<repo>/<branch>/README.md`).
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

GITHUB_ATOM_URL = "https://github.com/{repo_slug}/releases.atom"
GITHUB_RAW_README_URL = "https://raw.githubusercontent.com/{repo_slug}/{branch}/README.md"


def strip_html_tags(raw_html: str) -> str:
    """Strip HTML tags and unescape HTML entities into clean readable text."""
    if not raw_html:
        return ""
    # Unescape HTML entities first if nested or double-encoded
    unescaped = html.unescape(raw_html)
    # Strip HTML tags
    clean_text = re.sub(r"<[^>]+>", " ", unescaped)
    # Collapse whitespace and newlines
    clean_text = re.sub(r"\s+", " ", clean_text).strip()
    return clean_text


def parse_github_atom(atom_text: str) -> List[DiscoveredItem]:
    """Parse a GitHub releases.atom XML feed into DiscoveredItem models."""
    if not atom_text or not atom_text.strip():
        return []

    # Pre-clean unescaped ampersands
    cleaned_xml = re.sub(r"&(?!(amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);)", "&amp;", atom_text)

    try:
        root = ET.fromstring(cleaned_xml)
    except (ET.ParseError, ValueError) as err:
        logger.warning("Failed to parse GitHub Atom XML: %s", err)
        return []

    ns = {"atom": "http://www.w3.org/2005/Atom"}
    items: List[DiscoveredItem] = []

    for entry in root.findall("atom:entry", ns):
        title_elem = entry.find("atom:title", ns)
        link_elem = entry.find("atom:link", ns)
        content_elem = entry.find("atom:content", ns)
        updated_elem = entry.find("atom:updated", ns)
        author_elem = entry.find("atom:author", ns)
        id_elem = entry.find("atom:id", ns)

        title = title_elem.text.strip() if title_elem is not None and title_elem.text else ""
        url = link_elem.attrib.get("href", "").strip() if link_elem is not None else ""
        raw_content = content_elem.text if content_elem is not None and content_elem.text else ""
        clean_summary = strip_html_tags(raw_content)

        author_name = ""
        if author_elem is not None:
            name_elem = author_elem.find("atom:name", ns)
            if name_elem is not None and name_elem.text:
                author_name = name_elem.text.strip()

        # Tag from id or url
        raw_id = id_elem.text.strip() if id_elem is not None and id_elem.text else ""
        tag = url.split("/")[-1] if "/tag/" in url else ""

        dedup = DeduplicationEngine()
        content_hash = (
            dedup.calculate_canonical_hash(url)
            if url
            else hashlib.sha256(title.encode("utf-8")).hexdigest()
        )
        item_id = f"gh_{content_hash[:16]}"

        items.append(
            DiscoveredItem(
                id=item_id,
                source_type=SourceType.GITHUB,
                title=title,
                summary=clean_summary,
                source_url=url,
                content_hash=content_hash,
                raw_metadata={
                    "author": author_name,
                    "tag": tag,
                    "atom_id": raw_id,
                },
                is_verified=True,
                verification_score=80.0,
                verification_notes="Verified via GitHub Releases public Atom feed.",
            )
        )

    return items


def fetch_github_releases(
    repo_slug: str,
    client: Optional[httpx.Client] = None,
) -> List[DiscoveredItem]:
    """Fetch recent releases for a repository from its public Atom feed."""
    url = GITHUB_ATOM_URL.format(repo_slug=repo_slug)
    close_client = False
    if client is None:
        client = httpx.Client(timeout=5.0)
        close_client = True

    try:
        resp = client.get(url)
        resp.raise_for_status()
        items = parse_github_atom(resp.text)
        for item in items:
            item.raw_metadata["repo"] = repo_slug
        return items
    except (httpx.HTTPError, OSError) as exc:
        logger.warning("Failed to fetch GitHub releases for %s: %s", repo_slug, exc)
        return []
    finally:
        if close_client:
            client.close()


def fetch_github_readme(
    repo_slug: str,
    branch: str = "main",
    client: Optional[httpx.Client] = None,
) -> Optional[str]:
    """Fetch the raw README markdown content for a repository."""
    url = GITHUB_RAW_README_URL.format(repo_slug=repo_slug, branch=branch)
    close_client = False
    if client is None:
        client = httpx.Client(timeout=5.0)
        close_client = True

    try:
        resp = client.get(url)
        if resp.status_code == 404 and branch == "main":
            # Fallback to master branch
            url_master = GITHUB_RAW_README_URL.format(repo_slug=repo_slug, branch="master")
            resp_master = client.get(url_master)
            if resp_master.status_code == 200:
                return resp_master.text
            return None
        resp.raise_for_status()
        return resp.text
    except Exception as exc:
        logger.warning("Failed to fetch README for %s: %s", repo_slug, exc)
        return None
    finally:
        if close_client:
            client.close()
