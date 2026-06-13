"""3-legged OAuth 1.0a PIN flow to mint X.com user-context access tokens.

The agent needs four secrets to post:

    TWITTER_API_KEY        # the App's consumer key (X developer portal)
    TWITTER_API_SECRET     # the App's consumer secret
    TWITTER_ACCESS_TOKEN   # per-user, granted when the user authorizes the App
    TWITTER_ACCESS_SECRET  # per-user

Consumer key/secret come from the X developer portal (one App can post
as many accounts). Each account authorizes the App once, which yields its
(access_token, access_secret) pair.

The PIN flow needs no inbound HTTP, so it works from a headless VPS:

    1. python -m x_agent.authorize begin --label myproduct
       -> prints an x.com authorize URL. Open it in a browser logged in
          as the account you want to post as. Click Authorize. X shows a
          7-digit PIN.

    2. python -m x_agent.authorize finish <PIN> --label myproduct --primary
       -> exchanges the PIN for access tokens, writes them under
          state/tokens/<label>.json, and (with --primary) upserts
          TWITTER_ACCESS_TOKEN / TWITTER_ACCESS_SECRET into your .env.

Run again with a different --label per account you want to post as.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

from requests_oauthlib import OAuth1Session  # type: ignore

from . import config as cfg

REQUEST_TOKEN_URL = "https://api.twitter.com/oauth/request_token"
AUTHORIZE_URL = "https://api.twitter.com/oauth/authorize"
ACCESS_TOKEN_URL = "https://api.twitter.com/oauth/access_token"

PENDING_DIR = cfg.STATE_DIR / "oauth_pending"
TOKENS_DIR = cfg.STATE_DIR / "tokens"


def _label_path(base: Path, label: str) -> Path:
    safe = re.sub(r"[^a-z0-9_-]+", "-", label.strip().lower())
    if not safe:
        raise SystemExit(f"invalid label: {label!r}")
    return base / f"{safe}.json"


def _consumer_creds() -> tuple[str, str]:
    api_key = os.environ.get("TWITTER_API_KEY", "").strip()
    api_secret = os.environ.get("TWITTER_API_SECRET", "").strip()
    if not api_key or not api_secret:
        raise SystemExit(
            "TWITTER_API_KEY / TWITTER_API_SECRET must be set. Source your .env "
            "first (e.g. `set -a && . ./.env && set +a`)."
        )
    return api_key, api_secret


def cmd_begin(args: argparse.Namespace) -> int:
    api_key, api_secret = _consumer_creds()
    oauth = OAuth1Session(client_key=api_key, client_secret=api_secret, callback_uri="oob")
    try:
        body = oauth.fetch_request_token(REQUEST_TOKEN_URL)
    except Exception as exc:
        print(f"[authorize] request_token failed: {exc}", file=sys.stderr)
        return 2

    oauth_token = body.get("oauth_token")
    oauth_token_secret = body.get("oauth_token_secret")
    if not (oauth_token and oauth_token_secret):
        print(f"[authorize] unexpected response shape: {body}", file=sys.stderr)
        return 2

    PENDING_DIR.mkdir(parents=True, exist_ok=True)
    _label_path(PENDING_DIR, args.label).write_text(
        json.dumps({"oauth_token": oauth_token, "oauth_token_secret": oauth_token_secret})
    )

    print()
    print("Step 1: open this URL in a browser logged in as the X account to authorize:")
    print()
    print(f"    {AUTHORIZE_URL}?oauth_token={oauth_token}")
    print()
    print("Step 2: click Authorize, copy the 7-digit PIN, then run:")
    print()
    print(f"    python -m x_agent.authorize finish <PIN> --label {args.label} --primary")
    print()
    return 0


def cmd_finish(args: argparse.Namespace) -> int:
    api_key, api_secret = _consumer_creds()
    pending_path = _label_path(PENDING_DIR, args.label)
    if not pending_path.exists():
        print(
            f"[authorize] no pending request_token for label {args.label!r}. "
            f"Run `authorize begin --label {args.label}` first.",
            file=sys.stderr,
        )
        return 2
    pending = json.loads(pending_path.read_text())

    oauth = OAuth1Session(
        client_key=api_key,
        client_secret=api_secret,
        resource_owner_key=pending["oauth_token"],
        resource_owner_secret=pending["oauth_token_secret"],
        verifier=args.pin,
    )
    try:
        body = oauth.fetch_access_token(ACCESS_TOKEN_URL)
    except Exception as exc:
        print(f"[authorize] access_token exchange failed: {exc}", file=sys.stderr)
        return 2

    access_token = body.get("oauth_token")
    access_secret = body.get("oauth_token_secret")
    screen_name = body.get("screen_name") or "?"
    user_id = body.get("user_id") or "?"
    if not (access_token and access_secret):
        print(f"[authorize] unexpected response shape: {body}", file=sys.stderr)
        return 2

    TOKENS_DIR.mkdir(parents=True, exist_ok=True)
    tokens_path = _label_path(TOKENS_DIR, args.label)
    tokens_path.write_text(
        json.dumps(
            {
                "label": args.label,
                "screen_name": screen_name,
                "user_id": user_id,
                "access_token": access_token,
                "access_secret": access_secret,
            },
            indent=2,
        )
    )
    pending_path.unlink(missing_ok=True)

    print(f"[authorize] success. screen_name=@{screen_name} user_id={user_id}")
    print(f"[authorize] saved to {tokens_path}")

    if args.primary:
        env_file = Path(args.env_file).resolve()
        _upsert_env(env_file, "TWITTER_ACCESS_TOKEN", access_token)
        _upsert_env(env_file, "TWITTER_ACCESS_SECRET", access_secret)
        print(f"[authorize] upserted TWITTER_ACCESS_TOKEN / TWITTER_ACCESS_SECRET in {env_file}")
    else:
        print()
        print("To activate this account as the agent's poster, append to your .env:")
        print(f"    TWITTER_ACCESS_TOKEN={access_token}")
        print(f"    TWITTER_ACCESS_SECRET={access_secret}")
        print("Or re-run with --primary to do it automatically.")
    return 0


def _upsert_env(env_file: Path, key: str, value: str) -> None:
    """Replace an existing KEY=... line or append a new one (atomic write)."""
    if not env_file.exists():
        env_file.parent.mkdir(parents=True, exist_ok=True)
        env_file.write_text(f"{key}={value}\n")
        return
    text = env_file.read_text()
    pattern = re.compile(rf"^{re.escape(key)}=.*$", re.MULTILINE)
    if pattern.search(text):
        new_text = pattern.sub(f"{key}={value}", text)
    else:
        if not text.endswith("\n"):
            text += "\n"
        new_text = text + f"{key}={value}\n"
    tmp = env_file.with_suffix(env_file.suffix + ".tmp")
    tmp.write_text(new_text)
    tmp.replace(env_file)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="x_agent.authorize", description="3-legged OAuth 1.0a PIN flow for X.com"
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_begin = sub.add_parser("begin", help="Mint a request token and print the authorize URL")
    p_begin.add_argument("--label", required=True, help="Friendly account label, e.g. 'myproduct'")
    p_begin.set_defaults(func=cmd_begin)

    p_finish = sub.add_parser("finish", help="Exchange the PIN for access tokens")
    p_finish.add_argument("pin", help="The 7-digit PIN x.com showed after Authorize")
    p_finish.add_argument("--label", required=True, help="Same label you used in `begin`")
    p_finish.add_argument("--primary", action="store_true",
                          help="Also write TWITTER_ACCESS_TOKEN/SECRET into the .env")
    p_finish.add_argument("--env-file", default=cfg.DEFAULT_ENV_FILE,
                          help="Path to the .env to upsert into (with --primary)")
    p_finish.set_defaults(func=cmd_finish)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
