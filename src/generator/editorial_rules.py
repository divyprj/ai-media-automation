"""Editorial rules, zero em-dash linter, banned patterns, and platform formatters.

Enforces:
1. Guaranteed zero em-dash compliance (\\u2014, \\u2013, \\u2015, \\u2012, --, ---) with contextual CLI flag preservation.
2. Banned pattern catalog: 26+ robotic AI phrases, hype emojis, generic hashtags.
3. Platform text formatters: Twitter-text v2 weighted counter (<=280), X thread chaining, LinkedIn long-form (<=3000).
"""

from dataclasses import dataclass, field
import re
from typing import List, Optional, Tuple


@dataclass
class DashViolation:
    """Detailed record of a forbidden dash glyph occurrence."""

    glyph: str
    unicode_name: str
    codepoint: str
    line_number: int
    char_index: int
    context: str


@dataclass
class LintResult:
    """Summary result of editorial linting."""

    is_clean: bool
    violations: List[str] = field(default_factory=list)


# Forbidden dash codepoints and glyphs
FORBIDDEN_DASH_GLYPHS = {
    "\u2014": "EM DASH",
    "\u2013": "EN DASH",
    "\u2015": "HORIZONTAL BAR",
    "\u2012": "FIGURE DASH",
}

# 26+ Robotic AI phrases and slop buzzwords
BANNED_PHRASES = [
    r"\bin today's fast-paced(?: ai)? world\b",
    r"\bin the fast-paced landscape\b",
    r"\bdelv(?:e|es|ed|ing)?\b",
    r"\bgame[ -]changer\b",
    r"\brevolutionary\b",
    r"\b(?:rich )?tapestry\b",
    r"\btestament to\b",
    r"\bbeacon of\b",
    r"\blook no further\b",
    r"\bwithout further ado\b",
    r"\bneedless to say\b",
    r"\bbuckle up\b",
    r"\bdid you know\??\b",
    r"\bstop scrolling\b",
    r"\bhear me out\b",
    r"\bmind[ -]blowing:?\b",
    r"\bhere's why this matters\b",
    r"\b(?:it's|it is) (?:important to remember|worth noting that)\b",
    r"\bin (?:summary|conclusion)\b",
    r"\bharnessing the power of\b",
    r"\bpivotal moment\b",
    r"\btreasure trove\b",
    r"\bdouble-edged sword\b",
    r"\bmust-have\b",
    r"\binsane breakthrough\b",
    r"\bcrushing it\b",
    r"\b10x your productivity\b",
    r"\bkill chatgpt\b",
    r"\brip google\b",
    r"\bchange everything forever\b",
]

# Forbidden hype/cringe emojis
FORBIDDEN_HYPE_EMOJIS = [
    "🔥", "🚀", "🤯", "👇", "🧵", "✨", "⚡", "💥", "🚨", "💣", "👀", "🧠", "💡", "📈", "💯"
]

# Generic hashtag spam
GENERIC_HASHTAGS = [
    r"#ai\b",
    r"#tech\b",
    r"#artificialintelligence\b",
    r"#machinelearning\b",
    r"#ml\b",
    r"#innovation\b",
    r"#future\b",
    r"#trending\b",
    r"#technews\b",
]


def _mask_cli_flags_and_code(text: str) -> Tuple[str, List[Tuple[str, str]]]:
    """Temporarily mask CLI flags like `--batch-size` and backticked code.

    This preserves CLI flags from being flagged or corrupted during dash scanning/replacement.
    """
    replacements: List[Tuple[str, str]] = []

    def mask_code(match: re.Match) -> str:
        token = f"__CODE_TOKEN_{len(replacements)}__"
        replacements.append((token, match.group(0)))
        return token

    # Mask backtick code blocks first
    masked = re.sub(r"`[^`]+`", mask_code, text)

    # Mask CLI flags in plain text e.g. `--batch-size`, `--model`, `--port 8000`
    def mask_cli_flag(match: re.Match) -> str:
        prefix = match.group(1)
        flag = match.group(2)
        token = f"__CLI_FLAG_{len(replacements)}__"
        replacements.append((token, flag))
        return f"{prefix}{token}"

    masked = re.sub(
        r"(^|[\s\"'(\[{])(--[a-zA-Z][a-zA-Z0-9_-]*(?:=[^\s]+)?)",
        mask_cli_flag,
        masked,
    )

    return masked, replacements


def _unmask_cli_flags_and_code(text: str, replacements: List[Tuple[str, str]]) -> str:
    """Restore masked tokens in reverse order."""
    for token, original in reversed(replacements):
        text = text.replace(token, original)
    return text


def scan_forbidden_dashes(text: str) -> List[DashViolation]:
    """Scan text for any forbidden dash glyphs, respecting CLI flags.

    Detects: \\u2014, \\u2013, \\u2015, \\u2012, ---, and unshielded --.
    """
    masked, _ = _mask_cli_flags_and_code(text)
    violations: List[DashViolation] = []

    lines = masked.splitlines(keepends=True)
    current_char_offset = 0

    for line_idx, line in enumerate(lines, start=1):
        # 1. Unicode dash glyphs
        for idx, ch in enumerate(line):
            if ch in FORBIDDEN_DASH_GLYPHS:
                global_idx = current_char_offset + idx
                ctx_start = max(0, global_idx - 30)
                ctx_end = min(len(text), global_idx + 30)
                context_str = text[ctx_start:ctx_end]
                violations.append(
                    DashViolation(
                        glyph=ch,
                        unicode_name=FORBIDDEN_DASH_GLYPHS[ch],
                        codepoint=f"U+{ord(ch):04X}",
                        line_number=line_idx,
                        char_index=global_idx,
                        context=context_str,
                    )
                )

        # 2. Triple hyphens
        for m in re.finditer(r"---", line):
            global_idx = current_char_offset + m.start()
            ctx_start = max(0, global_idx - 30)
            ctx_end = min(len(text), global_idx + 30)
            violations.append(
                DashViolation(
                    glyph="---",
                    unicode_name="TRIPLE HYPHEN-MINUS",
                    codepoint="U+002D*3",
                    line_number=line_idx,
                    char_index=global_idx,
                    context=text[ctx_start:ctx_end],
                )
            )

        # 3. Double hyphens (not masked as CLI flags)
        # Note: ignore matches that were part of ---
        line_no_triple = re.sub(r"---", "   ", line)
        for m in re.finditer(r"--", line_no_triple):
            global_idx = current_char_offset + m.start()
            ctx_start = max(0, global_idx - 30)
            ctx_end = min(len(text), global_idx + 30)
            violations.append(
                DashViolation(
                    glyph="--",
                    unicode_name="DOUBLE HYPHEN-MINUS",
                    codepoint="U+002D*2",
                    line_number=line_idx,
                    char_index=global_idx,
                    context=text[ctx_start:ctx_end],
                )
            )

        current_char_offset += len(line)

    return violations


def replace_forbidden_dashes(text: str) -> str:
    """Intelligently replace forbidden dashes with colons, commas, or parentheses.

    Transforms:
    - Paired parenthetical dashes -> parentheses: ` (clause) `
    - Numeric/date ranges -> `$1 to $2`
    - Start-of-line bullet dashes -> `• `
    - Connecting dashes -> `: ` or `, `
    - Double/triple hyphens -> `: `
    Preserves CLI flags such as `--batch-size`.
    Enforces post-replacement verification invariant.
    """
    masked, replacements = _mask_cli_flags_and_code(text)

    # 1. Start of line bullet indicator
    masked = re.sub(r"(?m)^[—–―‒-]\s+", "• ", masked)

    # 2. Numeric / Date ranges e.g. 10 — 20 or 2024–2026
    masked = re.sub(r"(\d+)\s*[—–―‒]\s*(\d+)", r"\1 to \2", masked)

    # 3. Paired parenthetical dashes: "word — interrupter — word" -> "word (interrupter) word"
    masked = re.sub(r"\s*[—–―‒]\s*([^—–―‒\n]+?)\s*[—–―‒]\s*", r" (\1) ", masked)

    # 4. Connecting/terminal dashes: "word — explanation" -> "word: explanation"
    masked = re.sub(r"\s*[—–―‒]\s*", r": ", masked)

    # 5. Triple or double hyphens (outside CLI flags)
    masked = re.sub(r"\s*---+?\s*", r": ", masked)
    masked = re.sub(r"\s*--\s*", r": ", masked)
    masked = re.sub(r"[—–―‒]+", ":", masked)

    # Restore CLI flags and code blocks
    fixed = _unmask_cli_flags_and_code(masked, replacements)

    # Normalize multiple colons or awkward spaces
    fixed = re.sub(r":\s*:\s*", r": ", fixed)
    fixed = re.sub(r"\(\s+", "(", fixed)
    fixed = re.sub(r"\s+\)", ")", fixed)
    fixed = re.sub(r"[ \t]+", " ", fixed).strip()

    # Post-replacement verification invariant: if any dash remains, do a hard clean
    remaining = scan_forbidden_dashes(fixed)
    if remaining:
        # Fallback replacement for any straggler
        for v in remaining:
            if v.glyph in ("--", "---"):
                fixed = fixed.replace(v.glyph, ":")
            else:
                fixed = fixed.replace(v.glyph, ":")
        fixed = re.sub(r":\s*:\s*", r": ", fixed)
        fixed = re.sub(r"[ \t]+", " ", fixed).strip()

    return fixed


def scan_banned_patterns(text: str) -> List[str]:
    """Scan text for robotic AI phrases, hype emojis, and generic hashtag stuffing."""
    found: List[str] = []
    text_lower = text.lower()

    # Check robotic phrases
    for pat in BANNED_PHRASES:
        match = re.search(pat, text_lower, re.IGNORECASE)
        if match:
            found.append(f"Robotic AI phrase: '{match.group(0)}'")

    # Check hype emojis
    for emoji in FORBIDDEN_HYPE_EMOJIS:
        if emoji in text:
            found.append(f"Forbidden hype emoji: '{emoji}'")

    # Check generic hashtags
    for htag in GENERIC_HASHTAGS:
        match = re.search(htag, text_lower)
        if match:
            found.append(f"Generic hashtag: '{match.group(0)}'")

    return found


def clean_banned_patterns(text: str) -> str:
    """Clean text by stripping robotic phrases, forbidden emojis, and generic hashtags."""
    cleaned = text

    # Strip robotic phrases
    for pat in BANNED_PHRASES:
        cleaned = re.sub(pat, "", cleaned, flags=re.IGNORECASE)

    # Strip forbidden hype emojis
    for emoji in FORBIDDEN_HYPE_EMOJIS:
        cleaned = cleaned.replace(emoji, "")

    # Strip generic hashtags
    for htag in GENERIC_HASHTAGS:
        cleaned = re.sub(htag, "", cleaned, flags=re.IGNORECASE)

    # Clean up excess spaces or empty lines
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def calculate_twitter_weight(text: str) -> int:
    """Calculate Twitter-Text v2 weighted character count.

    Rules:
    - Basic Latin (U+0000 to U+10FF): 1 weight.
    - CJK, full-width characters, emojis (cp > 0x10FF): 2 weight.
    - Any valid http:// or https:// URL: exactly 23 weighted characters (t.co normalization).
    """
    if not text:
        return 0

    url_regex = re.compile(r"https?://\S+")
    urls = url_regex.findall(text)
    text_without_urls = url_regex.sub("", text)

    weight = len(urls) * 23

    for ch in text_without_urls:
        cp = ord(ch)
        # Basic Latin, Latin-1 Supplement, Latin Extended A/B up to U+10FF count as 1
        if cp <= 0x10FF:
            weight += 1
        else:
            # CJK, non-Latin, Emojis, Symbols count as 2
            weight += 2

    return weight


class TwitterTextCalculator:
    """Platform character counter and thread paginator adhering to Twitter-Text v2."""

    def calculate_weighted_length(self, text: str) -> int:
        """Return the weighted length of the text."""
        return calculate_twitter_weight(text)

    def is_valid_x_post(self, text: str) -> bool:
        """Validate if text satisfies 1 <= weight <= 280."""
        if not text or not text.strip():
            return False
        weight = self.calculate_weighted_length(text)
        return 1 <= weight <= 280

    def truncate_to_fit(self, text: str, limit: int = 280) -> str:
        """Truncate text to fit within the given weighted character limit."""
        if self.calculate_weighted_length(text) <= limit:
            return text

        words = text.split()
        truncated: List[str] = []
        for word in words:
            candidate = " ".join(truncated + [word])
            if self.calculate_weighted_length(candidate) <= limit:
                truncated.append(word)
            else:
                break

        res = " ".join(truncated)
        # If still over or empty, trim character by character
        while self.calculate_weighted_length(res) > limit and len(res) > 0:
            res = res[:-1].strip()

        return res

    def paginate_thread(self, text: str, max_tweets: int = 5) -> List[str]:
        """Paginate a long text into 3-7 chained tweets with (1/N) to (N/N) tags."""
        words = text.split()
        chunks: List[str] = []
        curr: List[str] = []

        for w in words:
            curr.append(w)
            # Estimate roughly ~180 chars to leave ample room for URLs and pagination tags
            if len(" ".join(curr)) > 150:
                chunks.append(" ".join(curr))
                curr = []
        if curr:
            chunks.append(" ".join(curr))

        # Enforce max_tweets boundary
        if len(chunks) > max_tweets:
            overflow = " ".join(chunks[max_tweets - 1 :])
            chunks = chunks[: max_tweets - 1] + [overflow]

        total = len(chunks)
        results: List[str] = []
        for i, chunk in enumerate(chunks):
            tag = f"({i + 1}/{total})"
            tweet = f"{chunk} {tag}".strip()
            # If over 280, truncate cleanly
            if self.calculate_weighted_length(tweet) > 280:
                available = 280 - self.calculate_weighted_length(f" {tag}") - 3
                fitted = self.truncate_to_fit(chunk, available)
                tweet = f"{fitted}... {tag}"
            results.append(tweet)

        return results


def format_x_post(text: str, source_url: Optional[str] = None) -> str:
    """Format a single X post, ensuring <=280 weighted characters and 0 em-dashes."""
    calc = TwitterTextCalculator()
    clean_text = replace_forbidden_dashes(text)
    clean_text = clean_banned_patterns(clean_text)

    if source_url and source_url not in clean_text:
        suffix = f"\n\nSource: {source_url}"
        # URL counts as 23, newline as 2
        suffix_weight = calculate_twitter_weight(suffix)
        max_body_weight = 280 - suffix_weight
        fitted_body = calc.truncate_to_fit(clean_text, max_body_weight)
        return f"{fitted_body}{suffix}"
    else:
        return calc.truncate_to_fit(clean_text, 280)


def format_x_thread(sections: List[str], source_url: Optional[str] = None) -> List[str]:
    """Format 3 to 7 chained tweets with (1/N) to (N/N) tags."""
    calc = TwitterTextCalculator()
    total = len(sections)
    if total < 3:
        total = 3
        # Expand sections if too few
        while len(sections) < 3:
            sections.append("Continuing architectural analysis and production implications.")
    elif total > 7:
        sections = sections[:6] + [" ".join(sections[6:])]
        total = 7

    tweets: List[str] = []
    for idx, sec in enumerate(sections, start=1):
        clean_sec = replace_forbidden_dashes(sec)
        clean_sec = clean_banned_patterns(clean_sec)

        tag = f"({idx}/{total})"
        if idx == total and source_url and source_url not in clean_sec:
            post = f"{clean_sec}\n\nCanonical paper & repo: {source_url} {tag}"
        else:
            post = f"{clean_sec} {tag}"

        if calc.calculate_weighted_length(post) > 280:
            allowed = 280 - calc.calculate_weighted_length(f" {tag}") - 4
            post = f"{calc.truncate_to_fit(clean_sec, allowed)}... {tag}"

        tweets.append(post)

    return tweets


class LinkedInFormatter:
    """Format professional long-form updates for LinkedIn adhering to <=3000 chars."""

    def format_post(self, title: str, body: str, source_url: str) -> str:
        """Format LinkedIn post with a crisp hook before the fold (<=200 chars)."""
        clean_title = replace_forbidden_dashes(title)
        clean_title = clean_banned_patterns(clean_title)
        clean_body = replace_forbidden_dashes(body)
        clean_body = clean_banned_patterns(clean_body)

        hook = f"{clean_title}: Empirical AI breakthrough."
        if len(hook) > 200:
            hook = hook[:197] + "..."

        post = f"{hook}\n\n{clean_body}\n\nSource: {source_url}"
        if len(post) > 3000:
            allowed_body = 3000 - len(hook) - len(f"\n\n\n\nSource: {source_url}") - 3
            post = f"{hook}\n\n{clean_body[:allowed_body]}...\n\nSource: {source_url}"

        return post

    def format_linkedin_post(
        self,
        title: str,
        summary: str,
        analysis: str,
        takeaways: List[str],
        source_url: str,
    ) -> str:
        """Format full structured LinkedIn post for Divyansh Prajapati."""
        clean_title = replace_forbidden_dashes(title)
        clean_summary = replace_forbidden_dashes(summary)
        clean_analysis = replace_forbidden_dashes(analysis)

        hook = f"{clean_title}: Architectural Breakdown for AI Builders"
        if len(hook) > 190:
            hook = hook[:187] + "..."

        bullets = "\n".join(f"• {replace_forbidden_dashes(t)}" for t in takeaways)

        body = (
            f"{hook}\n\n"
            f"Executive Context:\n{clean_summary}\n\n"
            f"Architectural Analysis:\n{clean_analysis}\n\n"
            f"Key Takeaways for Builders:\n{bullets}\n\n"
            f"Source & Implementation: {source_url}\n\n"
            f"What trade-offs are you seeing in production? Let's discuss in the comments."
        )

        body = clean_banned_patterns(body)
        if len(body) > 3000:
            body = body[:2997] + "..."

        return body

    def is_valid_linkedin_length(self, text: str) -> bool:
        """Validate if text satisfies 1 <= length <= 3000."""
        return 1 <= len(text) <= 3000

    def wrap_long_tokens(self, text: str, max_token_len: int = 80) -> str:
        """Wrap or split unbreakable tokens longer than max_token_len."""
        tokens = text.split()
        wrapped: List[str] = []
        for t in tokens:
            if len(t) > max_token_len:
                chunks = [t[i : i + max_token_len] for i in range(0, len(t), max_token_len)]
                wrapped.append("\n".join(chunks))
            else:
                wrapped.append(t)
        return " ".join(wrapped)


def format_linkedin_post(
    title: str, summary: str, analysis: str, takeaways: List[str], source_url: str
) -> str:
    """Module-level function to format structured LinkedIn post."""
    formatter = LinkedInFormatter()
    return formatter.format_linkedin_post(title, summary, analysis, takeaways, source_url)


class EditorialLinter:
    """Full-featured linter for zero-em-dash, banned phrases, emoji limits, and sanitization."""

    def scan_dashes(self, text: str) -> LintResult:
        """Scan text for forbidden dashes, respecting CLI flags in backticks or arguments."""
        violations = scan_forbidden_dashes(text)
        violation_msgs = [
            f"Forbidden dash found: {v.glyph!r} ({v.unicode_name}) at line {v.line_number}"
            for v in violations
        ]
        return LintResult(is_clean=len(violations) == 0, violations=violation_msgs)

    def replace_forbidden_dashes(self, text: str) -> str:
        """Intelligently replace forbidden dashes."""
        return replace_forbidden_dashes(text)

    def contains_zero_width(self, text: str) -> bool:
        """Check for zero-width spaces or hidden Unicode characters."""
        return bool(re.search(r"[\u200B-\u200F\uFEFF\u202A-\u202E]", text))

    def validate_emoji_count(self, text: str, max_allowed: int = 3) -> bool:
        """Validate emoji count does not exceed max_allowed."""
        emoji_pattern = re.compile(
            r"[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF\U0001F1E0-\U0001F1FF]"
        )
        emojis = emoji_pattern.findall(text)
        return len(emojis) <= max_allowed

    def sanitize_null_bytes(self, text: str) -> str:
        """Sanitize embedded null bytes."""
        return text.replace("\x00", "")

    def strip_control_chars(self, text: str) -> str:
        """Strip unprintable ASCII control characters."""
        return "".join(ch for ch in text if ch >= " " or ch in "\n\r\t")

    def scan_banned_phrases(self, text: str) -> List[str]:
        """Scan text for banned robotic AI phrases."""
        return scan_banned_patterns(text)
