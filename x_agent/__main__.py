"""`python -m x_agent` — print the available subcommands.

Each real entry point is its own module so the systemd units and cron
lines stay explicit:

    python -m x_agent.authorize begin --label myproduct
    python -m x_agent.health_check
    python -m x_agent.poster --dry-run
    python -m x_agent.engagement refresh
    python -m x_agent.engagement report
    python -m x_agent.loop --once
"""
from __future__ import annotations

import sys

USAGE = """\
vibe-x-agent — commands:

  python -m x_agent.authorize begin --label <name>     mint X OAuth tokens (step 1)
  python -m x_agent.authorize finish <PIN> --label <name> --primary   (step 2)
  python -m x_agent.health_check [--skip-x]             pre-launch check
  python -m x_agent.poster [--dry-run|--no-dry-run]     decide + post
  python -m x_agent.engagement refresh                 metrics -> bandit reward
  python -m x_agent.engagement report                  posteriors + recent posts
  python -m x_agent.loop [--once]                       foreground runner
"""


def main() -> int:
    print(USAGE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
