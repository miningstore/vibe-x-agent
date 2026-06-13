"""Local JSON state ledger — the whole feedback loop's memory.

One file on the VPS, no external database. It holds:

  * ``arms``            — per-angle Beta(alpha, beta) posteriors + counters.
                          This is what makes the agent *learn*.
  * ``posts``           — every post we've made, its angle, its engagement
                          snapshots, and whether its reward has been
                          credited to its arm yet (``settled``).
  * ``talking_points``  — last-used timestamps so the poster can rotate
                          through your facts least-recently-used.
  * ``account``         — the resolved X user id / handle (cached).

Atomic writes (tmp + rename) so a crash mid-write can't corrupt it.

Schema version 1::

    {
      "version": 1,
      "account": {"user_id": "...", "screen_name": "..."},
      "arms": {
        "pain_point": {"alpha": 1.0, "beta": 1.0, "impressions": 0,
                       "rewards_sum": 0.0, "updated_at": "..."}
      },
      "talking_points": {"<hash>": {"text": "...", "last_used_at": "..."}},
      "posts": {
        "<tweet_id>": {
          "tweet_id": "...", "arm": "pain_point", "format": "text",
          "talking_point": "...", "text": "...", "posted_at": "...",
          "link_included": true, "snapshots": [...], "viral_at": null,
          "replies_pulled": false, "replies": [], "settled": false,
          "reward": null
        }
      }
    }
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import config as cfg

log = logging.getLogger(__name__)

STATE_FILE = cfg.STATE_DIR / "agent_state.json"


# --- time helpers ---------------------------------------------------------

def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


# --- load / save ----------------------------------------------------------

def _empty() -> dict[str, Any]:
    return {"version": 1, "account": {}, "arms": {}, "talking_points": {}, "posts": {}}


def load() -> dict[str, Any]:
    try:
        data = json.loads(STATE_FILE.read_text())
    except FileNotFoundError:
        return _empty()
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("state: could not read %s (%s); starting fresh", STATE_FILE, exc)
        return _empty()
    # Defensive: backfill any missing top-level keys.
    for k, v in _empty().items():
        data.setdefault(k, v)
    return data


def save(state: dict[str, Any]) -> None:
    cfg.STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True))
    tmp.replace(STATE_FILE)


# --- account --------------------------------------------------------------

def set_account(state: dict, user_id: str, screen_name: str) -> None:
    state.setdefault("account", {})
    state["account"]["user_id"] = user_id
    state["account"]["screen_name"] = screen_name


# --- arms (the bandit posteriors) ----------------------------------------

def get_arm(state: dict, key: str) -> dict[str, Any]:
    """Return the arm record for an angle, creating it with the prior if new."""
    arms = state.setdefault("arms", {})
    rec = arms.get(key)
    if rec is None:
        rec = {
            "alpha": cfg.PRIOR_ALPHA,
            "beta": cfg.PRIOR_BETA,
            "impressions": 0,
            "rewards_sum": 0.0,
            "updated_at": now_iso(),
        }
        arms[key] = rec
    return rec


# --- posts ----------------------------------------------------------------

def record_post(
    state: dict,
    *,
    post_id: str,
    arm: str,
    fmt: str,
    talking_point: str,
    text: str,
    link_included: bool,
    posted_at: str | None = None,
) -> None:
    state.setdefault("posts", {})[post_id] = {
        "tweet_id": post_id,
        "arm": arm,
        "format": fmt,
        "talking_point": talking_point,
        "text": text,
        "link_included": link_included,
        "posted_at": posted_at or now_iso(),
        "snapshots": [],
        "viral_at": None,
        "replies_pulled": False,
        "replies": [],
        "settled": False,
        "reward": None,
    }


def recent_post_texts(state: dict, n: int) -> list[str]:
    posts = list((state.get("posts") or {}).values())
    posts.sort(key=lambda p: p.get("posted_at", ""), reverse=True)
    return [p.get("text", "") for p in posts[:n] if p.get("text")]


def count_posts_today(state: dict) -> int:
    today = datetime.now(timezone.utc).date().isoformat()
    n = 0
    for p in (state.get("posts") or {}).values():
        if (p.get("posted_at") or "").startswith(today):
            n += 1
    return n


def last_post_at(state: dict) -> datetime | None:
    times = [parse_iso(p.get("posted_at")) for p in (state.get("posts") or {}).values()]
    times = [t for t in times if t]
    return max(times) if times else None


# --- talking points (least-recently-used rotation) -----------------------

def _tp_hash(text: str) -> str:
    return hashlib.sha1(text.strip().encode("utf-8")).hexdigest()[:12]


def pick_talking_point(state: dict, talking_points: tuple[str, ...]) -> str | None:
    """Return the least-recently-used talking point and mark it used.

    Never-used points sort first (None < any timestamp). Caller saves state.
    """
    if not talking_points:
        return None
    tps = state.setdefault("talking_points", {})

    def last_used(text: str) -> str:
        rec = tps.get(_tp_hash(text))
        return (rec or {}).get("last_used_at") or ""

    chosen = min(talking_points, key=last_used)
    tps[_tp_hash(chosen)] = {"text": chosen, "last_used_at": now_iso()}
    return chosen
