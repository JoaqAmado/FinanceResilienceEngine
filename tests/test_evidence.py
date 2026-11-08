"""Backtest evidence (resilience/evidence.py): the headline numbers pinned, plus the rules behind them on toy data."""
import math

import numpy as np
import pandas as pd
import pytest

from resilience import evidence as E
from resilience import warning as W
from resilience.core import DATA_DIR, baseline_metrics, load_loans, load_monthly

needs_data = pytest.mark.skipif(not (DATA_DIR / "monthly_summary.csv").exists(), reason="track data not present")
ARTIFACTS = DATA_DIR.parent / "artifacts"


# ------------------------------------------------------------- toy data, no track data needed

def toy_scores(**cols):
    """A score_frame-shaped table for 6 accounts; override any column with a list."""
    base = dict(points=[0, 2, 2, 1, 4, 0], min_bal_over_S=[3.0, 0.4, 0.4, 0.2, -1.0, 24.0],
                irregular=[False, True, False, True, True, False],
                runway_ei55_exact=[12.0, 2.0, np.inf, 0.0, 5.97, 6.0], runway_ei55=[12.0, 2.0, np.inf, 0.0, 6.0, 6.0],
                buffer_months=[9.0, 1.0, np.inf, 0.0, 3.0, 2.0],
                went_overdrawn=[False, True, False, True, True, False])
    base.update(cols)
    df = pd.DataFrame(base, index=pd.Index([16, 11, 12, 13, 14, 15], name="account_id"))
    df["passes_ei55"] = df["runway_ei55"] >= E.PASS_MONTHS
    return df


def test_list_size_rounds_halves_up_in_integers():
    assert E.list_size(10, 3847) == 385          # 384.7
    assert E.list_size(1, 3847) == 38            # 38.47
    assert E.list_size(50, 3) == 2               # 1.5 -> 2 (Python's round() would give 2 as well; 2.5 would differ)
    assert E.list_size(50, 5) == 3               # 2.5 -> 3, not banker's 2
    assert E.list_size(30, 0) == 0


def test_light_ranks_points_then_lowest_balance_then_account_id():
    s = toy_scores()
    # 14: 4 pts; 11 and 12: 2 pts, same min balance -> lower id first; 13: 1 pt; then 0 pts by min balance
    assert list(E.risk_order(s, "light")) == [14, 11, 12, 13, 16, 15]
    # the tie-break never crosses a points boundary: a much lower balance can't lift 1 point over 2
    s2 = toy_scores(min_bal_over_S=[3.0, 24.0, 24.0, -5.0, -1.0, 24.0])
    assert list(E.risk_order(s2, "light"))[:4] == [14, 11, 12, 13]


def test_runway_ranks_unrounded_shortest_first_and_no_shortfall_last():
    s = toy_scores()
    # 5.97 ranks before 6.0 although both publish as 6.0; no shortfall (inf) comes last
    assert list(E.risk_order(s, "ei55_runway")) == [13, 11, 14, 15, 16, 12]
    assert list(E.risk_order(s, "buffer_months")) == [13, 11, 15, 14, 16, 12]
    with pytest.raises(ValueError):
        E.risk_order(s, "points")


def test_lift_table_counts_the_overdrawn_on_each_list():
    s = toy_scores()
    t = E.lift_table(s, pcts=(17, 50, 100))          # lists of 1, 3 and 6 accounts
    assert t.list_accounts.tolist() == [1, 3, 6]
    assert t.light.tolist() == [1, 2, 3]              # [14] -> 1; [14, 11, 12] -> 2
    assert t.ei55_runway.tolist() == [1, 3, 3]        # [13]; [13, 11, 14]
    assert t.buffer_months.tolist() == [1, 2, 3]
    assert (t.events == 3).all()


def test_flip_one_input_moves_an_account_onto_the_list():
    assert E.lift_table(toy_scores(), pcts=(50,)).light.iloc[0] == 2     # [14, 11, 12]: 12 never went overdrawn
    flipped = toy_scores(points=[0, 2, 2, 2, 4, 0])                       # 13 gains a point, nothing else changes
    assert list(E.risk_order(flipped, "light"))[:3] == [14, 13, 11]       # same points as 11, lower balance
    assert E.lift_table(flipped, pcts=(50,)).light.iloc[0] == 3


def test_summary_counts_passers_and_the_ones_the_light_flagged():
    s = toy_scores()
    out = E.summary(s, "2024-12", "2025")
    # overdrawn: 11 (2.0, fails), 13 (0, fails), 14 (publishes 6.0 -> passes, 4 pts -> flagged)
    assert out == {"snapshot": "2024-12", "label_year": "2025", "accounts": 6, "went_overdrawn": 3,
                   "passed_ei55": 1, "passed_and_flagged": 1, "watch_points": E.WATCH_POINTS}


def test_wilson_interval():
    lo, hi = E.wilson(19, 472)
    assert (round(lo, 4), round(hi, 4)) == (0.0259, 0.0620)
    lo, hi = E.wilson(0, 50)
    assert lo == pytest.approx(0.0, abs=1e-15) and 0 < hi < 0.08
    assert all(math.isnan(x) for x in E.wilson(0, 0))


def test_irregular_table_cells_cover_everyone():
    s = toy_scores()
    t = E.irregular_table(s)
    assert t[["irregular_money_in", "judges_ei55"]].values.tolist() == [["yes", "passes"], ["yes", "fails"],
                                                                         ["no", "passes"], ["no", "fails"]]
    assert t.accounts.sum() == len(s) and t.went_overdrawn.sum() == s.went_overdrawn.sum()
    a = E.irregular_cell(t, "yes", "passes")                              # account 14
    assert (a.accounts, a.went_overdrawn, a.rate) == (1, 1, 1.0)
    empty = E.irregular_cell(t, "no", "fails")                            # nobody steady fails here
    assert empty.accounts == 0 and math.isnan(empty.rate)


def test_score_frame_runway_and_buffer_edges():
    pop = pd.DataFrame({"points": pd.array([0, 1, 2], dtype="Int64"), "min_bal_over_S": [1.0, 1.0, 1.0],
                        "fires_inc_cv": [False, True, False], "went_overdrawn": [False, True, False]},
                       index=pd.Index([1, 2, 3], name="account_id"))
    m = pd.DataFrame({"I": [1000.0, 4000.0, 1000.0], "S": [1550.0, 1000.0, 0.0], "B": [5970.0, 100.0, -5.0],
                      "H": 0.0, "flexible_median": 0.0}, index=pop.index)
    s = E.score_frame(pop, m)
    # 1: gap = 1550 - 550 = 1000 -> 5.97 exact, publishes 6.0 -> passes
    assert s.loc[1, "runway_ei55_exact"] == pytest.approx(5.97) and s.loc[1, "runway_ei55"] == 6.0
    assert bool(s.loc[1, "passes_ei55"])
    # 2: money in at 55% covers spending: no shortfall
    assert math.isinf(s.loc[2, "runway_ei55_exact"]) and bool(s.loc[2, "passes_ei55"])
    # 3: no buffer -> runway 0; no spending -> buffer months never run out
    assert s.loc[3, "runway_ei55_exact"] == 0.0 and not s.loc[3, "passes_ei55"]
    assert math.isinf(s.loc[3, "buffer_months"])


def test_s6_check_flags_and_misses():
    h = pd.DataFrame({"B": [1000.0, 1000.0, 1000.0, 1000.0], "I": [0.0, 0.0, 0.0, 0.0],
                      "S": [100.0, 200.0, 100.0, 200.0], "S6": [200.0, 100.0, np.nan, 100.0],
                      "next_spending": [1200.0, 1200.0, 600.0, 900.0]})
    t = E.s6_check(h).set_index("spending_basis")
    # real fails: rows 0 and 1 (1000 - 1200 < 0). S flags rows 1 and 3 (6 x 200 = 1200 > 1000)
    assert t.loc["S", "real_fails"] == 2
    assert (t.loc["S", "flagged"], t.loc["S", "missed_real_fails"], t.loc["S", "false_alarms"]) == (2, 1, 1)
    # S6 flags row 0 only (an undefined S6 never flags)
    assert (t.loc["S6", "flagged"], t.loc["S6", "missed_real_fails"], t.loc["S6", "false_alarms"]) == (1, 1, 0)
    # flip: money in at 55% of I covers the gap -> no longer a real fail
    h2 = h.assign(I=[100.0, 0.0, 0.0, 0.0])                               # 6 x 0.55 x 100 = 330 > 200 short
    assert E.s6_check(h2).set_index("spending_basis").loc["S", "real_fails"] == 1


# ------------------------------------------------------------- the track data: headline numbers pinned

@pytest.fixture(scope="module")
def monthly():
    return load_monthly()


@pytest.fixture(scope="module")
def ev(monthly):
    return E.build_evidence(monthly, load_loans())


@needs_data
def test_population_is_the_light_backtest(monthly, ev):
    bt = W.backtest(monthly)
    s = ev["scores"]
    assert len(s) == bt.population == 3847 and int(s.went_overdrawn.sum()) == bt.events == 75
    tiers = [(p, int((s.points == p).sum()), int(((s.points == p) & s.went_overdrawn).sum())) for p in range(5)]
    assert tiers == [(t.points, t.accounts, t.went_overdrawn) for t in bt.tiers]
    assert ev["summary"]["accounts"] == 3847 and ev["summary"]["went_overdrawn"] == 75


@needs_data
def test_headline_lift_at_a_ten_percent_list(ev):
    r = ev["lift"].set_index("list_pct").loc[E.HEADLINE_LIST_PCT]
    assert (r.list_accounts, r.light, r.ei55_runway, r.buffer_months, r.events) == (385, 47, 25, 29, 75)
    assert E.lines(ev)["lift"] == ("On a 10% watch-list (385 accounts), the light catches 47 of the 75 accounts that "
                                   "went overdrawn in 2025; the judges' EI 55% runway catches 25 and buffer months 29.")


@needs_data
def test_lift_curve_pinned(ev):
    t = ev["lift"].set_index("list_pct")
    assert t.index.tolist() == list(range(1, 31))
    for pct, row in {1: (38, 12, 7, 4), 5: (192, 32, 14, 16), 25: (962, 64, 39, 43), 30: (1154, 71, 42, 44)}.items():
        assert tuple(t.loc[pct, ["list_accounts", *E.RANKINGS]]) == row, pct
    for r in E.RANKINGS:                                                   # a longer list never catches fewer
        assert t[r].is_monotonic_increasing


@needs_data
def test_light_order_is_points_then_min_balance_then_id(ev):
    s = ev["scores"]
    lex = s.assign(aid=s.index).sort_values(["points", "min_bal_over_S", "aid"], ascending=[False, True, True],
                                            kind="stable").index
    assert list(lex) == list(E.risk_order(s, "light"))


@needs_data
def test_passed_the_judges_test_and_still_went_overdrawn(ev):
    s = ev["summary"]
    assert (s["passed_ei55"], s["passed_and_flagged"]) == (28, 17)
    assert E.lines(ev)["passed"] == ("28 of the 75 accounts that first went overdrawn in 2025 had passed the judges' "
                                     "EI 55% test at the 2024-12 snapshot; the light had flagged 17 of them "
                                     "(2+ points).")


@needs_data
def test_rows_choice_is_the_conservative_one(monthly, ev):
    """With the partial opening month kept in I, S and B (as the live card computes them), more of the 75 had
    passed, the light flagged more of them, and the EI runway catches fewer on a 10% list."""
    pop = W.backtest_frame(monthly)
    rows = monthly[monthly.month <= W.BACKTEST_SNAPSHOT]
    kept = E.score_frame(pop, baseline_metrics(rows, load_loans()))
    s, lift = E.summary(kept), E.lift_table(kept).set_index("list_pct").loc[10]
    assert (s["passed_ei55"], s["passed_and_flagged"]) == (34, 22)
    assert (lift.light, lift.ei55_runway, lift.buffer_months) == (47, 23, 25)


@needs_data
def test_irregular_money_in_two_by_two(ev):
    t = ev["irregular"].set_index(["irregular_money_in", "judges_ei55"])
    assert t[["went_overdrawn", "accounts"]].to_dict("index") == {
        ("yes", "passes"): {"went_overdrawn": 14, "accounts": 376},
        ("yes", "fails"): {"went_overdrawn": 30, "accounts": 335},
        ("no", "passes"): {"went_overdrawn": 14, "accounts": 2064},
        ("no", "fails"): {"went_overdrawn": 17, "accounts": 1072},
    }
    lo, hi = t.loc[("yes", "passes"), ["ci_low", "ci_high"]]
    assert (round(lo, 3), round(hi, 3)) == (0.022, 0.062)
    lo, hi = t.loc[("no", "fails"), ["ci_low", "ci_high"]]
    assert (round(lo, 3), round(hi, 3)) == (0.010, 0.025)
    # irregular = exactly the light's rule 3 at the snapshot
    pop = W.backtest_frame(load_monthly())
    assert (ev["scores"].irregular == pop.fires_inc_cv).all()
    L = E.lines(ev)
    assert L["irregular"] == ("Accounts with irregular money in that pass the judges' EI 55% test: 14 of 376 went "
                              "overdrawn in 2025 (3.7%, 95% interval 2.2–6.2%). Accounts with steady money in that "
                              "fail it: 17 of 1,072 (1.6%, 1.0–2.5%).")
    assert L["irregular_caveat"] == ("A second finding with small numbers: it rests on 14 and 17 overdrafts. It shows "
                                     "who to watch, not why they went overdrawn.")


@needs_data
def test_s6_checked_forward(ev):
    t = ev["s6"].set_index("spending_basis")
    assert t.loc["S"].to_dict() == {"account_halfyears": 12681, "real_fails": 6652, "flagged": 4966,
                                    "missed_real_fails": 2406, "false_alarms": 720}
    assert t.loc["S6"].to_dict() == {"account_halfyears": 12681, "real_fails": 6652, "flagged": 7228,
                                     "missed_real_fails": 1003, "false_alarms": 1579}
    h = ev["halfyears"]
    assert h.groupby("origin").size().index.tolist() == list(E.S6_ORIGINS)
    assert not h.S6.isna().any()                                           # 13+ months: S6 is always defined
    assert E.lines(ev)["s6"] == (
        "Checked forward at 4 as-of months from 2023-12 to 2025-06 (12,681 account half-years, each using only the "
        "data up to its month): of the 6,652 half-years that fail the 6-month EI test on the money out that actually "
        "followed, the judges' median month S misses 2,406 and half-year spending S6 misses 1,003; S6 raises 1,579 "
        "false alarms against 720 for S.")


@needs_data
def test_s6_inputs_use_only_data_up_to_the_origin(monthly):
    loans = load_loans()
    full = E.s6_halfyears(monthly, loans, origins=("2024-06",))
    cut = E.s6_halfyears(monthly[monthly.month <= "2024-12"], loans, origins=("2024-06",))
    pd.testing.assert_frame_equal(full, cut)                               # later rows change nothing


@needs_data
@pytest.mark.parametrize("name", E.ARTIFACT_FILES)
def test_artifacts_match_the_engine(ev, name):
    want = {"backtest_summary": pd.DataFrame([ev["summary"]]), "backtest_lift": ev["lift"],
            "backtest_irregular": ev["irregular"], "s6_halfyear_check": ev["s6"]}[name]
    got = pd.read_csv(ARTIFACTS / f"{name}.csv", dtype={"snapshot": str, "label_year": str})
    pd.testing.assert_frame_equal(got, want.reset_index(drop=True), check_dtype=False)
