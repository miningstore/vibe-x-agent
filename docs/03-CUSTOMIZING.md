# 03 - Customizing for your product

Everything product-specific lives in one gitignored file:
`x_agent/product_config.py`. The rest of the package is generic.

## The overlay pattern (don't fight template updates)

DON'T edit `x_agent/config.py`. Create the overlay instead:

```bash
cp x_agent/product_config_example.py x_agent/product_config.py
```

It's gitignored, so you can `git pull` template updates forever without
merge conflicts. `config.py` loads it automatically (and falls back to
the bundled demo so a fresh clone can `--dry-run` immediately).

## PRODUCT — what you're promoting

```python
from .models import Product

PRODUCT = Product(
    name="Acme Analytics",
    one_liner="Session replay that doesn't slow your site down.",
    url="https://acme.example.com",
    audience="indie SaaS founders and frontend devs",
    description=(
        "Acme records real user sessions with a 3kb script and surfaces the "
        "rage-clicks and dead-ends that lose you signups."
    ),
    talking_points=(
        "Acme's script is 3kb gzipped. Most replay tools are 50kb+.",
        "We just shipped funnels: see exactly which step loses signups.",
        "Free tier records 1,000 sessions/month, no credit card.",
        "One customer cut their onboarding drop-off by 22% in a week.",
    ),
    voice="Direct, technical, a little dry. Talk like an engineer who hates bloat.",
    extra_links=("https://acme.example.com/docs",),
    hashtags=("#buildinpublic",),
)
```

### Talking points are the most important field

A `talking_point` is one concrete, postable fact. The poster picks the
**least-recently-used** one each run and hands it to the model as the
anchor, so consecutive posts stay specific instead of devolving into
"check out our amazing product". Treat this list as a living changelog:
add a line whenever you ship something, hit a milestone, or learn a
customer story. 6-15 is a good range; rotate them as they go stale.

## Angles — the bandit's arms

An **angle** is a repeatable *way* to talk about the product (pain point,
social proof, how-to, hot take, feature spotlight, build-in-public, meme).
The defaults live in [`x_agent/angles.py`](../x_agent/angles.py). Each
enabled angle is one bandit arm; the feedback loop learns which earn
engagement and biases selection toward them.

You usually don't need to touch these. To customize, set `ANGLES` in your
overlay:

```python
from .angles import DEFAULT_ANGLES
from .models import Angle

ANGLES = DEFAULT_ANGLES + [
    Angle(
        key="comparison",
        title="Vs the old way",
        brief="Contrast the painful manual workflow with the one-command "
              "version. Concrete before/after. Never name a competitor.",
    ),
]
```

- **Disable** an angle: copy `DEFAULT_ANGLES`, set `enabled=False` on the
  one you don't want. It stays in reports but is never selected.
- **Add** an angle: a new arm starts on a flat prior; the exploration
  floor guarantees it gets tried, then it earns or loses share on merit.
- **Enable memes**: flip the `meme` angle's `enabled=True` and either set
  `X_AGENT_MEME_TEMPLATE=/path/to/template.png` or let it render text on a
  solid brand background. Needs Pillow (already in requirements).

## Voice + house rules

Two layers:

1. `PRODUCT.voice` — one sentence, handed to the model verbatim. Be
   opinionated; generic voice produces generic posts.
2. [`x_agent/prompts/content_generator.md`](../x_agent/prompts/content_generator.md)
   — appended to every system prompt. Put hard house rules here (banned
   phrasings, structural preferences). Edit freely; delete the body to
   fall back to the built-in rules only.

## Banned tokens

Em/en dashes are always banned (they read as AI-written). Add your own —
competitor names, off-brand words — in the overlay:

```python
BANNED = ("Hootsuite", "synergy", "10x")
```

The generator is told never to emit them, and the slop gate docks any
draft that slips one through.

## Cadence, links, and the bandit — all via env

No code edits needed; set these in `.env` (see `.env.example`):

| Knob | Default | What it does |
|---|---|---|
| `X_AGENT_MAX_POSTS_PER_DAY` | 4 | hard daily ceiling |
| `X_AGENT_MIN_HOURS_BETWEEN_POSTS` | 3 | spacing; makes extra timer fires no-ops |
| `X_AGENT_LINK_POLICY` | sometimes | `always` / `sometimes` / `never` (X can throttle link posts) |
| `X_AGENT_LINK_EVERY_N` | 3 | with `sometimes`, link on every Nth post |
| `X_AGENT_LLM_MODEL` | sonnet | `sonnet` / `opus` / `haiku` |
| `X_AGENT_EXPLORATION_FLOOR` | 0.15 | min fraction of posts chosen at random |
| `X_AGENT_REWARD_SETTLE_DAYS` | 3 | post age at which engagement is scored |
| `X_AGENT_REWARD_SCALE` | 10 | higher = more engagement needed per reward unit |
| `X_AGENT_WEB_GROUNDING` | false | let the agent search for a timely hook (see below) |

The posting schedule itself (which clock times the agent wakes) lives in
`systemd/x-agent-post.timer` — edit the `OnCalendar=` lines for your
audience's timezone.

## Web grounding (freshness, opt-in)

By default the agent writes from your static `talking_points`. With web
grounding on, the first generation attempt per post lets Claude use the
read-only web tools (WebSearch/WebFetch) to find one timely, real hook (a
trend, a piece of news, a conversation your audience is having) and tie the
product to it. This is the difference between a bot that repeats itself and
one that feels plugged into the moment.

Turn it on in `.env`:

```bash
X_AGENT_WEB_GROUNDING=true
# optional:
X_AGENT_WEB_GROUNDING_BUDGET_USD=0.50   # per-post spend cap on the grounded call
X_AGENT_WEB_GROUNDING_TIMEOUT_S=240     # grounded calls are slower (they search)
```

Requirements and behavior:

- Needs the `claude` CLI logged in on the host (plan auth). `health_check`
  shows `grounding=on` and warns if the CLI is missing.
- The model is instructed to use only facts it actually finds and to fall
  back to a normal post if nothing strong and recent turns up. It never
  pastes URLs into the text.
- Any failure (timeout, budget, error) falls back to ordinary generation,
  which falls back to a template. Grounding can never block a post.
- It costs a little per post and is slower, which is why it is off by
  default. Verify it on your VPS with a dry run before going live:
  `X_AGENT_WEB_GROUNDING=true python -m x_agent.poster --dry-run`.

## Safety guardrails (always on)

Every generated post is held to a set of hard guardrails baked into the
content prompt (you cannot disable these by editing the overlay): no
reproduction of copyrighted text (lyrics, poems, book or article passages),
no quotes attributed to or impersonation of real named people, no hateful or
harassing content, no medical/legal/financial advice framed as fact, and no
invented statistics, testimonials, or features. The slop gate is a second
layer on top of these. They exist so the agent is safe to point at your
audience the moment you turn it on.
