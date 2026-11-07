"""Optional Gemini rewrite of the story. Off unless GEMINI_API_KEY is set.

Rules (so the live demo can never be hurt by it):
- The model only rephrases `narrative.facts()`; it never computes anything.
- Output must be JSON with the same keys as the template story, and every number in it
  must already appear in the facts (narrative.numbers_ok). Otherwise we return None
  and the caller shows the deterministic template.
- Responses are cached on disk by a fingerprint of (facts, prompt version, model), so
  re-running the same account and twist costs nothing.
- The key is read from the environment, Streamlit secrets, or a local .env file. It is
  never printed or logged.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from .narrative import numbers_ok

PROMPT_VERSION = "v1"
DEFAULT_MODEL = "gemini-3.5-flash-lite"  # stable per ai.google.dev model list (Nov 2026); override with GEMINI_MODEL
CACHE = Path(__file__).resolve().parent.parent / ".cache" / "gemini_story.json"
KEYS = ("headline", "what_changed", "reality_check", "plan_steps", "caveat")
SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string"},
        "what_changed": {"type": "string"},
        "reality_check": {"type": "string"},
        "plan_steps": {"type": "array", "items": {"type": "string"}},
        "caveat": {"type": "string"},
    },
    "required": list(KEYS),
}
SYSTEM = (
    "You are a Tangerine bank financial coach writing for one customer. You receive JSON facts that a "
    "deterministic engine already computed. Rewrite them as a warm, plain-English summary of about 90 words "
    "in total. Use ONLY numbers that appear in the facts, copied exactly as written. Never calculate, round, "
    "or invent a number, product or promise. Keep the judges' runway as the main number and call the other "
    "figures 'reality checks'. Mention Tangerine features only by these names: Savings Goal, Automatic "
    "Savings Program, Line of Credit. Return JSON with keys headline, what_changed, reality_check, "
    "plan_steps (2 or 3 short strings), caveat."
)


def _dotenv_value(name: str) -> str | None:
    env = Path(__file__).resolve().parent.parent / ".env"
    if not env.exists():
        return None
    for line in env.read_text().splitlines():
        line = line.strip()
        if line.startswith(f"{name}=") or line.startswith(f"export {name}="):
            return line.split("=", 1)[1].strip().strip("'\"") or None
    return None


def api_key() -> str | None:
    key = os.environ.get("GEMINI_API_KEY") or _dotenv_value("GEMINI_API_KEY")
    if key:
        return key
    try:  # Streamlit secrets, only when running inside Streamlit with a secrets file
        import streamlit as st
        return st.secrets.get("GEMINI_API_KEY")  # type: ignore[no-any-return]
    except Exception:
        return None


def available() -> bool:
    return bool(api_key())


def model_name() -> str:
    return os.environ.get("GEMINI_MODEL") or _dotenv_value("GEMINI_MODEL") or DEFAULT_MODEL


def _fingerprint(f: dict, model: str) -> str:
    blob = json.dumps({"facts": f, "prompt": PROMPT_VERSION, "model": model}, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


def _load_cache() -> dict:
    try:
        return json.loads(CACHE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_cache(cache: dict) -> None:
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(cache, indent=1))


def valid_story(story: object, f: dict) -> bool:
    if not isinstance(story, dict) or any(k not in story for k in KEYS):
        return False
    if not isinstance(story["plan_steps"], list) or not all(isinstance(s, str) for s in story["plan_steps"]):
        return False
    return numbers_ok(story, f)


def gemini_story(f: dict, timeout_s: float = 12.0) -> tuple[dict | None, str]:
    """(story, status). story is None when the template should be used; status says why."""
    key = api_key()
    if not key:
        return None, "no GEMINI_API_KEY: template used"
    model = model_name()
    fp = _fingerprint(f, model)
    cache = _load_cache()
    if fp in cache:
        return cache[fp], f"Gemini ({model}), cached"
    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=key, http_options=types.HttpOptions(timeout=int(timeout_s * 1000)))
        resp = client.models.generate_content(
            model=model,
            contents=json.dumps(f, default=str),
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM,
                response_mime_type="application/json",
                response_json_schema=SCHEMA,
                temperature=0.3,
                max_output_tokens=600,
            ),
        )
        story = json.loads(resp.text)
    except Exception as e:  # network, quota, bad JSON: never break the demo
        return None, f"Gemini unavailable ({type(e).__name__}): template used"
    if not valid_story(story, f):
        return None, "Gemini output used a number not in the facts: template used"
    cache[fp] = story
    _save_cache(cache)
    return story, f"Gemini ({model})"
