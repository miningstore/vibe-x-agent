# 04 - Operations

How the agent runs day to day, how to read what it's learned, and how to
debug it.

## The feedback loop, end to end

This is the part that makes the agent get better instead of just posting
forever at random.

```
                 ┌─────────────────────────────────────────────┐
                 │  x-agent-post.timer  (a few times a day)     │
                 └───────────────────────┬─────────────────────┘
                                         ▼
   allocator.choose_angle()  ──►  Thompson-sample each angle's Beta(α,β),
   (+ ε exploration floor)        post in the arm that drew highest
                                         │
                                         ▼
   content.generate()  ──►  Claude writes copy for (angle, talking point),
                            slop gate scores it, template fallback if needed
                                         │
                                         ▼
   x_client.post_tweet()  ──►  posted; state records the post + its angle
                                         │
            (1–3 days pass; the post accumulates likes/RTs/replies)
                                         │
                 ┌───────────────────────▼─────────────────────┐
                 │  x-agent-engagement.timer  (daily 06:00 UTC) │
                 └───────────────────────┬─────────────────────┘
                                         ▼
   engagement.refresh()  ──►  pull public_metrics, snapshot at 1/3/7d
                                         │
                  at REWARD_SETTLE_DAYS:  compute reward in [0,1]
                                         ▼
   allocator.credit()  ──►  α += reward, β += (1 − reward) on that angle
                                         │
                                         ▼
                 the NEXT choose_angle() is now biased by what landed
```

The reward for a settled post is

```
score  = 1·likes + 3·retweets + 2·replies + 3·quotes + 2·bookmarks
reward = 1 − exp(−score / REWARD_SCALE)        # bounded in [0, 1)
```

Saturating on purpose: one mega-viral post nudges an angle strongly but
can't peg it to certainty. Weights and scale are tunable (`.env`).

## Reading the bandit

```bash
python -m x_agent.engagement report
```

```
=== Angles (bandit posteriors) ===
angle                   on  posts  reward μ   alpha    beta
Social proof / traction yes    11     0.412    5.53    7.88
Build in public         yes     9     0.388    4.49    7.08
Pain point              yes    12     0.301    4.61   10.72
How-to / quick tip      yes     8     0.221    2.77    9.78
Hot take / opinion      yes    10     0.184    2.84   12.61
Feature spotlight       yes     7     0.142    1.99   12.03
Meme                    no      0     0.500    1.00    1.00
```

- **reward μ** = posterior mean `α/(α+β)` — the angle's estimated reward
  per post. Higher = posts in this angle tend to land for *your* audience.
- **posts** = settled trials backing that estimate. Early on (few posts)
  the means are noisy and the bandit is mostly exploring; trust them more
  as `posts` climbs.
- A disabled angle (`on=no`) keeps its prior and is never selected.

You don't *do* anything with this — the loop already acts on it. It's for
your understanding (and for deciding whether to add/retire angles).

## What to watch

```bash
# Did the last posting fire post or skip (and why)?
journalctl -u x-agent-post.service -n 50

# Did the nightly refresh settle rewards?
journalctl -u x-agent-engagement.service -n 50

# Timers healthy / next fire times
systemctl list-timers | grep x-agent
```

Healthy posting logs show one of: `posted ...`, `daily cap reached`, or
`only N.Nh since last post` (all normal). Slop fallbacks log
`slop gate not cleared ... using template` — an occasional one is fine; a
steady stream means the model is fighting your voice rules (tighten
`product_config.py` / `prompts/content_generator.md`).

## Tuning

| Symptom | Lever |
|---|---|
| Converges too fast onto one angle | raise `X_AGENT_EXPLORATION_FLOOR` (e.g. 0.25) |
| Too random / never settles | lower the floor (e.g. 0.08); let it run longer |
| Rewards feel too easy/hard | adjust `X_AGENT_REWARD_SCALE` (higher = harder) |
| Wrong metric prioritized | tune `X_AGENT_W_LIKE` / `_W_RETWEET` / `_W_REPLY` … |
| Posts too often / rarely | `X_AGENT_MAX_POSTS_PER_DAY`, timer `OnCalendar=` lines |

After changing reward weights/scale you can let the posteriors re-learn
naturally, or reset them (below) for a clean slate.

## State file

Everything lives in `x_agent/state/agent_state.json` (gitignored):
posts, per-angle posteriors, talking-point last-used times, the cached
handle. It's plain JSON — safe to inspect, back up, or hand-edit when the
agent is stopped.

- **Reset the learning** (keep posting history): delete the `"arms"` key.
- **Full reset**: delete the file. Posteriors return to the flat prior.
- **Back up**: copy the file; that's the entire brain.

## Recovering from a bad post

There's no auto-undo:

1. Delete the post in the X app.
2. Optionally remove its entry from the `"posts"` object in
   `agent_state.json` (when the agent is stopped) so it isn't tracked.

The reward it would have earned simply never gets credited — no harm.

## Cost

- **Claude**: a handful of short `claude -p` calls per post (generation +
  slop scoring). On a Pro/Max plan that's within your normal usage; no
  per-token bill. On `haiku` it's negligible even via API.
- **X**: Free tier (~500 posts/mo) covers the default 4/day with room to
  spare.
- **VPS**: a $5/mo box idles almost all day; the work is seconds per fire.

## Multiple accounts / products

Each `--label` in `authorize.py` mints a separate token set under
`state/tokens/`. To actually *run* multiple products, give each its own
clone + `.env` + `product_config.py` + renamed systemd units (see
[02-VPS_DEPLOY.md](02-VPS_DEPLOY.md)). They share one Claude login.
