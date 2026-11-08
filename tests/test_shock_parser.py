"""The chat's shock parser: golden phrases, the offline rules, account-relative amounts, edits, clamps and guards.

Every test runs offline: the LLM backend is never in the backend list here (tests/test_shock_llm.py covers it).
"""
import json

import pytest

from resilience import shock_parser as sp
from resilience.core import DATA_DIR, DOUBLE_WHAMMY, EI_2026_MAX_MONTHLY, FURNACE, LAID_OFF_EI, Shock, build_metrics

needs_data = pytest.mark.skipif(not (DATA_DIR / "monthly_summary.csv").exists(), reason="track data not present")
OFFLINE = [sp.GoldenParser(), sp.RuleParser()]
RULES = [sp.RuleParser()]


@pytest.fixture(scope="module")
def m():
    return build_metrics()


def parse(m, msg, acct=20331, current=Shock(), target=6, backends=OFFLINE, **kw):
    return sp.parse_shock(msg, m.loc[acct], current, target, metrics=m, backends=backends, **kw)


def fields(shock: Shock) -> dict:
    """The non-default fields of a Shock (the golden table's 'expect' format)."""
    base = sp.shock_key(Shock())
    return {k: v for k, v in sp.shock_key(shock).items() if v != base[k]}


# ------------------------------------------------------------------ numbers

@pytest.mark.parametrize("text, want", [
    ("15", 0.15), ("15%", 0.15), ("fifteen percent", 0.15), ("0.15", 0.15), (15, 0.15), (0.15, 0.15),
    ("twenty-five percent", 0.25), ("1%", 0.01), ("1", 1.0), ("100%", 1.0), ("12.5%", 0.125), ("150%", 1.5),
    ("55 per cent", 0.55),
])
def test_percent_coercion_is_one_function(text, want):
    assert sp.coerce_pct(text) == pytest.approx(want)


@pytest.mark.parametrize("bad", ["", "abc", "%", None, True])
def test_percent_coercion_rejects_non_numbers(bad):
    with pytest.raises(ValueError):
        sp.coerce_pct(bad)


@pytest.mark.parametrize("text, want", [("$2,500", 2500), ("2.5k", 2500), ("$2500/mo", 2500), ("2500", 2500),
                                        ("$300 a month", 300), ("2 thousand", 2000), (450, 450)])
def test_money_parsing(text, want):
    assert sp.parse_money(text) == want


def test_normalize_keeps_numbers_whole():
    assert sp.normalize("  Rent UP $2,500.50 a month!! ") == "rent up 2500.50 a month"
    assert sp.normalize("2.5k") != sp.normalize("25k") and sp.normalize("1%") != sp.normalize("1")
    assert sp.normalize("Laid off: EI 55%") == sp.normalize("laid   off ei 55%")


# ------------------------------------------------------------------ golden table

def _golden_entries():
    return json.loads(sp.GOLDEN_FILE.read_text())["twists"]


def test_golden_table_has_the_readme_twists_the_chips_and_20_paraphrases():
    keys = sp.golden_table()
    for shock in (LAID_OFF_EI, FURNACE, DOUBLE_WHAMMY):
        assert sp.normalize(shock.name) in keys, shock.name
    for chip in sp.HINT_CHIPS:
        assert sp.normalize(chip) in keys, chip
    assert len(keys) >= 3 + len(sp.HINT_CHIPS) + 20


@needs_data
@pytest.mark.parametrize("entry", [e for e in _golden_entries() if "expect" in e], ids=lambda e: e["name"])
def test_every_golden_phrase_gives_its_exact_shock(m, entry):
    want = dict(entry["expect"])
    target = want.pop("target", 6)
    for phrase in entry["phrases"]:
        res = parse(m, phrase, backends=[sp.GoldenParser()])
        assert res.source == "golden" and res.clarify is None, phrase
        assert fields(res.shock) == want and res.target == target, phrase


@needs_data
def test_readme_twists_by_golden_phrase_are_the_core_presets(m):
    for shock in (LAID_OFF_EI, FURNACE, DOUBLE_WHAMMY):
        res = parse(m, shock.name, backends=[sp.GoldenParser()])
        assert sp.same_shock(res.shock, shock)


@needs_data
def test_rules_alone_read_every_golden_phrase_the_same_way(m):
    for entry in _golden_entries():
        for phrase in entry["phrases"]:
            g = parse(m, phrase, backends=[sp.GoldenParser()])
            r = parse(m, phrase, backends=RULES)
            assert r.source == "rules" and r.clarify is None, phrase
            assert sp.same_shock(g.shock, r.shock) and g.target == r.target, (phrase, r.understood_as)


# ------------------------------------------------------------------ 30 unseen paraphrases, rules only

EI = dict(income_multiplier=0.55, job_loss=True)
UNSEEN = {  # phrase -> expected non-default Shock fields (account 20331 for the dollar ones), target, account
    "pt got laid off, ei kicks in, rent +15%": ({**EI, "bills_increase_pct": 0.15}, 6, None),
    "income down to 2k/mo and a 3k car repair": ({"income_multiplier": round(2000 / 21048.42, 6), "one_off_cost": 3000.0}, 6, None),
    "they lost their job, EI at 55 percent": (EI, 6, None),
    "unemployed on EI and utilities up 10%": ({**EI, "bills_increase_pct": 0.1}, 6, None),
    "income falls by 30%": ({"income_multiplier": 0.7}, 6, None),
    "income cut 0.25": ({"income_multiplier": 0.75}, 6, None),
    "pay cut 20% for 6 months": ({"income_multiplier": 0.8}, 6, None),
    "reduced hours 40%": ({"income_multiplier": 0.6}, 6, None),
    "income kept at 70%": ({"income_multiplier": 0.7}, 6, None),
    "only 60% of income coming in": ({"income_multiplier": 0.6}, 6, None),
    "partner loses their job": ({"income_multiplier": 0.5}, 6, None),
    "lose half the household income": ({"income_multiplier": 0.5}, 6, None),
    "rent goes to $1,800 a month": ({}, 6, None),  # 20331's bills are already $2,722: no new cost (warned)
    "rent up by $450/mo": ({"extra_monthly_cost": 450.0}, 6, None),
    "new car payment of $450": ({"extra_monthly_cost": 450.0}, 6, None),
    "baby on the way, $900 a month more": ({"extra_monthly_cost": 900.0}, 6, None),
    "a $2,500 furnace repair": ({"one_off_cost": 2500.0}, 6, None),
    "emergency vet bill of $1,200": ({"one_off_cost": 1200.0}, 6, None),
    "two months of spending one-off": ({"one_off_multiple_of_S": 2.0}, 6, None),
    "cut back on spending by 25%": ({"flexible_cut_pct": 0.25}, 6, None),
    "discretionary spending down fifteen percent": ({"flexible_cut_pct": 0.15}, 6, None),
    "survive 12 months": ({}, 12, None),
    "a 3-month test": ({}, 3, None),
    "laid off with the 2026 EI cap and waiting week": ({**EI, "income_cap_monthly": EI_2026_MAX_MONTHLY,
                                                        "waiting_week": True}, 6, None),
    "job loss on EI, keep pension": (EI, 6, None),  # 20331 has no pension: turned off with a warning
    "on EI, half-year spending": ({**EI, "spending_basis": "S6"}, 6, None),
    "bills by standing order up 20%": ({"bills_increase_pct": 0.2}, 6, None),  # H > 0 here: fallback off
    "account 20143, laid off": (EI, 6, 20143),
    "customer #98952 loses job, keep the pension": ({**EI, "pension_aware": True}, 6, 98952),
    "laid off and rent goes up $200 a month": ({**EI, "extra_monthly_cost": 200.0}, 6, None),
}


def test_the_unseen_paraphrases_are_the_practice_list_and_not_golden():
    assert set(UNSEEN) == set(sp.PRACTICE_PHRASINGS) and len(UNSEEN) == 30
    assert not {sp.normalize(p) for p in UNSEEN} & set(sp.golden_table())


@needs_data
@pytest.mark.parametrize("phrase", list(UNSEEN))
def test_rules_read_unseen_paraphrases(m, phrase):
    want, target, acct = UNSEEN[phrase]
    res = parse(m, phrase, backends=RULES)
    assert res.source == "rules" and res.clarify is None, res.clarify
    assert fields(res.shock) == {k: v for k, v in want.items()}, res.understood_as
    assert res.target == target and res.account_id == acct


@needs_data
def test_rules_are_order_independent(m):
    a = parse(m, "bills up 15% and laid off and must last 9 months", backends=RULES)
    b = parse(m, "must last 9 months, laid off, bills up 15%", backends=RULES)
    assert sp.same_shock(a.shock, b.shock) and a.target == b.target == 9
    assert fields(a.shock) == {**EI, "bills_increase_pct": 0.15}


@needs_data
def test_llm_only_wording_the_rules_still_try(m):
    res = parse(m, "their hours get cut in half from next month", backends=RULES)
    assert fields(res.shock) == {"income_multiplier": 0.5}
    res = parse(m, "baby on the way, about $900 a month more", backends=RULES)
    assert fields(res.shock) == {"extra_monthly_cost": 900.0}


# ------------------------------------------------------------------ account-relative amounts on real accounts

@needs_data
def test_income_to_amount_is_n_over_i(m):
    res = parse(m, "Income drops to $2,000 a month", acct=98952)
    I = float(m.loc[98952, "I"])
    assert res.shock.income_multiplier == round(2000 / I, 6) and not res.shock.job_loss
    assert res.understood_as.startswith("Income drops to $2,000/mo (51.1% of your usual $3,915)")
    assert res.resolved == ["income $2,000/mo ÷ usual $3,915/mo = 51.1% of money in"]


@needs_data
def test_income_to_more_than_usual_is_clamped_with_a_warning(m):
    res = parse(m, "income drops to $9,000 a month", acct=98952)
    assert res.shock.income_multiplier == 1.0 and any("more than the usual" in w for w in res.warnings)


@needs_data
def test_income_to_amount_with_zero_income_is_left_unchanged_with_a_warning(m):
    res = parse(m, "income drops to $500 a month", acct=26939, current=LAID_OFF_EI)
    assert sp.same_shock(res.shock, LAID_OFF_EI) and any("Usual money in is $0" in w for w in res.warnings)


@needs_data
def test_rent_goes_to_subtracts_household_bills(m):
    res = parse(m, "rent goes to $1,500 a month", acct=98952)  # H = $1,244
    assert res.shock.extra_monthly_cost == round(1500 - float(m.loc[98952, "H"]), 2)
    assert res.resolved and res.resolved[0].startswith("rent $1,500/mo − household bills now $1,244/mo")


@needs_data
def test_rent_goes_to_with_no_bills_counts_it_all_and_warns(m):
    assert float(m.loc[20303, "H"]) == 0
    res = parse(m, "rent goes to $1,500 a month", acct=20303)
    assert res.shock.extra_monthly_cost == 1500.0 and any("H = $0" in w for w in res.warnings)


@needs_data
def test_a_month_of_spending_plus_dollars_becomes_one_amount(m):
    res = parse(m, "add a $2,000 repair", acct=98952, current=FURNACE)
    S = float(m.loc[98952, "S"])
    assert res.shock.one_off_cost == round(2000 + S, 2) and res.shock.one_off_multiple_of_S == 0
    assert any("one-off $2,000 + 1× spending" in line for line in res.resolved)


@needs_data
def test_understood_as_uses_the_customers_dollars(m):
    res = parse(m, "Job loss on EI and bills up 15%", acct=98952, target=6)
    assert res.understood_as == ("Laid off, EI pays 55%: $2,153/mo of your usual $3,915 · household bills +15% "
                                 "(+$187/mo on $1,244) · must last 6 months")


# ------------------------------------------------------------------ edits relative to current

@needs_data
def test_make_it_x_instead_changes_the_last_percent_lever(m):
    first = parse(m, "bills up 15%", current=LAID_OFF_EI)
    assert first.pct_lever == "bills"
    second = parse(m, "make it 20% instead", current=first.shock, last_pct_lever=first.pct_lever)
    assert second.shock.bills_increase_pct == 0.2 and second.shock.income_multiplier == 0.55
    drop = parse(m, "income drops 30%")
    again = parse(m, "make it 20% instead", current=drop.shock, last_pct_lever=drop.pct_lever)
    assert again.shock.income_multiplier == 0.8


@needs_data
def test_make_it_x_instead_with_no_percent_lever_asks(m):
    dollars = parse(m, "Income drops to $2,000 a month", current=LAID_OFF_EI, last_pct_lever="income_ei")
    res = parse(m, "make it 20% instead", current=dollars.shock, last_pct_lever=dollars.pct_lever)
    assert res.clarify and "Which lever" in res.clarify and res.shock == dollars.shock


@needs_data
def test_add_a_repair_adds_to_the_one_off(m):
    first = parse(m, "a $2,500 repair")
    res = parse(m, "add a $2,000 repair", current=first.shock)
    assert res.shock.one_off_cost == 4500.0


@needs_data
def test_remove_the_bills_increase_and_no_job_loss(m):
    res = parse(m, "remove the bills increase", current=DOUBLE_WHAMMY)
    assert sp.same_shock(res.shock, LAID_OFF_EI)
    res = parse(m, "no job loss", current=DOUBLE_WHAMMY)
    assert fields(res.shock) == {"bills_increase_pct": 0.15}


@needs_data
def test_reset_goes_back_to_no_shock_and_six_months(m):
    current = DOUBLE_WHAMMY.with_(income_cap_monthly=EI_2026_MAX_MONTHLY, one_off_cost=900.0)
    for phrase in ("reset", "start over"):
        res = parse(m, phrase, current=current, target=11)
        assert sp.same_shock(res.shock, Shock()) and res.target == 6


@needs_data
def test_unmentioned_levers_keep_their_current_values(m):
    current = DOUBLE_WHAMMY.with_(one_off_cost=1200.0, flexible_cut_pct=0.1)
    res = parse(m, "must last 9 months", current=current)
    assert sp.same_shock(res.shock, current) and res.target == 9


# ------------------------------------------------------------------ clamps, guards and clarify

@needs_data
@pytest.mark.parametrize("intent, field, want", [
    ({"bills": {"kind": "increase_pct", "pct": 150}}, "bills_increase_pct", 1.0),      # 150 -> 150% -> 100%
    ({"spending_cut": {"kind": "set_pct", "pct": "200%"}}, "flexible_cut_pct", 1.0),
    ({"income": {"kind": "keep_pct", "pct": 120}}, "income_multiplier", 1.0),
    ({"monthly_cost": {"kind": "set", "amount": -50}}, "extra_monthly_cost", 0.0),
    ({"monthly_cost": {"kind": "set", "amount": 5_000_000}}, "extra_monthly_cost", 1_000_000.0),
    ({"one_off": {"kind": "set_amount", "amount": 2_000_000}}, "one_off_cost", 1_000_000.0),
    ({"one_off": {"kind": "months_of_spending", "months": 30}}, "one_off_multiple_of_S", 12.0),
])
def test_every_clamp_warns(m, intent, field, want):
    res = sp.validate_and_build(intent, m.loc[20331], Shock(), 6, metrics=m)
    assert getattr(res.shock, field) == want and any("out of range" in w for w in res.warnings)


@needs_data
@pytest.mark.parametrize("months, want", [(0, 1), (40, 24)])
def test_target_clamps(m, months, want):
    res = sp.validate_and_build({"target": {"kind": "set", "months": months}}, m.loc[20331], Shock(), 6, metrics=m)
    assert res.target == want and res.warnings


@needs_data
def test_ei_checks_need_a_job_loss(m):
    res = parse(m, "pay cut 20% with the 2026 EI cap and waiting week")
    assert res.shock.income_cap_monthly is None and not res.shock.waiting_week
    assert any("EI cap needs a job loss" in w for w in res.warnings)
    assert any("waiting week needs a job loss" in w for w in res.warnings)
    capped = LAID_OFF_EI.with_(income_cap_monthly=EI_2026_MAX_MONTHLY)
    res = parse(m, "no job loss", current=capped)
    assert res.shock.income_cap_monthly is None and any("EI cap" in w for w in res.warnings)


@needs_data
def test_keep_pension_needs_a_pension(m):
    res = parse(m, "laid off, keep pension", acct=20331)
    assert not res.shock.pension_aware and any("no pension income" in w for w in res.warnings)
    res = parse(m, "laid off, keep pension", acct=98952)
    assert res.shock.pension_aware and not res.warnings


@needs_data
def test_bills_by_standing_order_needs_no_h_and_bill_standing_orders(m):
    res = parse(m, "bills by standing order, bills up 20%", acct=20303)   # H = 0, H_SO > 0
    assert res.shock.bills_fallback and res.shock.bills_increase_pct == 0.2
    res = parse(m, "bills by standing order", acct=20331)
    assert not res.shock.bills_fallback and res.warnings


@needs_data
def test_unknown_account_asks_and_changes_nothing(m):
    res = parse(m, "account 12345, laid off", current=FURNACE, target=8)
    assert res.clarify and "12345" in res.clarify
    assert res.shock == FURNACE and res.target == 8 and res.account_id is None


@needs_data
@pytest.mark.parametrize("msg", ["hello there", "what is this?", "", "   ", "!!!", "the weather is nice"])
def test_nothing_parsed_asks_with_suggestions_and_changes_nothing(m, msg):
    res = parse(m, msg, current=DOUBLE_WHAMMY, target=7)
    assert res.clarify and res.shock == DOUBLE_WHAMMY and res.target == 7
    assert sum(s in res.clarify for s in sp.SUGGESTIONS) >= 2


@needs_data
def test_two_income_changes_ask_instead_of_guessing(m):
    res = parse(m, "laid off and income drops 30%", backends=RULES)
    assert res.clarify and "more than one income change" in res.clarify


@needs_data
def test_a_pay_cut_with_no_size_asks(m):
    res = parse(m, "reduced hours", backends=RULES)
    assert res.clarify and "How big" in res.clarify


# ------------------------------------------------------------------ state round trip, labels, determinism

@needs_data
def test_shock_and_state_round_trip(m):
    row = m.loc[98952]
    for msg in ["Income drops to $2,000 a month", "laid off, keep pension, half-year spending", "a $2,500 repair",
                "Furnace dies", "cut spending 25% and bills up 12.5%", "reset"]:
        res = parse(m, msg, acct=98952)
        state = sp.shock_to_state(res.shock, res.target)
        assert set(state) == set(sp.STATE_KEYS)
        assert sp.shock_from_state(state, row) == res.shock, msg


def test_twist_label_and_understood_as_are_one_function():
    assert sp.twist_label(LAID_OFF_EI) == "Laid off: EI 55%"
    assert sp.twist_label(Shock(extra_monthly_cost=400.0)) == "+$400/mo"
    assert sp.twist_label(Shock()) == "No shock"


@needs_data
def test_ten_identical_calls_give_identical_results(m):
    for msg in ["Job loss on EI and bills up 15%", "income down to 2k/mo and a 3k car repair", "nonsense words"]:
        results = [parse(m, msg, acct=98952, current=LAID_OFF_EI) for _ in range(10)]
        assert all(r == results[0] for r in results)
        assert len({repr(r) for r in results}) == 1


@needs_data
def test_backends_are_called_in_order_and_a_third_backend_is_validated(m):
    calls = []

    class Fake:
        def __init__(self, source, intent):
            self.source, self.intent = source, intent

        def parse(self, message, norm, current):
            calls.append(self.source)
            return self.intent

    backends = [Fake("golden", None), Fake("cache", None),
                Fake("llm", {"bills": {"kind": "increase_pct", "pct": 3.0}}), Fake("rules", None)]
    res = sp.parse_shock("something new", m.loc[20331], Shock(), 6, metrics=m, backends=backends)
    assert calls == ["golden", "cache", "llm"]
    assert res.source == "llm" and res.shock.bills_increase_pct == 0.03  # 3.0 read as 3%, through coerce_pct

    calls.clear()
    backends[2] = Fake("llm", {"bills": {"kind": "not-a-kind"}})  # unreadable: skipped, never trusted
    res = sp.parse_shock("something new", m.loc[20331], Shock(), 6, metrics=m, backends=backends)
    assert calls == ["golden", "cache", "llm", "rules"] and res.clarify


@needs_data
def test_follow_up_hints_fit_the_new_state(m):
    res = parse(m, "Laid off, EI pays 55%", acct=20331)
    hints = sp.follow_up_hints(res, m.loc[20331])
    assert hints == ["Try “with the 2026 EI cap”", "Try “cut spending 25%”"]
    assert 1 <= len(sp.follow_up_hints(parse(m, "reset"), m.loc[20331])) <= 2


def test_rehearsed_phrasings_cover_chips_golden_and_practice():
    phrases = {sp.normalize(p) for p in sp.rehearsed_phrasings()}
    assert {sp.normalize(c) for c in sp.HINT_CHIPS} <= phrases
    assert set(sp.golden_table()) <= phrases
    assert {sp.normalize(p) for p in sp.PRACTICE_PHRASINGS} <= phrases
