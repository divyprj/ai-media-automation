"""Editorial, visual generation, and content validation engine for @divyprjai.

Unifying facade integrating:
- Editorial rules & anti-slop linters
- Twitter-text v2 and LinkedIn formatters
- Local Ollama client & heuristic fallback
- Matplotlib & Pillow programmatic 16:9 dark-mode visual assets
"""

from typing import List, Optional
from pydantic import BaseModel, Field

from src.contracts.enums import Platform
from src.contracts.schemas import DiscoveredItem, GeneratedContent
from src.generator.editorial_rules import (
    DashViolation,
    EditorialLinter,
    LinkedInFormatter,
    LintResult,
    TwitterTextCalculator,
    calculate_twitter_weight,
    clean_banned_patterns,
    format_linkedin_post,
    format_x_post,
    format_x_thread,
    replace_forbidden_dashes,
    scan_banned_patterns,
    scan_forbidden_dashes,
)
from src.generator.llm_client import OllamaClient, strip_reasoning_tags
from src.generator.templates import (
    HeuristicContentGenerator,
    PractitionerPromptTemplates,
)
from src.generator.visuals import VisualGenerator


class ValidationResult(BaseModel):
    """Validation report for post drafts against platform and editorial criteria."""

    is_valid: bool = Field(description="Whether the text passes all platform and editorial constraints")
    errors: List[str] = Field(default_factory=list, description="List of validation failure explanations")
    weighted_count: int = Field(description="Calculated platform character or weighted count")
    has_em_dash: bool = Field(default=False, description="Whether forbidden dashes were detected")
    banned_patterns: List[str] = Field(default_factory=list, description="Detected robotic AI phrases or hype tokens")


class EditorialEngine:
    """Unified editorial generator and validator facade."""

    def __init__(
        self,
        llm_client: Optional[OllamaClient] = None,
        visual_generator: Optional[VisualGenerator] = None,
    ) -> None:
        self.llm_client = llm_client or OllamaClient()
        self.visual_generator = visual_generator or VisualGenerator()
        self.twitter_calc = TwitterTextCalculator()
        self.linkedin_formatter = LinkedInFormatter()
        self.linter = EditorialLinter()

    def validate_text(self, text: str, platform: Platform) -> ValidationResult:
        """Validate text against zero em-dash rules, banned patterns, and platform length."""
        errors: List[str] = []
        banned: List[str] = []
        has_em_dash = False

        if platform == Platform.X and "[TWEET]" in text:
            tweet_blocks = [t.strip() for t in text.split("[TWEET]") if t.strip()]
            if not tweet_blocks:
                errors.append("X thread cannot be empty.")
                weight = 0
            else:
                weights: List[int] = []
                for idx, t in enumerate(tweet_blocks, start=1):
                    # Zero em-dash check per tweet
                    t_dashes = scan_forbidden_dashes(t)
                    if t_dashes:
                        has_em_dash = True
                        for v in t_dashes:
                            errors.append(f"Tweet {idx} forbidden dash violation: {v.glyph!r} at line {v.line_number}")

                    # Banned patterns per tweet
                    t_banned = scan_banned_patterns(t)
                    if t_banned:
                        for b in t_banned:
                            if b not in banned:
                                banned.append(b)
                        errors.append(f"Tweet {idx} banned pattern detected: {', '.join(t_banned)}")

                    # Weight check per tweet
                    t_weight = calculate_twitter_weight(t)
                    weights.append(t_weight)
                    if t_weight == 0:
                        errors.append(f"Tweet {idx} cannot be empty.")
                    elif t_weight > 280:
                        errors.append(f"Tweet {idx} exceeds 280 weighted characters (current: {t_weight}).")

                weight = max(weights) if weights else 0
        else:
            # 1. Zero em-dash check
            dash_violations = scan_forbidden_dashes(text)
            has_em_dash = len(dash_violations) > 0
            if has_em_dash:
                for v in dash_violations:
                    errors.append(f"Forbidden dash violation: {v.glyph!r} at line {v.line_number}")

            # 2. Banned patterns & slop
            banned = scan_banned_patterns(text)
            if banned:
                errors.extend(banned)

            # 3. Platform length check
            if platform == Platform.X:
                weight = calculate_twitter_weight(text)
                if weight == 0:
                    errors.append("X post cannot be empty.")
                elif weight > 280:
                    errors.append(f"X post exceeds 280 weighted characters (current: {weight}).")
            else:
                weight = len(text)
                if weight == 0:
                    errors.append("LinkedIn post cannot be empty.")
                elif weight > 3000:
                    errors.append(f"LinkedIn post exceeds 3,000 characters (current: {weight}).")

        is_valid = len(errors) == 0
        return ValidationResult(
            is_valid=is_valid,
            errors=errors,
            weighted_count=weight,
            has_em_dash=has_em_dash,
            banned_patterns=banned,
        )

    def generate(
        self,
        item: DiscoveredItem,
        platform: Platform,
        format_type: str = "single_post",
        generate_visual: bool = True,
    ) -> GeneratedContent:
        """Generate publication-ready content and accompanying visuals for an item."""
        # 1. Generate text body
        raw_text = self.llm_client.generate_for_item(
            item=item,
            platform=platform,
            format_type=format_type,
        )

        # 2 & 3. Platform-specific processing & cleaning
        if platform == Platform.X:
            if format_type == "thread":
                if "[TWEET]" in raw_text:
                    tweet_blocks = [t.strip() for t in raw_text.split("[TWEET]") if t.strip()]
                else:
                    tweet_blocks = [t.strip() for t in raw_text.split("\n\n") if t.strip()]
                    tweet_blocks = format_x_thread(tweet_blocks, source_url=item.source_url)

                processed_tweets: List[str] = []
                for t in tweet_blocks:
                    clean_t = replace_forbidden_dashes(t)
                    clean_t = clean_banned_patterns(clean_t)
                    if calculate_twitter_weight(clean_t) > 280:
                        clean_t = self.twitter_calc.truncate_to_fit(clean_t, 280)
                    processed_tweets.append(clean_t)

                clean_text = "\n\n[TWEET]\n\n".join(processed_tweets)
                weights = [calculate_twitter_weight(t) for t in processed_tweets]
                count = max(weights) if weights else 0
            else:
                clean_text = replace_forbidden_dashes(raw_text)
                clean_text = clean_banned_patterns(clean_text)
                clean_text = format_x_post(clean_text, source_url=item.source_url)
                count = calculate_twitter_weight(clean_text)
        else:
            clean_text = replace_forbidden_dashes(raw_text)
            clean_text = clean_banned_patterns(clean_text)
            if len(clean_text) > 3000:
                clean_text = clean_text[:2997] + "..."
            count = len(clean_text)

        # 4. Generate accompanying visual if requested
        visual_path: Optional[str] = None
        if generate_visual:
            try:
                # Check if item metadata has quantitative benchmark scores
                meta = item.raw_metadata or {}
                if "benchmarks" in meta and isinstance(meta["benchmarks"], dict):
                    visual_path = self.visual_generator.create_benchmark_chart(
                        title=f"{item.title[:45]} Evaluation",
                        scores=meta["benchmarks"],
                        source_url=item.source_url,
                    )
                else:
                    # Render social metric card
                    metric_hint = HeuristicContentGenerator._extract_metric_hint(item)
                    visual_path = self.visual_generator.create_metric_card(
                        title=item.title,
                        metric_value=metric_hint[:20],
                        metric_label="Empirical AI Breakthrough",
                        source_url=item.source_url,
                    )
            except Exception:
                visual_path = None

        # 5. Check dash presence
        dash_violations = scan_forbidden_dashes(clean_text)
        has_em_dash = len(dash_violations) > 0

        return GeneratedContent(
            platform=platform,
            text=clean_text,
            character_count=count,
            has_em_dash=has_em_dash,
            visual_path=visual_path,
            attribution_url=item.source_url,
            is_sensitive=False,
        )


__all__ = [
    "EditorialEngine",
    "ValidationResult",
    "EditorialLinter",
    "LintResult",
    "DashViolation",
    "TwitterTextCalculator",
    "LinkedInFormatter",
    "VisualGenerator",
    "OllamaClient",
    "HeuristicContentGenerator",
    "PractitionerPromptTemplates",
    "scan_forbidden_dashes",
    "replace_forbidden_dashes",
    "scan_banned_patterns",
    "clean_banned_patterns",
    "calculate_twitter_weight",
    "format_x_post",
    "format_x_thread",
    "format_linkedin_post",
    "strip_reasoning_tags",
]
