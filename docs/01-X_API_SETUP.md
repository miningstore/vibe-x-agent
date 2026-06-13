# 01 - X (Twitter) API setup

You need an X developer App and four secrets. ~10 minutes, one-time.

## 1. Create a developer account + App

1. Go to <https://developer.x.com/en/portal/dashboard> and sign in as the
   account you want to post from (or any account that will own the App —
   one App can post as many accounts).
2. Sign up for the **Free** tier if prompted. It allows ~500 posts/month
   and includes `POST /2/tweets`, media upload, and tweet lookup, which is
   everything this agent needs.
3. Create a **Project**, then an **App** inside it.

## 2. Set the App to Read + Write

This is the step people miss. Tokens minted while the App is read-only
can't post.

1. App → **Settings** → **User authentication settings** → **Set up**.
2. **App permissions**: select **Read and write**.
3. **Type of App**: *Web App, Automated App or Bot*.
4. **Callback URI**: anything valid, e.g. `https://example.com/callback`
   (the agent uses the PIN/`oob` flow, so this isn't actually hit, but the
   form requires a value).
5. **Website URL**: your product URL.
6. Save.

## 3. Copy the consumer keys

App → **Keys and tokens** → **Consumer Keys** → **API Key and Secret** →
*Regenerate* if needed and copy both:

```
TWITTER_API_KEY=...        # "API Key"
TWITTER_API_SECRET=...     # "API Key Secret"
```

Put them in your `.env` (see `.env.example`).

> You do **not** need to copy the "Access Token and Secret" shown on that
> page. The agent mints per-account access tokens itself via the PIN flow
> below, which is the part that makes it easy to run on a headless VPS and
> to add more accounts later.

## 4. Mint the access tokens (PIN flow)

On the VPS (or locally), with the consumer keys in your env:

```bash
set -a; source .env; set +a
python -m x_agent.authorize begin --label myproduct
```

It prints an `x.com/oauth/authorize?...` URL. Open it in a browser logged
in as the account you want to post as, click **Authorize**, and copy the
7-digit PIN. Then:

```bash
python -m x_agent.authorize finish <PIN> --label myproduct --primary
```

`--primary` writes `TWITTER_ACCESS_TOKEN` / `TWITTER_ACCESS_SECRET` into
your `.env` automatically. The token also gets saved under
`x_agent/state/tokens/myproduct.json`.

Repeat with a different `--label` for each additional account.

## 5. (Optional) Bearer token

Only needed if you want the agent to pull *replies* on posts that go
viral. The reward/feedback loop reads metrics with the OAuth tokens above
and needs no bearer. If you want replies: App → Keys and tokens →
**Bearer Token** → Generate, then set `TWITTER_BEARER_TOKEN=...` in `.env`.

## Verify

```bash
python -m x_agent.health_check
```

Expect `X CREDS OK` and `X API OK  @yourhandle`. If `X API` fails with a
403, your App is still read-only — redo step 2, then re-mint tokens (step
4), because permissions are baked into the token at mint time.

## Free tier limits worth knowing

| Limit | Free tier |
|---|---|
| Posts | ~500 / month (the default cadence of 4/day = ~120/month) |
| Media upload | supported |
| Tweet lookup (metrics) | supported (this is the reward signal) |
| Recent search (replies) | limited; needs the bearer token |

If you outgrow Free, Basic ($100-200/mo) raises the caps; nothing in the
agent changes.
