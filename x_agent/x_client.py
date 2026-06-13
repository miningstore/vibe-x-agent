"""Minimal X.com (Twitter) API v2 client.

Just enough surface to run a promotion agent:
  * ``post_tweet(text, media_ids)``    — create a post (OAuth 1.0a user ctx)
  * ``upload_media(png)``              — upload an image, return media id
  * ``get_tweets_metrics(ids)``        — read public_metrics for the loop's
                                         reward (works with the same OAuth
                                         1.0a creds — no separate bearer token
                                         needed)
  * ``verify_credentials()``           — GET /2/users/me (health check + handle)

OAuth 1.0a user context is required to post and to upload media on behalf
of a user. The four secrets come from ``authorize.py`` (the PIN flow) and
live in ``.env``:

    TWITTER_API_KEY        TWITTER_API_SECRET
    TWITTER_ACCESS_TOKEN   TWITTER_ACCESS_SECRET

If ``TWITTER_BOT_DRY_RUN`` is truthy (the default), every network method
is a no-op returning deterministic stubs, so a fresh deploy never posts
until you explicitly opt in.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)

UPLOAD_URL = "https://api.x.com/2/media/upload"
TWEETS_URL = "https://api.x.com/2/tweets"
TWEETS_LOOKUP_URL = "https://api.x.com/2/tweets"
ME_URL = "https://api.x.com/2/users/me"


def dry_run_active() -> bool:
    """True unless TWITTER_BOT_DRY_RUN is explicitly disabled.

    Default true: nothing is posted until the operator opts in.
    """
    raw = (os.environ.get("TWITTER_BOT_DRY_RUN") or "true").strip().lower()
    return raw not in {"0", "false", "no", "off"}


@dataclass(frozen=True)
class Credentials:
    api_key: str
    api_secret: str
    access_token: str
    access_secret: str

    @classmethod
    def from_env(cls) -> "Credentials | None":
        ak = os.environ.get("TWITTER_API_KEY", "").strip()
        as_ = os.environ.get("TWITTER_API_SECRET", "").strip()
        at = os.environ.get("TWITTER_ACCESS_TOKEN", "").strip()
        ats = os.environ.get("TWITTER_ACCESS_SECRET", "").strip()
        if not (ak and as_ and at and ats):
            return None
        return cls(api_key=ak, api_secret=as_, access_token=at, access_secret=ats)


class XClient:
    def __init__(self, creds: Credentials | None = None):
        self.creds = creds or Credentials.from_env()
        self._oauth = None  # lazy

    # -- posting -----------------------------------------------------------

    def upload_media(self, png_bytes: bytes, *, filename: str = "image.png") -> str:
        """Upload one image, return its media id (v2 media upload endpoint)."""
        oauth = self._auth_or_raise()
        files = {"media": (filename, png_bytes, "image/png")}
        data = {"media_category": "tweet_image"}
        resp = oauth.post(UPLOAD_URL, data=data, files=files, timeout=60)
        if not resp.ok:
            raise RuntimeError(f"media upload failed: HTTP {resp.status_code} {resp.text[:300]}")
        body = resp.json() or {}
        media_id = (
            (body.get("data") or {}).get("id")
            or body.get("media_id_string")
            or (str(body.get("media_id")) if body.get("media_id") else "")
        )
        if not media_id:
            raise RuntimeError(f"unexpected media upload response: {body}")
        return media_id

    def post_tweet(self, *, text: str, media_ids: list[str] | None = None) -> dict[str, Any]:
        """Create one post. Returns the parsed response body."""
        oauth = self._auth_or_raise()
        payload: dict[str, Any] = {"text": text}
        if media_ids:
            payload["media"] = {"media_ids": media_ids}
        resp = oauth.post(
            TWEETS_URL,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=30,
        )
        if not resp.ok:
            raise RuntimeError(f"post create failed: HTTP {resp.status_code} {resp.text[:300]}")
        return resp.json() or {}

    # -- reading (for the feedback loop) -----------------------------------

    def get_tweets_metrics(self, ids: list[str]) -> dict[str, dict]:
        """Return {tweet_id: public_metrics} for up to many ids.

        Uses the same OAuth 1.0a user context as posting, so the loop's
        reward signal needs no extra credentials. public_metrics carries
        like / retweet / reply / quote / bookmark / impression counts,
        which is everything ``allocator.compute_reward`` weighs.
        """
        if not ids:
            return {}
        oauth = self._auth_or_raise()
        out: dict[str, dict] = {}
        for i in range(0, len(ids), 100):
            chunk = ids[i : i + 100]
            resp = oauth.get(
                TWEETS_LOOKUP_URL,
                params={"ids": ",".join(chunk), "tweet.fields": "public_metrics"},
                timeout=30,
            )
            if not resp.ok:
                log.info("[x_client] metrics lookup -> HTTP %d: %s", resp.status_code, resp.text[:200])
                continue
            body = resp.json() or {}
            for row in body.get("data") or []:
                tid = row.get("id")
                pm = row.get("public_metrics")
                if tid and isinstance(pm, dict):
                    out[str(tid)] = pm
        return out

    def verify_credentials(self) -> dict[str, Any]:
        """GET /2/users/me — confirms the creds work and returns the handle."""
        oauth = self._auth_or_raise()
        resp = oauth.get(ME_URL, params={"user.fields": "username"}, timeout=20)
        if not resp.ok:
            raise RuntimeError(f"verify failed: HTTP {resp.status_code} {resp.text[:300]}")
        return (resp.json() or {}).get("data") or {}

    # -- internal ----------------------------------------------------------

    def _auth_or_raise(self):
        if self._oauth is not None:
            return self._oauth
        if not self.creds:
            raise RuntimeError(
                "X.com credentials missing. Set TWITTER_API_KEY, TWITTER_API_SECRET, "
                "TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_SECRET in the env (see authorize.py)."
            )
        try:
            from requests_oauthlib import OAuth1Session  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "requests-oauthlib not installed. pip install -r x_agent/requirements.txt"
            ) from exc
        self._oauth = OAuth1Session(
            client_key=self.creds.api_key,
            client_secret=self.creds.api_secret,
            resource_owner_key=self.creds.access_token,
            resource_owner_secret=self.creds.access_secret,
        )
        return self._oauth
