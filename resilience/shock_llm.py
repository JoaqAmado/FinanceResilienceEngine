"""The LLM backend of the shock parser: words -> an intent dict, and nothing else.

The model never sees account data, never computes a number and never writes text the user reads. It gets
the normalized message and the current Shock as JSON, and must answer with the intent schema
(resilience.shock_parser.INTENT_SCHEMA). The answer is validated strictly, canonicalized and cached.

Determinism, built in:
- one pinned model version ID per provider (never a moving "latest" alias); it is part of the cache key;
- temperature 0, top_p 1, a fixed top_k and seed where the provider takes them (see each adapter);
- the provider's JSON-schema mode, every property required, no extra properties, enums for kinds;
- canonicalization (sorted keys, cents, 4-decimal fractions, lowercased enums) before anything uses it;
- a cache keyed on (message, current Shock, PROMPT_VERSION, model ID, schema version).

Provider: SHOCK_LLM=gemini|cortex|off. Default: gemini when GEMINI_API_KEY is set (env, Streamlit secrets or
.env, read by resilience.llm), else off. Cortex needs SNOWFLAKE_PAT and SNOWFLAKE_ACCOUNT. Keys are never printed,
logged, cached or put in an exception message.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Protocol

from . import llm as _gemini_keys
from .core import Shock
from .shock_parser import (
    CHECKS,
    INTENT_SCHEMA,
    INTENT_SCHEMA_VERSION,
    IntentError,
    cache_key,
    cache_put,
    canonicalize_intent,
    intent_out_of_range,
    shock_key,
)

PROMPT_VERSION = "shock-v1"
TIMEOUT_S = 10.0
COOLDOWN_S = 300.0          # after a network failure, skip the LLM for 5 minutes so the demo never hangs
SEED = 20261108
TOP_K = 1

# Pinned model version IDs. Changing one invalidates every cached answer on purpose (the ID is in the cache key).
GEMINI_MODEL = "gemini-3.5-flash-lite"      # a stable, versioned Gemini model code (not a "-latest" alias)
CORTEX_MODEL = "llama3.3-70b"               # a fixed Cortex model name


def _check_pinned(model: str) -> str:
    if "latest" in model.lower():
        raise ValueError(f"model {model!r} is a moving alias; pin an exact version")
    return model


# ------------------------------------------------------------------ the prompt

GLOSSARY = """Fixed meanings (always use these):
- "laid off", "lost job", "job loss", "on EI", "unemployed": income.kind=job_loss_ei with pct=0.55 (EI pays 55%), unless another EI percent is stated.
- A pay cut, reduced hours or fewer hours is NOT a job loss: income.kind=pay_cut_pct with the cut as pct ("hours cut in half" -> 0.5).
- "income drops/falls X%": drop_pct X. "income kept X%" or "X% of income": keep_pct X.
- "income drops to $N a month": to_amount with amount N (dollars, never converted).
- "partner loses job" or "lose half the income": partner_job_loss.
- "no job loss", "back to work": restore.
- Percents are fractions: 15% -> 0.15.
- Bills / utilities / hydro up X%: bills.kind=increase_pct. Rent up X% counts as bills.
- "rent up $N", "new/extra $N a month" (baby, car payment, insurance): monthly_cost.kind=set with amount N. Several monthly amounts in one message are summed. "add"/"another"/"on top" -> kind=add.
- "rent goes to $N": monthly_cost.kind=rent_to with amount N.
- "$N repair / one-off / emergency": one_off.kind=set_amount ("add a $N repair" -> add_amount).
- "a month of spending" = one_off.kind=months_of_spending, months=1; "N months of spending" -> months=N. A furnace dying with no amount = 1 month of spending.
- "cut spending / discretionary / non-fixed X%": spending_cut.kind=set_pct.
- "for N months", "survive N months", "N-month test": target.kind=set, months=N.
- "account 12345" / "customer #12345": account_id=12345 (else 0).
- Reality checks stay "unchanged" unless named: "EI cap"/"2026 max" -> ei_cap; "waiting week"; "keep pension"; "half-year spending"; "bills by standing order". "without the cap" -> off.
- "make it 20% instead": edit.kind=set_last_percent, pct=0.2. "reset"/"start over": edit.kind=reset_all. "remove/undo the bills increase": bills.kind=reset (same for other levers).
- Anything a lever doesn't mention: kind "none", numbers 0.
- If the message is not a financial twist or is too vague to map to levers, put one short question in clarify and leave every kind "none"."""


def _example(**parts) -> dict:
    from .shock_parser import blank_intent
    it = blank_intent()
    for k, v in parts.items():
        if isinstance(v, dict) and isinstance(it.get(k), dict):
            it[k] = {**it[k], **v}
        else:
            it[k] = v
    return it


FEW_SHOT = (
    ("laid off ei pays 55%", _example(income={"kind": "job_loss_ei", "pct": 0.55})),
    ("job loss on ei and bills up 15% with the 2026 ei cap",
     _example(income={"kind": "job_loss_ei", "pct": 0.55}, bills={"kind": "increase_pct", "pct": 0.15},
              checks={**{c: "unchanged" for c in CHECKS}, "ei_cap": "on"})),
    ("income drops to 2000 a month", _example(income={"kind": "to_amount", "amount": 2000})),
    ("their hours get cut in half from next month and the furnace dies",
     _example(income={"kind": "pay_cut_pct", "pct": 0.5}, one_off={"kind": "months_of_spending", "months": 1})),
    ("baby on the way about 900 a month more for 9 months",
     _example(monthly_cost={"kind": "set", "amount": 900}, target={"kind": "set", "months": 9})),
    ("make it 20% instead", _example(edit={"kind": "set_last_percent", "pct": 0.2})),
    ("add a 2000 repair and remove the bills increase",
     _example(one_off={"kind": "add_amount", "amount": 2000}, bills={"kind": "reset"})),
    ("things might get rough", _example(clarify="What happens? For example a job loss, a bill increase or a repair.")),
)

SYSTEM = (
    "You translate one short message about a bank customer's financial twist into lever values for a "
    "deterministic engine. You only translate words into the JSON schema; you never compute runways, dollars "
    "relative to the customer, plans or advice. You receive the message and the current shock as JSON. "
    "Describe only what THIS message says; levers it doesn't mention stay kind \"none\". Copy amounts exactly as "
    "stated, in dollars. Answer with JSON matching the schema and nothing else.\n\n" + GLOSSARY + "\n\nExamples:\n"
    + "\n".join(f"message: {m}\nanswer: {json.dumps(a, sort_keys=True)}" for m, a in FEW_SHOT)
)


def user_payload(norm: str, current: Shock) -> str:
    """The only thing sent with the system prompt: the message and the current Shock. No account data."""
    return json.dumps({"message": norm, "current": shock_key(current)}, sort_keys=True)


# ------------------------------------------------------------------ providers

class ProviderError(Exception):
    """kind: network | auth | rate_limit | server | bad_response | other. The message never holds a key or a response body."""

    def __init__(self, kind: str, detail: str = ""):
        super().__init__(f"{kind}{': ' + detail if detail else ''}")
        self.kind = kind


class Adapter(Protocol):
    name: str
    model: str

    def complete_json(self, system: str, user: str, schema: dict) -> dict:
        """The model's JSON answer as a dict. Raises ProviderError (or json.JSONDecodeError for bad JSON)."""


def _classify(e: Exception) -> ProviderError:
    if isinstance(e, ProviderError):
        return e
    code = getattr(e, "code", None) or getattr(e, "status_code", None)
    name = type(e).__name__
    if isinstance(code, int):
        if code in (401, 403):
            return ProviderError("auth", f"HTTP {code}")
        if code == 429:
            return ProviderError("rate_limit", "HTTP 429")
        if code >= 500:
            return ProviderError("server", f"HTTP {code}")
        return ProviderError("other", f"HTTP {code}")
    if any(w in name for w in ("Timeout", "Connect", "Network", "URLError")) or isinstance(e, (TimeoutError, OSError)):
        return ProviderError("network", name)
    return ProviderError("other", name)


class GeminiAdapter:
    """Gemini via google-genai.

    Honoured: temperature=0, top_p=1, top_k (fixed), seed (fixed; Gemini documents seed as best effort),
    candidate_count=1, response_json_schema (structured output) with response_mime_type=application/json.
    """

    name = "Gemini"

    def __init__(self, api_key: str, model: str | None = None, timeout_s: float = TIMEOUT_S):
        self._key = api_key
        self.model = _check_pinned(model or os.environ.get("SHOCK_GEMINI_MODEL") or GEMINI_MODEL)
        self.timeout_s = timeout_s

    def __repr__(self) -> str:  # never show the key
        return f"GeminiAdapter(model={self.model!r})"

    def complete_json(self, system: str, user: str, schema: dict) -> dict:
        from google import genai
        from google.genai import types
        try:
            client = genai.Client(api_key=self._key, http_options=types.HttpOptions(timeout=int(self.timeout_s * 1000)))
            resp = client.models.generate_content(
                model=self.model, contents=user,
                config=types.GenerateContentConfig(
                    system_instruction=system, response_mime_type="application/json", response_json_schema=schema,
                    temperature=0.0, top_p=1.0, top_k=TOP_K, seed=SEED, candidate_count=1, max_output_tokens=800))
            text = resp.text
        except Exception as e:  # noqa: BLE001 - every provider failure becomes a ProviderError without its text
            raise _classify(e) from None
        if not text:
            raise ProviderError("bad_response", "empty")
        return json.loads(text)


class CortexAdapter:
    """Snowflake Cortex REST (OpenAI-compatible chat completions), with a programmatic access token.

    Honoured: temperature=0, top_p=1, response_format json_schema (strict). Cortex documents no top_k or seed
    for this endpoint, so neither is sent.
    """

    name = "Cortex"

    def __init__(self, pat: str, account: str, model: str | None = None, timeout_s: float = TIMEOUT_S):
        self._pat = pat
        self.account = account
        self.model = _check_pinned(model or os.environ.get("SHOCK_CORTEX_MODEL") or CORTEX_MODEL)
        self.timeout_s = timeout_s

    def __repr__(self) -> str:
        return f"CortexAdapter(model={self.model!r})"

    def complete_json(self, system: str, user: str, schema: dict) -> dict:
        url = f"https://{self.account.replace('_', '-').lower()}.snowflakecomputing.com/api/v2/cortex/v1/chat/completions"
        body = json.dumps({
            "model": self.model, "temperature": 0, "top_p": 1, "max_tokens": 800,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "response_format": {"type": "json_schema", "json_schema": {"name": "shock_intent", "strict": True,
                                                                       "schema": schema}},
        }).encode()
        req = urllib.request.Request(url, data=body, method="POST", headers={
            "Authorization": f"Bearer {self._pat}", "Content-Type": "application/json", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as r:
                data = json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            raise _classify(e) from None
        except json.JSONDecodeError:
            raise ProviderError("bad_response", "not JSON") from None
        except Exception as e:  # noqa: BLE001
            raise _classify(e) from None
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise ProviderError("bad_response", "no content") from None
        return json.loads(content) if isinstance(content, str) else content


def _env(name: str) -> str | None:
    return os.environ.get(name) or _gemini_keys._dotenv_value(name)


def provider_name() -> str:
    choice = (_env("SHOCK_LLM") or "").strip().lower()
    if choice in ("off", "none", "0", "false"):
        return "off"
    if choice == "cortex":
        return "cortex" if _env("SNOWFLAKE_PAT") and _env("SNOWFLAKE_ACCOUNT") else "off"
    if choice in ("", "gemini"):
        return "gemini" if _gemini_keys.api_key() else "off"
    return "off"


def model_id() -> str:
    """The model whose answers the cache holds. With no provider, the Gemini ID, so frozen answers still match."""
    if (_env("SHOCK_LLM") or "").strip().lower() == "cortex":
        return _check_pinned(os.environ.get("SHOCK_CORTEX_MODEL") or CORTEX_MODEL)
    return _check_pinned(os.environ.get("SHOCK_GEMINI_MODEL") or GEMINI_MODEL)


def default_adapter():
    p = provider_name()
    if p == "gemini":
        return GeminiAdapter(_gemini_keys.api_key())
    if p == "cortex":
        return CortexAdapter(_env("SNOWFLAKE_PAT"), _env("SNOWFLAKE_ACCOUNT"))
    return None


# ------------------------------------------------------------------ one call

_down_until = 0.0


def reset_cooldown() -> None:
    global _down_until
    _down_until = 0.0


def _validated(raw) -> dict:
    """Strict schema check, canonicalization, then range check. Raises IntentError."""
    intent = canonicalize_intent(raw, strict=True)
    bad = intent_out_of_range(intent)
    if bad:
        raise IntentError("out of range: " + ", ".join(bad))
    return intent


def llm_intent(norm: str, current: Shock, adapter=None) -> tuple[dict | None, str]:
    """(intent, status). intent is None when the caller should fall through to the rules; status says why.

    One retry on invalid JSON or a response that fails validation; no retry on auth, server or network errors;
    a network failure turns the LLM off for COOLDOWN_S. Only a validated intent is cached.
    """
    global _down_until
    adapter = default_adapter() if adapter is None else adapter
    if adapter is None:
        return None, "LLM off"
    if time.time() < _down_until:
        return None, "LLM skipped after a recent network failure"
    model = _check_pinned(adapter.model)
    user = user_payload(norm, current)
    last = "invalid response"
    for _attempt in range(2):
        try:
            raw = adapter.complete_json(SYSTEM, user, INTENT_SCHEMA)
            intent = _validated(raw)
        except (json.JSONDecodeError, IntentError, TypeError, ValueError) as e:
            last = f"invalid response ({type(e).__name__})"
            continue
        except Exception as e:  # noqa: BLE001 - a provider or adapter failure must not break the demo
            err = _classify(e)   # its text is dropped: it may echo a key or a response body
            if err.kind == "network":
                _down_until = time.time() + COOLDOWN_S
            return None, f"{getattr(adapter, 'name', 'LLM')} unavailable ({err.kind})"
        key = cache_key(norm, current, model, PROMPT_VERSION)
        cache_put(key, norm, current, intent, model, PROMPT_VERSION)
        return intent, f"{getattr(adapter, 'name', 'LLM')} ({model})"
    return None, last


__all__ = ["PROMPT_VERSION", "INTENT_SCHEMA_VERSION", "GeminiAdapter", "CortexAdapter", "ProviderError",
           "llm_intent", "provider_name", "model_id", "user_payload", "SYSTEM"]
