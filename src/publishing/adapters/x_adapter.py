"""Official X (Twitter) API v2 Free Tier / Developer API publisher adapter."""

import base64
import hashlib
import hmac
import secrets
import time
import urllib.parse
from typing import Any, Dict, Optional
import httpx

from src.config import Settings, get_settings
from src.contracts.enums import Platform
from src.contracts.schemas import PublishJob
from src.publishing.adapters.base import BasePublisherAdapter, PublishResult
from src.publishing.adapters.manual_adapter import ManualAdapter


class RateLimitExceeded(Exception):
    """Raised when platform rate limit is exceeded."""

    def __init__(self, retry_after: float):
        super().__init__(f"Rate limit exceeded. Retry after {retry_after} seconds.")
        self.retry_after = retry_after


class XAdapter(BasePublisherAdapter):
    """Official X API v2 publisher utilizing POST /2/tweets."""

    API_URL = "https://api.twitter.com/2/tweets"

    def __init__(self, settings: Optional[Settings] = None, manual_fallback: bool = True):
        self.settings = settings or get_settings()
        self.manual_fallback = manual_fallback
        self.manual_adapter = ManualAdapter()

    def can_publish(self) -> bool:
        """Check if complete OAuth credentials are configured."""
        s = self.settings
        if not s:
            return False
        return bool(
            s.x_api_key and s.x_api_secret and s.x_access_token and s.x_access_secret
        )

    def publish(self, job: PublishJob) -> PublishResult:
        """Publish a tweet to X using official API v2 endpoint or fallback gracefully."""
        if job.platform != Platform.X:
            return PublishResult(
                success=False,
                error=f"Invalid platform for XAdapter: {job.platform}",
                mode="MODE_A",
            )

        if not self.can_publish():
            if self.manual_fallback:
                return self.manual_adapter.publish(job)
            return PublishResult(
                success=False,
                error="X API credentials missing; cannot publish via Mode A.",
                mode="MODE_A",
            )

        text = job.content.text.strip()
        if not text:
            return PublishResult(
                success=False,
                error="Tweet content text cannot be empty.",
                mode="MODE_A",
            )

        # Build OAuth 1.0a authorization header
        auth_header = self._build_oauth1_header("POST", self.API_URL)
        headers = {
            "Authorization": auth_header,
            "Content-Type": "application/json",
            "User-Agent": f"PersonalAIAutomation/{self.settings.owner_handle}",
        }
        payload = {"text": text}

        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.post(self.API_URL, json=payload, headers=headers)

                if response.status_code == 201:
                    data = response.json().get("data", {})
                    tweet_id = data.get("id")
                    return PublishResult(
                        success=True,
                        post_id=tweet_id,
                        post_url=f"https://x.com/i/status/{tweet_id}",
                        mode="MODE_A",
                        metadata=data,
                    )

                if response.status_code == 429:
                    backoff = self._parse_rate_limit(response.headers)
                    if self.manual_fallback:
                        res = self.manual_adapter.publish(job)
                        res.error = f"X API rate limited (429). Falling back to Mode B. Reset in {backoff:.1f}s."
                        res.rate_limit_reset = backoff
                        return res
                    return PublishResult(
                        success=False,
                        error=f"X API rate limit exceeded (429). Retry after {backoff:.1f}s.",
                        mode="MODE_A",
                        rate_limit_reset=backoff,
                    )

                error_detail = response.text
                try:
                    error_json = response.json()
                    error_detail = error_json.get("detail") or error_json.get("title") or error_detail
                except Exception:
                    pass

                return PublishResult(
                    success=False,
                    error=f"X API error (HTTP {response.status_code}): {error_detail}",
                    mode="MODE_A",
                )

        except httpx.RequestError as exc:
            if self.manual_fallback:
                res = self.manual_adapter.publish(job)
                res.error = f"Network error ({exc}). Routed to Mode B Manual Queue."
                return res
            return PublishResult(
                success=False,
                error=f"Network error communicating with X API: {str(exc)}",
                mode="MODE_A",
            )

    def _build_oauth1_header(self, method: str, url: str) -> str:
        s = self.settings
        nonce = secrets.token_hex(16)
        timestamp = str(int(time.time()))
        params = {
            "oauth_consumer_key": s.x_api_key,
            "oauth_nonce": nonce,
            "oauth_signature_method": "HMAC-SHA1",
            "oauth_timestamp": timestamp,
            "oauth_token": s.x_access_token,
            "oauth_version": "1.0",
        }
        encoded_pairs = [
            (urllib.parse.quote(str(k), safe=""), urllib.parse.quote(str(v), safe=""))
            for k, v in sorted(params.items())
        ]
        param_str = "&".join(f"{k}={v}" for k, v in encoded_pairs)
        base_string = f"{method.upper()}&{urllib.parse.quote(url, safe='')}&{urllib.parse.quote(param_str, safe='')}"
        signing_key = f"{urllib.parse.quote(s.x_api_secret or '', safe='')}&{urllib.parse.quote(s.x_access_secret or '', safe='')}"
        sig = base64.b64encode(
            hmac.new(signing_key.encode("utf-8"), base_string.encode("utf-8"), hashlib.sha1).digest()
        ).decode("utf-8")
        params["oauth_signature"] = sig
        parts = [
            f'{urllib.parse.quote(str(k), safe="")}="{urllib.parse.quote(str(v), safe="")}"'
            for k, v in sorted(params.items())
        ]
        return "OAuth " + ", ".join(parts)

    def _parse_rate_limit(self, headers: Any) -> float:
        if "retry-after" in headers:
            try:
                return max(0.0, float(headers["retry-after"]))
            except (ValueError, TypeError):
                pass
        if "x-rate-limit-reset" in headers:
            try:
                target = float(headers["x-rate-limit-reset"])
                return max(0.0, target - time.time())
            except (ValueError, TypeError):
                pass
        return 900.0
