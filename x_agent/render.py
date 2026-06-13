"""Content-type render dispatch (the pluggable content-type set).

A content type is identified by ``Angle.fmt``. Text posts need no image;
visual types (meme, comic) render a PNG here. To add a new visual content
type: write a renderer module and a branch below, then add an angle with
that ``fmt``. The poster calls ``render_for`` for every post and uploads
whatever bytes come back (or posts text-only when it gets None).

Renderer imports are lazy so text-only deployments never need Pillow.
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)

# The content types this build can render to an image. "text" is implicit
# (no image). Extend this tuple + render_for() to add more.
VISUAL_CONTENT_TYPES = ("meme", "comic")
CONTENT_TYPES = ("text",) + VISUAL_CONTENT_TYPES


def render_for(angle, post, *, brand: str = "#1d9bf0", handle: str = "") -> bytes | None:
    """Return PNG bytes for a post's content type, or None for text/unknown."""
    fmt = getattr(angle, "fmt", "text")
    if fmt == "text":
        return None
    try:
        if fmt == "meme":
            from . import meme
            return meme.render(post.meme_top, post.meme_bottom, brand_color=brand)
        if fmt == "comic":
            from . import comic
            return comic.render(post.media or {}, brand=brand, handle=handle)
    except ImportError:
        log.warning("render: Pillow not installed; cannot render %s, posting text only", fmt)
        return None
    log.warning("render: no renderer registered for fmt=%s; posting text only", fmt)
    return None
