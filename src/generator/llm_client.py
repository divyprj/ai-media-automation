"""Local Ollama client with reasoning tag stripper and automatic heuristic fallback.

Connects to local Ollama server (http://localhost:11434).
Strips DeepSeek R1 `<think>...</think>` internal reasoning tags completely.
Automatically falls back to HeuristicContentGenerator if Ollama is unreachable,
times out (30s), or errors.
"""

import logging
import re
from typing import Any, Dict, Optional

import httpx

from src.config import get_settings
from src.contracts.enums import Platform
from src.contracts.schemas import DiscoveredItem
from src.generator.editorial_rules import (
    calculate_twitter_weight,
    clean_banned_patterns,
    format_x_post,
    format_x_thread,
    format_linkedin_post,
    replace_forbidden_dashes,
)
from src.generator.templates import HeuristicContentGenerator, PractitionerPromptTemplates

logger = logging.getLogger(__name__)


def strip_reasoning_tags(text: str) -> str:
    """Strip DeepSeek R1 <think>...</think> reasoning tags and contents.

    Handles:
    - Whitespace variations: <think >, <think\n>, etc.
    - Arbitrarily nested tags: <think>outer <think>inner</think> outer</think>
    - Unclosed tags: <think>unclosed thought...
    - Orphaned closing tags: </think>
    """
    if not text:
        return ""

    # Split text into tokens: alternating between non-tag text and <think...>/ </think...> tags
    tag_pattern = re.compile(r"(</?think(?:\s[^>]*)?>)", re.IGNORECASE)
    tokens = tag_pattern.split(text)

    result_parts = []
    depth = 0

    open_pattern = re.compile(r"^<think(?:\s[^>]*)?>$", re.IGNORECASE)
    close_pattern = re.compile(r"^</think(?:\s[^>]*)?>$", re.IGNORECASE)

    for token in tokens:
        if not token:
            continue
        if open_pattern.match(token):
            depth += 1
        elif close_pattern.match(token):
            if depth > 0:
                depth -= 1
            # If depth == 0, orphaned closing tag is dropped
        else:
            if depth == 0:
                result_parts.append(token)

    cleaned = "".join(result_parts).strip()
    # Strip any truncated opening tag at the end (e.g. "<think" or "<think ...")
    cleaned = re.sub(r"<think[\s\S]*$", "", cleaned, flags=re.IGNORECASE).strip()
    # Strip any remaining stray tags just in case
    cleaned = re.sub(r"</?think(?:\s[^>]*)?>?", "", cleaned, flags=re.IGNORECASE).strip()
    return cleaned


class OllamaClient:
    """Client for local Ollama instance with robust error handling and fallback."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: float = 30.0,
    ) -> None:
        settings = get_settings()
        self.base_url = (base_url or settings.ollama_base_url).rstrip("/")
        self.model = model or settings.ollama_model
        self.timeout = timeout
        self.fallback_generator = HeuristicContentGenerator

    def generate(
        self,
        prompt: str,
        system: Optional[str] = None,
        temperature: float = 0.7,
        format_json: bool = False,
    ) -> str:
        """Call Ollama /api/generate synchronously with 30s timeout and reasoning tag stripping."""
        url = f"{self.base_url}/api/generate"
        payload: Dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": temperature},
        }
        if system:
            payload["system"] = system
        if format_json:
            payload["format"] = "json"

        try:
            timeout_cfg = httpx.Timeout(self.timeout, connect=2.0)
            with httpx.Client(timeout=timeout_cfg) as client:
                resp = client.post(url, json=payload)
                resp.raise_for_status()
                data = resp.json()
                raw_response = data.get("response", "")
                cleaned = strip_reasoning_tags(raw_response)
                cleaned = replace_forbidden_dashes(cleaned)
                cleaned = clean_banned_patterns(cleaned)
                return cleaned
        except (httpx.HTTPError, httpx.TimeoutException, OSError, ValueError) as exc:
            logger.warning(
                "Ollama request to %s failed (%s). Triggering heuristic fallback.",
                url,
                exc,
            )
            return ""

    async def generate_async(
        self,
        prompt: str,
        system: Optional[str] = None,
        temperature: float = 0.7,
        format_json: bool = False,
    ) -> str:
        """Call Ollama /api/generate asynchronously with 30s timeout and reasoning tag stripping."""
        url = f"{self.base_url}/api/generate"
        payload: Dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": temperature},
        }
        if system:
            payload["system"] = system
        if format_json:
            payload["format"] = "json"

        try:
            timeout_cfg = httpx.Timeout(self.timeout, connect=2.0)
            async with httpx.AsyncClient(timeout=timeout_cfg) as client:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                data = resp.json()
                raw_response = data.get("response", "")
                cleaned = strip_reasoning_tags(raw_response)
                cleaned = replace_forbidden_dashes(cleaned)
                cleaned = clean_banned_patterns(cleaned)
                return cleaned
        except (httpx.HTTPError, httpx.TimeoutException, OSError, ValueError) as exc:
            logger.warning(
                "Async Ollama request to %s failed (%s). Triggering heuristic fallback.",
                url,
                exc,
            )
            return ""

    def generate_for_item(
        self,
        item: DiscoveredItem,
        platform: Platform,
        format_type: str = "single_post",
    ) -> str:
        """Generate platform-adapted content for an item with guaranteed offline fallback."""
        prompt = ""
        if platform == Platform.X:
            if format_type == "thread":
                prompt = PractitionerPromptTemplates.thread_prompt(item, num_tweets=4)
            else:
                prompt = PractitionerPromptTemplates.single_post_prompt(item)
        else:
            prompt = PractitionerPromptTemplates.linkedin_prompt(item)

        llm_output = self.generate(
            prompt=prompt,
            system=PractitionerPromptTemplates.SYSTEM_PROMPT,
        )

        # Fall back to HeuristicContentGenerator if Ollama returned empty or failed
        if not llm_output or len(llm_output.strip()) < 20:
            if platform == Platform.X:
                if format_type == "thread":
                    thread_tweets = self.fallback_generator.generate_x_thread(item, num_tweets=4)
                    return "\n\n[TWEET]\n\n".join(thread_tweets)
                return self.fallback_generator.generate_x_post(item)
            else:
                return self.fallback_generator.generate_linkedin_post(item)

        # Ensure post-processing constraints on LLM output
        llm_output = replace_forbidden_dashes(llm_output)
        llm_output = clean_banned_patterns(llm_output)

        if platform == Platform.X:
            if format_type == "single_post":
                return format_x_post(llm_output, source_url=item.source_url)
            elif format_type == "thread":
                if "[TWEET]" in llm_output:
                    tweets = [t.strip() for t in llm_output.split("[TWEET]") if t.strip()]
                else:
                    tweets = [t.strip() for t in llm_output.split("\n\n") if t.strip()]
                return "\n\n[TWEET]\n\n".join(format_x_thread(tweets, source_url=item.source_url))
        else:
            if len(llm_output) > 3000:
                llm_output = llm_output[:2997] + "..."

        return llm_output
