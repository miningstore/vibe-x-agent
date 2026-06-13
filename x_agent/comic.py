"""Comic-strip renderer: turn a panel script into a shareable PNG.

The ``comic`` content type. Claude writes the script (a title plus 3-6
panels of caption / dialogue / sound-effect, see content.py); this renders
it as a clean multi-panel caption comic: per-panel setting captions,
alternating character avatars (a colored chip with the speaker's initial,
stable per character), speech bubbles, and sound effects. Pillow only, no
image-generation dependency, so it works out of the box.

The art is caption-comic style (panels + avatars + bubbles), not
hand-drawn. To get richer art, register a different renderer for the
"comic" format in render.py (e.g. an SVG or image-model backend).

Panel spec (one dict per panel)::

    {"caption": "MONDAY",                          # optional setting/narration
     "lines": [{"speaker": "DEV", "line": "..."},   # 0-3 dialogue bubbles
               {"speaker": "AGENT", "line": "..."}],
     "sfx": "KA-CHUNK!"}                            # optional sound effect
"""
from __future__ import annotations

import io
import math
import os

from PIL import Image, ImageDraw, ImageFont  # type: ignore

PALETTE = ["#FDE68A", "#BBF7D0", "#BFDBFE", "#FBCFE8", "#DDD6FE", "#FED7AA"]
SPEAKER_COLORS = ["#2563EB", "#DC2626", "#059669", "#D97706", "#7C3AED", "#DB2777", "#0891B2"]
INK = (17, 17, 17)
PAPER = (255, 255, 255)
CAPTION_BG = (17, 17, 17)
CAPTION_FG = (255, 238, 140)
SFX_FG = (220, 38, 38)

_REG = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/Library/Fonts/Arial.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
]
_BOLD = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    override = os.environ.get("X_AGENT_COMIC_FONT", "").strip()
    cands = ([override] if override else []) + (_BOLD if bold else _REG) + _REG + _BOLD
    for p in cands:
        try:
            return ImageFont.truetype(p, size=size)
        except (OSError, ValueError):
            continue
    return ImageFont.load_default()


def _hex(s: str) -> tuple[int, int, int]:
    s = (s or "").lstrip("#")
    if len(s) == 6:
        try:
            return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore
        except ValueError:
            pass
    return (29, 155, 240)


def _speaker_color(name: str) -> tuple[int, int, int]:
    if not name.strip():
        return (100, 116, 139)  # slate for narrator / unattributed
    return _hex(SPEAKER_COLORS[sum(ord(c) for c in name.lower()) % len(SPEAKER_COLORS)])


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_w: int) -> list[str]:
    out: list[str] = []
    for raw in text.split("\n"):
        cur = ""
        for w in raw.split():
            t = (cur + " " + w).strip()
            if draw.textlength(t, font=font) <= max_w or not cur:
                cur = t
            else:
                out.append(cur)
                cur = w
        out.append(cur)
    return out or [""]


def _fit_one_line(draw, text, font, max_w) -> str:
    """Trim `text` to one line that fits `max_w`, adding an ellipsis if cut."""
    if draw.textlength(text, font=font) <= max_w:
        return text
    out = ""
    for w in text.split():
        t = (out + " " + w).strip()
        if draw.textlength(t + "…", font=font) > max_w:
            break
        out = t
    return (out + "…") if out else text


def _text_block(draw, xy, text, font, max_w, fill, gap=4, center=False) -> int:
    x, y = xy
    for ln in _wrap(draw, text, font, max_w):
        w = draw.textlength(ln, font=font)
        draw.text((x + (max_w - w) / 2 if center else x, y), ln, font=font, fill=fill)
        y += font.size + gap
    return y


def _draw_avatar(draw, x, y, d, speaker):
    col = _speaker_color(speaker)
    draw.ellipse([x, y, x + d, y + d], fill=col, outline=INK, width=3)
    initial = (speaker.strip()[:1] or "?").upper()
    f = _font(int(d * 0.5), bold=True)
    w = draw.textlength(initial, font=f)
    draw.text((x + (d - w) / 2, y + (d - f.size) / 2 - 2), initial, font=f, fill=PAPER)
    if speaker.strip():
        nf = _font(16, bold=True)
        nm = speaker.strip().upper()[:10]
        nw = draw.textlength(nm, font=nf)
        draw.text((x + (d - nw) / 2, y + d + 2), nm, font=nf, fill=INK)


def render(spec: dict, *, brand: str = "#1d9bf0", handle: str = "",
           size: tuple[int, int] = (1200, 1500)) -> bytes:
    title = (spec.get("title") or "").strip()
    panels = [p for p in (spec.get("panels") or []) if isinstance(p, dict)][:6]
    tagline = (spec.get("tagline") or "").strip()
    if not panels:
        panels = [{"caption": "", "lines": [], "sfx": ""}]

    W, H = size
    img = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(img)
    margin = 28
    title_h = 124 if title else margin
    footer_h = 104 if (tagline or handle) else margin

    if title:
        d.rectangle([0, 0, W, title_h], fill=_hex(brand))
        _text_block(d, (margin, 26), title, _font(58, bold=True), W - 2 * margin, PAPER, center=True)

    n = len(panels)
    cols = 1 if n <= 3 else 2
    rows = math.ceil(n / cols)
    gx = gy = 24
    ax0, ay0 = margin, title_h + gy
    aw = W - 2 * margin
    ah = H - title_h - footer_h - 2 * gy
    pw = (aw - (cols - 1) * gx) // cols
    ph = (ah - (rows - 1) * gy) // rows

    txt_f = _font(25)
    cap_f = _font(22, bold=True)
    av_d, gap, pad = 72, 14, 14

    for i, p in enumerate(panels):
        r, c = divmod(i, cols)
        x0 = ax0 + c * (pw + gx)
        y0 = ay0 + r * (ph + gy)
        x1, y1 = x0 + pw, y0 + ph
        d.rounded_rectangle([x0, y0, x1, y1], radius=20, fill=_hex(PALETTE[i % len(PALETTE)]),
                            outline=INK, width=5)
        d.text((x0 + 14, y1 - 34), str(i + 1), font=_font(22, bold=True), fill=INK)

        inset = 22
        ix0, iy0, ix1, iy1 = x0 + inset, y0 + inset, x1 - inset, y1 - inset
        top = iy0

        cap = (p.get("caption") or "").strip()
        if cap:
            cap_lines = _wrap(d, cap.upper(), cap_f, (ix1 - ix0) - 20)
            ch = 8 + len(cap_lines) * (cap_f.size + 2) + 8
            d.rectangle([ix0, iy0, ix1, iy0 + ch], fill=CAPTION_BG)
            yy = iy0 + 8
            for ln in cap_lines:
                d.text((ix0 + 10, yy), ln, font=cap_f, fill=CAPTION_FG)
                yy += cap_f.size + 2
            top = iy0 + ch + 14

        # Measure dialogue items so we can vertically center them in the body.
        lines = p.get("lines") or []
        if isinstance(lines, dict):
            lines = [lines]
        items = []  # (speaker, wrapped_lines, item_height, bubble_w)
        bubble_w = (ix1 - ix0) - av_d - gap
        for ln in list(lines)[:3]:
            if isinstance(ln, dict):
                sp, tx = (ln.get("speaker") or "").strip(), (ln.get("line") or "").strip()
            else:
                sp, tx = "", str(ln).strip()
            if not tx:
                continue
            wl = _wrap(d, tx, txt_f, bubble_w - 2 * pad)
            bh = pad * 2 + len(wl) * (txt_f.size + 5)
            item_h = max(bh, av_d + 20)
            items.append((sp, wl, item_h, bh))

        total = sum(it[2] for it in items) + gap * max(0, len(items) - 1)
        y = top + max(0, ((iy1 - top) - total) // 2)

        for idx, (sp, wl, item_h, bh) in enumerate(items):
            left = idx % 2 == 0
            if left:
                ax = ix0
                bx0, bx1 = ix0 + av_d + gap, ix1
            else:
                ax = ix1 - av_d
                bx0, bx1 = ix0, ix1 - av_d - gap
            _draw_avatar(d, ax, y, av_d, sp)
            d.rounded_rectangle([bx0, y, bx1, y + bh], radius=18, fill=PAPER, outline=INK, width=3)
            cy = y + pad
            for tl in wl:
                d.text((bx0 + pad, cy), tl, font=txt_f, fill=INK)
                cy += txt_f.size + 5
            y += item_h + gap

        sfx = (p.get("sfx") or "").strip()
        if sfx:
            sf = _font(40, bold=True)
            w = d.textlength(sfx.upper(), font=sf)
            d.text((ix1 - w - 4, iy1 - sf.size - 4), sfx.upper(), font=sf,
                   fill=SFX_FG, stroke_width=2, stroke_fill=PAPER)

    if tagline or handle:
        fy = H - footer_h
        d.rectangle([0, fy, W, H], fill=CAPTION_BG)
        if tagline:
            tf = _font(30, bold=True)
            line = _fit_one_line(d, tagline, tf, W - 2 * margin)
            w = d.textlength(line, font=tf)
            d.text(((W - w) / 2, fy + 20), line, font=tf, fill=PAPER)
        if handle:
            hf = _font(24)
            w = d.textlength(handle, font=hf)
            d.text(((W - w) / 2, H - 38), handle, font=hf, fill=(170, 170, 170))

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
