"""Optional meme renderer: classic top/bottom text on an image.

Generic and dependency-light. Renders white Impact-style text with a
black stroke over either:
  * a template image you supply (X_AGENT_MEME_TEMPLATE=path), or
  * a solid brand-color background (default).

Only imported when a ``meme`` angle actually fires, so text-only
deployments never need Pillow installed.
"""
from __future__ import annotations

import io
import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont  # type: ignore

_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/impact/impact.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/Library/Fonts/Impact.ttf",
    "/System/Library/Fonts/Supplemental/Impact.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]


def _font(size: int) -> ImageFont.FreeTypeFont:
    override = os.environ.get("X_AGENT_MEME_FONT", "").strip()
    candidates = ([override] if override else []) + _FONT_CANDIDATES
    for path in candidates:
        try:
            return ImageFont.truetype(path, size=size)
        except (OSError, ValueError):
            continue
    return ImageFont.load_default()


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_w: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    cur = ""
    for w in words:
        trial = (cur + " " + w).strip()
        if draw.textlength(trial, font=font) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def _draw_block(draw, text, font, img_w, y, *, anchor_top: bool, stroke=4):
    lines = _wrap(draw, text.upper(), font, int(img_w * 0.92))
    line_h = font.size + 10
    if not anchor_top:
        y = y - line_h * len(lines)
    for line in lines:
        w = draw.textlength(line, font=font)
        x = (img_w - w) / 2
        draw.text((x, y), line, font=font, fill="white",
                  stroke_width=stroke, stroke_fill="black")
        y += line_h


def render(
    top: str,
    bottom: str,
    *,
    template_path: str | None = None,
    brand_color: str = "#1d9bf0",
    size: tuple[int, int] = (1080, 1080),
) -> bytes:
    """Render a meme PNG and return its bytes."""
    template_path = template_path or os.environ.get("X_AGENT_MEME_TEMPLATE") or None
    if template_path and Path(template_path).exists():
        base = Image.open(template_path).convert("RGB")
        base = base.resize(size)
    else:
        base = Image.new("RGB", size, brand_color)

    draw = ImageDraw.Draw(base)
    font = _font(int(size[1] * 0.085))
    if top:
        _draw_block(draw, top, font, size[0], int(size[1] * 0.04), anchor_top=True)
    if bottom:
        _draw_block(draw, bottom, font, size[0], int(size[1] * 0.94), anchor_top=False)

    buf = io.BytesIO()
    base.save(buf, format="PNG")
    return buf.getvalue()
