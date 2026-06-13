"""Foreground continuous runner (optional).

The recommended deployment is two systemd timers (post + engagement) —
see systemd/. This loop is for running the agent in the foreground, for
local testing, or on hosts without systemd. Each tick:

  1. poster.run()         — maybe post, respecting the caps.
  2. engagement.refresh() — pull metrics, settle rewards into the bandit.
  3. sleep LOOP_COOLDOWN_S.

    python -m x_agent.loop                 # run forever
    python -m x_agent.loop --once          # one tick then exit
    python -m x_agent.loop --iterations 5  # bounded
"""
from __future__ import annotations

import argparse
import logging
import sys
import time

from . import config as cfg, engagement, poster
from .x_client import dry_run_active

log = logging.getLogger("x_agent.loop")


def tick() -> None:
    poster.run()
    # Engagement refresh only does anything against live posts.
    if not dry_run_active():
        try:
            engagement.refresh()
        except Exception:
            log.exception("loop: engagement.refresh failed; continuing")


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    ap = argparse.ArgumentParser(description="vibe-x-agent foreground loop")
    ap.add_argument("--once", action="store_true", help="One tick then exit")
    ap.add_argument("--iterations", type=int, default=0, help="Run N ticks then exit (0 = forever)")
    args = ap.parse_args(argv)

    n = 0
    while True:
        try:
            tick()
        except KeyboardInterrupt:
            log.info("interrupted; exiting")
            return 0
        except Exception:
            log.exception("loop: tick failed; backing off")
        n += 1
        if args.once or (args.iterations and n >= args.iterations):
            return 0
        log.info("loop: sleeping %ds", cfg.LOOP_COOLDOWN_S)
        time.sleep(cfg.LOOP_COOLDOWN_S)


if __name__ == "__main__":
    sys.exit(main())
