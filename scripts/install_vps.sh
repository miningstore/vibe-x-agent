#!/usr/bin/env bash
# Install vibe-x-agent on a fresh Ubuntu VPS.
#
# Pre-reqs (do these first — see docs/02-VPS_DEPLOY.md):
#   1. Created an X developer App (docs/01-X_API_SETUP.md), have the
#      consumer key/secret.
#   2. Cloned this repo to ~/vibe-x-agent on the VPS.
#   3. Created x_agent/product_config.py (copy product_config_example.py).
#   4. cp .env.example .env, filled in TWITTER_API_KEY / TWITTER_API_SECRET.
#   5. Installed Claude Code on the VPS and ran /login (so the agent
#      inherits your plan auth via ~/.claude/.credentials.json).
#
# Then run this on the VPS:
#   bash scripts/install_vps.sh

set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-$HOME/vibe-x-agent}"
cd "$PROJECT_DIR"

# --- 1. System deps ---------------------------------------------------------
if ! command -v python3 >/dev/null; then
  sudo apt update && sudo apt install -y python3 python3-venv python3-pip git
fi

# --- 2. Python venv + deps --------------------------------------------------
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
source .venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet -r x_agent/requirements.txt

# --- 3. Sanity: required files present --------------------------------------
if [ ! -f .env ]; then
  echo "ERROR: .env missing. cp .env.example .env and fill it in."
  exit 1
fi
if [ ! -f x_agent/product_config.py ]; then
  echo "ERROR: x_agent/product_config.py missing."
  echo "  cp x_agent/product_config_example.py x_agent/product_config.py"
  echo "  then edit it to describe YOUR product."
  exit 1
fi
chmod 600 .env

# --- 4. Mint X tokens if not present ----------------------------------------
set -a; source .env; set +a
if [ -z "${TWITTER_ACCESS_TOKEN:-}" ] || [ -z "${TWITTER_ACCESS_SECRET:-}" ]; then
  echo ""
  echo "No TWITTER_ACCESS_TOKEN in .env yet. Run the OAuth PIN flow now:"
  echo "  source .env"
  echo "  python -m x_agent.authorize begin --label myproduct"
  echo "  # open the URL, authorize, copy the PIN, then:"
  echo "  python -m x_agent.authorize finish <PIN> --label myproduct --primary"
  echo ""
  echo "Re-run this script once the tokens are in .env."
  exit 1
fi

# --- 5. Claude CLI auth (plan auth, not API key) — advisory ----------------
if [ ! -f "$HOME/.claude/.credentials.json" ]; then
  echo "WARNING: ~/.claude/.credentials.json not found."
  echo "  The agent will fall back to plain-template posts (no AI copy)."
  echo "  To enable Claude-written posts: install Claude Code and run /login:"
  echo "    curl -fsSL https://claude.ai/install.sh | bash && ~/.local/bin/claude"
fi

# --- 6. Health check (your launch gate) ------------------------------------
echo ""
echo "=== Running health check ==="
python -m x_agent.health_check || {
  echo "Health check FAILED. Fix the above before installing the timers."
  exit 1
}

# --- 7. Install systemd units ----------------------------------------------
SYSTEMD_USER="${SUDO_USER:-$USER}"
echo ""
echo "Install + enable the systemd timers (posting + engagement)?"
read -rp "Proceed? [y/N] " yn
if [[ "$yn" != "y" && "$yn" != "Y" ]]; then
  echo "Skipping systemd install. Re-run when ready."
  exit 0
fi

sudo cp systemd/x-agent-post.service systemd/x-agent-post.timer \
        systemd/x-agent-engagement.service systemd/x-agent-engagement.timer \
        /etc/systemd/system/

# Patch paths/user if the project dir or user differs from the defaults.
sudo sed -i \
  -e "s|/home/ubuntu/vibe-x-agent|$PROJECT_DIR|g" \
  -e "s|User=ubuntu|User=$SYSTEMD_USER|g" \
  /etc/systemd/system/x-agent-post.service \
  /etc/systemd/system/x-agent-engagement.service

sudo systemctl daemon-reload
sudo systemctl enable --now x-agent-post.timer x-agent-engagement.timer

echo ""
echo "Enabled timers:"
sudo systemctl list-timers | grep x-agent || true
echo ""
echo "DONE. Next:"
echo "  • Keep TWITTER_BOT_DRY_RUN=true in .env for the first day and watch"
echo "    state/dry_runs/ fill with sample posts:"
echo "      python -m x_agent.poster --dry-run"
echo "  • When happy, set TWITTER_BOT_DRY_RUN=false in .env and reload."
echo "  • Watch it work:"
echo "      journalctl -u x-agent-post.service -f"
echo "      python -m x_agent.engagement report"
