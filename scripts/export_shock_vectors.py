"""Export the chat shock parser's golden table and expected outputs for the TypeScript port in web/.

    .venv/bin/python scripts/export_shock_vectors.py

Writes
    web/src/engine/goldenTwists.json     a byte-for-byte copy of resilience/golden_twists.json
    web/test/shock_vectors.json          outputs of the PYTHON parser (golden table + offline rules, the backends the
                                         keyless web app has) that web/test/shock.test.ts must reproduce exactly

tests/test_shock_parser.py checks that both files are up to date.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from resilience import shock_parser as sp  # noqa: E402
from resilience.core import (  # noqa: E402
    DOUBLE_WHAMMY,
    EI_2026_MAX_MONTHLY,
    FURNACE,
    LAID_OFF_EI,
    Shock,
    build_metrics,
)

WEB = ROOT / "web"
GOLDEN_COPY = WEB / "src" / "engine" / "goldenTwists.json"
VECTORS = WEB / "test" / "shock_vectors.json"

ACCOUNTS = [20331, 98952, 20303, 26939, 20578, 77743, 32078]   # big I, pension, bills by SO, I=0, S=0, default, overdrawn
CURRENTS = {
    "none": Shock(),
    "ei": LAID_OFF_EI.with_(name="Laid off: EI 55%"),
    "double_cap": DOUBLE_WHAMMY.with_(income_cap_monthly=EI_2026_MAX_MONTHLY, one_off_cost=900.0,
                                      flexible_cut_pct=0.1),
    "furnace": FURNACE,
}
EXTRA_MESSAGES = [
    "", "   ", "hello there", "what's the weather like?", "!!!", "account 12345", "account 12345, laid off",
    "laid off and income drops 30%", "reduced hours", "their hours get cut in half from next month",
    "baby on the way, about $900 a month more", "make it 20% instead", "make it 9 months", "add a $2,000 repair",
    "another month of spending", "remove the bills increase", "no job loss", "undo the job loss",
    "remove the one-off", "drop the extra costs", "no spending cut", "without the cap", "no waiting week",
    "rent goes to $1,500 a month", "rent goes to $900 a month", "income drops to $9,000 a month",
    "income drops to $500 a month", "income drops to 60%", "hours cut to 60%", "bills up 150%",
    "cut spending 200%", "one-off of 30 months of spending", "survive 40 months", "for 4.5 months",
    "a $2,500 repair and 2 months of spending", "EI pays 60% and bills up twelve percent",
    "income kept 0.7", "bills up 0.15", "1% income drop", "income cut 1%", "rent +$250", "rent up 50%",
    "$300 more in rent", "insurance of $120", "laid off, keep pension, half-year spending, waiting week",
    "bills by standing order, bills up 20%", "spend 10% less", "cut 30% of spending", "a 2.5k car repair",
    "back to work", "full income", "jobless", "double whammy", "Furnace dies: 1× spending",
    "2x spending one-off", "half a month of spending", "emergency repair $1,750.50",
]
CONVERSATIONS = [
    ["Job loss on EI and bills up 15%", "make it 20% instead", "no job loss", "make it 25% instead", "reset"],
    ["income drops 30%", "make it 20% instead", "with the 2026 EI cap", "laid off", "with the 2026 EI cap",
     "make it 60% instead"],
    ["Income drops to $2,000 a month", "make it 20% instead", "cut spending 25%", "make it 10% instead"],
    ["a $2,500 repair", "add a $2,000 repair", "Furnace dies", "add a $1,000 repair", "remove the repair"],
    ["account 98952", "laid off, keep pension", "account 20331", "must last 9 months", "start over"],
    ["Rent up $300 a month", "baby on the way, $900 a month more", "add $100 a month", "drop the extra costs"],
    ["partner loses their job", "make it 30% instead", "bills by standing order", "account 20303",
     "bills by standing order, bills up 20%"],
]


def shock_js(s: Shock) -> dict:
    return {"incomeMultiplier": s.income_multiplier, "incomeCapMonthly": s.income_cap_monthly,
            "billsIncreasePct": s.bills_increase_pct, "extraMonthlyCost": s.extra_monthly_cost,
            "oneOffCost": s.one_off_cost, "oneOffMultipleOfS": s.one_off_multiple_of_S,
            "flexibleCutPct": s.flexible_cut_pct, "waitingWeek": bool(s.waiting_week),
            "pensionAware": bool(s.pension_aware), "spendingBasis": s.spending_basis,
            "billsFallback": bool(s.bills_fallback), "jobLoss": bool(s.job_loss), "name": s.name}


def result_js(res: sp.ParseResult, row) -> dict:
    return {
        "shock": shock_js(res.shock), "target": res.target, "accountId": res.account_id, "source": res.source,
        "understoodAs": res.understood_as, "resolved": res.resolved, "warnings": res.warnings,
        "clarify": res.clarify, "pctLever": res.pct_lever, "intent": res.intent,
        "hints": None if res.clarify else sp.follow_up_hints(res, row),
        "state": None if res.clarify else sp.shock_to_state(res.shock, res.target),
    }


def build(m=None) -> dict:
    """The vectors, as a JSON-ready dict (tests/test_shock_parser.py compares it with the committed file)."""
    m = build_metrics() if m is None else m
    offline = [sp.GoldenParser(), sp.RuleParser()]

    golden_phrases = [p for e in json.loads(sp.GOLDEN_FILE.read_text())["twists"] for p in e["phrases"]]
    messages = list(dict.fromkeys([*sp.HINT_CHIPS, *golden_phrases, *sp.PRACTICE_PHRASINGS, *EXTRA_MESSAGES]))

    def run(msg, acct, current, target, lever):
        return sp.parse_shock(msg, m.loc[acct], current, target, metrics=m, last_pct_lever=lever, backends=offline)

    parse = []
    for msg in messages:
        for acct in ACCOUNTS:
            for cname, current in CURRENTS.items():
                if cname != "none" and acct not in (20331, 98952):
                    continue
                lever = {"none": None, "ei": "income_ei", "double_cap": "bills", "furnace": None}[cname]
                res = run(msg, acct, current, 6, lever)
                row = m.loc[res.account_id or acct]
                parse.append({"msg": msg, "acct": acct, "current": cname, "target": 6, "lever": lever,
                              "result": result_js(res, row)})

    convos = []
    for msgs in CONVERSATIONS:
        for acct in (20331, 98952, 20303):
            current, target, lever, a, steps = Shock(), 6, None, acct, []
            for msg in msgs:
                res = run(msg, a, current, target, lever)
                if res.clarify is None:
                    current, target, lever = res.shock, res.target, res.pct_lever
                    a = res.account_id or a
                steps.append(result_js(res, m.loc[a]))
            convos.append({"acct": acct, "msgs": msgs, "steps": steps})

    describe = []
    shocks = [*CURRENTS.values(), Shock(income_multiplier=0.361011), Shock(extra_monthly_cost=400.0),
              Shock(bills_increase_pct=0.125, bills_fallback=True), Shock(flexible_cut_pct=0.25, one_off_cost=2500.0),
              LAID_OFF_EI.with_(pension_aware=True, waiting_week=True, spending_basis="S6"),
              Shock(income_multiplier=0.7), Shock(one_off_multiple_of_S=2.5)]
    for s in shocks:
        describe.append({"shock": shock_js(s), "acct": None, "target": None, "text": sp.describe_shock(s)})
        for acct in ACCOUNTS:
            describe.append({"shock": shock_js(s), "acct": acct, "target": 6,
                             "text": sp.describe_shock(s, m.loc[acct], 6)})

    pct_inputs = ["15", "15%", "fifteen percent", "0.15", 15, 0.15, "twenty-five percent", "1%", "1", "100%",
                  "12.5%", "150%", "55 per cent", "", "abc", "%", ".5", "-5%", 0, 1, 250]
    coerce = []
    for x in pct_inputs:
        try:
            coerce.append([x, sp.coerce_pct(x)])
        except ValueError:
            coerce.append([x, None])
    money_inputs = ["$2,500", "2.5k", "$2500/mo", "2500", "$300 a month", "2 thousand", 450, "abc", "$"]
    money = []
    for x in money_inputs:
        try:
            money.append([x, sp.parse_money(x)])
        except ValueError:
            money.append([x, None])

    out = {
        "meta": {"accounts": ACCOUNTS, "messages": len(messages), "parse": len(parse), "conversations": len(convos)},
        "messages": messages,
        "normalize": [[msg, sp.normalize(msg)] for msg in messages],
        "rules": [[msg, sp.rule_intent(msg)] for msg in messages],
        "coerce_pct": coerce,
        "parse_money": money,
        "parse": parse,
        "conversations": convos,
        "describe": describe,
        "hint_chips": list(sp.HINT_CHIPS),
        "suggestions": list(sp.SUGGESTIONS),
    }
    return out


def dumps(out: dict) -> str:
    return json.dumps(out, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n"


def main() -> None:
    GOLDEN_COPY.write_bytes(sp.GOLDEN_FILE.read_bytes())
    out = build()
    VECTORS.write_text(dumps(out), encoding="utf-8")
    print(f"{GOLDEN_COPY.relative_to(ROOT)} copied; {VECTORS.relative_to(ROOT)}: {out['meta']}, "
          f"{VECTORS.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
