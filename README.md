# vibe-x-agent

A self-improving X.com (Twitter) promotion agent you run on your own VPS.
Point it at your product, and a Claude-CLI content engine posts about it
across a set of content angles. An engagement-driven bandit then learns
which angles actually land with your audience and shifts the mix toward
them, automatically, forever.

> **Lineage.** The posting engine is distilled from the production
> `@AverageRent` bot (slop-gated Claude copy, OAuth PIN flow, engagement
> tracker). The closed feedback loop is the
> [vibe-seo-agent](https://github.com/miningstore/vibe-seo-agent) Thompson-
> sampling bandit, ported from "which page title wins" to "which content
> angle wins". That bot collected engagement but never acted on it; this
> one does.

No database, no cloud account, no webhooks. State is one JSON file on the
box. If you have a `$5/mo` VPS and a product, you can be live in 15
minutes.

## What it does

Every time its timer fires, the agent:

1. **Picks an angle** by Thompson-sampling each angle's Beta posterior
   (pain-point, social-proof, how-to, feature-spotlight, hot-take,
   build-in-public, meme — all configurable).
2. **Picks a talking point** — your least-recently-used real fact — so
   posts stay specific instead of generic brand mush.
3. **Writes the post** with `claude -p` (your Claude plan, no API key),
   gated by an AI-slop scorer with a deterministic template fallback. The
   post can be plain text, a meme, or a multi-panel **comic strip** —
   whichever the chosen angle's content type is (all rendered locally).
4. **Posts to X** with the product link applied per your policy.
5. **Tracks engagement** and, a few days later, turns it into a reward
   that updates that angle's posterior — so the next pick is smarter.

## Architecture in one picture

```
your-vps
└── ~/vibe-x-agent/
    ├── x_agent/                     # the Python package
    │   ├── product_config.py        # YOUR product (the one file you edit)
    │   ├── poster.py                # pick angle -> generate -> post
    │   ├── allocator.py             # Thompson sampling + reward crediting
    │   ├── engagement.py            # metrics -> reward -> posterior
    │   └── state/agent_state.json   # posts + learned posteriors (no DB)
    ├── systemd: x-agent-post.timer        # posts a few times a day
    └── systemd: x-agent-engagement.timer  # nightly: credits the bandit

your X account  ◄── posts ── agent ── reads metrics ──►  the feedback loop
```

## What makes this different

| Problem | Common (broken) approach | What this repo does |
|---|---|---|
| Bots post forever at the same quality | Hand-pick content, hope | **Bandit feedback loop**: engagement updates Beta posteriors per angle; Thompson sampling shifts the mix toward what lands |
| `claude` on a VPS needs an API key? | `--bare`, `ANTHROPIC_API_KEY` | Use your Claude Pro/Max plan via `~/.claude/.credentials.json`; the loop calls `claude -p` (never `--bare`) |
| Auth on a headless box | Spin up an OAuth callback server | **PIN flow** (`authorize.py`) — open a URL, paste a 7-digit code, done. Add accounts with `--label` |
| Reading engagement needs a separate API tier | Set up a bearer token + app-only auth | Metrics come back through the **same OAuth tokens you post with** — zero extra setup |
| AI posts read like AI | Ship them anyway | **Slop gate**: every draft scored 0-50, regenerated against flagged tells, template fallback below threshold |
| Bots drift into spam or infringement | Hope the prompt holds | **Hard guardrails** baked in: no copyrighted text, no fake quotes from real people, no hateful copy or advice-as-fact, no invented stats |
| Stale, repetitive posts | Feed it news by hand | **Optional web grounding**: the agent searches for one timely, real hook and ties the product to it (opt-in, falls back safely) |
| One format forever (just text) | Bolt on a separate tool per format | **Pluggable content types**: text, classic memes, and multi-panel **comic strips** (rendered locally, no image-gen), each its own bandit arm so the loop learns which format lands |
| A heavy stack to babysit | Postgres + a queue + a dashboard | One JSON state file. `git pull` never fights your config (gitignored overlay) |

## The feedback loop (the core idea)

Each **angle** is a bandit arm with a Beta(α, β) posterior on its reward
per post.

- **Select**: draw one sample from every enabled arm's Beta; post in the
  arm that drew highest (plus an ε floor so nothing starves and new angles
  get tried).
- **Reward** (when a post is `REWARD_SETTLE_DAYS` old):
  ```
  score  = 1·likes + 3·retweets + 2·replies + 3·quotes + 2·bookmarks
  reward = 1 − exp(−score / REWARD_SCALE)          # bounded in [0, 1)
  ```
- **Credit**: `α += reward`, `β += (1 − reward)`. One settled post = one
  trial. The next selection is now informed by what actually earned
  engagement.

Inspect what it has learned any time:

```bash
python -m x_agent.engagement report
```

Full walkthrough with a diagram: [docs/04-OPERATIONS.md](docs/04-OPERATIONS.md).

## Quickstart

```bash
# 1. Clone + deps
git clone https://github.com/miningstore/vibe-x-agent.git ~/vibe-x-agent
cd ~/vibe-x-agent
python3 -m venv .venv && source .venv/bin/activate
pip install -r x_agent/requirements.txt

# 2. Describe your product (gitignored overlay)
cp x_agent/product_config_example.py x_agent/product_config.py
$EDITOR x_agent/product_config.py        # name, one-liner, url, talking_points

# 3. X developer App -> consumer keys (docs/01-X_API_SETUP.md)
cp .env.example .env
$EDITOR .env                              # TWITTER_API_KEY + TWITTER_API_SECRET

# 4. Mint your posting tokens (PIN flow, no callback server needed)
set -a; source .env; set +a
python -m x_agent.authorize begin --label myproduct
python -m x_agent.authorize finish <PIN> --label myproduct --primary

# 5. (Recommended) Claude plan auth so posts are AI-written, free
curl -fsSL https://claude.ai/install.sh | bash && ~/.local/bin/claude   # /login

# 6. Verify, then preview without posting
python -m x_agent.health_check
python -m x_agent.poster --dry-run        # writes samples to state/dry_runs/

# 7. Deploy the timers, then flip live when the dry runs look good
bash scripts/install_vps.sh
sed -i 's/TWITTER_BOT_DRY_RUN=true/TWITTER_BOT_DRY_RUN=false/' .env
```

That's it. It posts a few times a day, scores engagement nightly, and
tunes itself. `TWITTER_BOT_DRY_RUN=true` is the default — it cannot post
until you opt in.

## How the parts fit

| File | Purpose |
|---|---|
| `x_agent/product_config.py` | **YOUR product** — the one file you edit (overlay; gitignored) |
| `x_agent/models.py` | `Product` + `Angle` dataclasses |
| `x_agent/angles.py` | default content angles (the bandit's arms) |
| `x_agent/allocator.py` | Thompson sampling, reward function, posterior crediting |
| `x_agent/content.py` | `claude -p` generation + slop gate + template fallback |
| `x_agent/poster.py` | the orchestrator: pick → generate → post → record |
| `x_agent/engagement.py` | pull metrics, snapshot, settle reward into the bandit |
| `x_agent/x_client.py` | minimal X API v2 client (post, media, metrics) |
| `x_agent/authorize.py` | OAuth 1.0a PIN flow to mint per-account tokens |
| `x_agent/state.py` | the single local JSON ledger |
| `x_agent/health_check.py` | pre-launch verification gate |
| `x_agent/loop.py` | optional foreground runner (instead of systemd) |
| `x_agent/render.py` | content-type render dispatch (text / meme / comic) |
| `x_agent/meme.py` | top/bottom-text meme renderer (Pillow) |
| `x_agent/comic.py` | multi-panel comic-strip renderer (Pillow) |

## Customizing

Everything product-specific is one gitignored file:
`x_agent/product_config.py`. Cadence, link policy, and bandit knobs are
all env vars in `.env`. The posting schedule is the `OnCalendar=` lines in
`systemd/x-agent-post.timer`. See
[docs/03-CUSTOMIZING.md](docs/03-CUSTOMIZING.md).

## Docs

| Doc | Purpose |
|---|---|
| [01-X_API_SETUP.md](docs/01-X_API_SETUP.md) | X developer App, permissions, the PIN flow |
| [02-VPS_DEPLOY.md](docs/02-VPS_DEPLOY.md) | clone → venv → tokens → Claude auth → systemd |
| [03-CUSTOMIZING.md](docs/03-CUSTOMIZING.md) | product config, angles, voice, cadence |
| [04-OPERATIONS.md](docs/04-OPERATIONS.md) | the feedback loop, reading the bandit, tuning, debugging |

## Safety + cost

- **Dry-run by default.** `TWITTER_BOT_DRY_RUN=true` writes would-be posts
  to `state/dry_runs/` and makes zero network calls until you flip it.
- **Slop gate** keeps AI tells out of your timeline; **template fallback**
  means a Claude outage degrades gracefully instead of going silent.
- **Free-tier friendly.** Default 4 posts/day ≈ 120/month, well under X's
  ~500/month Free cap. Claude runs on your plan (no per-token cost). A
  `$5/mo` VPS idles between fires.

## License

MIT.
