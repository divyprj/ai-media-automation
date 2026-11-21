"""4-Layer prompt injection defense and input sanitization engine.

Defense in Depth:
- Layer 1: Zero-width Unicode stripping and regex injection pattern scanning
- Layer 2: XML boundary bracket escaping (< to &lt;, > to &gt;)
- Layer 3: Untrusted content sandboxing inside immutable <untrusted_content> tags
- Layer 4: Output gate validator blocking leaked system commands or attack tokens
"""

import json
import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from src.contracts.schemas import DiscoveredItem

logger = logging.getLogger(__name__)

# Zero-width spaces, joiners, bi-di overrides, invisible characters, and BOM markers
ZERO_WIDTH_PATTERN = re.compile(
    r"[\u200B-\u200F\uFEFF\u202A-\u202E\u2060-\u2069\u034F\u00AD\u180E\uFFF9-\uFFFB]",
    re.UNICODE,
)

INJECTION_SIGNATURES = [
    (re.compile(r"(?:ignore|disregard|forget|override|bypass)\s+(?:all\s+)?(?:the\s+)?(?:previous\s+|prior\s+|system\s+|ethical\s+|safety\s+)?(?:instructions|directives|rules|constraints)", re.IGNORECASE), "ignore_previous_instructions"),
    (re.compile(r"<\s*system\s*>", re.IGNORECASE), "xml_system_tag"),
    (re.compile(r"<\s*/\s*untrusted_content\s*>", re.IGNORECASE), "xml_sandbox_breakout"),
    (re.compile(r"\[\s*INST\s*\]", re.IGNORECASE), "llama_inst_tag"),
    (re.compile(r"<\|im_start\|>", re.IGNORECASE), "chatml_im_start"),
    (re.compile(r"you\s+(?:are\s+now|will\s+now\s+act\s+as)\s+(?:a\s+|an\s+)?(?:totally\s+)?(?:dan|unrestricted|ai\s+with\s+no\s+rules)", re.IGNORECASE), "dan_persona_switch"),
    (re.compile(r"\b(?:delete\s+from|drop\s+table|drop\s+database|truncate\s+table|(?:delete|drop)\s+(?:all\s+)?(?:records|tables?|database))\b", re.IGNORECASE), "destructive_db_command"),
    (re.compile(r"\b(?:eval|exec)\s*\(", re.IGNORECASE), "eval_code_injection"),
    (re.compile(r"\bbase64_decode\b", re.IGNORECASE), "base64_decode_call"),
]

BANNED_OUTPUT_TOKENS = [
    "pwned",
    "system prompt:",
    "eval(",
    "exec(",
    "base64_decode",
    "delete records",
    "delete all records",
    "drop table",
    "<system>",
    "</system>",
    "ignore previous instructions",
    "ignore all previous",
    "<|im_start|>",
    "[inst]",
]

BANNED_OUTPUT_PATTERNS = [
    (re.compile(r"\b(?:eval|exec)\s*\(", re.IGNORECASE), "eval_or_exec_call"),
    (re.compile(r"\bbase64_decode\s*\(?", re.IGNORECASE), "base64_decode_call"),
    (re.compile(r"\b(?:delete\s+from|drop\s+table|drop\s+database|truncate\s+table)\b", re.IGNORECASE), "dangerous_db_command"),
    (re.compile(r"\b(?:delete|drop)\s+(?:all\s+)?(?:records|tables?|database)\b", re.IGNORECASE), "destructive_db_command"),
    (re.compile(r"\brm\s+-rf\b", re.IGNORECASE), "dangerous_shell_rm_rf"),
    (re.compile(r"\bos\.system\s*\(", re.IGNORECASE), "dangerous_os_system"),
    (re.compile(r"\bsubprocess\.", re.IGNORECASE), "dangerous_subprocess"),
    (re.compile(r"(?:ignore|disregard|forget|override|bypass)\s+(?:all\s+)?(?:the\s+)?(?:previous\s+|prior\s+|system\s+|ethical\s+|safety\s+)?(?:instructions|directives|rules|constraints)", re.IGNORECASE), "ignore_instructions"),
    (re.compile(r"<\s*/?\s*system\s*>", re.IGNORECASE), "system_tag"),
    (re.compile(r"<\|im_start\|>", re.IGNORECASE), "chatml_tag"),
    (re.compile(r"\[\s*inst\s*\]", re.IGNORECASE), "llama_inst_tag"),
    (re.compile(r"\bpwned\b", re.IGNORECASE), "pwned_token"),
    (re.compile(r"\bsystem\s+prompt\s*:", re.IGNORECASE), "system_prompt_leak"),
]


class InputSanitizer:
    """Multi-layer input sanitizer protecting against prompt injections and malicious payloads."""

    def strip_zero_width(self, text: str) -> str:
        """Layer 1: Strip zero-width spaces, BOMs, and hidden directional joiners."""
        if not text:
            return ""
        return ZERO_WIDTH_PATTERN.sub("", text)

    def escape_xml_brackets(self, text: str) -> str:
        """Layer 2: Escape XML tag boundary brackets (< and >) to prevent sandbox breakout."""
        if not text:
            return ""
        return text.replace("<", "&lt;").replace(">", "&gt;")

    def scan_injection_risks(self, text: str) -> Tuple[bool, List[str]]:
        """Scan text for adversarial prompt injection patterns."""
        if not text:
            return False, []

        detected: List[str] = []
        if ZERO_WIDTH_PATTERN.search(text):
            detected.append("zero_width_hidden_chars")

        for regex, name in INJECTION_SIGNATURES:
            if regex.search(text):
                detected.append(name)

        return len(detected) > 0, detected

    def wrap_untrusted(self, text: str, source_id: str = "src_1") -> str:
        """Layer 2/3: Enclose sanitized untrusted content inside isolated XML sandbox tags."""
        escaped_text = self.escape_xml_brackets(text)
        safe_source_id = re.sub(r"[^\w\-]", "", source_id)
        return f'<untrusted_content source_id="{safe_source_id}">{escaped_text}</untrusted_content>'

    def decode_constrained_json(
        self, text: str, allowed_keys: Optional[Set[str]] = None
    ) -> Dict[str, Any]:
        """Layer 3: Parse JSON output and filter exclusively to allowed schema keys."""
        if not text or not text.strip():
            return {}

        raw_text = text.strip()
        # Strip markdown fences if present
        if raw_text.startswith("```"):
            lines = raw_text.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            raw_text = "\n".join(lines).strip()

        try:
            data = json.loads(raw_text)
            if not isinstance(data, dict):
                return {}
            if allowed_keys is not None:
                return {k: v for k, v in data.items() if k in allowed_keys}
            return data
        except (json.JSONDecodeError, ValueError, TypeError) as err:
            logger.debug("Failed to decode constrained JSON: %s", err)
            return {}

    def passes_output_gate(self, text: str) -> bool:
        """Layer 4: Validate generated text to guarantee no leaked injection tokens or commands."""
        if not text:
            return True

        clean_text = self.strip_zero_width(text)
        lower_text = clean_text.lower()

        for token in BANNED_OUTPUT_TOKENS:
            if token in lower_text:
                logger.warning("Output gate violation detected: '%s' found in output.", token)
                return False

        for pattern, name in BANNED_OUTPUT_PATTERNS:
            if pattern.search(clean_text):
                logger.warning("Output gate violation detected: pattern '%s' matched in output.", name)
                return False

        return True

    def sanitize_item(self, item: DiscoveredItem) -> DiscoveredItem:
        """Sanitize a DiscoveredItem in-place: strip zero-width characters and flag injection risks."""
        clean_title = self.strip_zero_width(item.title)
        clean_summary = self.strip_zero_width(item.summary)

        # Scan for injection risks
        has_risk_title, risks_title = self.scan_injection_risks(item.title)
        has_risk_summary, risks_summary = self.scan_injection_risks(item.summary)
        has_risk = has_risk_title or has_risk_summary

        item.title = clean_title
        item.summary = clean_summary

        if has_risk:
            item.raw_metadata["has_injection_risk"] = True
            item.raw_metadata["injection_alerts"] = list(set(risks_title + risks_summary))

        return item
