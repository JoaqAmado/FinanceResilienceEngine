"""check_view: every number the Live twist tab shows agrees with every other number and with the raw data.

Clean views must give no issues, on the rehearsal accounts, every edge-case account and 200 random accounts, for
15 shocks; and a deliberately corrupted value must be caught.
"""
import dataclasses

import numpy as np
import pytest

from resilience import shock_parser as sp
from resilience.consistency import check_view, raw_account
from resilience.core import DATA_DIR, build_metrics
from resilience.view import build_view

needs_data = pytest.mark.skipif(not (DATA_DIR / "monthly_summary.csv").exists(), reason="track data not present")

REHEARSAL = [20331, 20143, 88269, 98952, 77743]
EDGE = [32078, 20578, 26939, 20303, 20866, 21903,        # overdrawn, S=0, I=0, bills by SO, stale, minor
        75489, 91609, 99477, 55819, 36427, 72845, 20111]  # loan trouble, stale, tiny spending, H=0
SHOCKS = [  # chat messages, read by the offline parser: README twists, combinations, dollar shocks, each check
    "Laid off: EI at 55% of usual income",
    "Furnace dies: repair = 1 month of typical spending",
    "Job loss (EI 55%) + household bills +15%",
    "job loss, bills up 15% and two months of spending one-off",
    "partner loses their job and cut spending 25%",
    "pay cut 30% for 9 months",
    "Income drops to $2,000 a month",
    "rent goes to $1,800 a month",
    "laid off and a $2,500 repair",
    "laid off with the 2026 EI cap",
    "laid off, waiting week, 2026 EI cap",
    "job loss on EI, keep pension",
    "on EI, half-year spending",
    "bills by standing order, bills up 20%",
    "rent up $300 a month and must last 12 months",
]


@pytest.fixture(scope="module")
def m():
    return build_metrics()


@pytest.fixture(scope="module")
def accounts(m):
    rng = np.random.default_rng(20261108)
    random = [int(a) for a in rng.choice(m.index.to_numpy(), 200, replace=False)]
    return list(dict.fromkeys(REHEARSAL + EDGE + random))


def view_for(m, acct, msg):
    row = m.loc[acct]
    res = sp.parse_shock(msg, row, sp.Shock(), 6, metrics=m, backends=[sp.GoldenParser(), sp.RuleParser()])
    assert res.clarify is None, (msg, res.clarify)
    state = sp.shock_to_state(res.shock, res.target)
    chat = {"shock": res.shock, "state": state, "account_id": acct, "understood_as": res.understood_as}
    return row, build_view(acct, row, state, chat=chat)


def test_the_shock_list_has_15_shocks_and_the_readme_twists():
    assert len(SHOCKS) == 15
    from resilience.core import README_TWISTS
    assert all(t.name in SHOCKS for t in README_TWISTS)


@needs_data
@pytest.mark.parametrize("msg", SHOCKS)
def test_every_view_is_consistent(m, accounts, msg):
    assert len(accounts) >= 215
    bad = []
    for acct in accounts:
        row, v = view_for(m, acct, msg)
        issues = check_view(row, v["engine_shock"], v["target"], v)
        if issues:
            bad.append((acct, [str(i) for i in issues]))
    assert not bad, bad[:5]


@needs_data
def test_independent_recomputation_matches_build_metrics(m):
    for acct in REHEARSAL + EDGE:
        d = raw_account(acct)
        for f in ("I", "F", "S", "B", "H", "P", "Pn"):
            assert d[f] == pytest.approx(float(m.loc[acct, f]), abs=0.01), (acct, f)


# ------------------------------------------------------------------ corruptions are caught

@pytest.fixture(scope="module")
def clean(m):
    row, v = view_for(m, 20331, "Job loss (EI 55%) + household bills +15%")
    assert check_view(row, v["engine_shock"], v["target"], v) == []
    return row, v


def caught(row, v, check_prefix):
    issues = check_view(row, v["engine_shock"], v["target"], v)
    assert any(i.check.startswith(check_prefix) for i in issues), issues
    return issues


@needs_data
def test_a_shown_buffer_off_by_a_dollar_is_caught(clean):
    row, v = clean
    caught(row, {**v, "card": {**v["card"], "B": v["card"]["B"] + 1.0}}, "2 ")


@needs_data
def test_a_ladder_marked_wrong_is_caught(m):
    row, v = view_for(m, 20331, "Laid off: EI at 55% of usual income")
    lad = v["ladder"]
    assert lad.first_sufficient is not None and lad.first_sufficient > 0
    i = lad.first_sufficient
    wrong = dataclasses.replace(lad, first_sufficient=i - 1, rungs=tuple(
        dataclasses.replace(r, reaches_target=(k == i - 1) or r.reaches_target) for k, r in enumerate(lad.rungs)))
    caught(row, {**v, "ladder": wrong}, "5 ")


@needs_data
@pytest.mark.parametrize("what, change, prefix", [
    ("state", lambda v: {"state": {**v["state"], "bills_pct": 20.0}}, "1 "),
    ("chat", lambda v: {"chat": {**v["chat"], "shock": v["chat"]["shock"].with_(extra_monthly_cost=10.0)}}, "1 "),
    ("label", lambda v: {"understood_as": v["understood_as"].replace("15%", "25%")}, "1 "),
    ("card text", lambda v: {"card_text": {**v["card_text"], "I": "$1"}}, "2 "),
    ("runway", lambda v: {"judge_text": "9.9 mo"}, "3 "),
    ("verdict", lambda v: {"verdict": "survives"}, "3 "),
    ("january", lambda v: {"jan": v["jan"] + 1.0}, "4 "),
    ("chart", lambda v: {"chart": [100.0, 50.0, -1.0]}, "4 "),
    ("goal", lambda v: {"goal": dataclasses.replace(v["goal"], shortfall=v["goal"].shortfall + 5.0)}, "5 "),
    ("checks", lambda v: {"checks_alone": [(n, "99.9 mo") for n, _ in v["checks_alone"]]}, "6 "),
    ("story", lambda v: {"story": {**v["story"], "headline": v["story"]["headline"] + " 7,777"}}, "7 "),
    ("flags", lambda v: {"flags": [*v["flags"], "no_income"]}, "9 "),
])
def test_each_corruption_is_caught(clean, what, change, prefix):
    row, v = clean
    caught(row, {**v, **change(v)}, prefix)


@needs_data
def test_a_check_that_cannot_apply_is_caught(m):
    row, v = view_for(m, 20331, "Furnace dies: repair = 1 month of typical spending")
    from resilience.core import EI_2026_MAX_MONTHLY
    bad_shock = v["engine_shock"].with_(income_cap_monthly=EI_2026_MAX_MONTHLY)
    issues = check_view(row, bad_shock, v["target"], {})
    assert any(i.check.startswith("6 ") for i in issues)
