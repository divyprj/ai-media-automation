"""Programmatic visual generation engine operating at absolute zero financial cost.

Generates 1200x675 16:9 dark-mode visual assets:
1. Matplotlib benchmark charts (Agg headless backend)
2. Direct Pillow social metric cards (<20ms generation)
3. Dual-layer attribution: visible canvas watermark & digital PNG `tEXt` chunks.
"""

from datetime import datetime, timezone
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from PIL import Image, ImageDraw, ImageFont
from PIL.PngImagePlugin import PngInfo

from src.config import get_settings

# Design system tokens
CANVAS_BG = "#0B0F19"      # Deep Obsidian
CARD_SURFACE = "#111827"   # Rich Slate
BORDER_COLOR = "#1F2937"   # Subtle Charcoal
ACCENT_CYAN = "#38BDF8"    # Sky 400
ACCENT_INDIGO = "#818CF8"  # Indigo 400
ACCENT_EMERALD = "#34D399" # Emerald 400
TEXT_PRIMARY = "#F8FAFC"   # Slate 50
TEXT_SECONDARY = "#94A3B8" # Slate 400
TEXT_FOOTER = "#64748B"    # Slate 500

FONT_DEJAVU_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_DEJAVU_REG = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def _get_font(path: str, size: int) -> ImageFont.ImageFont:
    """Safely load TrueType font or fallback to default."""
    try:
        return ImageFont.truetype(path, size)
    except (OSError, IOError):
        return ImageFont.load_default()


class VisualGenerator:
    """Generates 16:9 dark-mode programmatic visuals with zero API cost."""

    def __init__(self, output_dir: str = "data/visuals") -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        settings = get_settings()
        self.owner_name = settings.owner_name
        self.owner_handle = settings.owner_handle

    def _generate_png_info(
        self,
        source_url: str,
        license_tag: str,
    ) -> PngInfo:
        """Construct standard digital PNG metadata chunk dictionary."""
        png_info = PngInfo()
        png_info.add_text("Source", source_url)
        png_info.add_text("License", license_tag)
        png_info.add_text("Author", self.owner_name)
        png_info.add_text("Handle", self.owner_handle)
        png_info.add_text(
            "Attribution",
            f"{self.owner_name} ({self.owner_handle}) - Source: {source_url}",
        )
        png_info.add_text("Generator", "AI-Media-Automation/1.0 (Zero-Cost Engine)")
        png_info.add_text("Timestamp", datetime.now(timezone.utc).isoformat())
        return png_info

    def create_benchmark_chart(
        self,
        title: str,
        scores: Union[Dict[str, float], List[float]],
        output_path: Optional[str] = None,
        source_url: str = "https://arxiv.org",
        license_tag: str = "Apache 2.0",
    ) -> str:
        """Render a 1200x675 16:9 dark-mode benchmark comparison bar chart with Matplotlib."""
        fig, ax = plt.subplots(figsize=(12, 6.75), facecolor=CANVAS_BG)
        ax.set_facecolor(CARD_SURFACE)

        # Parse and sanitize scores dict
        clean_scores: Dict[str, float] = {}
        if isinstance(scores, dict):
            for k, v in scores.items():
                if v is None:
                    clean_scores[str(k)] = 0.0
                else:
                    try:
                        val = float(v)
                        if math.isnan(val) or math.isinf(val):
                            clean_scores[str(k)] = 0.0
                        else:
                            clean_scores[str(k)] = val
                    except (ValueError, TypeError):
                        clean_scores[str(k)] = 0.0
        elif isinstance(scores, list):
            for idx, v in enumerate(scores):
                if v is None:
                    clean_scores[f"Model {idx+1}"] = 0.0
                else:
                    try:
                        val = float(v)
                        if math.isnan(val) or math.isinf(val):
                            clean_scores[f"Model {idx+1}"] = 0.0
                        else:
                            clean_scores[f"Model {idx+1}"] = val
                    except (ValueError, TypeError):
                        clean_scores[f"Model {idx+1}"] = 0.0

        if not clean_scores:
            labels = ["N/A"]
            vals = [0.0]
            colors = ["#475569"]
        else:
            labels = list(clean_scores.keys())
            vals = list(clean_scores.values())
            # Palette: cyan for top, indigo for others
            colors = [ACCENT_CYAN if i == len(vals) - 1 else ACCENT_INDIGO for i in range(len(vals))]

        y_positions = range(len(labels))
        bars = ax.barh(y_positions, vals, color=colors, height=0.55, edgecolor=BORDER_COLOR)

        # Value labels on bars
        for bar, val in zip(bars, vals):
            label_text = f"{val:.1f}%" if val > 0 else "N/A"
            ax.text(
                bar.get_width() + (max(vals) * 0.02 if vals and max(vals) > 0 else 0.5),
                bar.get_y() + bar.get_height() / 2,
                label_text,
                va="center",
                color=TEXT_PRIMARY,
                fontweight="bold",
                fontsize=12,
            )

        ax.set_yticks(y_positions)
        ax.set_yticklabels(labels, color=TEXT_PRIMARY, fontsize=13, fontweight="bold")
        ax.tick_params(colors=TEXT_SECONDARY, labelsize=11)

        # Style borders and grid
        for spine in ax.spines.values():
            spine.set_color(BORDER_COLOR)
        ax.grid(axis="x", color=BORDER_COLOR, linestyle="--", alpha=0.6)

        # Title
        ax.set_title(title, color=TEXT_PRIMARY, fontsize=18, fontweight="bold", pad=20)

        # Footer watermark
        footer_text = f"Source: {source_url}  |  License: {license_tag}  |  {self.owner_name} ({self.owner_handle})"
        fig.text(0.5, 0.03, footer_text, ha="center", color=TEXT_FOOTER, fontsize=10)

        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            try:
                plt.tight_layout()
            except Exception:
                pass

        if not output_path:
            filename = f"benchmark_{int(datetime.now().timestamp()*1000)}.png"
            output_path = str(self.output_dir / filename)

        plt.savefig(
            output_path,
            dpi=100,
            facecolor=fig.get_facecolor(),
            edgecolor="none",
        )
        plt.close(fig)

        # Embed PNG tEXt metadata
        png_info = self._generate_png_info(source_url, license_tag)
        with Image.open(output_path) as im:
            im.save(output_path, "PNG", pnginfo=png_info)

        return output_path

    def generate_benchmark_chart(
        self,
        title: str,
        models: List[str],
        scores: List[float],
        metric_name: str,
        output_path: Optional[str] = None,
        source_url: str = "https://arxiv.org",
        license_tag: str = "Apache 2.0",
    ) -> str:
        """Alias adhering to SCOPE contract taking separate models and scores lists."""
        scores_dict = {m: s for m, s in zip(models, scores)}
        full_title = f"{title} ({metric_name})" if metric_name else title
        return self.create_benchmark_chart(
            title=full_title,
            scores=scores_dict,
            output_path=output_path,
            source_url=source_url,
            license_tag=license_tag,
        )

    def create_metric_card(
        self,
        title: str,
        metric_value: str,
        metric_label: str,
        source_url: str,
        license_tag: str = "Open Source",
        output_path: Optional[str] = None,
    ) -> str:
        """Render a dark-mode social metric card using Pillow in <20ms."""
        width, height = 1200, 675
        img = Image.new("RGB", (width, height), color=CANVAS_BG)
        draw = ImageDraw.Draw(img)

        # Outer card container with 1px border
        draw.rectangle([(30, 30), (width - 30, height - 30)], fill=CARD_SURFACE, outline=BORDER_COLOR, width=2)

        # Header Badge
        badge_font = _get_font(FONT_DEJAVU_BOLD, 14)
        badge_text = "RESEARCH UPDATE"
        try:
            bbox = draw.textbbox((0, 0), badge_text, font=badge_font)
            text_w = bbox[2] - bbox[0]
            text_h = bbox[3] - bbox[1]
        except AttributeError:
            text_w, text_h = 160, 18

        pad_x, pad_y = 16, 8
        b_x1, b_y1 = 70, 70
        b_x2 = b_x1 + text_w + pad_x * 2
        b_y2 = b_y1 + text_h + pad_y * 2
        draw.rounded_rectangle([(b_x1, b_y1), (b_x2, b_y2)], radius=6, fill="#1E293B", outline=ACCENT_CYAN, width=1)
        draw.text((b_x1 + pad_x, b_y1 + pad_y), badge_text, fill=ACCENT_CYAN, font=badge_font)

        # Title (wrapped if needed)
        title_font = _get_font(FONT_DEJAVU_BOLD, 36)
        display_title = title if len(title) <= 65 else title[:62] + "..."
        draw.text((70, 140), display_title, fill=TEXT_PRIMARY, font=title_font)

        # Separator line
        draw.line([(70, 220), (width - 70, 220)], fill=BORDER_COLOR, width=1)

        # Big Highlight Metric Value
        metric_font = _get_font(FONT_DEJAVU_BOLD, 84)
        draw.text((70, 260), str(metric_value), fill=ACCENT_CYAN, font=metric_font)

        # Metric Description / Subtitle
        desc_font = _get_font(FONT_DEJAVU_REG, 24)
        draw.text((70, 380), str(metric_label), fill=TEXT_SECONDARY, font=desc_font)

        # Practitioner Takeaway Box
        box_y1 = 450
        box_y2 = 540
        draw.rounded_rectangle([(70, box_y1), (width - 70, box_y2)], radius=8, fill="#0F172A", outline=BORDER_COLOR, width=1)
        sub_font = _get_font(FONT_DEJAVU_REG, 18)
        draw.text((95, box_y1 + 18), f"Architecture Breakdown & Analysis by {self.owner_name} ({self.owner_handle})", fill=ACCENT_EMERALD, font=badge_font)
        draw.text((95, box_y1 + 48), "Optimized for local inference, verifiable weights, and zero-cost self-hosting.", fill=TEXT_SECONDARY, font=sub_font)

        # Footer Bar with Source & License
        footer_font = _get_font(FONT_DEJAVU_REG, 15)
        footer_text = f"Source: {source_url} | License: {license_tag} | {self.owner_name} ({self.owner_handle})"
        draw.text((70, 595), footer_text, fill=TEXT_FOOTER, font=footer_font)

        if not output_path:
            filename = f"card_{int(datetime.now().timestamp()*1000)}.png"
            output_path = str(self.output_dir / filename)

        png_info = self._generate_png_info(source_url, license_tag)
        img.save(output_path, "PNG", pnginfo=png_info)

        return output_path

    def generate_social_card(
        self,
        title: str,
        subtitle: str,
        metric_value: str,
        metric_label: str,
        output_path: Optional[str] = None,
        source_url: str = "https://arxiv.org",
        license_tag: str = "Open Source",
    ) -> str:
        """Alias adhering to SCOPE contract for social cards."""
        return self.create_metric_card(
            title=title,
            metric_value=metric_value,
            metric_label=f"{metric_label}: {subtitle}",
            source_url=source_url,
            license_tag=license_tag,
            output_path=output_path,
        )

    def inspect_visual_footer(self, image_path: str) -> Dict[str, Any]:
        """Inspect visible footer and digital metadata of a generated image."""
        metadata = self.read_png_metadata(image_path)
        source = metadata.get("Source", "")
        license_tag = metadata.get("License", "")
        author = metadata.get("Author", "")
        footer_str = f"Source: {source} | License: {license_tag} | {author}"
        return {"footer_text": footer_str, "metadata": metadata}

    def read_png_metadata(self, image_path: str) -> Dict[str, str]:
        """Read embedded digital tEXt chunks from PNG image."""
        with Image.open(image_path) as im:
            return dict(im.info)
