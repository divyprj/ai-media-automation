"""Mode B Manual Publishing Adapter (1-Click Clipboard & Web Intents)."""

import os
import urllib.parse
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field

from src.contracts.enums import Platform
from src.contracts.schemas import PublishJob
from src.publishing.adapters.base import BasePublisherAdapter, PublishResult


class ManualPayload(BaseModel):
    """Payload packaged for 1-click clipboard and browser intent workflow."""

    intent_url: str = Field(description="Formatted web intent URL for browser opening")
    clipboard_text: str = Field(description="Sanitized, 1-click copyable publication text")
    visual_path: Optional[str] = Field(default=None, description="Path to rendered visual card if present")
    instructions: str = Field(description="Step-by-step human instructions for publishing")
    platform: Platform = Field(description="Target social platform")
    character_count: int = Field(description="Length of post text")
    has_truncation_warning: bool = Field(default=False, description="Whether text exceeds platform limit")

    model_config = ConfigDict(populate_by_name=True)


class ManualAdapter(BasePublisherAdapter):
    """Mode B publisher: Generates formatted web intent URLs and copyable clipboard payloads."""

    def can_publish(self) -> bool:
        """Mode B requires zero credentials and is always operational."""
        return True

    def get_mode(self) -> str:
        """Return operational mode for ManualAdapter."""
        return "MODE_B"

    def generate_manual_payload(self, job: PublishJob) -> ManualPayload:
        """Generate platform-specific clipboard text, intent URL, and operator instructions."""
        raw_text = job.content.text.strip()
        # Enforce zero em dash invariant on clipboard text
        clean_text = raw_text.replace("—", ": ").replace("--", "-").replace("–", "-")
        url = job.content.attribution_url.strip() if job.content.attribution_url else ""
        visual_path = job.content.visual_path
        if visual_path and not os.path.exists(visual_path):
            visual_path = None

        if job.platform == Platform.X:
            return self._build_x_payload(clean_text, url, visual_path)
        else:
            return self._build_linkedin_payload(clean_text, url, visual_path)

    def publish(self, job: PublishJob) -> PublishResult:
        """Execute Mode B publishing: packaging payload and returning intent URL."""
        payload = self.generate_manual_payload(job)
        return PublishResult(
            success=True,
            post_id=None,
            post_url=payload.intent_url,
            error=None,
            mode="MODE_B",
            metadata={"manual_payload": payload.model_dump()},
        )

    def _build_x_payload(self, text: str, url: str, visual_path: Optional[str]) -> ManualPayload:
        params = {"text": text}
        # Avoid duplicate URL in intent if already inside body text
        if url and url not in text:
            params["url"] = url

        intent_url = f"https://twitter.com/intent/tweet?{urllib.parse.urlencode(params)}"
        char_count = len(text)
        has_warning = char_count > 280

        instructions = (
            "1. Click 'Copy to Clipboard' to copy post text.\n"
            "2. Click 'Open in X' to open the compose intent in your browser.\n"
        )
        if visual_path:
            instructions += f"3. Attach the generated visual card from: {visual_path}\n"
        else:
            instructions += "3. Verify post text formatting in the compose dialog.\n"
        instructions += (
            "4. Click 'Post' on X.\n"
            "5. Return here and click 'Mark as Published' to update status."
        )

        return ManualPayload(
            intent_url=intent_url,
            clipboard_text=text,
            visual_path=visual_path,
            instructions=instructions,
            platform=Platform.X,
            character_count=char_count,
            has_truncation_warning=has_warning,
        )

    def _build_linkedin_payload(self, text: str, url: str, visual_path: Optional[str]) -> ManualPayload:
        target_url = url or "https://www.linkedin.com"
        params = {"url": target_url}
        intent_url = f"https://www.linkedin.com/sharing/share-offsite/?{urllib.parse.urlencode(params)}"
        char_count = len(text)
        has_warning = char_count > 3000

        instructions = (
            "1. Click 'Copy to Clipboard' to copy full LinkedIn post text.\n"
            "2. Click 'Open in LinkedIn' to launch the share dialog with the source URL.\n"
            "3. Paste (Ctrl+V / Cmd+V) the copied text into the commentary box.\n"
        )
        if visual_path:
            instructions += f"4. Drag and drop the visual graphic from: {visual_path}\n"
        instructions += (
            "5. Click 'Post' on LinkedIn.\n"
            "6. Return here and click 'Mark as Published' to record publication."
        )

        return ManualPayload(
            intent_url=intent_url,
            clipboard_text=text,
            visual_path=visual_path,
            instructions=instructions,
            platform=Platform.LINKEDIN,
            character_count=char_count,
            has_truncation_warning=has_warning,
        )


ManualQueueAdapter = ManualAdapter
