"""Hugging Face public feeds and APIs parser.

Fetches and parses:
- Hugging Face Daily Papers API (`https://huggingface.co/api/daily_papers`)
- Hugging Face Trending Models API (`https://huggingface.co/api/models?sort=trendingScore`)
- Raw model card READMEs (`https://huggingface.co/<model_id>/raw/main/README.md`)
"""

import hashlib
import json
import logging
from typing import Any, Dict, List, Optional
import httpx

from src.contracts.enums import SourceType
from src.contracts.schemas import DiscoveredItem
from src.discovery.dedup import DeduplicationEngine

logger = logging.getLogger(__name__)

HF_DAILY_PAPERS_URL = "https://huggingface.co/api/daily_papers"
HF_MODELS_URL = "https://huggingface.co/api/models"
HF_RAW_README_URL = "https://huggingface.co/{model_id}/raw/main/README.md"


def parse_hf_daily_papers(json_text: str) -> List[DiscoveredItem]:
    """Parse Hugging Face daily papers JSON payload into DiscoveredItem models."""
    if not json_text or not json_text.strip():
        return []

    try:
        data = json.loads(json_text)
    except (json.JSONDecodeError, ValueError) as err:
        logger.warning("Failed to parse HF daily papers JSON: %s", err)
        return []

    if not isinstance(data, list):
        return []

    items: List[DiscoveredItem] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue

        paper = entry.get("paper", entry)
        if not isinstance(paper, dict):
            continue

        paper_id = paper.get("id", "").strip()
        title = paper.get("title", "").strip()
        summary = paper.get("summary", "").strip()
        upvotes = paper.get("upvotes", 0)
        github_repo = paper.get("githubRepo")
        github_stars = paper.get("githubStars", 0)
        published_at = paper.get("publishedAt")

        url = f"https://huggingface.co/papers/{paper_id}" if paper_id else "https://huggingface.co"
        dedup = DeduplicationEngine()
        content_hash = (
            dedup.calculate_canonical_hash(url)
            if url
            else hashlib.sha256(title.encode("utf-8")).hexdigest()
        )
        item_id = f"hf_{content_hash[:16]}"

        raw_meta: Dict[str, Any] = {
            "arxiv_id": paper_id,
            "upvotes": upvotes,
            "github_repo": github_repo,
            "github_stars": github_stars,
            "published_at": published_at,
        }

        items.append(
            DiscoveredItem(
                id=item_id,
                source_type=SourceType.HUGGINGFACE,
                title=title,
                summary=summary,
                source_url=url,
                content_hash=content_hash,
                raw_metadata=raw_meta,
                is_verified=True,
                verification_score=75.0,
                verification_notes="Verified via Hugging Face Daily Papers public API.",
            )
        )

    return items


def parse_hf_models(json_text: str) -> List[DiscoveredItem]:
    """Parse Hugging Face trending models JSON payload into DiscoveredItem models."""
    if not json_text or not json_text.strip():
        return []

    try:
        data = json.loads(json_text)
    except (json.JSONDecodeError, ValueError) as err:
        logger.warning("Failed to parse HF models JSON: %s", err)
        return []

    if not isinstance(data, list):
        return []

    items: List[DiscoveredItem] = []
    for model in data:
        if not isinstance(model, dict):
            continue

        model_id = model.get("id", "").strip()
        if not model_id:
            continue

        likes = model.get("likes", 0)
        downloads = model.get("downloads", 0)
        pipeline_tag = model.get("pipeline_tag", "ai-model")
        tags = model.get("tags", [])

        title = f"{model_id}: Trending {pipeline_tag} model"
        summary = (
            f"Trending model on Hugging Face Hub: {model_id}. "
            f"Pipeline: {pipeline_tag}. Downloads: {downloads:,}. Likes: {likes:,}."
        )
        url = f"https://huggingface.co/{model_id}"
        dedup = DeduplicationEngine()
        content_hash = (
            dedup.calculate_canonical_hash(url)
            if url
            else hashlib.sha256(title.encode("utf-8")).hexdigest()
        )
        item_id = f"hf_{content_hash[:16]}"

        items.append(
            DiscoveredItem(
                id=item_id,
                source_type=SourceType.HUGGINGFACE,
                title=title,
                summary=summary,
                source_url=url,
                content_hash=content_hash,
                raw_metadata={
                    "model_id": model_id,
                    "likes": likes,
                    "downloads": downloads,
                    "pipeline_tag": pipeline_tag,
                    "tags": tags,
                },
                is_verified=True,
                verification_score=75.0,
                verification_notes="Verified via Hugging Face Model Hub API.",
            )
        )

    return items


def fetch_hf_daily_papers(client: Optional[httpx.Client] = None) -> List[DiscoveredItem]:
    """Fetch recent curated papers from Hugging Face Daily Papers API."""
    close_client = False
    if client is None:
        client = httpx.Client(timeout=5.0)
        close_client = True

    try:
        resp = client.get(HF_DAILY_PAPERS_URL)
        resp.raise_for_status()
        return parse_hf_daily_papers(resp.text)
    except (httpx.HTTPError, OSError) as exc:
        logger.warning("Failed to fetch HF daily papers: %s", exc)
        return []
    finally:
        if close_client:
            client.close()


def fetch_hf_trending_models(
    limit: int = 20,
    sort: str = "trendingScore",
    client: Optional[httpx.Client] = None,
) -> List[DiscoveredItem]:
    """Fetch top trending models from Hugging Face Model Hub."""
    close_client = False
    if client is None:
        client = httpx.Client(timeout=5.0)
        close_client = True

    params = {
        "sort": sort,
        "direction": "-1",
        "limit": str(limit),
    }

    try:
        resp = client.get(HF_MODELS_URL, params=params)
        resp.raise_for_status()
        return parse_hf_models(resp.text)
    except (httpx.HTTPError, OSError) as exc:
        logger.warning("Failed to fetch HF trending models: %s", exc)
        return []
    finally:
        if close_client:
            client.close()


def fetch_hf_model_readme(
    model_id: str,
    client: Optional[httpx.Client] = None,
) -> Optional[str]:
    """Fetch raw markdown README of a Hugging Face model repository."""
    url = HF_RAW_README_URL.format(model_id=model_id)
    close_client = False
    if client is None:
        client = httpx.Client(timeout=5.0)
        close_client = True

    try:
        resp = client.get(url)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.text
    except Exception as exc:
        logger.warning("Failed to fetch HF README for %s: %s", model_id, exc)
        return None
    finally:
        if close_client:
            client.close()
