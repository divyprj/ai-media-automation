"""Multi-layer deduplication engine for AI news discovery.

Implements a 3-tier cascade:
- Tier 1: Canonical URL normalizer (strips UTM/referrals, standardizes arXiv/GitHub/HF URNs) + SHA-256 hash
- Tier 2: Normalized title tokenization & character 3-gram Jaccard similarity calculator
- Tier 3: 48-hour entity clustering grouping cross-source items into unified clusters
"""

import hashlib
import re
import urllib.parse
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.contracts.schemas import DiscoveredItem
from src.database.connection import get_db_connection
from src.database.repository import Repository

STOP_WORDS = {
    "a", "an", "the", "and", "or", "of", "to", "in", "on", "with", "by", "for",
    "at", "from", "is", "as", "via", "about", "into", "through", "over",
}

TRACKING_PARAM_REGEX = re.compile(
    r"^(utm_|ref$|source$|fbclid$|gclid$|mc_eid$|igshid$)",
    re.IGNORECASE,
)


def _parse_timestamp(val: Any) -> Optional[datetime]:
    """Parse various timestamp representations into a UTC datetime object."""
    if val is None:
        return None
    if isinstance(val, datetime):
        if val.tzinfo is None:
            return val.replace(tzinfo=timezone.utc)
        return val.astimezone(timezone.utc)
    if isinstance(val, (int, float)):
        try:
            return datetime.fromtimestamp(val, tz=timezone.utc)
        except Exception:
            return None
    if isinstance(val, str):
        val_clean = val.strip()
        if not val_clean:
            return None
        # Try ISO 8601
        try:
            dt = datetime.fromisoformat(val_clean.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                return dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            pass
        # Try RFC 2822 (pubDate)
        try:
            import email.utils
            parsed = email.utils.parsedate_to_datetime(val_clean)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except Exception:
            pass
    return None


def _get_item_dt(item: Dict[str, Any]) -> Optional[datetime]:
    """Extract and parse timestamp from item dict or object."""
    if not isinstance(item, dict):
        return None
    ts = item.get("timestamp") or item.get("discovered_at")
    if not ts and isinstance(item.get("raw_metadata"), dict):
        ts = item["raw_metadata"].get("published_at") or item["raw_metadata"].get("pub_date")
    return _parse_timestamp(ts)


class DeduplicationEngine:
    """Multi-layer deduplication engine managing canonical URL hashing, title Jaccard similarity, and clustering."""

    def __init__(self, repo: Optional[Repository] = None):
        self.repo = repo

    def normalize_url(self, url: str) -> str:
        """Normalize URL by stripping tracking parameters, normalizing schemes, and converting to canonical URNs.

        Conversions:
        - arXiv (/abs/, /pdf/, v1/v2): -> arxiv:<id>
        - GitHub releases/blobs/tags: -> github:<owner>/<repo>
        - Hugging Face models/papers: -> hf:<owner>/<model> or arxiv:<id>
        - General web: lowercased host, stripped trailing slashes and tracking params
        """
        if not url:
            return ""

        url = url.strip()

        # Direct URN inputs
        lower_url = url.lower()
        if lower_url.startswith("arxiv:"):
            return lower_url
        if lower_url.startswith("github:"):
            return lower_url
        if lower_url.startswith("hf:"):
            return lower_url

        try:
            split_url = "https://" + url if "://" not in url else url
            parsed = urllib.parse.urlsplit(split_url)
            netloc = parsed.netloc.lower().split(":")[0]
            path = parsed.path
        except Exception:
            netloc = ""
            path = ""

        # Only trigger arXiv rules if netloc belongs to arxiv.org
        if netloc == "arxiv.org" or netloc.endswith(".arxiv.org"):
            m_arxiv = re.search(r"/(?:abs|pdf)/(\d+\.\d+)(?:v\d+)?(?:\.pdf)?", path, re.IGNORECASE)
            if m_arxiv:
                return f"arxiv:{m_arxiv.group(1)}"

        # Only trigger GitHub rules if netloc belongs to github.com
        elif netloc == "github.com" or netloc.endswith(".github.com"):
            m_gh = re.match(r"^/([^/]+)/([^/?#]+)", path, re.IGNORECASE)
            if m_gh:
                owner = m_gh.group(1).lower()
                repo = m_gh.group(2).lower()
                if repo.endswith(".git"):
                    repo = repo[:-4]
                return f"github:{owner}/{repo}"

        # Only trigger Hugging Face rules if netloc belongs to huggingface.co
        elif netloc == "huggingface.co" or netloc.endswith(".huggingface.co"):
            m_hf_paper = re.match(r"^/papers/(\d+\.\d+)", path, re.IGNORECASE)
            if m_hf_paper:
                return f"arxiv:{m_hf_paper.group(1)}"

            m_hf_model = re.match(r"^/(?:models/)?([^/]+/[^/?#]+)", path, re.IGNORECASE)
            if m_hf_model:
                model_slug = m_hf_model.group(1).lower()
                parts = model_slug.split("/")
                if parts[0] not in {"blog", "docs", "api", "spaces", "datasets"}:
                    return f"hf:{model_slug}"

        # Standard URL parsing and query cleaning for general web URLs
        try:
            parsed = urllib.parse.urlparse(split_url)
            scheme = parsed.scheme.lower() or "https"
            norm_netloc = parsed.netloc.lower().split(":")[0]

            # Filter query parameters
            query_pairs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=False)
            filtered_query = [
                (k, v) for k, v in query_pairs if not TRACKING_PARAM_REGEX.search(k)
            ]
            # Sort remaining query parameters deterministically
            filtered_query.sort(key=lambda x: x[0])
            new_query = urllib.parse.urlencode(filtered_query)

            # Strip trailing slash from path
            norm_path = parsed.path.rstrip("/")

            normalized = urllib.parse.urlunparse((scheme, norm_netloc, norm_path, "", new_query, ""))
            return normalized.rstrip("?")
        except Exception:
            clean = re.sub(r"([?&])(utm_[^&]+|ref=[^&]+|source=[^&]+|fbclid=[^&]+)", "", url)
            clean = clean.rstrip("?&")
            return clean.rstrip("/")

    def calculate_canonical_hash(self, url: str) -> str:
        """Calculate SHA-256 hash of the canonicalized URL."""
        canonical = self.normalize_url(url)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def is_unique(self, item: DiscoveredItem) -> bool:
        """Check whether an item is unique in the repository (Tier 1 check).

        Returns False if content_hash, id, or normalized source_url/URN already exists in the database.
        """
        if self.repo is None:
            return True

        norm_url = self.normalize_url(item.source_url)
        canonical_hash = self.calculate_canonical_hash(item.source_url)

        with get_db_connection(self.repo.db_path) as conn:
            # 1. Exact match on content_hash, id, exact URL, or canonical hash
            cursor = conn.execute(
                """
                SELECT COUNT(*) FROM discovered_items
                WHERE content_hash = ?
                   OR id = ?
                   OR source_url = ?
                   OR content_hash = ?;
                """,
                (item.content_hash, item.id, item.source_url, canonical_hash),
            )
            count = cursor.fetchone()[0]
            if count > 0:
                return False

            # 2. Canonical URN matching against database rows (cross-URL deduplication)
            entity_id = None
            if norm_url.startswith("arxiv:"):
                entity_id = norm_url.split("arxiv:", 1)[1]
            elif norm_url.startswith("github:"):
                entity_id = norm_url.split("github:", 1)[1]
            elif norm_url.startswith("hf:"):
                entity_id = norm_url.split("hf:", 1)[1]

            if entity_id:
                cursor = conn.execute(
                    "SELECT source_url FROM discovered_items WHERE source_url LIKE ?",
                    (f"%{entity_id}%",),
                )
                for row in cursor.fetchall():
                    if self.normalize_url(row["source_url"]) == norm_url:
                        return False

            # 3. Check candidate rows with matching or query-variant URLs
            cursor = conn.execute(
                """
                SELECT source_url FROM discovered_items
                WHERE source_url = ?
                   OR source_url LIKE ?
                   OR ? LIKE source_url || '?%';
                """,
                (norm_url, f"{norm_url}?%", item.source_url),
            )
            for row in cursor.fetchall():
                if self.normalize_url(row["source_url"]) == norm_url:
                    return False

            return True

    def normalize_title(self, title: str) -> str:
        """Normalize title by lowercasing, stripping punctuation, and removing stop words."""
        if not title:
            return ""
        words = re.findall(r"\b[a-zA-Z0-9_\-\.]+\b", title.lower())
        meaningful = [w for w in words if w not in STOP_WORDS]
        return " ".join(meaningful)

    def calculate_title_similarity(self, t1: str, t2: str) -> float:
        """Calculate character 3-gram Jaccard similarity between two titles (Tier 2 check)."""
        clean1 = re.sub(r"\W+", "", t1.lower())
        clean2 = re.sub(r"\W+", "", t2.lower())

        if not clean1 or not clean2:
            return 0.0

        if len(clean1) < 3 or len(clean2) < 3:
            return 1.0 if clean1 == clean2 else 0.0

        ng1 = {clean1[i : i + 3] for i in range(len(clean1) - 2)}
        ng2 = {clean2[i : i + 3] for i in range(len(clean2) - 2)}

        intersection = len(ng1.intersection(ng2))
        union = len(ng1.union(ng2))

        return intersection / union if union > 0 else 0.0

    def is_title_duplicate(
        self, title: str, existing_titles: List[str], threshold: float = 0.40
    ) -> bool:
        """Check if title matches any existing title above the Jaccard similarity threshold."""
        for existing in existing_titles:
            if self.calculate_title_similarity(title, existing) >= threshold:
                return True
        return False

    def cluster_items(
        self, items: List[Dict[str, Any]], max_cluster_size: int = 20
    ) -> List[Dict[str, Any]]:
        """Cluster items sharing significant title word overlap or high Jaccard similarity within 48h (Tier 3)."""
        if not items:
            return []

        clusters: List[Dict[str, Any]] = []

        for item in items:
            title = item.get("title", "")
            words = set(re.findall(r"\w+", title.lower())) - STOP_WORDS
            item_dt = _get_item_dt(item)
            matched = False

            for c in clusters:
                sources = c.get("cluster_sources", [c])
                if len(sources) >= max_cluster_size:
                    continue

                cluster_dt = _get_item_dt(c)
                if item_dt is not None and cluster_dt is not None:
                    hours_diff = abs((item_dt - cluster_dt).total_seconds()) / 3600.0
                    if hours_diff > 48.0:
                        continue

                c_title = c.get("title", "")
                c_words = set(re.findall(r"\w+", c_title.lower())) - STOP_WORDS
                common_words = words.intersection(c_words)

                # Match if at least 2 significant words overlap or trigram similarity >= 0.30
                if len(common_words) >= 2 or self.calculate_title_similarity(c_title, title) >= 0.30:
                    matched = True
                    # Record related sources in cluster if available
                    if "cluster_sources" not in c:
                        c["cluster_sources"] = [c]
                    c["cluster_sources"].append(item)
                    break

            if not matched:
                item_copy = dict(item)
                item_copy["cluster_sources"] = [item]
                clusters.append(item_copy)

        return clusters

    def enrich_cluster(self, items: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Aggregate cross-source URLs and metadata into an enriched multi-source mapping."""
        enriched: Dict[str, Any] = {}
        for it in items:
            source = it.get("source")
            url = it.get("url") or it.get("source_url")
            if source and url:
                enriched[source] = url
            elif url:
                # Infer source from URL
                if "arxiv.org" in url:
                    enriched["arxiv"] = url
                elif "github.com" in url:
                    enriched["github"] = url
                elif "huggingface.co" in url:
                    enriched["huggingface"] = url
                else:
                    enriched["blog"] = url
        return enriched
