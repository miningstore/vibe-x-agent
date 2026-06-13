"""Engagement tracker + the reward step that closes the feedback loop.

The poster registers every post in the shared state ledger. This module,
run on a daily timer, does three things per tracked post:

  1. **Snapshot** public metrics at the 1d / 3d / 7d marks (for reports).
  2. **Settle + credit** — once a post is REWARD_SETTLE_DAYS old, turn its
     engagement into a reward in [0,1] and credit it to its angle's Beta
     posterior via ``allocator.credit``. This is the wire the original
     apartment bot was missing: from here on, the *next* angle the poster
     picks is informed by what actually earned engagement.
  3. **Viral flag + replies** — when a post crosses a viral threshold,
     record it and (if a bearer token is available) pull recent replies
     so you can read what landed.

Metrics are read with the same OAuth 1.0a user creds the poster uses, so
no extra credential is required. If ``TWITTER_BEARER_TOKEN`` is set it's
used instead (and unlocks the replies pull, which needs recent-search).

Commands:
    python -m x_agent.engagement refresh   # daily cron entry
    python -m x_agent.engagement report     # human-readable status
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any

import requests

from . import allocator, config as cfg, state as _state
from .x_client import XClient, dry_run_active

log = logging.getLogger(__name__)

TWEETS_LOOKUP_URL = "https://api.x.com/2/tweets"
SEARCH_URL = "https://api.x.com/2/tweets/search/recent"
MAX_REPLIES_STORED = 50


# --- metric fetch (bearer if present, else OAuth1 user ctx) ---------------

def _fetch_all_metrics(ids: list[str]) -> dict[str, dict]:
    if not ids:
        return {}
    bearer = os.environ.get("TWITTER_BEARER_TOKEN", "").strip()
    if bearer:
        out: dict[str, dict] = {}
        for i in range(0, len(ids), 100):
            chunk = ids[i : i + 100]
            try:
                resp = requests.get(
                    TWEETS_LOOKUP_URL,
                    params={"ids": ",".join(chunk), "tweet.fields": "public_metrics"},
                    headers={"Authorization": f"Bearer {bearer}"},
                    timeout=30,
                )
            except Exception as exc:
                log.info("engagement: bearer metrics fetch failed: %s", exc)
                continue
            if not resp.ok:
                log.info("engagement: bearer metrics -> HTTP %d: %s", resp.status_code, resp.text[:200])
                continue
            for row in (resp.json() or {}).get("data") or []:
                tid, pm = row.get("id"), row.get("public_metrics")
                if tid and isinstance(pm, dict):
                    out[str(tid)] = pm
        return out
    # OAuth1 user context (the creds the poster already has)
    try:
        return XClient().get_tweets_metrics(ids)
    except Exception as exc:
        log.warning("engagement: OAuth metrics fetch failed: %s", exc)
        return {}


def _is_viral(m: dict) -> bool:
    return (
        int(m.get("like_count", 0) or 0) >= cfg.VIRAL_LIKES
        or int(m.get("retweet_count", 0) or 0) >= cfg.VIRAL_RETWEETS
        or int(m.get("reply_count", 0) or 0) >= cfg.VIRAL_REPLIES
    )


# --- refresh (the loop's daily heartbeat) --------------------------------

def refresh() -> int:
    if dry_run_active():
        log.info("engagement: dry-run mode; nothing to refresh (no live posts).")
        return 0

    state = _state.load()
    posts = state.get("posts") or {}
    if not posts:
        log.info("engagement: no posts tracked yet")
        return 0

    now = datetime.now(timezone.utc)

    # Which posts are still inside the tracking window?
    tracked_ids: list[str] = []
    for tid, rec in posts.items():
        posted = _state.parse_iso(rec.get("posted_at"))
        if posted is None:
            continue
        age_days = (now - posted).total_seconds() / 86400.0
        if age_days <= cfg.MAX_TRACK_AGE_DAYS:
            tracked_ids.append(tid)

    if not tracked_ids:
        log.info("engagement: nothing within the %d-day window", cfg.MAX_TRACK_AGE_DAYS)
        return 0

    metrics_by_id = _fetch_all_metrics(tracked_ids)

    snapshotted = settled = viral_now = 0
    viralized: list[str] = []
    for tid in tracked_ids:
        rec = posts[tid]
        metrics = metrics_by_id.get(tid)
        if metrics is None:
            continue
        posted = _state.parse_iso(rec.get("posted_at"))
        age_days = (now - posted).total_seconds() / 86400.0

        # Snapshot at the largest bucket we've newly passed.
        passed = [b for b in cfg.SNAPSHOT_AGE_DAYS if age_days >= b]
        already = {s.get("age_days") for s in rec.get("snapshots", [])}
        due = [b for b in passed if b not in already]
        if due:
            rec.setdefault("snapshots", []).append(
                {"at": _state.now_iso(), "age_days": due[-1], "metrics": metrics}
            )
            snapshotted += 1

        # Viral flag (once).
        if rec.get("viral_at") is None and _is_viral(metrics):
            rec["viral_at"] = _state.now_iso()
            viralized.append(tid)
            viral_now += 1

        # Settle + credit the reward to the angle's posterior (once).
        if not rec.get("settled") and age_days >= cfg.REWARD_SETTLE_DAYS:
            reward = allocator.compute_reward(metrics)
            allocator.credit(state, rec.get("arm", ""), reward)
            rec["settled"] = True
            rec["reward"] = round(reward, 4)
            settled += 1
            log.info(
                "engagement: settled %s arm=%s reward=%.3f (likes=%s rt=%s replies=%s)",
                tid, rec.get("arm"), reward,
                metrics.get("like_count"), metrics.get("retweet_count"),
                metrics.get("reply_count"),
            )

    _state.save(state)

    # Replies pull for newly-viral posts (needs a bearer token).
    bearer = os.environ.get("TWITTER_BEARER_TOKEN", "").strip()
    for tid in viralized:
        rec = posts.get(tid)
        if not rec or rec.get("replies_pulled") or not bearer:
            continue
        replies = _fetch_replies(tid, bearer)
        if replies is None:
            continue
        rec["replies"] = replies[:MAX_REPLIES_STORED]
        rec["replies_pulled"] = True
        _state.save(state)

    log.info(
        "engagement: refresh done. tracked=%d snapshotted=%d settled=%d viral_now=%d",
        len(tracked_ids), snapshotted, settled, viral_now,
    )
    return 0


def _fetch_replies(tweet_id: str, bearer: str) -> list[dict[str, Any]] | None:
    try:
        resp = requests.get(
            SEARCH_URL,
            params={
                "query": f"conversation_id:{tweet_id}",
                "max_results": "100",
                "tweet.fields": "author_id,created_at,public_metrics,text",
            },
            headers={"Authorization": f"Bearer {bearer}"},
            timeout=30,
        )
    except Exception as exc:
        log.info("engagement: replies fetch failed for %s: %s", tweet_id, exc)
        return None
    if not resp.ok:
        log.info("engagement: replies fetch %s -> HTTP %d: %s", tweet_id, resp.status_code, resp.text[:200])
        return None
    out: list[dict[str, Any]] = []
    for r in (resp.json() or {}).get("data") or []:
        if isinstance(r, dict):
            out.append({
                "id": r.get("id"),
                "author_id": r.get("author_id"),
                "created_at": r.get("created_at"),
                "text": (r.get("text") or "")[:500],
            })
    return out


# --- report ---------------------------------------------------------------

def report() -> int:
    state = _state.load()
    posts = list((state.get("posts") or {}).values())

    print("=== Angles (bandit posteriors) ===")
    print(f"{'angle':22} {'on':3} {'posts':>5} {'reward μ':>9} {'alpha':>7} {'beta':>7}")
    for r in allocator.report(cfg.ANGLES, state):
        print(f"{r.title:22} {'yes' if r.enabled else 'no ':3} {r.impressions:>5} "
              f"{r.mean:>9.3f} {r.alpha:>7.2f} {r.beta:>7.2f}")

    if not posts:
        print("\nNo posts yet.")
        return 0

    print(f"\n=== Posts ({len(posts)}) ===")
    posts.sort(key=lambda p: p.get("posted_at", ""), reverse=True)
    for p in posts[:40]:
        snaps = p.get("snapshots") or []
        latest = snaps[-1].get("metrics", {}) if snaps else {}
        viral = "VIRAL" if p.get("viral_at") else "     "
        reward = p.get("reward")
        reward_s = f"{reward:.2f}" if isinstance(reward, (int, float)) else "  -  "
        print(
            f"{(p.get('tweet_id') or '')[:19]:19}  {p.get('arm',''):16}  {viral}  "
            f"reward={reward_s}  likes={latest.get('like_count', 0):>4} "
            f"rt={latest.get('retweet_count', 0):>3} "
            f"replies={latest.get('reply_count', 0):>3}  {p.get('posted_at','')}"
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(prog="x_agent.engagement")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("refresh", help="Pull metrics, snapshot, settle rewards into the bandit (cron)")
    sub.add_parser("report", help="Print bandit posteriors + recent posts")
    args = parser.parse_args(argv)
    if args.cmd == "refresh":
        return refresh()
    if args.cmd == "report":
        return report()
    return 0


if __name__ == "__main__":
    sys.exit(main())
