"""Decide what to post and post it — the orchestrator.

One run = one (or a few) posts. Designed to be fired by a systemd timer
several times a day. Each post:

  1. Thompson-sample an angle from the live posteriors (allocator).
  2. Pick the least-recently-used talking point (keeps posts specific).
  3. Generate slop-gated copy for that (angle, talking point).
  4. Append the product link per LINK_POLICY.
  5. Post to X (or write a dry-run file).
  6. Register the post against its angle so engagement.refresh() can later
     credit the reward back to that angle's posterior.

Caps (MAX_POSTS_PER_DAY, MIN_HOURS_BETWEEN_POSTS) make repeated timer
fires safe and idempotent-ish: an extra fire inside the cooldown is a
no-op.

    python -m x_agent.poster --dry-run     # write would-be posts to disk
    python -m x_agent.poster                # respect TWITTER_BOT_DRY_RUN
    python -m x_agent.poster --no-dry-run   # force live (careful)
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import allocator, config as cfg, content as _content, state as _state
from .models import Angle
from .x_client import XClient, dry_run_active

log = logging.getLogger(__name__)

LINK_RESERVE = 28   # chars held back for "\n\n" + a t.co-wrapped URL
NOLINK_RESERVE = 4


def _should_include_link(state: dict) -> bool:
    policy = cfg.LINK_POLICY
    if policy == "always":
        return True
    if policy == "never":
        return False
    n = len(state.get("posts") or {})
    return cfg.LINK_EVERY_N > 0 and (n % cfg.LINK_EVERY_N == 0)


def _assemble(body: str, include_link: bool) -> str:
    if include_link and cfg.PRODUCT.url:
        return f"{body}\n\n{cfg.PRODUCT.url}"
    return body


def _render_meme_png(post: _content.GeneratedPost) -> bytes | None:
    try:
        from . import meme  # lazy: Pillow only needed for meme angles
    except ImportError:
        log.warning("poster: meme angle selected but Pillow not installed; posting text only")
        return None
    try:
        return meme.render(post.meme_top, post.meme_bottom)
    except Exception as exc:
        log.warning("poster: meme render failed (%s); posting text only", exc)
        return None


def _write_dry_run(post_id: str, text: str, png: bytes | None) -> None:
    cfg.DRY_RUN_DIR.mkdir(parents=True, exist_ok=True)
    base = cfg.DRY_RUN_DIR / post_id
    base.with_suffix(".txt").write_text(text)
    if png:
        base.with_suffix(".png").write_bytes(png)
    log.info("poster: dry-run wrote %s.txt%s", base.name, " (+.png)" if png else "")


def _post_once(state: dict, client: XClient | None, *, dry: bool) -> bool:
    angle = allocator.choose_angle(cfg.ANGLES, state)
    if angle is None:
        log.warning("poster: no enabled angles; nothing to do")
        return False
    talking_point = _state.pick_talking_point(state, cfg.TALKING_POINTS)
    include_link = _should_include_link(state)
    reserve = LINK_RESERVE if include_link else NOLINK_RESERVE
    recent = _state.recent_post_texts(state, cfg.RECENT_POSTS_TO_AVOID)

    post = _content.generate(
        cfg.PRODUCT, angle, talking_point,
        recent_texts=recent, max_chars=280 - reserve,
    )
    text = _assemble(post.text, include_link)
    png = _render_meme_png(post) if angle.fmt == "meme" else None

    log.info("poster: angle=%s tp=%r src=%s link=%s chars=%d",
             angle.key, (talking_point or "")[:48], post.source, include_link, len(text))

    if dry or client is None:
        post_id = "dry-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f") + "-" + angle.key
        _write_dry_run(post_id, text, png)
        _state.record_post(state, post_id=post_id, arm=angle.key, fmt=angle.fmt,
                           talking_point=talking_point or "", text=post.text,
                           link_included=include_link)
        return True

    media_ids: list[str] | None = None
    if png:
        try:
            media_ids = [client.upload_media(png)]
        except Exception as exc:
            log.error("poster: media upload failed (%s); posting text only", exc)
            media_ids = None
    try:
        resp = client.post_tweet(text=text, media_ids=media_ids)
        tweet_id = (resp.get("data") or {}).get("id")
    except Exception as exc:
        log.error("poster: post failed for angle=%s: %s", angle.key, exc)
        return False
    if not tweet_id:
        log.error("poster: post returned no id: %s", resp)
        return False

    _state.record_post(state, post_id=str(tweet_id), arm=angle.key, fmt=angle.fmt,
                       talking_point=talking_point or "", text=post.text,
                       link_included=include_link)
    log.info("poster: posted https://x.com/i/status/%s", tweet_id)
    return True


def run(*, max_posts: int | None = None, dry_run_override: bool | None = None) -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    dry = dry_run_active() if dry_run_override is None else dry_run_override

    if cfg.using_demo_product() and not dry:
        log.error("poster: refusing to post live with the DEMO product. Create "
                  "x_agent/product_config.py first (see product_config_example.py).")
        return 2

    state = _state.load()

    # Live-budget gates (daily cap + spacing) apply only to real posting.
    # Dry-run is for previewing copy, so it ignores them.
    remaining = 10**9
    if not dry:
        posted_today = _state.count_posts_today(state)
        if posted_today >= cfg.MAX_POSTS_PER_DAY:
            log.info("poster: daily cap reached (%d/%d); idle", posted_today, cfg.MAX_POSTS_PER_DAY)
            return 0
        last = _state.last_post_at(state)
        if last is not None:
            hours = (datetime.now(timezone.utc) - last).total_seconds() / 3600.0
            if hours < cfg.MIN_HOURS_BETWEEN_POSTS:
                log.info("poster: only %.1fh since last post (min %.1fh); idle",
                         hours, cfg.MIN_HOURS_BETWEEN_POSTS)
                return 0
        remaining = cfg.MAX_POSTS_PER_DAY - posted_today

    cap = cfg.MAX_POSTS_PER_RUN if max_posts is None else max_posts
    cap = min(cap, remaining)

    client: XClient | None = None
    if not dry:
        client = XClient()

    posted = 0
    for _ in range(max(0, cap)):
        if _post_once(state, client, dry=dry):
            posted += 1
            _state.save(state)  # save after each for crash safety
    log.info("poster: done. posted=%d (dry_run=%s)", posted, dry)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="vibe-x-agent poster")
    parser.add_argument("--dry-run", action="store_true",
                        help="Force dry-run regardless of TWITTER_BOT_DRY_RUN")
    parser.add_argument("--no-dry-run", action="store_true",
                        help="Force live posting (overrides env). Use with care.")
    parser.add_argument("--max-posts", type=int, default=None)
    args = parser.parse_args(argv)
    override: bool | None = None
    if args.dry_run:
        override = True
    elif args.no_dry_run:
        override = False
    return run(max_posts=args.max_posts, dry_run_override=override)


if __name__ == "__main__":
    sys.exit(main())
