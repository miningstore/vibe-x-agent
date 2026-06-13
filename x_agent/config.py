"""Runtime configuration for vibe-x-agent.

Two kinds of config live here:

  1. **Runtime knobs** — cadence, caps, bandit thresholds, reward
     weights. Safe defaults; every one is overridable by an env var so
     you can tune from `.env` without editing code.

  2. **Your product** — loaded from the `product_config.py` overlay you
     create (see `product_config_example.py`). DON'T edit this file to
     describe your product; create the overlay so `git pull` never
     fights your customizations.

The overlay may define any of: ``PRODUCT`` (required for real posting),
``ANGLES`` (defaults to ``angles.DEFAULT_ANGLES``), ``BANNED`` (extra
banned tokens), ``TALKING_POINTS`` (defaults to ``PRODUCT.talking_points``).
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from . import angles as _angles
from .models import Angle, Product

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
PKG_DIR = Path(__file__).resolve().parent
STATE_DIR = Path(os.environ.get("X_AGENT_STATE_DIR") or (PKG_DIR / "state"))
PROMPTS_DIR = PKG_DIR / "prompts"
DRY_RUN_DIR = STATE_DIR / "dry_runs"

# --- Claude CLI (plan auth, same pattern as vibe-seo-agent) --------------
# We shell out to `claude -p` so generation bills against your Claude
# Pro/Max plan via ~/.claude/.credentials.json. Do NOT pass --bare.
CLAUDE_BIN = os.environ.get("CLAUDE_BIN", os.path.expanduser("~/.local/bin/claude"))
CLAUDE_MODEL = os.environ.get("X_AGENT_LLM_MODEL", "sonnet")
CLAUDE_TIMEOUT_S = int(os.environ.get("X_AGENT_LLM_TIMEOUT_S", "120"))

# --- Web grounding (opt-in freshness) ------------------------------------
# When on, the FIRST generation attempt per post lets Claude use the
# read-only web tools (WebSearch/WebFetch) to find one timely, real hook and
# tie the product to it, instead of relying only on your static talking
# points. Off by default: it's slower and costs a little per post. Requires
# the claude CLI to be logged in on the host (plan auth). Any failure falls
# back to normal generation, so enabling it can never block a post.
WEB_GROUNDING = (
    os.environ.get("X_AGENT_WEB_GROUNDING", "false").strip().lower()
    in {"1", "true", "yes", "on"}
)
WEB_GROUNDING_BUDGET_USD = float(os.environ.get("X_AGENT_WEB_GROUNDING_BUDGET_USD", "0.50"))
WEB_GROUNDING_TIMEOUT_S = int(os.environ.get("X_AGENT_WEB_GROUNDING_TIMEOUT_S", "240"))

# --- Posting cadence + caps ----------------------------------------------
# The systemd timer decides WHEN the agent wakes; these decide how much
# it does once awake. Keep well under the X Free tier's ~500 posts/month.
MAX_POSTS_PER_RUN = int(os.environ.get("X_AGENT_MAX_POSTS_PER_RUN", "1"))
MAX_POSTS_PER_DAY = int(os.environ.get("X_AGENT_MAX_POSTS_PER_DAY", "4"))
MIN_HOURS_BETWEEN_POSTS = float(os.environ.get("X_AGENT_MIN_HOURS_BETWEEN_POSTS", "3"))

# Link policy. X sometimes suppresses reach on posts that carry an
# outbound link, so by default we include it on a fraction of posts.
#   "always"    — every post ends with the product URL
#   "sometimes" — every Nth post carries the link (LINK_EVERY_N)
#   "never"     — never append a link (rely on the profile bio)
LINK_POLICY = os.environ.get("X_AGENT_LINK_POLICY", "sometimes").strip().lower()
LINK_EVERY_N = int(os.environ.get("X_AGENT_LINK_EVERY_N", "3"))

# Avoid re-posting near-duplicate copy: this many recent posts are shown
# to the model as "do not repeat these".
RECENT_POSTS_TO_AVOID = int(os.environ.get("X_AGENT_RECENT_POSTS_TO_AVOID", "8"))

# --- Visual content types (meme / comic image rendering) -----------------
# Brand accent used on rendered images (title bars, backgrounds) and the
# account handle printed on comic footers. Handle is cosmetic; leave blank
# to omit it from the image.
BRAND_COLOR = os.environ.get("X_AGENT_BRAND_COLOR", "#1d9bf0")
HANDLE = os.environ.get("X_AGENT_HANDLE", "")

# --- Slop gate -----------------------------------------------------------
SLOP_THRESHOLD = int(os.environ.get("X_AGENT_SLOP_THRESHOLD", "45"))   # of 50
MAX_SLOP_RETRIES = int(os.environ.get("X_AGENT_SLOP_RETRIES", "2"))

# --- Feedback loop / bandit ----------------------------------------------
# Beta(alpha, beta) prior for a brand-new angle. (1, 1) = uniform.
PRIOR_ALPHA = float(os.environ.get("X_AGENT_PRIOR_ALPHA", "1.0"))
PRIOR_BETA = float(os.environ.get("X_AGENT_PRIOR_BETA", "1.0"))
# Epsilon exploration floor: with this probability the next angle is
# chosen uniformly at random instead of by Thompson sampling. Guarantees
# every enabled angle (including ones you just added) keeps getting tried
# and never starves to zero.
EXPLORATION_FLOOR = float(os.environ.get("X_AGENT_EXPLORATION_FLOOR", "0.15"))

# How long after posting we wait before crediting a post's engagement to
# its angle's posterior. Long enough for a post to accumulate most of its
# reach, short enough that the loop learns quickly.
REWARD_SETTLE_DAYS = float(os.environ.get("X_AGENT_REWARD_SETTLE_DAYS", "3"))
# Engagement snapshot buckets (days after posting) and the age past which
# we stop refreshing a tweet entirely.
SNAPSHOT_AGE_DAYS = (1, 3, 7)
MAX_TRACK_AGE_DAYS = int(os.environ.get("X_AGENT_MAX_TRACK_AGE_DAYS", "8"))

# Reward = 1 - exp(-score / SCALE), where score is a weighted sum of the
# public engagement metrics. Bounded to [0, 1), informative from the very
# first post, and saturating so one mega-viral post can't swamp the arm.
REWARD_WEIGHTS = {
    "like_count": float(os.environ.get("X_AGENT_W_LIKE", "1.0")),
    "retweet_count": float(os.environ.get("X_AGENT_W_RETWEET", "3.0")),
    "reply_count": float(os.environ.get("X_AGENT_W_REPLY", "2.0")),
    "quote_count": float(os.environ.get("X_AGENT_W_QUOTE", "3.0")),
    "bookmark_count": float(os.environ.get("X_AGENT_W_BOOKMARK", "2.0")),
}
REWARD_SCALE = float(os.environ.get("X_AGENT_REWARD_SCALE", "10.0"))

# "Viral" thresholds — any one crossing flags a post in `report` and
# pulls its replies so you can read what landed.
VIRAL_LIKES = int(os.environ.get("X_AGENT_VIRAL_LIKES", "50"))
VIRAL_RETWEETS = int(os.environ.get("X_AGENT_VIRAL_RETWEETS", "10"))
VIRAL_REPLIES = int(os.environ.get("X_AGENT_VIRAL_REPLIES", "20"))

# --- Loop cooldowns (only used by `python -m x_agent.loop`) --------------
# The recommended deployment is the systemd timer (one post per wake),
# not a long-running loop. loop.py exists for foreground/manual runs.
LOOP_COOLDOWN_S = int(os.environ.get("X_AGENT_LOOP_COOLDOWN_S", "3600"))

# Default .env path that `authorize.py --primary` writes tokens into.
DEFAULT_ENV_FILE = os.environ.get("X_AGENT_ENV_FILE", str(REPO_ROOT / ".env"))


# === Product + angles overlay ============================================
# Try the user's overlay first; fall back to the shipped example so a
# fresh clone can `--dry-run` immediately without any setup.
_overlay_source = "product_config (your overlay)"
try:
    from . import product_config as _pc  # type: ignore
except ImportError:
    from . import product_config_example as _pc  # type: ignore
    _overlay_source = "product_config_example (DEMO — copy it to product_config.py)"
    log.warning(
        "x_agent.config: no product_config.py found; using the demo product. "
        "Copy x_agent/product_config_example.py to x_agent/product_config.py "
        "and edit it before posting for real."
    )

PRODUCT: Product = _pc.PRODUCT
ANGLES: list[Angle] = list(getattr(_pc, "ANGLES", _angles.DEFAULT_ANGLES))
TALKING_POINTS: tuple[str, ...] = tuple(
    getattr(_pc, "TALKING_POINTS", None) or PRODUCT.talking_points
)

# Banned tokens: em/en dash always, plus anything the overlay adds.
BANNED: tuple[str, ...] = ("—", "–") + tuple(getattr(_pc, "BANNED", ()))

OVERLAY_SOURCE = _overlay_source


def enabled_angles() -> list[Angle]:
    return [a for a in ANGLES if a.enabled]


def using_demo_product() -> bool:
    return "example" in OVERLAY_SOURCE
