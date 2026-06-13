"""Pure data models shared across the package.

Kept import-free (no intra-package imports) so both ``config.py`` and a
user's ``product_config.py`` overlay can import these without any risk
of a circular import.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Product:
    """Everything the content engine needs to know about what it's promoting.

    This is the analog of the SEO agent's per-site ``SLOTS`` — the one
    chunk you fill in for *your* product. The richer and more specific
    you make it, the less generic the posts. ``talking_points`` in
    particular is what keeps posts concrete instead of vague brand mush:
    each one is a real, postable fact ("we just shipped dark mode",
    "now 12k developers use it", "import a CSV in 4 seconds").
    """

    name: str                              # "Acme Analytics"
    one_liner: str                         # "Session replay that doesn't slow your site down"
    url: str                               # "https://acme.example.com"
    audience: str                          # "indie SaaS founders and frontend devs"
    description: str                       # 2-4 sentences of what it is / who it's for
    # Concrete, postable facts. The poster rotates through these
    # (least-recently-used) so consecutive posts stay specific and fresh.
    talking_points: tuple[str, ...] = field(default_factory=tuple)
    # Voice guidance handed to the model verbatim. Be opinionated.
    voice: str = (
        "Plain, confident, a little playful. Lead with a concrete benefit "
        "or number. Sound like a person who built the thing, not a brand "
        "account."
    )
    # Optional secondary links the model may use (docs, pricing, a demo).
    extra_links: tuple[str, ...] = field(default_factory=tuple)
    # Hashtags to consider (the model uses 0-2, only when they fit).
    hashtags: tuple[str, ...] = field(default_factory=tuple)


@dataclass
class Angle:
    """One content strategy. Each enabled angle is a bandit arm.

    The feedback loop learns which angles earn engagement for *your*
    audience and biases future posts toward them (Thompson sampling),
    while still exploring the rest.
    """

    key: str                 # stable id, used as the bandit arm key. e.g. "pain_point"
    title: str               # human label for reports
    brief: str               # the instruction handed to the model for this angle
    fmt: str = "text"        # "text" | "meme"
    enabled: bool = True
