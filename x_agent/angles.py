"""Default content angles (the bandit's arms).

Each angle is one repeatable *way* to talk about a product. The agent
posts in one angle per run, the engagement it earns updates that angle's
Beta posterior, and the allocator Thompson-samples the next angle from
those posteriors. Over time the mix shifts toward whatever your audience
actually rewards.

Override or extend this list by defining ``ANGLES`` in your
``product_config.py``. Disable one by setting ``enabled=False`` (it stays
in reports but is never selected). Add your own — a fresh angle starts
with a flat prior and the exploration floor guarantees it gets tried.
"""
from __future__ import annotations

from .models import Angle

DEFAULT_ANGLES: list[Angle] = [
    Angle(
        key="pain_point",
        title="Pain point",
        brief=(
            "Open on the specific, visceral problem your audience has BEFORE "
            "they find the product. Name the frustration precisely. The "
            "product is the quiet answer at the end, not the headline."
        ),
    ),
    Angle(
        key="social_proof",
        title="Social proof / traction",
        brief=(
            "Lead with a real number or milestone (users, throughput, time "
            "saved, revenue, a customer quote). Concrete proof that this is "
            "working for real people. No vague 'loved by teams everywhere'."
        ),
    ),
    Angle(
        key="how_to",
        title="How-to / quick tip",
        brief=(
            "Teach one genuinely useful thing the audience can act on today, "
            "even without the product. Weave the product in as the obvious "
            "way to do it faster. Give value first; earn the click."
        ),
    ),
    Angle(
        key="feature_spotlight",
        title="Feature spotlight",
        brief=(
            "Pick ONE feature and the ONE benefit it unlocks. Show the before/"
            "after of a user's day. Specific over comprehensive: one sharp "
            "feature beats a feature list."
        ),
    ),
    Angle(
        key="hot_take",
        title="Hot take / opinion",
        brief=(
            "Stake out an opinionated, on-brand position your audience nods "
            "along to (or argues with). It should follow naturally that the "
            "product is built around that belief. Confident, not preachy."
        ),
    ),
    Angle(
        key="build_in_public",
        title="Build in public",
        brief=(
            "Share a behind-the-scenes detail: a decision, a metric, a thing "
            "you just shipped or fixed. Founder-voice, candid. People follow "
            "the story, then the product."
        ),
    ),
    Angle(
        key="meme",
        title="Meme",
        brief=(
            "A short, funny, relatable post about the audience's problem. "
            "Punchy, terminally-online register is fine. The humor lands "
            "first; the product is the wink at the end."
        ),
        fmt="meme",
        enabled=False,  # off by default; needs a meme template + Pillow
    ),
]


def by_key(angles: list[Angle], key: str) -> Angle | None:
    for a in angles:
        if a.key == key:
            return a
    return None
