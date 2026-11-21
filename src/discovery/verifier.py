"""Deterministic fact verification and scoring engine for AI discoveries.

Evaluates discoveries on a 0-100 confidence scale based on:
- Domain reputation tiering (+40 Tier 1, +20 Tier 2, 0 Tier 3)
- Live OpenGraph / 64KB stream artifact probing (+30 points)
- Verifiable quantitative benchmark metrics (+20 points)
- Code repository, model weights, or paper artifacts (+20 points)
- Speculation and rumor deduction (-30 penalty points)

Status routing:
- Score >= 70.0 -> PostStatus.VERIFIED
- Score 40.0 - 69.9 -> PostStatus.AWAITING_APPROVAL
- Score < 40.0 -> PostStatus.REJECTED
"""

import html
import logging
import re
from typing import Any, Dict, Optional, Tuple
import urllib.parse
import httpx

from src.contracts.enums import PostStatus
from src.contracts.schemas import DiscoveredItem

logger = logging.getLogger(__name__)

# Domain reputation tiers
TIER_1_DOMAINS = [
    "openai.com",
    "deepmind.google",
    "anthropic.com",
    "mistral.ai",
    "meta.com",
    "fb.com",
    "microsoft.com",
    "amazon.com/blogs/machine-learning",
    "aws.amazon.com",
    "arxiv.org",
    "github.com",
    "huggingface.co",
]

TIER_2_DOMAINS = [
    "techcrunch.com",
    "theverge.com",
    "venturebeat.com",
    "technologyreview.com",
    "wired.com",
    "arstechnica.com",
]

# Benchmark metrics regex
BENCHMARK_PATTERNS = [
    re.compile(r"\bAIME\b", re.IGNORECASE),
    re.compile(r"\bMATH-?500\b", re.IGNORECASE),
    re.compile(r"\bGSM8K\b", re.IGNORECASE),
    re.compile(r"\bMMLU\b", re.IGNORECASE),
    re.compile(r"\bHumanEval\b", re.IGNORECASE),
    re.compile(r"\bGPQA\b", re.IGNORECASE),
    re.compile(r"\bMMLU-Pro\b", re.IGNORECASE),
    re.compile(r"\bSWE-bench\b", re.IGNORECASE),
    re.compile(r"\d+(?:\.\d+)?%", re.IGNORECASE),
    re.compile(r"\d+\s*ms\b", re.IGNORECASE),
    re.compile(r"\d+\s*tokens/s\b", re.IGNORECASE),
    re.compile(r"\d+\s*fps\b", re.IGNORECASE),
]

# Speculation and rumor patterns
SPECULATION_PATTERNS = [
    re.compile(r"\ballegedly\b", re.IGNORECASE),
    re.compile(r"\brumor(?:ed|s)?\b", re.IGNORECASE),
    re.compile(r"\bsources?\s+claims?\b", re.IGNORECASE),
    re.compile(r"\bunconfirmed\b", re.IGNORECASE),
    re.compile(r"\bleak(?:ed|s)?\b", re.IGNORECASE),
    re.compile(r"\breportedly\b", re.IGNORECASE),
    re.compile(r"\bpurportedly\b", re.IGNORECASE),
    re.compile(r"\bspeculat(?:ed|ion|ive|ing|es)?\b", re.IGNORECASE),
    re.compile(r"\binsiders?\s+says?\b", re.IGNORECASE),
]

NEGATION_PREFIX_PATTERN = re.compile(
    r"\b(?:not|no|no\s+longer|never|debunk(?:ed)?|refut(?:ed)?|disprov(?:ed)?|denie(?:d|s)|without)\s+(?:a\s+|an\s+|any\s+|mere\s+)?(?:\w+\s+)?$",
    re.IGNORECASE,
)


def _matches_domain(netloc: str, path: str, spec: str) -> bool:
    """Check whether a URL's netloc and path match a domain specification."""
    spec = spec.lower()
    if "/" in spec:
        spec_domain, spec_path = spec.split("/", 1)
        spec_path = "/" + spec_path.rstrip("/")
        domain_match = (netloc == spec_domain or netloc.endswith("." + spec_domain))
        path_clean = path.rstrip("/")
        path_match = path.startswith(spec_path + "/") or path_clean == spec_path
        return domain_match and path_match
    else:
        return netloc == spec or netloc.endswith("." + spec)


class FactVerifier:
    """Deterministic fact verification and scoring engine for AI discoveries."""

    def __init__(self, client: Optional[httpx.Client] = None):
        self.client = client

    def score_domain(self, url: str) -> float:
        """Score source domain reputation: +40 for Tier 1, +20 for Tier 2, 0 for Tier 3."""
        if not url:
            return 0.0

        split_url = "https://" + url if "://" not in url else url
        try:
            split_res = urllib.parse.urlsplit(split_url)
            netloc = split_res.netloc.lower().split(":")[0]
            path = split_res.path
        except Exception:
            return 0.0

        for d in TIER_1_DOMAINS:
            if _matches_domain(netloc, path, d):
                return 40.0

        for d in TIER_2_DOMAINS:
            if _matches_domain(netloc, path, d):
                return 20.0

        return 0.0

    def parse_opengraph(self, html_content: str) -> Dict[str, str]:
        """Extract OpenGraph metadata and title from HTML stream."""
        if not html_content:
            return {}

        metadata: Dict[str, str] = {}

        # Extract <title>
        title_match = re.search(r"<title[^>]*>(.*?)</title>", html_content, re.IGNORECASE | re.DOTALL)
        if title_match:
            metadata["title"] = html.unescape(title_match.group(1).strip())

        # Extract <meta property="og:..." content="...">
        og_matches = re.findall(
            r'<meta\s+[^>]*property=["\']og:([^"\']+)["\'][^>]*content=["\']([^"\']*)["\']',
            html_content,
            re.IGNORECASE,
        )
        for prop, content in og_matches:
            metadata[f"og:{prop.lower()}"] = html.unescape(content.strip())

        # Also support content before property
        og_matches_rev = re.findall(
            r'<meta\s+[^>]*content=["\']([^"\']*)["\'][^>]*property=["\']og:([^"\']+)["\']',
            html_content,
            re.IGNORECASE,
        )
        for content, prop in og_matches_rev:
            metadata[f"og:{prop.lower()}"] = html.unescape(content.strip())

        return metadata

    def verify_live_artifacts(self, url: str) -> float:
        """Probe live URL for OpenGraph metadata and valid HTTP response (+30 points)."""
        if self.client is None:
            return 30.0

        try:
            resp = self.client.get(
                url,
                headers={"Range": "bytes=0-65536"},
                timeout=5.0,
            )
            if resp.status_code in (200, 206):
                return 30.0
            return 0.0
        except (httpx.HTTPError, OSError) as exc:
            logger.debug("Failed to verify live artifact at %s: %s", url, exc)
            return 0.0

    def evaluate_benchmark_metrics(self, text: str) -> float:
        """Evaluate presence of verifiable quantitative benchmark metrics (+20 points)."""
        if not text:
            return 0.0

        for pattern in BENCHMARK_PATTERNS:
            if pattern.search(text):
                return 20.0

        return 0.0

    def check_artifacts(
        self, text: str, url: str = "", metadata: Optional[Dict[str, Any]] = None
    ) -> float:
        """Check presence of verifiable open artifacts: code repository, model weights, or PDF."""
        combined = f"{text} {url}"
        if metadata:
            combined += f" {metadata}"

        has_repo = "github.com" in combined.lower()
        has_weights = "huggingface.co" in combined.lower()
        has_paper = "arxiv.org" in combined.lower() or ".pdf" in combined.lower()

        if has_repo or has_weights or has_paper:
            return 20.0
        return 0.0

    def check_speculation_penalties(self, text: str) -> float:
        """Scan text for speculative or unverified rumor phrases (-30 penalty points)."""
        if not text:
            return 0.0

        for pattern in SPECULATION_PATTERNS:
            for m in pattern.finditer(text):
                prefix = text[max(0, m.start() - 40) : m.start()]
                if not NEGATION_PREFIX_PATTERN.search(prefix):
                    return -30.0

        return 0.0

    def route_by_score(self, score: float) -> PostStatus:
        """Classify post lifecycle status based on verification score threshold."""
        if score >= 70.0:
            return PostStatus.VERIFIED
        elif score >= 40.0:
            return PostStatus.AWAITING_APPROVAL
        else:
            return PostStatus.REJECTED

    def calculate_score(self, item: DiscoveredItem) -> Tuple[float, PostStatus, str]:
        """Compute holistic fact verification score (0-100) and lifecycle status."""
        text = f"{item.title} {item.summary}"
        domain_pts = self.score_domain(item.source_url)
        live_pts = self.verify_live_artifacts(item.source_url)
        bench_pts = self.evaluate_benchmark_metrics(text)
        art_pts = self.check_artifacts(text, item.source_url, item.raw_metadata)
        spec_pts = self.check_speculation_penalties(text)

        raw_total = domain_pts + live_pts + bench_pts + art_pts + spec_pts
        clamped_score = max(0.0, min(100.0, raw_total))
        status = self.route_by_score(clamped_score)

        breakdown = (
            f"Fact score: {clamped_score:.1f}/100.0 (Domain: +{domain_pts}, "
            f"Live: +{live_pts}, Benchmarks: +{bench_pts}, Artifacts: +{art_pts}, "
            f"Speculation Penalty: {spec_pts}). Status: {status.value}."
        )

        return clamped_score, status, breakdown

    def verify(self, item: DiscoveredItem) -> DiscoveredItem:
        """Verify DiscoveredItem and update its verification attributes in-place."""
        score, status, notes = self.calculate_score(item)
        item.verification_score = score
        item.is_verified = (status == PostStatus.VERIFIED)
        item.verification_notes = notes
        return item
