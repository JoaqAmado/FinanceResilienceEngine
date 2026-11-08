"""Free-text twists -> a `Shock`, deterministically.

    parse_shock("Job loss on EI and bills up 15%", row, current, target)

Backends run in a fixed order, and the first one that understands the message wins:

    golden table  ->  cache (frozen, then local)  ->  LLM (resilience.shock_llm)  ->  rule parser

Every backend returns the same *intent* dict: what the user said ("income drops to $2,000 a month"),
never a computed lever. One function, `validate_and_build`, turns an intent into a `Shock` for the
selected account: account-relative maths (N / I, N - H), clamps, reality-check guards and warnings
all happen there, in code. The LLM never sees account data, never computes a number and never writes
text the user reads: `understood_as` and `resolved` are built here from the final Shock and the row.

Determinism: golden and cached inputs give byte-identical results with no network; a new input costs
one LLM call and is cached from then on; offline, an uncached input falls back to the rules (the source
badge says so). `python -m resilience.shock_parser warm` removes that last case for rehearsed phrasings.

    python -m resilience.shock_parser warm      # run the rehearsed phrasings through the LLM once
    python -m resilience.shock_parser freeze    # copy them from .cache/ into llm_cache_frozen.json
"""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import math
import re
import sys
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

import pandas as pd

from .core import DOUBLE_WHAMMY, EI_2026_MAX_MONTHLY, FURNACE, LAID_OFF_EI, Shock, _get, apply_shock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
GOLDEN_FILE = HERE / "golden_twists.json"
FROZEN_CACHE = HERE / "llm_cache_frozen.json"
CACHE_DIR = ROOT / ".cache"
LOCAL_CACHE = CACHE_DIR / "shock_intents.json"
DISAGREEMENTS = CACHE_DIR / "disagreements.jsonl"

INTENT_SCHEMA_VERSION = "intent-v1"

# ------------------------------------------------------------------ the app's lever state

ONEOFF_X = "× typical spending"
ONEOFF_AMT = "$ amount"
STATE_KEYS = ("income_pct", "job_loss", "bills_pct", "extra", "oneoff_mode", "oneoff_x", "oneoff_amt", "cut_pct",
              "target", "t_cap", "t_ww", "t_pens", "t_s6", "t_bfb")
DEFAULT_TARGET = 6

# ranges validate_and_build clamps to (the sliders accept the same ranges)
MONEY_MAX = 1_000_000.0
ONEOFF_MULTIPLE_MAX = 12.0
TARGET_MIN, TARGET_MAX = 1, 24

HINT_CHIPS = (
    "Laid off, EI pays 55%",
    "Furnace dies, repair = a month of spending",
    "Job loss on EI and bills up 15%",
    "Income drops to $2,000 a month",
    "Rent up $300 a month",
    "Must last 9 months",
)
SUGGESTIONS = ("Laid off, EI pays 55%", "Rent up $300 a month", "Must last 9 months")

# Rehearsal phrasings that are NOT in the golden table: the rule parser must handle every one, and `warm` runs them
# through the LLM ahead of the demo.
PRACTICE_PHRASINGS = (
    "pt got laid off, ei kicks in, rent +15%",
    "income down to 2k/mo and a 3k car repair",
    "they lost their job, EI at 55 percent",
    "unemployed on EI and utilities up 10%",
    "income falls by 30%",
    "income cut 0.25",
    "pay cut 20% for 6 months",
    "reduced hours 40%",
    "income kept at 70%",
    "only 60% of income coming in",
    "partner loses their job",
    "lose half the household income",
    "rent goes to $1,800 a month",
    "rent up by $450/mo",
    "new car payment of $450",
    "baby on the way, $900 a month more",
    "a $2,500 furnace repair",
    "emergency vet bill of $1,200",
    "a one-off worth 3 months of spending",
    "cut back on spending by 25%",
    "discretionary spending down fifteen percent",
    "survive 12 months",
    "a 3-month test",
    "laid off with the 2026 EI cap and waiting week",
    "job loss on EI, keep pension",
    "on EI, half-year spending",
    "bills by standing order up 20%",
    "account 20143, laid off",
    "customer #98952 loses job, keep the pension",
    "laid off and rent goes up $200 a month",
)

# ------------------------------------------------------------------ numbers

_WORD_NUMBERS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90, "hundred": 100,
}
_TENS = "twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety"
_UNITS = "one|two|three|four|five|six|seven|eight|nine"
_ALL_WORDS = "|".join(sorted(_WORD_NUMBERS, key=len, reverse=True))
# a number word only counts when a unit follows it, so "one-off" stays a word
_WORD_NUMBER = re.compile(rf"\b(?:({_TENS})[\s-]({_UNITS})|({_ALL_WORDS}))\b(?=\s*(?:%|percent|per cent|pct|months?\b|"
                          rf"-month|x\b|×|times\b|thousand\b|dollars\b))")


def _words_to_digits(text: str) -> str:
    def sub(m: re.Match) -> str:
        if m.group(1):
            return str(_WORD_NUMBERS[m.group(1)] + _WORD_NUMBERS[m.group(2)])
        return str(_WORD_NUMBERS[m.group(3)])
    return _WORD_NUMBER.sub(sub, text)


def coerce_pct(value: Any) -> float:
    """THE percent conversion. Returns a fraction: "15", "15%", "fifteen percent", 15, 0.15 -> 0.15.

    A value written with "%" or "percent" is always divided by 100 ("1%" -> 0.01). A bare number in [0, 1] is
    already a fraction ("0.15" -> 0.15, "1" -> 1.0); a bare number above 1 is a percent ("15" -> 0.15).
    Out-of-range results are returned as they are, for the caller to clamp with a warning.
    Raises ValueError when there is no number.
    """
    if isinstance(value, bool):
        raise ValueError(f"not a percent: {value!r}")
    if isinstance(value, (int, float)):
        x = float(value)
        if math.isnan(x) or math.isinf(x):
            raise ValueError(f"not a percent: {value!r}")
        return x if 0.0 <= x <= 1.0 else x / 100.0
    text = _words_to_digits(str(value).strip().lower())
    m = re.fullmatch(r"([+-]?\d+(?:\.\d+)?|[+-]?\.\d+)\s*(%|percent|per cent|pct)?", text)
    if not m:
        raise ValueError(f"not a percent: {value!r}")
    x = float(m.group(1))
    return x / 100.0 if m.group(2) else coerce_pct(x)


def parse_money(value: Any) -> float:
    """Dollars from "$2,500", "2.5k", "$2500/mo", "2 thousand" or a number. Raises ValueError when there is none."""
    if isinstance(value, bool):
        raise ValueError(f"not an amount: {value!r}")
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().lower().replace(",", "")
    m = re.fullmatch(r"\$?\s*(\d+(?:\.\d+)?|\.\d+)\s*(k|thousand)?\s*(?:/\s*mo(?:nth)?|a month|per month|monthly)?",
                     text)
    if not m:
        raise ValueError(f"not an amount: {value!r}")
    return float(m.group(1)) * (1000.0 if m.group(2) else 1.0)


def normalize(message: str) -> str:
    """The golden-table and cache key: lowercase, punctuation stripped, spaces collapsed.

    Decimal points and thousands commas inside numbers are kept as a number ("2.5k" never becomes "25k"),
    and "%" is kept ("1%" is not "1"). "$" goes, so "$300" and "300" are the same key.
    """
    t = str(message).lower().replace("×", "x").replace("’", "'")
    t = re.sub(r"(?<=\d),(?=\d{3}\b)", "", t)
    t = re.sub(r"(?<=\d)\.(?=\d)", "\x00", t)  # protect decimal points
    t = re.sub(r"[^\w\s%\x00]", " ", t)
    t = t.replace("\x00", ".").replace("_", " ")
    return re.sub(r"\s+", " ", t).strip()


# ------------------------------------------------------------------ the intent schema

INCOME_KINDS = ("none", "job_loss_ei", "drop_pct", "keep_pct", "pay_cut_pct", "to_amount", "partner_job_loss",
                "restore")
BILLS_KINDS = ("none", "increase_pct", "reset")
MONTHLY_KINDS = ("none", "set", "add", "rent_to", "reset")
ONE_OFF_KINDS = ("none", "set_amount", "add_amount", "months_of_spending", "add_months_of_spending", "reset")
CUT_KINDS = ("none", "set_pct", "reset")
TARGET_KINDS = ("none", "set")
EDIT_KINDS = ("none", "reset_all", "set_last_percent")
CHECK_VALUES = ("unchanged", "on", "off")
CHECKS = ("ei_cap", "waiting_week", "keep_pension", "half_year_spending", "bills_by_standing_order")

# section -> (kind enum, numeric fields and their unit)
SECTIONS: dict[str, tuple[tuple[str, ...], dict[str, str]]] = {
    "income": (INCOME_KINDS, {"pct": "pct", "amount": "money"}),
    "bills": (BILLS_KINDS, {"pct": "pct"}),
    "monthly_cost": (MONTHLY_KINDS, {"amount": "money"}),
    "one_off": (ONE_OFF_KINDS, {"amount": "money", "months": "months"}),
    "spending_cut": (CUT_KINDS, {"pct": "pct"}),
    "target": (TARGET_KINDS, {"months": "months"}),
    "edit": (EDIT_KINDS, {"pct": "pct"}),
}


def _obj(props: dict) -> dict:
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


# Every property required, no extra properties, enums for kinds, and no minimum/maximum: ranges are checked in code.
INTENT_SCHEMA = _obj({
    **{name: _obj({"kind": {"type": "string", "enum": list(kinds)},
                   **{f: {"type": "number"} for f in fields}})
       for name, (kinds, fields) in SECTIONS.items()},
    "account_id": {"type": "integer"},
    "checks": _obj({c: {"type": "string", "enum": list(CHECK_VALUES)} for c in CHECKS}),
    "clarify": {"type": "string"},
})


def blank_intent() -> dict:
    """An intent that says nothing: every kind "none", every number 0, every check "unchanged"."""
    out: dict[str, Any] = {name: {"kind": "none", **{f: 0.0 for f in fields}} for name, (_, fields) in SECTIONS.items()}
    out["account_id"] = 0
    out["checks"] = {c: "unchanged" for c in CHECKS}
    out["clarify"] = ""
    return out


class IntentError(ValueError):
    """The intent does not fit the schema (a wrong kind, a missing section, a non-number)."""


def _num(v: Any, unit: str) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float, str)):
        raise IntentError(f"not a number: {v!r}")
    try:
        if unit == "pct":
            return round(coerce_pct(v), 4) + 0.0
        x = parse_money(v) if isinstance(v, str) else float(v)
    except ValueError as e:
        raise IntentError(str(e)) from None
    if math.isnan(x) or math.isinf(x):
        raise IntentError(f"not a number: {v!r}")
    return round(x, 2) + 0.0  # cents for money, hundredths for months; +0.0 turns -0.0 into 0.0


def canonicalize_intent(raw: Any, strict: bool = False) -> dict:
    """The one canonical form of an intent: sorted keys, money to cents, percents as fractions to 4 decimals,
    enums lowercased, unknown keys stripped, missing parts filled with "nothing said".

    strict=True (used on LLM output) additionally rejects missing or extra keys, as the schema does.
    Raises IntentError when the intent can't be read.
    """
    if not isinstance(raw, dict):
        raise IntentError("the intent is not an object")
    expected = set(SECTIONS) | {"account_id", "checks", "clarify"}
    if strict and set(raw) != expected:
        raise IntentError(f"keys differ from the schema: extra {sorted(set(raw) - expected)}, "
                          f"missing {sorted(expected - set(raw))}")
    out = blank_intent()
    for name, (kinds, fields) in SECTIONS.items():
        part = raw.get(name)
        if part is None:
            continue
        if not isinstance(part, dict):
            raise IntentError(f"{name} is not an object")
        if strict and set(part) != {"kind", *fields}:
            raise IntentError(f"{name}: keys differ from the schema")
        kind = str(part.get("kind", "none")).strip().lower().replace(" ", "_").replace("-", "_")
        if kind not in kinds:
            raise IntentError(f"{name}: unknown kind {kind!r}")
        out[name]["kind"] = kind
        for f, unit in fields.items():
            if f in part and part[f] is not None:
                out[name][f] = _num(part[f], unit)
    acct = raw.get("account_id", 0)
    if acct is None:
        acct = 0
    if isinstance(acct, bool) or not isinstance(acct, (int, float, str)):
        raise IntentError("account_id is not a number")
    try:
        acct_f = float(acct)
    except ValueError:
        raise IntentError("account_id is not a number") from None
    if math.isnan(acct_f) or acct_f != int(acct_f):
        raise IntentError("account_id is not a whole number")
    out["account_id"] = int(acct_f)
    checks = raw.get("checks") or {}
    if not isinstance(checks, dict):
        raise IntentError("checks is not an object")
    if strict and set(checks) != set(CHECKS):
        raise IntentError("checks: keys differ from the schema")
    for c in CHECKS:
        v = str(checks.get(c, "unchanged")).strip().lower()
        if v not in CHECK_VALUES:
            raise IntentError(f"checks.{c}: unknown value {v!r}")
        out["checks"][c] = v
    clarify = raw.get("clarify", "")
    out["clarify"] = "" if clarify is None else str(clarify).strip()
    return json.loads(json.dumps(out, sort_keys=True))


def intent_out_of_range(intent: dict) -> list[str]:
    """Values outside the ranges validate_and_build accepts (used to reject an LLM answer instead of clamping)."""
    bad = []
    for name, (_, fields) in SECTIONS.items():
        for f, unit in fields.items():
            v = intent[name][f]
            if unit == "pct" and not 0.0 <= v <= 1.0:
                bad.append(f"{name}.{f}={v}")
            if unit == "money" and not 0.0 <= v <= MONEY_MAX:
                bad.append(f"{name}.{f}={v}")
    if not 0.0 <= intent["one_off"]["months"] <= ONEOFF_MULTIPLE_MAX:
        bad.append(f"one_off.months={intent['one_off']['months']}")
    if intent["target"]["kind"] == "set" and not TARGET_MIN <= intent["target"]["months"] <= TARGET_MAX:
        bad.append(f"target.months={intent['target']['months']}")
    if intent["account_id"] < 0:
        bad.append(f"account_id={intent['account_id']}")
    return bad


def intent_is_empty(intent: dict) -> bool:
    return (all(intent[name]["kind"] == "none" for name in SECTIONS) and intent["account_id"] == 0
            and all(v == "unchanged" for v in intent["checks"].values()) and not intent["clarify"])


# ------------------------------------------------------------------ Shock <-> state, and words for a Shock

def _r(x: float, nd: int) -> float:
    return round(float(x), nd) + 0.0


def same_shock(a: Shock, b: Shock) -> bool:
    """Equal levers and checks; the display name doesn't count."""
    return a.with_(name="") == b.with_(name="")


def shock_key(shock: Shock) -> dict:
    """The Shock as a sorted, name-free dict (part of the cache key, and what the LLM is told is current)."""
    d = dataclasses.asdict(shock)
    d.pop("name")
    return {k: (_r(v, 6) if isinstance(v, float) else v) for k, v in sorted(d.items())}


def can_pension(shock: Shock, row) -> bool:
    return shock.is_job_loss and float(_get(row, "Pn")) > 0


def can_bills_fallback(row) -> bool:
    return float(_get(row, "H")) == 0 and float(_get(row, "H_SO")) > 0


def judges_shock_from_state(v) -> Shock:
    """The judges' levers a set of lever values means (inactive one-off inputs don't count). No reality checks."""
    by_x = v["oneoff_mode"] == ONEOFF_X
    pct = float(v["income_pct"])
    s = Shock(income_multiplier=_r(pct / 100, 6), bills_increase_pct=_r(float(v["bills_pct"]) / 100, 6),
              extra_monthly_cost=_r(v["extra"], 2), one_off_cost=0.0 if by_x else _r(v["oneoff_amt"], 2),
              one_off_multiple_of_S=_r(v["oneoff_x"], 6) if by_x else 0.0,
              flexible_cut_pct=_r(float(v.get("cut_pct", 0.0)) / 100, 6),
              job_loss=bool(v["job_loss"]) and pct < 100)
    return s.with_(name=twist_label(s))


def shock_from_state(v, row) -> Shock:
    """The full Shock the engine runs: judges' levers plus the reality checks that apply to this account.
    A check that can't apply (EI cap without a job loss, say) is off, whatever its toggle says."""
    j = judges_shock_from_state(v)
    jl = j.is_job_loss
    return j.with_(income_cap_monthly=EI_2026_MAX_MONTHLY if v.get("t_cap") and jl else None,
                   waiting_week=bool(v.get("t_ww")) and jl,
                   pension_aware=bool(v.get("t_pens")) and can_pension(j, row),
                   spending_basis="S6" if v.get("t_s6") else "S",
                   bills_fallback=bool(v.get("t_bfb")) and can_bills_fallback(row))


def shock_to_state(shock: Shock, target: int) -> dict:
    """The lever values (the app's session-state keys) that mean this Shock. Inverse of shock_from_state."""
    if shock.one_off_cost > 0 and shock.one_off_multiple_of_S > 0:
        raise ValueError("a Shock with both a $ one-off and a multiple-of-S one-off has no single lever state")
    by_x = not shock.one_off_cost > 0
    mult = shock.income_multiplier
    return {
        "income_pct": _r(mult * 100, 4),
        "job_loss": bool(shock.job_loss and mult < 1),
        "bills_pct": _r(shock.bills_increase_pct * 100, 4),
        "extra": _r(shock.extra_monthly_cost, 2),
        "oneoff_mode": ONEOFF_X if by_x else ONEOFF_AMT,
        "oneoff_x": _r(shock.one_off_multiple_of_S, 6) if by_x else 0.0,
        "oneoff_amt": 0.0 if by_x else _r(shock.one_off_cost, 2),
        "cut_pct": _r(shock.flexible_cut_pct * 100, 4),
        "target": int(target),
        "t_cap": shock.income_cap_monthly is not None,
        "t_ww": bool(shock.waiting_week),
        "t_pens": bool(shock.pension_aware),
        "t_s6": shock.spending_basis == "S6",
        "t_bfb": bool(shock.bills_fallback),
    }


def _money(x: float) -> str:
    x = 0.0 if abs(x) < 0.5 else x
    return f"-${-x:,.0f}" if x < 0 else f"${x:,.0f}"


def _pct(x: float) -> str:
    return f"{round(x * 100, 1):g}%"


# the app's twist-card names, kept for the three track twists so the story headline still names them
PRESET_NAMES = ((LAID_OFF_EI, "Laid off: EI 55%"), (FURNACE, "Furnace dies: 1× spending"),
                (DOUBLE_WHAMMY, "Job loss + bills +15%"))


def _checks_free(shock: Shock) -> Shock:
    return shock.with_(income_cap_monthly=None, waiting_week=False, pension_aware=False, spending_basis="S",
                       bills_fallback=False, name="")


def describe_shock(shock: Shock, row=None, target: float | None = None) -> str:
    """Plain English for a Shock: THE one function behind both the twist label and `understood_as`.

    Without a row: the short label ("Laid off: EI 55%", "Income kept 70%, +$400/mo").
    With a row: every lever in this customer's dollars, joined by " · ", plus "must last N months" if a target
    is given. Built from the Shock alone, never from the user's words.
    """
    long = row is not None
    if not long:
        for preset, name in PRESET_NAMES:
            if _checks_free(shock) == preset.with_(name=""):
                parts = [name]
                break
        else:
            parts = []
            _lever_parts(shock, None, parts)
        _check_parts(shock, parts)
        if not parts:
            return "No shock"
        text = ", ".join(parts)
        return text[0].upper() + text[1:]
    parts: list[str] = []
    _lever_parts(shock, row, parts)
    _check_parts(shock, parts)
    if not parts:
        parts.append("no shock")
    if target is not None:
        parts.append(f"must last {target:g} month{'' if target == 1 else 's'}")
    text = " · ".join(parts)
    return text[0].upper() + text[1:]


def _lever_parts(shock: Shock, row, parts: list[str]) -> None:
    long = row is not None
    mult = shock.income_multiplier
    I = float(_get(row, "I")) if long else 0.0
    if shock.is_job_loss:
        p = f"laid off, EI pays {_pct(mult)}"
        parts.append(p + (f": {_money(mult * I)}/mo of your usual {_money(I)}" if long else ""))
    elif mult != 1.0:
        parts.append(f"income drops to {_money(mult * I)}/mo ({_pct(mult)} of your usual {_money(I)})" if long
                     else f"income kept {_pct(mult)}")
    if shock.bills_increase_pct:
        H = float(_get(row, "H")) if long else 0.0
        if long and shock.bills_fallback:
            H = max(H, float(_get(row, "H_SO")))
        parts.append(f"household bills +{_pct(shock.bills_increase_pct)}" +
                     (f" (+{_money(shock.bills_increase_pct * H)}/mo on {_money(H)})" if long else ""))
    if shock.extra_monthly_cost:
        parts.append(f"+{_money(shock.extra_monthly_cost)}/mo" + (" new monthly costs" if long else ""))
    if shock.one_off_cost:
        parts.append(f"one-off {_money(shock.one_off_cost)}")
    if shock.one_off_multiple_of_S:
        x = shock.one_off_multiple_of_S
        parts.append(f"one-off {x:g}× spending" +
                     (f" ({_money(x * float(_get(row, 'S')))})" if long else ""))
    if shock.flexible_cut_pct:
        parts.append(f"non-fixed spending cut {_pct(shock.flexible_cut_pct)}" +
                     (f" (-{_money(shock.flexible_cut_pct * float(_get(row, 'flexible_median')))}/mo)" if long
                      else ""))


def _check_parts(shock: Shock, parts: list[str]) -> None:
    if shock.income_cap_monthly is not None:
        parts.append(f"2026 EI cap ({_money(shock.income_cap_monthly)}/mo)")
    if shock.waiting_week:
        parts.append("EI waiting week")
    if shock.pension_aware:
        parts.append("pension kept")
    if shock.spending_basis == "S6":
        parts.append("half-year spending")
    if shock.bills_fallback:
        parts.append("bills by standing order")


def twist_label(shock: Shock) -> str:
    """The story's short name for a twist: describe_shock without a row."""
    return describe_shock(shock)


# ------------------------------------------------------------------ validate_and_build

@dataclass(frozen=True)
class ParseResult:
    shock: Shock
    target: int
    account_id: int | None
    source: str                      # "golden" | "cache" | "llm" | "rules" ("none" when nothing understood it)
    understood_as: str               # plain English, built from the Shock and the row, never from the message
    resolved: list[str] = field(default_factory=list)   # how account-relative amounts became levers
    warnings: list[str] = field(default_factory=list)
    clarify: str | None = None
    pct_lever: str | None = None     # the most recently set percent lever, for "make it 20% instead"
    intent: dict | None = None


@lru_cache(maxsize=1)
def _default_metrics() -> pd.DataFrame:
    from .core import build_metrics
    return build_metrics()


def _clamp(x: float, lo: float, hi: float, what: str, warnings: list[str], fmt=lambda v: f"{v:g}") -> float:
    if x < lo or x > hi:
        y = min(max(x, lo), hi)
        warnings.append(f"{what} {fmt(x)} is out of range; using {fmt(y)}.")
        return y
    return x


def _suggest() -> str:
    return "I couldn't read a twist there. Try: " + " · ".join(f"“{s}”" for s in SUGGESTIONS)


def validate_and_build(intent: dict, row, current: Shock, target: int, *, metrics: pd.DataFrame | None = None,
                       last_pct_lever: str | None = None, source: str = "none") -> ParseResult:
    """Intent + the selected account's row + the current Shock -> the new Shock. The same for every backend.

    Levers the intent doesn't mention keep their `current` values. Amounts stated in dollars or relative to the
    customer are resolved here against `row` (or the row of the account the message names). Out-of-range values
    are clamped with a warning; reality checks that can't apply are turned off with a warning; an unknown
    account or an intent that says nothing returns `clarify` and leaves the state unchanged.
    """
    intent = canonicalize_intent(intent)
    warnings: list[str] = []
    resolved: list[str] = []

    def unchanged(msg: str) -> ParseResult:
        return ParseResult(current, int(target), None, source, describe_shock(current, row, target), [], warnings,
                           msg, last_pct_lever, intent)

    if intent["clarify"]:
        return unchanged(intent["clarify"])
    if intent_is_empty(intent):
        return unchanged(_suggest())

    account_id = None
    if intent["account_id"]:
        m = _default_metrics() if metrics is None else metrics
        if intent["account_id"] not in m.index:
            return unchanged(f"Account {intent['account_id']} isn't in the data (IDs run {m.index.min()} to "
                             f"{m.index.max()} with gaps). Which account did you mean?")
        account_id = int(intent["account_id"])
        row = m.loc[account_id]

    I, H, S = float(_get(row, "I")), float(_get(row, "H")), float(_get(row, "S"))
    s = current
    mult, jl = s.income_multiplier, s.job_loss
    bills, extra, cost, xS, cut = (s.bills_increase_pct, s.extra_monthly_cost, s.one_off_cost,
                                   s.one_off_multiple_of_S, s.flexible_cut_pct)
    cap, ww, pens, s6, bfb = (s.income_cap_monthly is not None, s.waiting_week, s.pension_aware,
                              s.spending_basis == "S6", s.bills_fallback)
    tgt = float(target)
    pct_lever = last_pct_lever

    edit = intent["edit"]
    if edit["kind"] == "reset_all":
        mult, jl, bills, extra, cost, xS, cut = 1.0, False, 0.0, 0.0, 0.0, 0.0, 0.0
        cap = ww = pens = s6 = bfb = False
        tgt, pct_lever = float(DEFAULT_TARGET), None

    inc = intent["income"]
    if inc["kind"] == "job_loss_ei":
        mult, jl = (inc["pct"] if inc["pct"] > 0 else LAID_OFF_EI.income_multiplier), True
        pct_lever = "income_ei"
    elif inc["kind"] == "drop_pct":
        mult, jl, pct_lever = 1.0 - inc["pct"], False, "income_drop"
    elif inc["kind"] == "keep_pct":
        mult, jl, pct_lever = inc["pct"], False, "income_keep"
    elif inc["kind"] == "pay_cut_pct":
        if inc["pct"] <= 0:
            return unchanged("How big is the pay cut? For example: “pay cut 20%” or “hours cut in half”.")
        mult, jl, pct_lever = 1.0 - inc["pct"], False, "income_drop"
    elif inc["kind"] == "to_amount":
        n = inc["amount"]
        if I <= 0:
            warnings.append(f"Usual money in is {_money(I)}, so an income of {_money(n)}/mo can't be expressed as a "
                            "share of it; income left unchanged.")
        else:
            ratio = n / I
            if ratio > 1:
                warnings.append(f"{_money(n)}/mo is more than the usual {_money(I)}/mo; income kept at 100%.")
                ratio = 1.0
            mult, jl, pct_lever = ratio, False, None  # set in dollars: no percent to change "instead"
            resolved.append(f"income {_money(n)}/mo ÷ usual {_money(I)}/mo = {_pct(ratio)} of money in")
    elif inc["kind"] == "partner_job_loss":
        mult, jl, pct_lever = 0.5, False, None
        warnings.append("Assumed the partner brings in half the household's money in (income kept 50%, not an EI "
                        "job loss); adjust under Fine-tune if the split is different.")
    elif inc["kind"] == "restore":
        mult, jl = 1.0, False
        if pct_lever and pct_lever.startswith("income"):
            pct_lever = None

    b = intent["bills"]
    if b["kind"] == "increase_pct":
        bills, pct_lever = b["pct"], "bills"
    elif b["kind"] == "reset":
        bills = 0.0

    mc = intent["monthly_cost"]
    if mc["kind"] == "set":
        extra = mc["amount"]
    elif mc["kind"] == "add":
        extra = extra + mc["amount"]
    elif mc["kind"] == "rent_to":
        n = mc["amount"]
        if H > 0:
            extra = max(n - H, 0.0)
            resolved.append(f"rent {_money(n)}/mo − household bills now {_money(H)}/mo = +{_money(extra)}/mo")
            if n < H:
                warnings.append(f"{_money(n)}/mo is less than the household bills already recorded ({_money(H)}/mo): "
                                "a rent cut isn't modelled, so no new monthly cost.")
        else:
            extra = n
            warnings.append(f"No household bills are recorded for this account (H = $0), so the whole "
                            f"{_money(n)}/mo rent counts as a new monthly cost.")
    elif mc["kind"] == "reset":
        extra = 0.0

    oo = intent["one_off"]
    if oo["kind"] == "set_amount":
        cost, xS = oo["amount"], 0.0
    elif oo["kind"] == "add_amount":
        cost = cost + oo["amount"]
    elif oo["kind"] == "months_of_spending":
        cost, xS = 0.0, (oo["months"] if oo["months"] > 0 else 1.0)
    elif oo["kind"] == "add_months_of_spending":
        xS = xS + (oo["months"] if oo["months"] > 0 else 1.0)
    elif oo["kind"] == "reset":
        cost, xS = 0.0, 0.0

    sc = intent["spending_cut"]
    if sc["kind"] == "set_pct":
        cut, pct_lever = sc["pct"], "cut"
    elif sc["kind"] == "reset":
        cut = 0.0

    if intent["target"]["kind"] == "set":
        tgt = intent["target"]["months"]

    if edit["kind"] == "set_last_percent":
        p = edit["pct"]
        if pct_lever == "income_ei":
            mult, jl = p, True
        elif pct_lever == "income_drop":
            mult, jl = 1.0 - p, False
        elif pct_lever == "income_keep":
            mult, jl = p, False
        elif pct_lever == "bills":
            bills = p
        elif pct_lever == "cut":
            cut = p
        else:
            return unchanged(f"Which lever should be {_pct(p)}? For example: “bills up {_pct(p)}” or "
                             f"“cut spending {_pct(p)}”.")

    for name in CHECKS:
        v = intent["checks"][name]
        if v == "unchanged":
            continue
        on = v == "on"
        if name == "ei_cap":
            cap = on
        elif name == "waiting_week":
            ww = on
        elif name == "keep_pension":
            pens = on
        elif name == "half_year_spending":
            s6 = on
        else:
            bfb = on

    # ---- clamps
    pct_fmt = _pct
    mult = _clamp(mult, 0.0, 1.0, "Income kept", warnings, pct_fmt)
    bills = _clamp(bills, 0.0, 1.0, "Bills increase", warnings, pct_fmt)
    cut = _clamp(cut, 0.0, 1.0, "Spending cut", warnings, pct_fmt)
    extra = _clamp(extra, 0.0, MONEY_MAX, "Monthly cost", warnings, _money)
    cost = _clamp(cost, 0.0, MONEY_MAX, "One-off cost", warnings, _money)
    xS = _clamp(xS, 0.0, ONEOFF_MULTIPLE_MAX, "One-off of", warnings, lambda v: f"{v:g}× spending")
    tgt = _clamp(tgt, TARGET_MIN, TARGET_MAX, "Target of", warnings, lambda v: f"{v:g} months")
    if tgt != round(tgt):
        warnings.append(f"Target of {tgt:g} months rounded to {round(tgt):d} months.")
    tgt_i = int(round(tgt))

    # a $ one-off and a multiple-of-spending one-off together become one $ amount for this account
    if cost > 0 and xS > 0:
        total = cost + xS * S
        resolved.append(f"one-off {_money(cost)} + {xS:g}× spending ({_money(xS * S)}) = {_money(total)}")
        cost, xS = _r(total, 2), 0.0

    jl = jl and mult < 1.0
    # ---- reality checks that can't apply are turned off, with a warning (the toggles' own guards)
    if cap and not jl:
        cap = False
        warnings.append("The 2026 EI cap needs a job loss on EI; turned off.")
    if ww and not jl:
        ww = False
        warnings.append("The EI waiting week needs a job loss on EI; turned off.")
    if pens and not jl:
        pens = False
        warnings.append("Keeping the pension needs a job loss on EI; turned off.")
    elif pens and not float(_get(row, "Pn")) > 0:
        pens = False
        warnings.append("This account has no pension income (Pn = $0); “keep pension” turned off.")
    if bfb and not can_bills_fallback(row):
        bfb = False
        warnings.append("“Bills by standing order” only applies when H = $0 and household bills are paid by "
                        "standing order; turned off.")

    candidate = Shock(income_multiplier=mult, job_loss=jl, bills_increase_pct=bills, extra_monthly_cost=extra,
                      one_off_cost=cost, one_off_multiple_of_S=xS, flexible_cut_pct=cut,
                      income_cap_monthly=EI_2026_MAX_MONTHLY if cap else None, waiting_week=ww,
                      pension_aware=pens, spending_basis="S6" if s6 else "S", bills_fallback=bfb)
    # built through the state round trip, so the chat's Shock and the sliders' Shock are equal by construction
    final = shock_from_state(shock_to_state(candidate, tgt_i), row)
    return ParseResult(final, tgt_i, account_id, source, describe_shock(final, row, tgt_i), resolved, warnings, None,
                       pct_lever, intent)


# ------------------------------------------------------------------ backends

class Parser(Protocol):
    source: str

    def parse(self, message: str, norm: str, current: Shock) -> dict | None:
        """An intent dict for the message, or None when this backend can't read it."""


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


@lru_cache(maxsize=1)
def golden_table() -> dict[str, dict]:
    """normalized phrase -> canonical intent, from golden_twists.json."""
    out: dict[str, dict] = {}
    for entry in _read_json(GOLDEN_FILE).get("twists", []):
        intent = canonicalize_intent(entry["intent"])
        for phrase in entry["phrases"]:
            key = normalize(phrase)
            if key in out and out[key] != intent:
                raise ValueError(f"golden phrase {phrase!r} has two different intents")
            out[key] = intent
    return out


class GoldenParser:
    source = "golden"

    def parse(self, message: str, norm: str, current: Shock) -> dict | None:
        hit = golden_table().get(norm)
        return None if hit is None else json.loads(json.dumps(hit))


def cache_key(norm: str, current: Shock, model_id: str, prompt_version: str) -> str:
    blob = json.dumps({"message": norm, "current": shock_key(current), "prompt": prompt_version, "model": model_id,
                       "schema": INTENT_SCHEMA_VERSION}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()


def _entries(path: Path) -> dict:
    return _read_json(path).get("entries", {})


def cache_get(key: str) -> dict | None:
    for path in (FROZEN_CACHE, LOCAL_CACHE):  # the committed, read-only file wins
        hit = _entries(path).get(key)
        if hit is not None:
            try:
                return canonicalize_intent(hit["intent"])
            except (IntentError, KeyError, TypeError):
                continue
    return None


def _write_entries(path: Path, entries: dict, about: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"about": about, "entries": entries}, indent=1, sort_keys=True, ensure_ascii=False)
                   + "\n", encoding="utf-8")
    tmp.replace(path)


def cache_put(key: str, norm: str, current: Shock, intent: dict, model_id: str, prompt_version: str) -> None:
    """Store a validated intent in the local (gitignored) cache. Only ever called after a successful parse."""
    entries = _entries(LOCAL_CACHE)
    entries[key] = {"message": norm, "current": shock_key(current), "model": model_id, "prompt": prompt_version,
                    "schema": INTENT_SCHEMA_VERSION, "intent": intent}
    _write_entries(LOCAL_CACHE, entries, "LLM shock intents, written after every successful parse. Not committed.")


class CacheLookup:
    source = "cache"

    def parse(self, message: str, norm: str, current: Shock) -> dict | None:
        from . import shock_llm
        return cache_get(cache_key(norm, current, shock_llm.model_id(), shock_llm.PROMPT_VERSION))


class LLMParser:
    source = "llm"

    def __init__(self, adapter=None):
        self.adapter = adapter
        self.last_status = ""

    def parse(self, message: str, norm: str, current: Shock) -> dict | None:
        from . import shock_llm
        intent, self.last_status = shock_llm.llm_intent(norm, current, adapter=self.adapter)
        return intent


class RuleParser:
    source = "rules"

    def parse(self, message: str, norm: str, current: Shock) -> dict | None:
        return rule_intent(message)


def default_backends() -> list:
    return [GoldenParser(), CacheLookup(), LLMParser(), RuleParser()]


def _log_disagreement(message: str, llm: ParseResult, rules: ParseResult) -> None:
    try:
        DISAGREEMENTS.parent.mkdir(parents=True, exist_ok=True)
        line = {"message": normalize(message), "llm": shock_key(llm.shock), "llm_target": llm.target,
                "rules": shock_key(rules.shock), "rules_target": rules.target,
                "llm_intent": llm.intent, "rules_intent": rules.intent}
        with DISAGREEMENTS.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(line, sort_keys=True) + "\n")
    except OSError:
        pass


def _same_result(a: ParseResult, b: ParseResult) -> bool:
    return same_shock(a.shock, b.shock) and a.target == b.target and a.account_id == b.account_id


def parse_shock(message: str, row, current: Shock, target: int, *, metrics: pd.DataFrame | None = None,
                last_pct_lever: str | None = None, backends: list | None = None) -> ParseResult:
    """Free text -> ParseResult, trying golden -> cache -> LLM -> rules in that order. Never raises on bad input."""
    norm = normalize(message)
    backends = default_backends() if backends is None else backends
    if not norm:
        return validate_and_build(blank_intent(), row, current, target, metrics=metrics, last_pct_lever=last_pct_lever)
    for backend in backends:
        intent = backend.parse(message, norm, current)
        if intent is None:
            continue
        try:
            res = validate_and_build(intent, row, current, target, metrics=metrics, last_pct_lever=last_pct_lever,
                                     source=backend.source)
        except IntentError:
            continue  # a backend that returns an unreadable intent is skipped, never trusted
        if backend.source in ("llm", "cache") and res.clarify is None:
            rules_intent = rule_intent(message)
            if rules_intent is not None:
                rules = validate_and_build(rules_intent, row, current, target, metrics=metrics,
                                           last_pct_lever=last_pct_lever, source="rules")
                if rules.clarify is None and not _same_result(res, rules):
                    res = dataclasses.replace(res, warnings=[*res.warnings,
                                                             f"rules read this differently: {rules.understood_as}"])
                    if backend.source == "llm":
                        _log_disagreement(message, res, rules)
        return res
    return validate_and_build(blank_intent(), row, current, target, metrics=metrics, last_pct_lever=last_pct_lever)


def follow_up_hints(res: ParseResult, row) -> list[str]:
    """1-2 next things to try that fit the new state. The engine decides "under the target"; no number is shown."""
    hints = []
    if res.shock.is_job_loss and res.shock.income_cap_monthly is None:
        hints.append("Try “with the 2026 EI cap”")
    judge = _checks_free(res.shock)
    if not apply_shock(row, judge).survives(res.target) and not res.shock.flexible_cut_pct:
        hints.append("Try “cut spending 25%”")
    if not hints:
        hints.append(f"Try “must last {min(res.target + 3, TARGET_MAX)} months”")
    return hints[:2]


# ------------------------------------------------------------------ rule parser

_FILL = "░"   # what a consumed span is replaced with: not a word character and not a space
_NUM = r"(\d+(?:\.\d+)?)"
_PCT = _NUM + r"\s*(%)?"
_MO = r"(?:\s*/mo)?"
_MONEY_NOT_PCT = r"(?!\s*%|\d|\.\d)"
_ADD_WORDS = re.compile(r"\b(?:add|adds|adding|another|also|plus|on top|additional)\b")


def _rule_text(message: str) -> str:
    t = str(message).lower().replace("’", "'").replace("−", "-")
    t = re.sub(r"(?<=\d),(?=\d{3}\b)", "", t)
    t = re.sub(r"\b(per cent|percent|pct)\b", "%", t)
    t = _words_to_digits(t)
    t = re.sub(r"\b(?:in|by) half\b", "by 50%", t)
    t = re.sub(r"\bhalf (?:a|of a) month\b", "0.5 month", t)
    t = re.sub(r"\bby a quarter\b", "by 25%", t)
    t = re.sub(r"\b(?:a|one) quarter of\b", "25% of", t)

    def k(m: re.Match) -> str:
        return f"{float(m.group(1)) * 1000:g}"
    t = re.sub(r"(\d+(?:\.\d+)?)\s*(?:k|thousand)\b", k, t)
    t = re.sub(r"\$\s+(?=\d)", "$", t)
    t = re.sub(r"(\d)\s*(?:/\s*mo(?:nth)?\b|/\s*m\b|(?:a|per|each|every)\s+mo(?:nth)?\b|monthly\b|/\s*month\b)",
               r"\1/mo", t)
    return re.sub(r"[ \t]+", " ", t).strip()


class _Text:
    """The message with consumed spans masked, so each phrase feeds exactly one lever."""

    def __init__(self, s: str):
        self.s = s

    def take(self, pattern: str) -> list[re.Match]:
        ms = list(re.finditer(pattern, self.s))
        for m in ms:
            self.s = self.s[:m.start()] + _FILL * (m.end() - m.start()) + self.s[m.end():]
        return ms

    def has(self, pattern: str) -> bool:
        return re.search(pattern, self.s) is not None


def _pct_of(m: re.Match, num_group: int = 1, pct_group: int = 2) -> float:
    v = m.group(num_group)
    return coerce_pct(v + ("%" if m.group(pct_group) else ""))


_INCOME = r"(?:income|pay|paycheque|paycheck|money in|earnings|wages?)"
_OFF = r"(?:no|without|remove|drop|turn off|undo|cancel|skip|forget)"
_CHECKS_OFF = {
    "ei_cap": rf"\b{_OFF}\s+(?:the\s+)?(?:2026\s+)?(?:ei\s+)?(?:cap|max(?:imum)?)\b",
    "waiting_week": rf"\b{_OFF}\s+(?:the\s+)?(?:ei\s+)?waiting (?:week|period)\b",
    "keep_pension": rf"\b{_OFF}\s+(?:the\s+)?pension(?:\s+check)?\b|\blos(?:e|es|ing) (?:the\s+)?pension\b",
    "half_year_spending": rf"\b{_OFF}\s+(?:the\s+)?half-?\s?year(?:\s+spending)?\b",
    "bills_by_standing_order": rf"\b{_OFF}\s+(?:the\s+)?(?:bills\s+(?:paid\s+)?by\s+)?standing orders?\b",
}
_CHECKS_ON = {
    "ei_cap": r"\b(?:2026\s+)?ei\s+(?:cap|max(?:imum)?)\b|\b2026\s+(?:cap|max(?:imum)?)\b"
              r"|\bcap(?:ped)?\s+(?:at\s+)?(?:the\s+)?(?:2026|ei|max(?:imum)?)\b|\bwith the cap\b"
              r"|\$?729\s*(?:/|a|per)?\s*w(?:ee)?k\b",
    "waiting_week": r"\b(?:ei\s+)?waiting (?:week|period)\b",
    "keep_pension": r"\b(?:keeps?|keeping|kept)\s+(?:the\s+|their\s+|my\s+|his\s+|her\s+)?pension\b"
                    r"|\bpension\s+(?:is\s+)?(?:kept|stays|continues|keeps coming)\b|\bpension[- ]aware\b",
    "half_year_spending": r"\bhalf-?\s?year(?:ly)?(?:\s+spending)?\b|\bs6\b",
    "bills_by_standing_order": r"\b(?:(?:paid\s+)?by\s+)?standing orders?\b|\bbills fallback\b",
}


def rule_intent(message: str) -> dict | None:
    """The offline parser: regexes over the message, combined in one intent, independent of word order.
    None when nothing in the message is a twist. Ambiguous income wording returns a clarify intent."""
    t = _Text(_rule_text(message))
    it = blank_intent()
    found = False
    income_kinds: list[tuple[str, float, float]] = []
    adding = bool(_ADD_WORDS.search(t.s))

    def income(kind: str, pct: float = 0.0, amount: float = 0.0) -> None:
        income_kinds.append((kind, pct, amount))

    if t.take(r"\bdouble whammy\b"):
        income("job_loss_ei", LAID_OFF_EI.income_multiplier)
        it["bills"] = {"kind": "increase_pct", "pct": DOUBLE_WHAMMY.bills_increase_pct}
        found = True
    if t.take(r"\b(?:reset|start over|start again|clear (?:it|everything|all)|from scratch|no shock|back to baseline)\b"):
        it["edit"]["kind"], found = "reset_all", True

    for m in t.take(r"\b(?:account|acct|customer|client)(?:\s+(?:id|number|no\.?))?\s*#?\s*(\d{4,6})\b|#(\d{4,6})\b"):
        it["account_id"], found = int(m.group(1) or m.group(2)), True

    for name, pat in _CHECKS_OFF.items():
        if t.take(pat):
            it["checks"][name], found = "off", True
    for name, pat in _CHECKS_ON.items():
        if t.take(pat):
            it["checks"][name], found = "on", True

    # lever resets ("remove the bills increase") before the levers themselves
    if t.take(rf"\b{_OFF}\s+(?:the\s+)?(?:household\s+)?(?:bills?|utilities)(?:\s+(?:increase|rise|hike|shock|change))?\b"):
        it["bills"]["kind"], found = "reset", True
    if t.take(rf"\b{_OFF}\s+(?:the\s+)?(?:one-off|one off|repair|furnace|emergency)(?:\s+(?:cost|repair|bill))?\b"):
        it["one_off"]["kind"], found = "reset", True
    if t.take(rf"\b{_OFF}\s+(?:the\s+)?(?:(?:extra|new|monthly)\s+(?:monthly\s+)?(?:costs?|payments?|expenses?)"
              rf"|rent(?:\s+(?:increase|rise|hike))?)\b"):
        it["monthly_cost"]["kind"], found = "reset", True
    if t.take(rf"\b{_OFF}\s+(?:the\s+)?(?:spending\s+)?cuts?\b"):
        it["spending_cut"]["kind"], found = "reset", True

    # target: "for 6 months", "survive 9 months", "a 3-month test"
    for m in t.take(r"\b(?:for|survive|survives|surviving|last|lasts|lasting|through|cover|covers|make it|change it to)"
                    r"\s+" + _NUM + r"\s*-?\s*months?\b(?!\s+(?:of|worth))"
                    r"|\b" + _NUM + r"\s*-?\s*months?\s+(?:test|target|goal|horizon|runway)\b"
                    r"|\b(?:target|goal|horizon|test)\s+(?:of\s+|is\s+|=\s*|to\s+)?" + _NUM + r"\s*months?\b"):
        it["target"] = {"kind": "set", "months": float(m.group(1) or m.group(2) or m.group(3))}
        found = True

    # partner / second earner before the plain job loss
    if t.take(r"\b(?:partner|spouse|wife|husband|second earner|other earner)(?:'s)?\b[^.;,]{0,30}?"
              r"\b(?:loses?|lost|losing|laid off|out of work|job loss)\b(?:\s+(?:his|her|their|the|a))?(?:\s+jobs?)?"
              r"|\b(?:lose|loses|losing|lost)\s+half\s+(?:of\s+)?(?:the\s+|their\s+|our\s+|my\s+)?(?:household\s+)?"
              r"income\b|\bhalf\s+(?:of\s+)?(?:the\s+)?(?:household\s+)?income\s+(?:is\s+)?(?:lost|gone)\b"):
        income("partner_job_loss")
    if t.take(r"\bno (?:job loss|lay-?off)\b|\bnot (?:a )?(?:job loss|laid off)\b"
              r"|\b(?:undo|remove|cancel|drop)\s+(?:the\s+)?(?:job loss|lay-?off|income (?:drop|cut|change|shock))\b"
              r"|\b(?:keeps?|kept)\s+(?:the\s+|their\s+|my\s+|his\s+|her\s+)?job\b|\bback to work\b"
              r"|\bincome (?:back to normal|restored|back)\b|\bfull income\b"):
        income("restore")
    ei_pct = None
    for m in t.take(r"\bei\s+(?:pays|paying|at|of|is|covers|gives)?\s*" + _PCT + r"(?!\s*-?\s*months?)"):
        ei_pct = _pct_of(m)
    job = t.take(r"\b(?:laid off|lay-?off|layoff|lost (?:\w+\s+)?jobs?|los(?:e|es|ing) (?:\w+\s+)?jobs?|job loss"
                 r"|jobless|unemployed|on ei|ei kicks in|goes on ei|go on ei|fired|let go|out of work"
                 r"|employment insurance)\b")
    if job or ei_pct is not None:
        income("job_loss_ei", ei_pct if ei_pct is not None else 0.0)
    for m in t.take(r"\b" + _PCT + r"\s+(?:pay|wage|hours?)\s+(?:cut|reduction)\b"):
        income("pay_cut_pct", _pct_of(m))
    for m in t.take(r"\b(?:pay cut|wage cut|pay reduction|reduced hours|hours? (?:\w+\s+){0,2}?(?:cut|reduced|drop)"
                    r"|cut (?:\w+\s+)?hours|fewer hours)\b(?:\s+(?:of|by|to))?(?:\s+" + _PCT + r")?"):
        to = re.search(r"\bto\s+\d", m.group(0))
        if m.group(1):
            income("keep_pct" if to else "pay_cut_pct", _pct_of(m))
        else:
            income("pay_cut_pct", 0.0)
    for m in t.take(r"\b" + _INCOME + r"\s+(?:\w+\s+){0,2}?(?:drops?|falls?|goes|go|cut|down|reduced|shrinks?"
                    r"|decreases?|is|comes in)\s+(?:down\s+)?to\s+(\$)?" + _NUM + r"\s*(%)?" + _MO):
        if m.group(3):
            income("keep_pct", coerce_pct(m.group(2) + "%"))
        elif not m.group(1) and float(m.group(2)) <= 1:
            income("keep_pct", coerce_pct(m.group(2)))
        else:
            income("to_amount", 0.0, float(m.group(2)))
    for m in t.take(r"\b" + _INCOME + r"\s+(?:\w+\s+){0,2}?(?:drops?|falls?|cut|down|decreases?|reduced|shrinks?"
                    r"|goes down|declines?|lower)\s+(?:by\s+)?" + _PCT + r"(?!\s*/mo)"
                    r"|\b" + _PCT + r"\s+(?:drop|fall|cut|decrease|reduction|less|lower|loss)\s+(?:in\s+|of\s+)?"
                    r"(?:\w+\s+)?" + _INCOME
                    + r"|\b(?:lose|loses|losing|lost)\s+" + _PCT + r"\s+of\s+(?:\w+\s+)?" + _INCOME):
        g = [x for x in m.groups()]
        num = next(i for i in (0, 2, 4) if g[i] is not None)
        income("drop_pct", coerce_pct(g[num] + ("%" if g[num + 1] else "")))
    for m in t.take(r"\b" + _INCOME + r"\s+(?:is\s+)?(?:kept|keeps?|stays|at|only)\s+(?:at\s+)?" + _PCT
                    + r"|\b(?:keeps?|kept|keeping|only)\s+" + _NUM + r"\s*(%)\s+of\s+(?:\w+\s+){0,2}?" + _INCOME
                    + r"|\b" + _NUM + r"\s*(%)\s+of\s+(?:\w+\s+){0,2}?" + _INCOME + r"\b"):
        g = m.groups()
        num = next(i for i in (0, 2, 4) if g[i] is not None)
        income("keep_pct", coerce_pct(g[num] + ("%" if g[num + 1] else "")))

    # rent and bills
    for m in t.take(r"\brent\s+(?:\w+\s+){0,2}?(?:goes|going|go|rises|rise|jumps|jump|increases|increase|up|climbs)"
                    r"\s+to\s+\$?" + _NUM + _MONEY_NOT_PCT + _MO):
        it["monthly_cost"] = {"kind": "rent_to", "amount": float(m.group(1))}
        found = True
    _BILLS = r"(?:household\s+)?(?:bills?|utilities|utility bills?|hydro|heating|rent)"
    _GAP = r"(?:[\w\u2591'-]+\s+){0,2}?"  # may step over a consumed span ("bills by standing order up 20%")
    _UP = r"(?:up|rise|rises|rising|go up|goes up|increase[sd]?|jumps?|climbs?|grows?|higher)"
    for m in t.take(r"\b(" + _BILLS + r")\s+" + _GAP + _UP + r"\s*(?:by\s+)?\+?\s*" + _NUM + r"\s*(%)"
                    r"|\b(" + _BILLS + r")\s*\+\s*" + _NUM + r"\s*(%)"
                    r"|\b" + _NUM + r"\s*(%)\s+(?:higher|more|increase in|rise in|jump in|hike in|up on)\s+(?:the\s+)?("
                    + _BILLS + r")"
                    r"|\b((?:household\s+)?(?:bills?|utilities))\s+" + _GAP + _UP + r"\s*(?:by\s+)?"
                    + _NUM + r"(?!\s*/mo|\d|\.\d|\s*%)"):
        g = m.groups()
        if g[0]:
            pct = coerce_pct(g[1] + "%")
        elif g[3]:
            pct = coerce_pct(g[4] + "%")
        elif g[6]:
            pct = coerce_pct(g[6] + "%")
        else:
            pct = coerce_pct(g[10])
        it["bills"] = {"kind": "increase_pct", "pct": pct}
        found = True
    monthly: list[float] = []
    for m in t.take(r"\brent\s+(?:\w+\s+){0,2}?(?:up|rises?|goes up|go up|increases?|jumps?|climbs?|higher)\s*"
                    r"(?:by\s+)?\+?\s*\$?" + _NUM + _MONEY_NOT_PCT + _MO
                    + r"|\brent\s*\+\s*\$?" + _NUM + _MONEY_NOT_PCT + _MO
                    + r"|\$" + _NUM + r"(?:/mo)?\s+(?:more\s+)?(?:in\s+|on\s+)?rent\b"):
        monthly.append(float(next(x for x in m.groups() if x is not None)))
    for m in t.take(r"(?:\b(?:new|extra|another|additional|plus|add(?:ed)?|more)\s+)?\$?" + _NUM
                    + r"/mo(?:\s+(?:more|extra))?"):
        monthly.append(float(m.group(1)))
    for m in t.take(r"\b(?:payment|insurance|daycare|day care|childcare|child care|subscription|tuition)\s+"
                    r"(?:\w+\s+){0,2}?(?:of\s+|costs?\s+|is\s+|at\s+|=\s*)?\$?" + _NUM + _MONEY_NOT_PCT
                    + r"|\$" + _NUM + r"\s+(?:\w+\s+)?(?:car payment|payment|insurance premium|daycare|childcare)\b"):
        monthly.append(float(next(x for x in m.groups() if x is not None)))
    if monthly:
        it["monthly_cost"] = {"kind": "add" if adding else "set", "amount": sum(monthly)}
        found = True

    # one-offs
    for m in t.take(r"\b(?:" + _NUM + r"|an?|one|another)\s+(?:full\s+|whole\s+|entire\s+)?months?(?:'s)?\s+"
                    r"(?:of|worth of)\s+(?:typical\s+|usual\s+|normal\s+|their\s+|my\s+)?"
                    r"(?:spending|expenses|costs|money out|outgoings)\b"
                    r"|\b(?:an?\s+)?(?:full\s+|whole\s+)?month's\s+(?:typical\s+)?spending\b"
                    r"|\b" + _NUM + r"\s*(?:x|×|times)\s*(?:typical\s+|usual\s+|monthly\s+)?(?:spending|s)\b"):
        n = float(m.group(1) or m.group(2) or 1.0)
        another = m.group(0).startswith("another")
        it["one_off"] = {"kind": "add_months_of_spending" if (adding or another) else "months_of_spending",
                         "amount": 0.0, "months": n}
        found = True
    _KW = (r"(?:repairs?|one-off|one off|emergency|furnace|boiler|roof|vet|dental|dentist|medical|transmission|fix"
           r"|expense|bill|cost|hit|replacement)")
    amounts = []
    for m in t.take(r"\$?" + _NUM + r"(?!\s*/mo|\d|\.\d|\s*%|\s*-?\s*months?)\s+(?:\w+\s+){0,2}?" + _KW + r"\b"
                    r"|\b(?:repairs?|one-off|one off|emergency|furnace|boiler|roof|vet bill|dental bill|medical bill"
                    r"|transmission|unexpected (?:bill|cost|expense)|surprise (?:bill|cost|expense))\b"
                    r"(?:\s+(?:\w+\s+){0,3}?)(?:of\s+|costs?\s+|for\s+|=\s*|is\s+|at\s+)?\$?" + _NUM
                    + r"(?!\s*(?:%|/mo|\d|\.\d|-?\s*months?|x\b|×))"):
        amounts.append(float(m.group(1) or m.group(2)))
    if amounts:
        if it["one_off"]["kind"] in ("months_of_spending", "add_months_of_spending"):
            return {**blank_intent(), "clarify": "I read two one-off costs there (a dollar amount and months of "
                                                 "spending). Which one did you mean?"}
        it["one_off"] = {"kind": "add_amount" if adding else "set_amount", "amount": sum(amounts), "months": 0.0}
        found = True
    if it["one_off"]["kind"] == "none" and t.take(r"\b(?:furnace|boiler|water heater)\b"):
        it["one_off"] = {"kind": "add_months_of_spending" if adding else "months_of_spending", "amount": 0.0,
                         "months": 1.0}
        found = True

    # spending cut
    for m in t.take(r"\bcut(?:s|ting)?\s+(?:back\s+)?(?:on\s+)?(?:[\w-]+\s+){0,2}?(?:spending|expenses|outgoings)\s+"
                    r"(?:by\s+)?" + _PCT
                    + r"|\b(?:non-fixed|discretionary|flexible|card and cash)\s+(?:spending\s+)?(?:cut|down|reduced"
                    r"|drops?|lower)\s+(?:by\s+)?" + _PCT
                    + r"|\bspend(?:s|ing)?\s+" + _NUM + r"\s*(%)\s+less\b"
                    + r"|\bcut\s+" + _NUM + r"\s*(%)\s+(?:of\s+)?(?:\w+\s+)?spending\b"):
        g = m.groups()
        num = next(i for i in (0, 2, 4, 6) if g[i] is not None)
        it["spending_cut"] = {"kind": "set_pct", "pct": coerce_pct(g[num] + ("%" if g[num + 1] else ""))}
        found = True

    # "make it 20% instead" changes the last percent lever
    if t.has(r"\b(?:instead|make it|change it to|set it to|actually|rather)\b"):
        for m in t.take(r"\b" + _NUM + r"\s*(%)"):
            it["edit"] = {"kind": "set_last_percent", "pct": coerce_pct(m.group(1) + "%")}
            found = True

    kinds = {k for k, _, _ in income_kinds}
    if len(kinds) > 1 or len({(k, p, a) for k, p, a in income_kinds}) > 1:
        return {**blank_intent(), "clarify": "I read more than one income change there. Which one did you mean? "
                                             "For example: “laid off, EI pays 55%” or “income drops 30%”."}
    if income_kinds:
        k, p, a = income_kinds[0]
        it["income"] = {"kind": k, "pct": p, "amount": a}
        found = True
    if not found:
        return None
    return canonicalize_intent(it)


# ------------------------------------------------------------------ CLI: warm and freeze

def rehearsed_phrasings() -> list[str]:
    phrases = list(HINT_CHIPS)
    for entry in _read_json(GOLDEN_FILE).get("twists", []):
        phrases += entry["phrases"]
    phrases += PRACTICE_PHRASINGS
    seen, out = set(), []
    for p in phrases:
        if normalize(p) not in seen:
            seen.add(normalize(p))
            out.append(p)
    return out


RATE_LIMIT_WAITS = (15.0, 30.0, 60.0)


def warm(phrases: list[str] | None = None, adapter=None, out=sys.stdout, sleep=None) -> dict[str, int]:
    """Run each phrasing through the LLM once (current = no shock), so later runs are cache hits."""
    import time

    from . import shock_llm
    sleep = time.sleep if sleep is None else sleep
    phrases = rehearsed_phrasings() if phrases is None else phrases
    counts = {"cached": 0, "new": 0, "failed": 0}
    current = Shock()
    for p in phrases:
        norm = normalize(p)
        key = cache_key(norm, current, shock_llm.model_id(), shock_llm.PROMPT_VERSION)
        if cache_get(key) is not None:
            counts["cached"] += 1
            continue
        intent, status = shock_llm.llm_intent(norm, current, adapter=adapter)
        for wait in RATE_LIMIT_WAITS:  # a free-tier key allows a burst of calls a minute: wait it out, then retry
            if intent is not None or "rate_limit" not in status:
                break
            print(f"  rate-limited; waiting {wait:g}s", file=out)
            sleep(wait)
            intent, status = shock_llm.llm_intent(norm, current, adapter=adapter)
        if intent is None:
            counts["failed"] += 1
            print(f"  failed: {p!r} ({status})", file=out)
        else:
            counts["new"] += 1
    print(f"warm: {counts['cached']} already cached, {counts['new']} new, {counts['failed']} failed", file=out)
    return counts


def freeze(phrases: list[str] | None = None, everything: bool = False, out=sys.stdout) -> int:
    """Copy local-cache entries for the given phrasings (default: the hint chips and golden phrases) into the
    committed frozen cache. Returns how many entries the frozen file holds afterwards."""
    if phrases is None:
        phrases = list(HINT_CHIPS) + [p for e in _read_json(GOLDEN_FILE).get("twists", []) for p in e["phrases"]]
    wanted = {normalize(p) for p in phrases}
    local = _entries(LOCAL_CACHE)
    frozen = _entries(FROZEN_CACHE)
    added = 0
    for key, entry in sorted(local.items()):
        if everything or entry.get("message") in wanted:
            if key not in frozen:
                added += 1
            frozen[key] = entry
    _write_entries(FROZEN_CACHE, frozen, "Rehearsed LLM shock intents (read-only at runtime). Written by "
                                         "`python -m resilience.shock_parser freeze`.")
    print(f"freeze: {added} added, {len(frozen)} in {FROZEN_CACHE.name}", file=out)
    return len(frozen)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m resilience.shock_parser",
                                 description="Warm the LLM shock cache before a demo, then freeze it.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("warm", help="run the rehearsed phrasings through the LLM once")
    w.add_argument("phrases", nargs="*", help="phrasings to warm (default: hint chips, golden and practice phrasings)")
    f = sub.add_parser("freeze", help="copy chosen local-cache entries into resilience/llm_cache_frozen.json")
    f.add_argument("phrases", nargs="*", help="phrasings to freeze (default: hint chips and golden phrases)")
    f.add_argument("--all", action="store_true", help="freeze every local-cache entry")
    args = ap.parse_args(argv)
    if args.cmd == "warm":
        from . import shock_llm
        if shock_llm.provider_name() == "off":
            print("warm: no LLM configured (set GEMINI_API_KEY, or SNOWFLAKE_PAT with SHOCK_LLM=cortex). "
                  "Nothing was sent.")
            return 1
        counts = warm(args.phrases or None)
        return 0 if counts["failed"] == 0 else 2
    freeze(args.phrases or None, everything=args.all)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
