"""Official LinkedIn Share / Community Management API publisher adapter."""

import os
from typing import Any, Dict, Optional
import httpx

from src.contracts.enums import Platform
from src.contracts.schemas import PublishJob
from src.publishing.adapters.base import BasePublisherAdapter, PublishResult
from src.publishing.adapters.manual_adapter import ManualAdapter


class LinkedInAdapter(BasePublisherAdapter):
    """Official LinkedIn UGC Post / Community Management publisher."""

    UGC_POSTS_URL = "https://api.linkedin.com/v2/ugcPosts"

    def __init__(
        self,
        access_token: Optional[str] = None,
        author_urn: Optional[str] = None,
        manual_fallback: bool = True,
    ):
        self.access_token = access_token or os.environ.get("LINKEDIN_ACCESS_TOKEN")
        self.author_urn = author_urn or os.environ.get("LINKEDIN_AUTHOR_URN")
        self.manual_fallback = manual_fallback
        self.manual_adapter = ManualAdapter()

    def can_publish(self) -> bool:
        """Check if LinkedIn access token and author URN are configured."""
        return bool(self.access_token and self.author_urn)

    def publish(self, job: PublishJob) -> PublishResult:
        """Publish post to LinkedIn via REST API or fallback to Mode B."""
        if job.platform != Platform.LINKEDIN:
            return PublishResult(
                success=False,
                error=f"Invalid platform for LinkedInAdapter: {job.platform}",
                mode="MODE_A",
            )

        if not self.can_publish():
            if self.manual_fallback:
                return self.manual_adapter.publish(job)
            return PublishResult(
                success=False,
                error="LinkedIn credentials unconfigured; cannot publish via Mode A.",
                mode="MODE_A",
            )

        text = job.content.text.strip()
        if not text:
            return PublishResult(
                success=False,
                error="LinkedIn post text cannot be empty.",
                mode="MODE_A",
            )

        author = self.author_urn or ""
        if not author.startswith("urn:li:"):
            author = f"urn:li:person:{author}"

        payload: Dict[str, Any] = {
            "author": author,
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {"text": text},
                    "shareMediaCategory": "NONE",
                }
            },
            "visibility": {
                "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"
            },
        }

        # If attribution URL exists, format as ARTICLE share
        if job.content.attribution_url:
            payload["specificContent"]["com.linkedin.ugc.ShareContent"]["shareMediaCategory"] = "ARTICLE"
            payload["specificContent"]["com.linkedin.ugc.ShareContent"]["media"] = [
                {
                    "status": "READY",
                    "originalUrl": job.content.attribution_url,
                    "title": {"text": text[:60]},
                }
            ]

        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "X-Restli-Protocol-Version": "2.0.0",
            "Content-Type": "application/json",
        }

        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.post(self.UGC_POSTS_URL, json=payload, headers=headers)

                if response.status_code == 201:
                    post_urn = response.headers.get("x-restli-id") or response.json().get("id", "")
                    return PublishResult(
                        success=True,
                        post_id=post_urn,
                        post_url=f"https://www.linkedin.com/feed/update/{post_urn}/",
                        mode="MODE_A",
                    )

                if response.status_code == 429:
                    backoff = float(response.headers.get("retry-after", "60"))
                    if self.manual_fallback:
                        res = self.manual_adapter.publish(job)
                        res.error = f"LinkedIn rate limited (429). Routed to Mode B. Backoff: {backoff}s."
                        res.rate_limit_reset = backoff
                        return res
                    return PublishResult(
                        success=False,
                        error=f"LinkedIn rate limit exceeded (429). Retry after {backoff}s.",
                        mode="MODE_A",
                        rate_limit_reset=backoff,
                    )

                return PublishResult(
                    success=False,
                    error=f"LinkedIn API error (HTTP {response.status_code}): {response.text}",
                    mode="MODE_A",
                )

        except httpx.RequestError as exc:
            if self.manual_fallback:
                res = self.manual_adapter.publish(job)
                res.error = f"Network error ({exc}). Routed to Mode B."
                return res
            return PublishResult(
                success=False,
                error=f"Network error communicating with LinkedIn: {str(exc)}",
                mode="MODE_A",
            )
