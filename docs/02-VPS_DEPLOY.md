# 02 - Deploy to your VPS

Any Ubuntu VPS works (a $5/mo box is plenty). End to end: ~15 minutes.

## 1. Clone

```bash
ssh you@your-vps
git clone https://github.com/miningstore/vibe-x-agent.git ~/vibe-x-agent
cd ~/vibe-x-agent
```

## 2. Python deps

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r x_agent/requirements.txt
```

## 3. Describe your product

```bash
cp x_agent/product_config_example.py x_agent/product_config.py
$EDITOR x_agent/product_config.py
```

Fill in `PRODUCT` (name, one-liner, URL, audience, description) and — most
importantly — `talking_points`: a handful of real, postable facts. The
agent rotates through them so posts stay specific. See
[03-CUSTOMIZING.md](03-CUSTOMIZING.md).

`product_config.py` is gitignored, so `git pull` never clobbers it.

## 4. Credentials

```bash
cp .env.example .env
$EDITOR .env        # paste TWITTER_API_KEY + TWITTER_API_SECRET
set -a; source .env; set +a
python -m x_agent.authorize begin --label myproduct
# open the URL, authorize, copy the PIN:
python -m x_agent.authorize finish <PIN> --label myproduct --primary
```

Full walkthrough: [01-X_API_SETUP.md](01-X_API_SETUP.md).

## 5. Claude CLI auth (recommended)

The agent writes posts by shelling out to `claude -p`, billing against
your Claude Pro/Max plan — no API key, no per-token cost.

```bash
curl -fsSL https://claude.ai/install.sh | bash
~/.local/bin/claude        # then type /login and complete OAuth
```

This writes `~/.claude/.credentials.json`, which the agent reads on every
run. Do **not** set `ANTHROPIC_API_KEY` and do **not** pass `--bare`
anywhere — both bypass plan auth. (Without Claude installed the agent
still runs; it just posts plain template copy instead of AI-written copy.)

## 6. Health check (your launch gate)

```bash
python -m x_agent.health_check
```

Want `OVERALL: PASS`. `PRODUCT WARN` means you're still on the demo
product (finish step 3). `CLAUDE WARN` means template-only mode (step 5
optional).

## 7. Dry-run first

`.env` ships with `TWITTER_BOT_DRY_RUN=true`, so nothing posts yet:

```bash
python -m x_agent.poster --dry-run
ls x_agent/state/dry_runs/      # review the would-be posts
```

Eyeball a few. Tweak `product_config.py` / `prompts/content_generator.md`
until you like them.

## 8. Install the timers

```bash
bash scripts/install_vps.sh
```

It re-runs the health check, then installs and enables two systemd timers:

| Timer | Default schedule | Job |
|---|---|---|
| `x-agent-post.timer` | 13:00 / 16:30 / 20:00 / 23:30 UTC | maybe post one |
| `x-agent-engagement.timer` | 06:00 UTC daily | pull metrics → credit the bandit |

The script patches the unit paths if your project dir or user isn't the
default `ubuntu`/`~/vibe-x-agent`.

## 9. Go live

When the dry runs look good:

```bash
sed -i 's/TWITTER_BOT_DRY_RUN=true/TWITTER_BOT_DRY_RUN=false/' .env
```

Watch it:

```bash
journalctl -u x-agent-post.service -f
python -m x_agent.engagement report
```

## Running more than one product on one VPS

Clone into a second directory, give it its own `.env` and
`product_config.py`, and copy the systemd units under new names (e.g.
`x-agent-post-acme.*`). One VPS, N products, one Claude login shared by
all of them.

## Stop / pause

```bash
sudo systemctl disable --now x-agent-post.timer x-agent-engagement.timer
```

State (posts + learned posteriors) stays on disk; re-enabling resumes
exactly where it left off.
