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

PROMPT_VERSION = "v2"
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
    "You are a Tangerine bank financial coach talking to one customer. You receive JSON facts that a "
    "deterministic engine already computed. Rewrite them as a warm, specific summary of about 90 words. Rules: "
    "(1) headline: one sentence that states the customer's runway EXACTLY as given in judge_runway and whether "
    "they make the target_months test. Say 'your runway', never 'judges'. "
    "(2) what_changed: the income after the shock, the spending, and the buffer, using the given dollar figures. "
    "(3) reality_check: one sentence comparing the 'reality' figures to the runway. "
    "(4) plan_steps: 2 or 3 steps. The first is the backup step from ladder_step with its dollar amount from "
    "ladder_saving (or the cash_or_credit amount); the second is the savings goal with goal_target and goal_gap "
    "(and goal_months if present). Name Tangerine features only as: Savings Goal, Automatic Savings Program, "
    "Line of Credit. No generic advice: every step must contain a dollar amount or a number of months from the facts. "
    "(5) caveat: one short sentence that the runway uses the track's official formula. "
    "Use ONLY numbers that appear in the facts, copied exactly as written. Never calculate, round or invent a "
    "number. Plain English, no underscores, no markdown."
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
    runway_number = str(f.get("judge_runway", "")).split(" ")[0]
    if runway_number and runway_number != "no" and runway_number not in str(story["headline"]):
        return False  # the headline must carry the judges' runway
    if "_" in " ".join(str(v) for v in story.values()):
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
    from google import genai
    from google.genai import types

    story, last_err = None, None
    for attempt in range(2):  # one retry for transient server errors
        try:
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
            break
        except Exception as e:  # network, quota, bad JSON: never break the demo
            last_err = e
    if story is None:
        return None, f"Gemini unavailable ({type(last_err).__name__}): template used"
    if not valid_story(story, f):
        return None, "Gemini output failed the checks (number or headline): template used"
    cache[fp] = story
    _save_cache(cache)
    return story, f"Gemini ({model})"
