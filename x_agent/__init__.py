"""vibe-x-agent — a self-improving X.com promotion agent for your VPS.

A Claude-CLI content engine posts about your product across configurable
angles; an engagement-driven Thompson-sampling bandit learns which angles
land and biases future posts toward them. State lives in a single local
JSON file — no external database required.

Entry points (all `python -m x_agent.<module>`):
  authorize     — mint X OAuth tokens (PIN flow)
  health_check  — pre-launch verification
  poster        — decide + post (fired by the systemd timer)
  engagement    — refresh metrics + settle rewards into the bandit
  loop          — optional foreground runner (post + engagement)
"""

__version__ = "0.1.0"
