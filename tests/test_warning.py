"""Early-warning light: each rule's cut, a flip case, edge cases, and the pinned 2025 backtest table."""
import numpy as np
import pandas as pd
import pytest

from resilience import warning as W
from resilience.core import DATA_DIR, load_monthly

needs_data = pytest.mark.skipif(not (DATA_DIR / "monthly_summary.csv").exists(), reason="track data not present")

# a backtest with made-up counts, so unit tests never depend on the track data
FAKE_BT = W.Backtest("2024-12", "2025", tuple(W.Tier(p, 100, 10 * p) for p in range(5)))


def frame(n=7, account_id=1, start="2024-06", **cols):
    """n monthly rows for one account; row 0 is the opening month (dropped by the light).

    Defaults give a quiet account: S6 = 2,000, lowest balance 2.5 months of it, cash 50% of
    spending, steady money in, flat balance -> 0 points. Pass a scalar or a list of length n.
    """
    months = pd.period_range(start, periods=n, freq="M").strftime("%Y-%m")
    base = dict(money_in=3000.0, money_out=2000.0, cash_withdrawals_genuine=1000.0, min_balance=5000.0,
                avg_daily_balance=6000.0, days_below_zero=0.0)
    base.update(cols)
    data = {k: (list(map(float, v)) if np.ndim(v) else [float(v)] * n) for k, v in base.items()}
    return pd.DataFrame({"account_id": account_id, "month": list(months), **data})


def light(df, account_id=1, snapshot=None):
    return W.account_light(df, account_id, FAKE_BT, snapshot)


def fired(lt):
    return {r.rule.code for r in lt.rules if r.fired}


def test_quiet_account_scores_zero():
    lt = light(frame())
    assert lt.status == W.RATED and lt.points == 0 and fired(lt) == set()
    values = {r.rule.code: r.value for r in lt.rules}
    assert values == {"min_bal_over_S": 2.5, "cash_share": 0.5, "inc_cv": 0.0, "bal_trend": 0.0}
    assert lt.tier == FAKE_BT.tier(0)
    assert lt.line == ("Early-warning light 0/4: no rule fired. "
                       "In the 2025 backtest, 0 of 100 accounts with 0 points went overdrawn (0.00%).")


# ------------------------------------------------------------- each rule's cut

def test_rule1_lowest_balance_under_half_a_month():
    at_cut = [5000.0] * 6 + [1000.0]          # 1,000 / 2,000 = 0.5: not under half
    under = [5000.0] * 6 + [999.0]            # 0.4995
    assert fired(light(frame(min_balance=at_cut))) == set()
    lt = light(frame(min_balance=under))
    assert fired(lt) == {"min_bal_over_S"} and lt.points == 1
    assert lt.fired == ["lowest balance under half a month of spending"]


def test_rule1_is_clipped_like_the_backtest():
    assert {r.rule.code: r.value for r in light(frame(min_balance=-50_000.0)).rules}["min_bal_over_S"] == -5.0
    big = light(frame(min_balance=100_000.0))
    r1 = big.rules[0]
    assert r1.value == 24.0 and r1.raw == 50.0 and r1.value_text == "50.00 months of spending"


def test_rule2_almost_all_spending_is_cash():
    assert fired(light(frame(cash_withdrawals_genuine=1900.0))) == set()   # exactly 95%
    lt = light(frame(cash_withdrawals_genuine=1901.0))                      # 95.05%
    assert fired(lt) == {"cash_share"} and lt.fired == ["almost all spending is cash"]


def test_rule3_irregular_money_in_uses_sample_std():
    # alternating 3,000 +/- d: CV = d * sqrt(6/5) / 3,000 with ddof=1 (pandas default), d / 3,000 with ddof=0
    def money_in(d):
        return [3000.0] + [3000.0 - d, 3000.0 + d] * 3
    assert fired(light(frame(money_in=money_in(1300.0)))) == set()          # 0.475
    lt = light(frame(money_in=money_in(1400.0)))                            # 0.511 (ddof=0 would be 0.467)
    assert fired(lt) == {"inc_cv"} and lt.fired == ["irregular money in"]
    assert lt.rules[2].value == pytest.approx(1400.0 * np.sqrt(1.2) / 3000.0)


def test_rule4_balance_sliding():
    def adb(slope):
        return [6000.0] + [6000.0 + slope * k for k in range(6)]
    assert fired(light(frame(avg_daily_balance=adb(-199.0)))) == set()     # -0.0995 of S6 per month
    lt = light(frame(avg_daily_balance=adb(-201.0)))                        # -0.1005
    assert fired(lt) == {"bal_trend"}
    assert lt.fired == ["balance sliding more than 10% of a month's spending per month"]
    assert lt.rules[3].value == pytest.approx(-201.0 / 2000.0)
    assert light(frame(avg_daily_balance=adb(-10_000.0))).rules[3].value == -3.0  # clipped


def test_flip_one_input_flips_a_rule_and_the_points():
    base = dict(cash_withdrawals_genuine=1950.0)                            # rule 2 fires: 1 point
    before = light(frame(min_balance=[5000.0] * 6 + [1001.0], **base))
    after = light(frame(min_balance=[5000.0] * 6 + [999.0], **base))        # only one month's low point moved
    assert (before.points, fired(before)) == (1, {"cash_share"})
    assert (after.points, fired(after)) == (2, {"cash_share", "min_bal_over_S"})
    assert before.tier.points == 1 and after.tier.points == 2
    assert "with 1 point went" in before.line and "with 2 points went" in after.line


def test_four_points():
    lt = light(frame(min_balance=0.0, cash_withdrawals_genuine=2000.0,
                     money_in=[3000.0] + [500.0, 5500.0] * 3,
                     avg_daily_balance=[6000.0] + [6000.0 - 500.0 * k for k in range(6)]))
    assert lt.points == 4 and lt.badge == "Early-warning light 4/4"


# ------------------------------------------------------------- what the rules see

def test_only_the_last_six_rows_and_not_the_opening_month():
    # a very low point in the opening month and in a row just outside the window: neither counts
    lt = light(frame(n=8, min_balance=[-9000.0, -9000.0] + [5000.0] * 6))
    assert lt.points == 0 and lt.rows_used == 7
    assert light(frame(n=8, min_balance=[5000.0] * 7 + [-9000.0])).points == 1


def test_rows_after_the_snapshot_are_ignored():
    df = frame(n=9, min_balance=[5000.0] * 7 + [0.0, 0.0])                  # low point only in the last 2 months
    assert light(df).points == 1
    T = df.month.iloc[6]
    lt = light(df, snapshot=T)
    assert lt.points == 0 and lt.rows_used == 6


def test_input_frame_is_not_changed():
    df = frame(min_balance=0.0)
    copy = df.copy()
    light(df)
    W.light_table(df)
    pd.testing.assert_frame_equal(df, copy)


# ------------------------------------------------------------- edge cases

def test_typical_spending_zero_means_no_low_point_and_no_slide():
    # median money_out over the window is 0: rules 1 and 4 can't be measured -> not fired
    out = [2000.0] + [0.0, 0.0, 0.0, 0.0, 600.0, 600.0]
    lt = light(frame(money_out=out, cash_withdrawals_genuine=[1000.0] + [0.0] * 4 + [600.0, 600.0],
                     min_balance=-500.0, avg_daily_balance=[6000.0] + [6000.0 - 900.0 * k for k in range(6)]))
    r = {x.rule.code: x for x in lt.rules}
    assert r["min_bal_over_S"].value == 24.0 and np.isnan(r["min_bal_over_S"].raw)
    assert r["bal_trend"].value == 0.0 and np.isnan(r["bal_trend"].raw)
    assert r["min_bal_over_S"].value_text == "n/a (typical spending in the window is $0)"
    assert fired(lt) == {"cash_share"} and r["cash_share"].value == 1.0     # what spending there was is all cash


def test_no_spending_at_all():
    lt = light(frame(money_out=0.0, cash_withdrawals_genuine=0.0))
    r = {x.rule.code: x for x in lt.rules}
    assert lt.points == 0 and r["cash_share"].value == 0.0 and np.isnan(r["cash_share"].raw)
    assert r["cash_share"].value_text == "n/a (no spending in the window)"


def test_money_in_all_zero():
    lt = light(frame(money_in=0.0))
    r = lt.rules[2]
    assert r.value == 0.0 and np.isnan(r.raw) and not r.fired
    assert r.value_text == "n/a (no money in during the window)"


def test_fewer_than_six_usable_rows_is_not_enough_history():
    lt = light(frame(n=6))                                                  # opening month + 5
    assert lt.status == W.NOT_ENOUGH_HISTORY and lt.points is None and lt.rules == () and lt.tier is None
    assert lt.rows_used == 5
    assert lt.backtest_line == ("Not enough history: the light needs 6 months after the opening month and this "
                                "account has 5, so no points or backtest rate.")
    # the card line names the light, the same sentence the web card renders
    assert lt.line == "Early-warning light: " + lt.backtest_line
    assert lt.badge == "Early-warning light: not enough history"
    assert lt.spending_note is None
    assert light(frame(n=7)).status == W.RATED                              # 6 usable rows is enough


def test_short_history_wins_over_overdrawn():
    lt = light(frame(n=4, days_below_zero=[0.0, 3.0, 0.0, 0.0]))
    assert lt.status == W.NOT_ENOUGH_HISTORY and lt.points is None


def test_already_overdrawn_keeps_points_but_no_rate():
    # went below zero in an early row, outside the 6-row window: the backtest population excluded it
    lt = light(frame(n=10, days_below_zero=[0.0, 2.0] + [0.0] * 8, cash_withdrawals_genuine=1990.0))
    assert lt.status == W.ALREADY_OVERDRAWN and lt.points == 1 and lt.tier is None
    assert "with 1 point" not in lt.line and "Already overdrawn before" in lt.line
    assert lt.line.startswith("Early-warning light 1/4: almost all spending is cash. Already overdrawn before:")


def test_below_zero_only_in_the_opening_month_is_still_rated():
    # same as the backtest: the opening month is dropped everywhere, including this check
    assert light(frame(days_below_zero=[4.0] + [0.0] * 6)).status == W.RATED


def test_stale_account_keeps_points_but_no_rate():
    # activity stops in 2024-12 but T is 2025-06: the backtest only held accounts whose window ends at T
    df = frame(cash_withdrawals_genuine=1990.0)                             # 2024-06 .. 2024-12
    lt = light(df, snapshot="2025-06")
    assert lt.status == W.STALE and lt.points == 1 and lt.tier is None and lt.last_month == "2024-12"
    assert "backtest, " not in lt.line and "with 1 point" not in lt.line
    assert lt.line == ("Early-warning light 1/4: almost all spending is cash. Activity stops in 2024-12: the points "
                       "are from the account's last 6 months up to then, so no backtest rate is shown (the backtest "
                       "only followed accounts that were still active).")
    assert light(df, snapshot="2024-12").status == W.RATED                  # the same rows, window ending at T


def test_stale_is_set_by_the_last_month_of_all_accounts():
    # account 2 runs one month longer, so T = its last month and account 1 has stopped
    df = pd.concat([frame(account_id=1), frame(n=8, account_id=2)], ignore_index=True)
    lt = W.light_table(df)
    assert lt.status.to_dict() == {1: W.STALE, 2: W.RATED}
    assert lt.last_month.to_dict() == {1: "2024-12", 2: "2025-01"}
    assert W.account_light(df, 1, FAKE_BT).status == W.STALE


def test_stale_after_going_below_zero_is_already_overdrawn():
    lt = light(frame(n=10, days_below_zero=[0.0, 2.0] + [0.0] * 8), snapshot="2026-01")
    assert lt.status == W.ALREADY_OVERDRAWN and lt.tier is None


def test_spending_note_names_the_rules_own_month_of_spending():
    lt = light(frame())
    assert lt.recent_spending == 2000.0
    assert lt.spending_note == ("In the lowest-balance and balance-trend rules, a month of spending is this account's "
                                "median money out over the same 6 months: $2,000.00. That is not the card's S (the "
                                "median over all history), so these months can differ from the Buffer's.")
    # only the window counts: a big spender before the window does not change the rules' month of spending
    assert light(frame(n=9, money_out=[2000.0, 90_000.0, 90_000.0] + [2000.0] * 6)).recent_spending == 2000.0
    zero = light(frame(money_out=0.0, cash_withdrawals_genuine=0.0))
    assert zero.spending_note.endswith("over the same 6 months: $0.00, so those two rules can't be measured and "
                                       "don't fire.")
    # the light's column is not called S6: that name is the engine's rolling half-year spending
    assert "S6" not in W.light_table(frame()).columns


def test_rule4_at_the_cut_does_not_fire():
    # slope exactly -200 on S6 = 2,000: -200 / 2000 is the double nearest -0.1, the same as the cut
    lt = light(frame(avg_daily_balance=[6000.0] + [6000.0 - 200.0 * k for k in range(6)]))
    assert lt.rules[3].value == W.BAL_TREND_CUT and not lt.rules[3].fired and lt.points == 0


@pytest.mark.parametrize("rule", W.RULES, ids=lambda r: r.code)
def test_every_rule_is_strict_at_its_cut(rule):
    past = np.nextafter(rule.cut, -np.inf if rule.op == "<" else np.inf)
    short = np.nextafter(rule.cut, np.inf if rule.op == "<" else -np.inf)
    assert (rule.fires(rule.cut), rule.fires(past), rule.fires(short)) == (False, True, False)


def test_unknown_account_raises():
    with pytest.raises(KeyError):
        light(frame(), account_id=2)


def test_value_text_never_rounds_onto_the_cut():
    r3 = W.RULES[2]
    assert r3.value_text(0.5026) == "0.503" and r3.value_text(0.4975) == "0.497" and r3.value_text(1.234) == "1.23"
    assert W.RULES[1].value_text(0.9504) == "95.04% of spending"
    assert W.RULES[3].value_text(-0.1004) == "-0.1004 months of spending per month"
    assert W.RULES[3].value_text(-0.25) == "-0.25 months of spending per month"


def test_tier_line_wording_and_rates():
    assert W.Tier(1, 833, 18).line() == "In the 2025 backtest, 18 of 833 accounts with 1 point went overdrawn (2.2%)."
    assert W.Tier(0, 2390, 2).rate_text == "0.08%"
    assert W.Tier(4, 0, 0).rate_text == "n/a"


# ------------------------------------------------------------- the track data

@pytest.fixture(scope="module")
def monthly():
    return load_monthly()


@pytest.fixture(scope="module")
def bt(monthly):
    return W.backtest(monthly)


@needs_data
def test_backtest_tier_table_matches_the_verified_research(bt):
    rows = [(t.points, t.accounts, t.went_overdrawn) for t in bt.tiers]
    assert rows == [(0, 2390, 2), (1, 833, 18), (2, 463, 33), (3, 146, 15), (4, 15, 7)]
    assert (bt.population, bt.events) == (3847, 75)
    assert (bt.snapshot, bt.label_year) == ("2024-12", "2025")
    # the figures quoted in the decision note: 0 pts -> 2/2,390; 2 -> 7.1%; 3 -> 10.3%; 4 -> 7/15
    assert [t.rate_text for t in bt.tiers] == ["0.08%", "2.2%", "7.1%", "10.3%", "46.7%"]
    assert bt.tier(2).line() == "In the 2025 backtest, 33 of 463 accounts with 2 points went overdrawn (7.1%)."
    assert bt.tier(4).line() == "In the 2025 backtest, 7 of 15 accounts with 4 points went overdrawn (46.7%)."


@needs_data
def test_cached_backtest_is_the_same_table(bt):
    assert W.cached_backtest() == bt and W.cached_backtest() is W.cached_backtest()


@needs_data
def test_artifact_matches_the_engine(bt):
    path = DATA_DIR.parent / "artifacts" / "early_warning_tiers.csv"
    if not path.exists():
        pytest.skip("artifact not written (python -m resilience.warning)")
    pd.testing.assert_frame_equal(pd.read_csv(path), bt.table(), check_dtype=False)


@needs_data
def test_today_statuses(monthly):
    today = W.light_table(monthly)
    assert today.status.value_counts().to_dict() == {W.RATED: 4143, W.ALREADY_OVERDRAWN: 288, W.STALE: 69}
    ever_negative = monthly.groupby("account_id").days_below_zero.sum() > 0
    assert set(today.index[today.status == W.ALREADY_OVERDRAWN]) == set(ever_negative[ever_negative].index)
    # stale = activity stops before T and never below zero; 7 more stopped accounts are already overdrawn
    stopped = monthly.groupby("account_id").month.max() < monthly.month.max()
    assert set(today.index[today.status == W.STALE]) == set(stopped[stopped & ~ever_negative].index)
    assert (stopped & ever_negative).sum() == 7
    # every rated account's window ends at T, like every account in the backtest
    assert (today.loc[today.status == W.RATED, "last_month"] == monthly.month.max()).all()


@needs_data
def test_backtest_population_was_active_at_the_snapshot(monthly, bt):
    snap = W.light_table(monthly, W.BACKTEST_SNAPSHOT)
    ms = W.usable_months(monthly)
    observed = set(ms[ms.month.str.startswith(W.BACKTEST_LABEL_YEAR)].account_id)
    pop = snap[(snap.status == W.RATED) & snap.index.isin(observed)]
    assert len(pop) == bt.population == 3847
    assert (pop.last_month == W.BACKTEST_SNAPSHOT).all()
    # the 8 accounts stale at the snapshot have no 2025 rows: none of them is in the backtest
    stale = snap.index[snap.status == W.STALE]
    assert sorted(stale) == [31500, 49900, 56808, 71945, 75246, 90198, 96730, 99477]
    assert not set(stale) & observed


@needs_data
def test_backtest_needs_six_months_after_the_opening_month(monthly, bt):
    # the caption's "6+ months after the opening month": 7+ months counting the opening month
    snap = W.light_table(monthly, W.BACKTEST_SNAPSHOT)
    ms = W.usable_months(monthly)
    pop = snap[(snap.status == W.RATED) & snap.index.isin(set(ms[ms.month.str.startswith("2025")].account_id))]
    months_incl_opening = monthly[monthly.month <= W.BACKTEST_SNAPSHOT].groupby("account_id").size()
    assert pop.rows_used.min() == 6 and months_incl_opening.reindex(pop.index).min() == 7
    six = months_incl_opening[months_incl_opening == 6].index
    assert len(six) == 79 and not set(six) & set(pop.index)
    assert (snap.loc[six, "status"] == W.NOT_ENOUGH_HISTORY).all()


@needs_data
def test_stale_accounts_get_no_backtest_rate(monthly, bt):
    lt = W.account_light(monthly, 99477, bt)                               # activity stops 2024-03
    assert (lt.status, lt.points, lt.tier, lt.last_month) == (W.STALE, 3, None, "2024-03")
    assert lt.line == ("Early-warning light 3/4: almost all spending is cash; irregular money in; balance sliding "
                       "more than 10% of a month's spending per month. Activity stops in 2024-03: the points are "
                       "from the account's last 6 months up to then, so no backtest rate is shown (the backtest "
                       "only followed accounts that were still active).")
    for a in (75246, 49900, 56808):
        assert W.account_light(monthly, a, bt).tier is None and "backtest, " not in W.account_light(monthly, a, bt).line


@needs_data
def test_spending_note_on_an_account_whose_recent_spending_is_far_from_S(monthly, bt):
    # 55819: card S is $18,680/mo, the rules' month of spending is $9.19 (money out was 9.19 in 2025-07..10)
    lt = W.account_light(monthly, 55819, bt)
    assert lt.recent_spending == pytest.approx(9.19)
    assert "over the same 6 months: $9.19. That is not the card's S" in lt.spending_note
    assert lt.rules[0].value_text == "116.96 months of spending"


@needs_data
def test_single_account_matches_the_vector_table(monthly, bt):
    today = W.light_table(monthly)
    for a in list(today.sample(40, random_state=7).index) + [20331, 77743, 20578, 49900]:
        lt = W.account_light(monthly, a, bt)
        row = today.loc[a]
        assert lt.status == row.status and lt.points == int(row.points)
        assert all(r.value == row[r.rule.code] and r.fired == row[f"fires_{r.rule.code}"] for r in lt.rules)


@needs_data
@pytest.mark.parametrize("acct, points, status, rules", [
    (77743, 3, W.RATED, {"min_bal_over_S", "cash_share", "inc_cv"}),
    (20143, 0, W.RATED, set()),
    (98952, 0, W.RATED, set()),
    (20331, 2, W.ALREADY_OVERDRAWN, {"min_bal_over_S", "inc_cv"}),
    (88269, 2, W.ALREADY_OVERDRAWN, {"cash_share", "bal_trend"}),
    (20578, 2, W.RATED, {"cash_share", "inc_cv"}),                         # S6 = 0
    (49900, 2, W.STALE, {"cash_share", "bal_trend"}),                       # money in all 0, stops 2023-09
])
def test_rehearsal_and_edge_accounts(monthly, bt, acct, points, status, rules):
    lt = W.account_light(monthly, acct, bt)
    assert (lt.points, lt.status, fired(lt)) == (points, status, rules)


@needs_data
def test_card_text_for_the_app_accounts(monthly, bt):
    lt = W.account_light(monthly, 77743, bt)
    assert lt.line == ("Early-warning light 3/4: lowest balance under half a month of spending; almost all spending "
                       "is cash; irregular money in. In the 2025 backtest, 15 of 146 accounts with 3 points went "
                       "overdrawn (10.3%).")
    assert [r.value_text for r in lt.rules] == ["0.04 months of spending", "99.9% of spending", "1.13",
                                                "+0.49 months of spending per month"]
    lt = W.account_light(monthly, 20331, bt)
    assert lt.line.startswith("Early-warning light 2/4: lowest balance under half a month of spending; irregular "
                              "money in. Already overdrawn before:")
    assert [r.value_text for r in lt.rules] == ["0.49 months of spending", "68.0% of spending", "0.503",
                                                "+0.01 months of spending per month"]
