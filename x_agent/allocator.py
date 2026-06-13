"""The bandit: choose the next angle, credit engagement back to it.

This is the closed feedback loop, ported from vibe-seo-agent's
``allocator.py`` and adapted to operate on the local state ledger
instead of Cloudflare D1.

Posterior interpretation, per angle (arm):
  * ``alpha`` = PRIOR_ALPHA + total reward observed
  * ``beta``  = PRIOR_BETA  + total (1 - reward) observed
  * Beta(alpha, beta) is the posterior on that angle's expected reward
    per post. Reward is a saturating function of engagement in [0, 1).

Selection is Thompson sampling: draw one sample from each enabled arm's
Beta and post in the arm that drew highest. High-performing angles win
more draws; weak ones still occasionally win and keep getting data. An
epsilon exploration floor on top guarantees even a brand-new angle (flat
prior) gets tried and nothing starves to zero.

Crediting (``credit``) is the wire the original apartment bot never had:
when a post's engagement settles, its reward bumps its arm's posterior,
so the *next* selection is informed by what actually landed.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass

from . import config as cfg, state as _state
from .models import Angle


@dataclass
class ArmReport:
    key: str
    title: str
    enabled: bool
    alpha: float
    beta: float
    impressions: int
    rewards_sum: float
    mean: float          # posterior mean reward, alpha / (alpha + beta)


# --- reward ---------------------------------------------------------------

def compute_reward(metrics: dict) -> float:
    """Map a tweet's public_metrics to a reward in [0, 1).

    reward = 1 - exp(-score / SCALE), score = sum(weight_i * metric_i).
    Saturating: rewards strong engagement, but no single viral post can
    push an arm's posterior to 1.0 on its own.
    """
    score = 0.0
    for metric, weight in cfg.REWARD_WEIGHTS.items():
        try:
            score += weight * float(metrics.get(metric, 0) or 0)
        except (TypeError, ValueError):
            continue
    if score <= 0:
        return 0.0
    return 1.0 - math.exp(-score / cfg.REWARD_SCALE)


# --- selection ------------------------------------------------------------

def _beta_sample(a: float, b: float, rng: random.Random) -> float:
    return rng.betavariate(max(1e-6, a), max(1e-6, b))


def choose_angle(
    angles: list[Angle],
    state: dict,
    rng: random.Random | None = None,
) -> Angle | None:
    """Thompson-sample the next angle from the live posteriors.

    With probability EXPLORATION_FLOOR, pick uniformly at random instead
    (guarantees coverage / handles newly-added angles). Returns None if
    no angle is enabled.
    """
    enabled = [a for a in angles if a.enabled]
    if not enabled:
        return None
    rng = rng or random.Random()

    if rng.random() < cfg.EXPLORATION_FLOOR:
        return rng.choice(enabled)

    best: Angle | None = None
    best_draw = -1.0
    for angle in enabled:
        arm = _state.get_arm(state, angle.key)
        draw = _beta_sample(float(arm["alpha"]), float(arm["beta"]), rng)
        if draw > best_draw:
            best_draw = draw
            best = angle
    return best


# --- crediting (closing the loop) ----------------------------------------

def credit(state: dict, arm_key: str, reward: float) -> None:
    """Apply one settled post's reward to its angle's Beta posterior.

    One post = one trial. reward in [0, 1] adds to alpha; (1 - reward)
    adds to beta. Caller is responsible for saving state.
    """
    reward = max(0.0, min(1.0, float(reward)))
    arm = _state.get_arm(state, arm_key)
    arm["alpha"] = float(arm["alpha"]) + reward
    arm["beta"] = float(arm["beta"]) + (1.0 - reward)
    arm["impressions"] = int(arm["impressions"]) + 1
    arm["rewards_sum"] = float(arm["rewards_sum"]) + reward
    arm["updated_at"] = _state.now_iso()


# --- reporting ------------------------------------------------------------

def report(angles: list[Angle], state: dict) -> list[ArmReport]:
    out: list[ArmReport] = []
    for a in angles:
        arm = _state.get_arm(state, a.key)
        alpha = float(arm["alpha"])
        beta = float(arm["beta"])
        denom = alpha + beta
        out.append(
            ArmReport(
                key=a.key,
                title=a.title,
                enabled=a.enabled,
                alpha=alpha,
                beta=beta,
                impressions=int(arm["impressions"]),
                rewards_sum=float(arm["rewards_sum"]),
                mean=(alpha / denom) if denom > 0 else 0.0,
            )
        )
    out.sort(key=lambda r: r.mean, reverse=True)
    return out
