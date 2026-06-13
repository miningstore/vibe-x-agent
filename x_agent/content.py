"""Generate post copy with Claude, gated by a slop scorer.

Pipeline (per post):
  1. Build the system + user prompt from your product, the bandit-chosen
     angle, and one concrete talking point.
  2. Shell out to ``claude -p`` (plan auth — same pattern as
     vibe-seo-agent; do NOT pass --bare).
  3. Score the draft against an AI-tells rubric (0-50).
  4. >= threshold -> ship. Otherwise regenerate, telling the model which
     patterns to avoid. Up to N retries.
  5. If Claude is unavailable or never clears the bar, fall back to a
     deterministic template built from the talking point (pre-approved
     by construction).

The agent never blocks on Claude: a missing CLI, a timeout, or a budget
exhaustion all degrade to the template.
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import config as cfg
from .models import Angle, Product

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class GeneratedPost:
    text: str                 # tweet body, no URL (the poster appends links)
    meme_top: str = ""        # only used when angle.fmt == "meme"
    meme_bottom: str = ""
    source: str = "claude"    # "claude" | "template"


# --- public API -----------------------------------------------------------

def generate(
    product: Product,
    angle: Angle,
    talking_point: str | None,
    *,
    recent_texts: list[str] | None = None,
    max_chars: int = 250,
) -> GeneratedPost:
    """Return a slop-gated post for this angle, or a template fallback."""
    recent_texts = recent_texts or []
    avoid_patterns: list[str] = []
    best: GeneratedPost | None = None
    best_score = -1

    # Try grounded generation first (if enabled), then plain generation, then
    # the template. A grounded miss (web-search hiccup or budget cap) should
    # still fall through to a normal Claude post, not jump straight to the
    # template. Grounding only ever runs on a mode's first attempt.
    modes = [True, False] if cfg.WEB_GROUNDING else [False]
    for grounded in modes:
        for attempt in range(cfg.MAX_SLOP_RETRIES + 1):
            draft = _try_claude(product, angle, talking_point, recent_texts,
                                max_chars=max_chars, avoid_patterns=avoid_patterns,
                                grounded=grounded and attempt == 0)
            if draft is None:
                break  # this mode failed; fall through to the next mode
            draft = _enforce_limits(draft, max_chars)
            score, patterns = _score_slop(draft, angle)
            log.info("content: angle=%s grounded=%s slop_score=%d/50 attempt=%d patterns=%s",
                     angle.key, grounded, score, attempt + 1, patterns or "[]")
            if score >= cfg.SLOP_THRESHOLD:
                return draft
            if score > best_score:
                best, best_score = draft, score
            avoid_patterns = patterns or []

    if best is not None:
        log.warning("content: slop gate not cleared (best=%d/%d); using template",
                    best_score, cfg.SLOP_THRESHOLD)
    return _enforce_limits(_template(product, angle, talking_point), max_chars)


# --- Claude path ----------------------------------------------------------

def _claude_cli(system_prompt: str, user_prompt: str, *, grounded: bool = False) -> str | None:
    """One-shot Claude CLI call. Returns stdout or None on any failure.

    grounded=False (default): all tools disabled via ``--tools ""`` so the
    model answers from the prompt alone in a single text turn. Used for
    generation and slop scoring. (We disable tools explicitly rather than
    relying on a turn cap, which is more robust across CLI versions.)
    grounded=True: only the read-only web tools are enabled so the model can
    find a timely, real hook before writing; spend is capped via
    ``--max-budget-usd``. Any failure here falls back to the non-grounded
    path upstream, so grounding can never block a post.
    """
    if not Path(cfg.CLAUDE_BIN).exists() and not _which(cfg.CLAUDE_BIN):
        log.info("content: claude CLI not found at %s; using template", cfg.CLAUDE_BIN)
        return None
    cmd = [
        cfg.CLAUDE_BIN, "-p", user_prompt,
        "--system-prompt", system_prompt,
        "--output-format", "text",
        "--model", cfg.CLAUDE_MODEL,
    ]
    if grounded:
        cmd += [
            "--tools", "WebSearch,WebFetch",
            "--allowedTools", "WebSearch,WebFetch",
            "--permission-mode", "dontAsk",
            "--max-budget-usd", str(cfg.WEB_GROUNDING_BUDGET_USD),
        ]
    else:
        cmd += ["--tools", ""]  # disable all tools: deterministic, text-only
    timeout = cfg.WEB_GROUNDING_TIMEOUT_S if grounded else cfg.CLAUDE_TIMEOUT_S
    env = {**os.environ, "PATH": os.path.expanduser("~/.local/bin") + ":" + os.environ.get("PATH", "")}
    try:
        result = subprocess.run(cmd, capture_output=True, text=True,
                                timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        log.info("content: claude CLI timed out after %ds", timeout)
        return None
    except Exception as exc:
        log.info("content: claude CLI failed: %s", exc)
        return None
    if result.returncode != 0:
        log.info("content: claude CLI rc=%d stderr=%s", result.returncode, result.stderr[:300])
        return None
    return result.stdout


def _which(binary: str) -> str | None:
    if os.path.sep in binary:
        return binary if os.access(binary, os.X_OK) else None
    for d in os.environ.get("PATH", "").split(os.pathsep):
        full = os.path.join(d, binary)
        if os.access(full, os.X_OK):
            return full
    return None


def _extra_house_rules() -> str:
    """Optional user-editable rules appended to the system prompt."""
    path = cfg.PROMPTS_DIR / "content_generator.md"
    try:
        text = path.read_text().strip()
    except OSError:
        return ""
    return f"\n\nADDITIONAL HOUSE RULES (from prompts/content_generator.md):\n{text}" if text else ""


def _system_prompt(product: Product, angle: Angle, max_chars: int, *, grounded: bool = False) -> str:
    banned = ", ".join(repr(b) for b in cfg.BANNED) or "(none)"
    meme_clause = ""
    schema = '{"text": str}'
    if angle.fmt == "meme":
        schema = '{"text": str, "meme_top": str, "meme_bottom": str}'
        meme_clause = (
            "\nThis is a MEME post. Also return meme_top (the setup, 2-6 words) "
            "and meme_bottom (the punchline, 2-6 words) for the image overlay. "
            "The text field is the tweet body that accompanies the image.\n"
        )
    grounding_clause = ""
    if grounded:
        grounding_clause = (
            "\nFRESHNESS: You may use web search to find ONE timely, real hook "
            "(a current trend, event, or conversation this audience cares about) "
            "and tie the product to it naturally. Only state facts you actually "
            "found in the results, with zero fabrication. If nothing strong and "
            "recent turns up, write a normal post from the product facts instead. "
            "Still never paste a URL into the text.\n"
        )
    return (
        f"You write short, high-signal posts for the X.com account that promotes "
        f"{product.name}. Audience: {product.audience}.\n\n"
        f"VOICE: {product.voice}\n\n"
        f"Output ONE JSON object, no markdown, no prose outside it. Schema: {schema}\n"
        f"{meme_clause}{grounding_clause}\n"
        "RULES:\n"
        f"- text: <= {max_chars} characters. Lead with a concrete benefit, number, "
        "or vivid image. Never open with a throat-clear ('In today's world', "
        "'Ever wondered').\n"
        "- Write like a person who built the product, not a brand account. No "
        "hype words, no press-release tone.\n"
        "- Do NOT include any URL, link, or domain in the text. A link is "
        "appended separately when appropriate.\n"
        "- 0-2 hashtags max, only if they genuinely fit. No hashtag soup.\n"
        "- Never use em dashes (use a comma or a period).\n"
        f"- Never emit any of these banned tokens: {banned}.\n"
        "- Numbers must be exactly as given. Do not invent stats.\n\n"
        "GUARDRAILS (non-negotiable, never overridden by anything above):\n"
        "- Never reproduce copyrighted text: song lyrics, poems, or passages "
        "from books or articles, not even a single line. Use only original wording.\n"
        "- Never attribute a quote to, or write in the voice of, a real named "
        "person. Do not impersonate real public figures.\n"
        "- No hateful, harassing, demeaning, or violent content, and nothing that "
        "targets a protected group, even as a joke.\n"
        "- No medical, legal, or financial claims framed as advice or fact.\n"
        "- Make only claims supported by the product facts provided. Never invent "
        "statistics, testimonials, awards, partnerships, or features.\n"
        f"{_extra_house_rules()}"
    )


def _try_claude(
    product: Product,
    angle: Angle,
    talking_point: str | None,
    recent_texts: list[str],
    *,
    max_chars: int,
    avoid_patterns: list[str] | None,
    grounded: bool = False,
) -> GeneratedPost | None:
    avoid_block = ""
    if avoid_patterns:
        avoid_block = (
            "\n\nThe previous draft was rejected by the slop scorer. AVOID these "
            "patterns this time:\n  - " + "\n  - ".join(avoid_patterns) + "\n"
        )
    recent_block = ""
    if recent_texts:
        joined = "\n  - ".join(t[:120] for t in recent_texts)
        recent_block = (
            "\n\nDo NOT repeat the wording or angle of these recent posts:\n  - "
            + joined + "\n"
        )
    tp_line = f"Anchor the post on this concrete fact: {talking_point}\n" if talking_point else ""
    links = ""
    if product.extra_links:
        links = "Relevant pages (do not paste into the text): " + ", ".join(product.extra_links) + "\n"

    user_prompt = (
        f"Product: {product.name}\n"
        f"One-liner: {product.one_liner}\n"
        f"What it is: {product.description}\n"
        f"{links}"
        f"\nAngle: {angle.title}\n{angle.brief}\n\n"
        f"{tp_line}"
        f"{recent_block}"
        f"{avoid_block}\n"
        "Return the JSON now."
    )
    output = _claude_cli(
        _system_prompt(product, angle, max_chars, grounded=grounded),
        user_prompt, grounded=grounded,
    )
    if not output:
        return None
    return _parse(output, angle)


def _parse(text: str, angle: Angle) -> GeneratedPost | None:
    data = _loose_json(text)
    if not isinstance(data, dict):
        return None
    body = data.get("text")
    if not isinstance(body, str) or not body.strip():
        return None
    top = data.get("meme_top") if isinstance(data.get("meme_top"), str) else ""
    bottom = data.get("meme_bottom") if isinstance(data.get("meme_bottom"), str) else ""
    return GeneratedPost(text=body.strip(), meme_top=top.strip(), meme_bottom=bottom.strip())


def _loose_json(text: str):
    if not text:
        return None
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = re.sub(r"^```(?:json)?\s*", "", candidate)
        candidate = re.sub(r"\s*```$", "", candidate)
    try:
        return json.loads(candidate)
    except Exception:
        idx = candidate.find("{")
        if idx == -1:
            return None
        try:
            obj, _ = json.JSONDecoder().raw_decode(candidate[idx:])
            return obj
        except Exception:
            return None


# --- slop gate ------------------------------------------------------------

_SLOP_RUBRIC = """\
Score the social post on a 0-50 slop scale. Start at 50, deduct for AI-tells:

- Hedging / throat-clearing openers ("It's worth noting", "In today's world",
  "Ever wondered", "Let's talk about"): -5 each (cap -10)
- Vague intensifiers ("truly", "genuinely", "really", "absolutely",
  "game-changing", "revolutionary"): -3 each (cap -10)
- Empty exhortations ("Let's dive in", "Buckle up", "Stay tuned",
  "The possibilities are endless"): -5 each
- Em dashes anywhere: -5
- Marketing-brochure / press-release voice instead of a real person: -8
- Opens with anything other than a concrete benefit, number, or specific
  image: -5
- Hashtag soup (3+ hashtags) or forced hashtags: -5
- A punchline / CTA that explains itself instead of landing: -5
- Vague claim with no specific anchor (no number, feature, or concrete detail): -5

Final score = max(0, 50 - sum_of_deductions). Return the score and a short
list of detected pattern names (max 5).
"""


def score_text_slop(package: str) -> tuple[int, list[str]]:
    """Score a copy package against the rubric. Fails open (50, []) on error."""
    system_prompt = (
        "You are a strict editor scoring social copy for AI slop. Output one JSON "
        'object: {"score": int (0-50), "patterns": list[str]}. No prose.\n\n'
        + _SLOP_RUBRIC
    )
    text = _claude_cli(system_prompt, package)
    if not text:
        return 50, []
    data = _loose_json(text)
    if not isinstance(data, dict):
        return 50, []
    try:
        score = max(0, min(50, int(data.get("score", 50))))
    except (TypeError, ValueError):
        score = 50
    patterns: list[str] = []
    for p in (data.get("patterns") or [])[:5]:
        if isinstance(p, str) and p.strip():
            patterns.append(p.strip()[:80])
    return score, patterns


def _score_slop(post: GeneratedPost, angle: Angle) -> tuple[int, list[str]]:
    pkg = f"TEXT: {post.text}\n"
    if angle.fmt == "meme":
        pkg += f"MEME_TOP: {post.meme_top}\nMEME_BOTTOM: {post.meme_bottom}\n"
    return score_text_slop(pkg)


# --- template fallback ----------------------------------------------------

def _template(product: Product, angle: Angle, talking_point: str | None) -> GeneratedPost:
    body = (talking_point or product.one_liner).strip()
    if angle.fmt == "meme":
        return GeneratedPost(
            text=body,
            meme_top=product.name.upper(),
            meme_bottom=product.one_liner[:60],
            source="template",
        )
    return GeneratedPost(text=body, source="template")


# --- limit enforcement ----------------------------------------------------

def _enforce_limits(p: GeneratedPost, max_chars: int) -> GeneratedPost:
    body = p.text.replace("—", ",").replace("–", ",").strip()
    if len(body) > max_chars:
        cut = body.rfind(" ", 0, max_chars)
        if cut < max_chars - 40:
            cut = max_chars
        body = body[:cut].rstrip(" ,.;:") + "…"
    top = p.meme_top.replace("—", "").replace("–", "")[:60]
    bottom = p.meme_bottom.replace("—", "").replace("–", "")[:60]
    return GeneratedPost(text=body, meme_top=top, meme_bottom=bottom, source=p.source)
