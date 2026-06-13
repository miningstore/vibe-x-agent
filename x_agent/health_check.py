"""Pre-launch health check — run this before enabling the timer.

Verifies, in one command, that this host can actually run the agent:

  1. Product config    — loaded, and not still the bundled demo.
  2. Claude CLI        — present (the agent degrades to templates without
                         it, so this is advisory, not fatal).
  3. X credentials     — all four OAuth tokens present in the env.
  4. X API             — the creds actually work (GET /2/users/me) and
                         the handle is printed. Skip with --skip-x before
                         you've run the authorize flow.
  5. Generation        — one dry content generation produces non-empty
                         copy (exercises the Claude+slop pipeline).

Exits 0 if the required checks pass (X creds + X API, unless --skip-x).

    python -m x_agent.health_check
    python -m x_agent.health_check --skip-x   # before authorize.py is done
    python -m x_agent.health_check --json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from . import config as cfg


def _check_product() -> dict:
    demo = cfg.using_demo_product()
    return {
        "ok": True,
        "advisory": demo,
        "product": cfg.PRODUCT.name,
        "source": cfg.OVERLAY_SOURCE,
        "angles_enabled": len(cfg.enabled_angles()),
        "talking_points": len(cfg.TALKING_POINTS),
        "reason": "using DEMO product — create product_config.py" if demo else "",
    }


def _check_claude() -> dict:
    bin_path = cfg.CLAUDE_BIN
    found = Path(bin_path).exists() or any(
        os.access(os.path.join(d, bin_path), os.X_OK)
        for d in os.environ.get("PATH", "").split(os.pathsep)
    )
    return {
        "ok": True,             # advisory: agent falls back to templates
        "advisory": not found,
        "claude_bin": bin_path,
        "found": found,
        "model": cfg.CLAUDE_MODEL,
        "reason": "" if found else "claude CLI not found; posts will use templates only",
    }


def _check_x_creds() -> dict:
    from .x_client import Credentials
    creds = Credentials.from_env()
    present = creds is not None
    return {
        "ok": present,
        "present": present,
        "reason": "" if present else "TWITTER_API_KEY/SECRET + ACCESS_TOKEN/SECRET missing (run authorize.py)",
    }


def _check_x_api() -> dict:
    from .x_client import XClient, Credentials
    started = time.time()
    if Credentials.from_env() is None:
        return {"ok": False, "reason": "no X credentials in env"}
    try:
        me = XClient().verify_credentials()
    except Exception as exc:
        return {"ok": False, "reason": f"verify failed: {exc}",
                "elapsed_ms": int((time.time() - started) * 1000)}
    return {
        "ok": bool(me.get("id")),
        "user_id": me.get("id"),
        "username": me.get("username"),
        "elapsed_ms": int((time.time() - started) * 1000),
    }


def _check_generation() -> dict:
    from . import content
    started = time.time()
    angles = cfg.enabled_angles()
    if not angles:
        return {"ok": False, "reason": "no enabled angles"}
    tp = cfg.TALKING_POINTS[0] if cfg.TALKING_POINTS else None
    post = content.generate(cfg.PRODUCT, angles[0], tp, max_chars=250)
    return {
        "ok": bool(post.text),
        "source": post.source,
        "sample": post.text[:120],
        "elapsed_ms": int((time.time() - started) * 1000),
    }


def run(skip_x: bool = False) -> dict:
    results: dict = {}
    failures: list[str] = []

    results["product"] = _check_product()
    results["claude"] = _check_claude()

    creds = _check_x_creds()
    results["x_creds"] = creds
    if not skip_x and not creds["ok"]:
        failures.append(f"x_creds: {creds['reason']}")

    if skip_x:
        results["x_api"] = {"ok": None, "reason": "skipped"}
    else:
        api = _check_x_api()
        results["x_api"] = api
        if not api["ok"]:
            failures.append(f"x_api: {api.get('reason')}")

    try:
        results["generation"] = _check_generation()
        if not results["generation"]["ok"]:
            failures.append(f"generation: {results['generation'].get('reason')}")
    except Exception as e:
        results["generation"] = {"ok": False, "reason": f"exception: {e}"}
        failures.append(f"generation: {e}")

    results["overall"] = "PASS" if not failures else "FAIL"
    results["failures"] = failures
    return results


def _print_human(r: dict) -> None:
    def status(c: dict) -> str:
        if c.get("ok") is True:
            return "WARN" if c.get("advisory") else "OK"
        if c.get("ok") is False:
            return "FAIL"
        return "SKIP"

    p = r["product"]
    print(f"PRODUCT  {status(p):4s}  {p['product']} | {p['angles_enabled']} angles, "
          f"{p['talking_points']} talking points | {p['source']}")
    if p.get("reason"):
        print(f"               -> {p['reason']}")

    c = r["claude"]
    print(f"CLAUDE   {status(c):4s}  {c['claude_bin']} (model={c['model']})"
          + (f"  -> {c['reason']}" if c.get("reason") else ""))

    xc = r["x_creds"]
    print(f"X CREDS  {status(xc):4s}  " + ("present" if xc.get("present") else xc.get("reason", "?")))

    xa = r["x_api"]
    if xa.get("ok"):
        print(f"X API    OK    @{xa.get('username')} (id={xa.get('user_id')}, {xa.get('elapsed_ms')}ms)")
    elif xa.get("ok") is None:
        print("X API    SKIP  skipped")
    else:
        print(f"X API    FAIL  {xa.get('reason')}")

    g = r["generation"]
    if g.get("ok"):
        print(f"GEN      OK    source={g['source']} ({g['elapsed_ms']}ms): {g['sample']!r}")
    else:
        print(f"GEN      FAIL  {g.get('reason')}")

    print()
    print(f"OVERALL: {r['overall']}")
    for f in r["failures"]:
        print(f"  • {f}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="vibe-x-agent health check")
    ap.add_argument("--skip-x", action="store_true", help="Skip X credential + API checks")
    ap.add_argument("--json", action="store_true", help="Machine-readable output")
    args = ap.parse_args(argv)
    results = run(skip_x=args.skip_x)
    if args.json:
        print(json.dumps(results, indent=2, default=str))
    else:
        _print_human(results)
    return 0 if results["overall"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
