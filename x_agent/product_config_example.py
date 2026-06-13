"""EXAMPLE product config. Copy me, then edit.

    cp x_agent/product_config_example.py x_agent/product_config.py
    $EDITOR x_agent/product_config.py

`product_config.py` is gitignored, so your edits survive `git pull`.
Until you create it, the agent uses this demo product (so `--dry-run`
works out of the box, but every post will be about a fake product).

You can define any of:
  PRODUCT         (required)  — what you're promoting, see models.Product
  TALKING_POINTS  (optional)  — overrides PRODUCT.talking_points if set
  ANGLES          (optional)  — overrides the default angle set
  BANNED          (optional)  — extra tokens the model must never emit
"""
from __future__ import annotations

from .models import Product

PRODUCT = Product(
    name="Pixelpost",
    one_liner="Schedule a week of social posts in 10 minutes, from your terminal.",
    url="https://pixelpost.example.com",
    audience="indie hackers, solo founders, and devs who hate marketing busywork",
    description=(
        "Pixelpost is a CLI + tiny web app that turns a few bullet points "
        "into a week of scheduled posts across X, LinkedIn, and Bluesky. "
        "Built for people who would rather ship than babysit a content "
        "calendar."
    ),
    talking_points=(
        "Pixelpost just crossed 2,000 weekly active users.",
        "You can go from zero to a full week of scheduled posts in under 10 minutes.",
        "New this week: a --dry-run flag that previews every post before it ships.",
        "Pixelpost runs entirely from your terminal. No browser tab to leave open.",
        "Drafts are stored as plain markdown files you own, not locked in a SaaS.",
        "One user scheduled 90 days of posts during a single flight to SF.",
    ),
    voice=(
        "Direct, dry, a little funny. Talk like a developer who built this "
        "to scratch their own itch. Concrete over hype. No corporate sheen."
    ),
    extra_links=(
        "https://pixelpost.example.com/docs",
    ),
    hashtags=(
        "#buildinpublic",
        "#indiehackers",
    ),
)

# Leave ANGLES / TALKING_POINTS / BANNED unset to use the defaults.
# Example of adding a banned token (a competitor you don't want to name):
# BANNED = ("Buffer", "Hootsuite")

# --- Content types: text (default), meme, comic ---
# Posts are plain text unless you enable a visual content type. They render
# locally via Pillow (no image-generation service). To turn on comic strips
# (a multi-panel mini-story that lands the product as the punchline) while
# keeping every text angle, enable that angle in an ANGLES override:
#
# import dataclasses
# from .angles import DEFAULT_ANGLES
# ANGLES = [dataclasses.replace(a, enabled=True) if a.key == "comic" else a
#           for a in DEFAULT_ANGLES]
#
# (Use a.key == "meme" for the classic top/bottom meme type.) Then set the
# look via env vars in .env:
#   X_AGENT_BRAND_COLOR=#1d9bf0   title bar + panel accents
#   X_AGENT_HANDLE=@yourhandle    printed on the comic footer
