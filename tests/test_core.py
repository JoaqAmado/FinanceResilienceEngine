import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from resilience.core import (
    DATA_DIR,
    DOUBLE_WHAMMY,
    FURNACE,
    EI_2026_MAX_MONTHLY,
    LAID_OFF_EI,
    LAID_OFF_EI_CAPPED,
    NO_SHORTFALL_LABEL,
    Shock,
    apply_shock,
    backup_plan,
    baseline_metrics,
    goal_plan,
    load_loans,
    load_monthly,
    portfolio_runway,
    runway,
)


def row(**kw):
    base = dict(I=5000.0, F=1500.0, S=4000.0, B=12000.0, H=1000.0, P=0.0, flexible_median=1500.0)
    base.update(kw)
    return pd.Series(base)


# ------------------------------------------------ the judges' runway formula

def test_buffer_gone_means_zero_runway():
    r = runway(buffer=1000, one_off=1500, spending_after=5000, income_after=0)
    assert r.months == 0.0 and not r.no_shortfall


def test_buffer_exactly_zero_is_zero_not_no_shortfall():
    # buffer_left <= 0 is checked before gap <= 0
    r = runway(buffer=0, one_off=0, spending_after=100, income_after=500)
    assert r.months == 0.0 and not r.no_shortfall


def test_no_gap_means_no_shortfall():
    r = runway(buffer=1000, one_off=0, spending_after=4000, income_after=4000)
    assert r.no_shortfall and r.months is None and r.label == NO_SHORTFALL_LABEL


def test_runway_is_capped_at_120_and_rounded():
    assert runway(1_000_000, 0, 101, 100).months == 120.0
    assert runway(1000, 0, 300, 0).months == 3.3  # 3.333...


def test_readme_shock_definitions():
    r = row()
    ei = apply_shock(r, LAID_OFF_EI)
    assert ei.income_after == pytest.approx(0.55 * 5000)
    assert ei.spending_after == pytest.approx(4000)
    dw = apply_shock(r, DOUBLE_WHAMMY)
    assert dw.spending_after == pytest.approx(4000 + 0.15 * 1000)
    fu = apply_shock(r, FURNACE)
    assert fu.one_off == pytest.approx(4000) and fu.buffer_left == pytest.approx(8000)


def test_flip_case_same_customer_survives_baseline_but_not_job_loss():
    r = row()  # earns more than they spend -> no shortfall at baseline
    assert apply_shock(r, Shock()).no_shortfall
    ei = apply_shock(r, LAID_OFF_EI)  # gap = 4000 - 2750 = 1250 -> 12000/1250 = 9.6
    assert ei.months == 9.6
    tighter = apply_shock(row(B=6000.0), LAID_OFF_EI)  # 6000/1250 = 4.8 -> fails 6-month test
    assert tighter.months == 4.8 and not tighter.survives(6)


def test_income_cap_binds_only_above_cap():
    capped = apply_shock(row(I=20000.0), Shock(income_multiplier=0.55, income_cap_monthly=3000))
    assert capped.income_after == 3000
    uncapped = apply_shock(row(I=4000.0), Shock(income_multiplier=0.55, income_cap_monthly=3000))
    assert uncapped.income_after == pytest.approx(2200)


# ------------------------------------------------------------------- plans

def test_backup_plan_cut_restores_target_runway():
    r = row(B=6000.0)
    plan = backup_plan(r, LAID_OFF_EI, target_months=6)
    # buffer 6000 over 6 months allows a 1000 gap; gap is 1250 -> cut 250
    assert plan.monthly_cut_needed == pytest.approx(250.0)
    assert plan.feasible and plan.after_cut.months == 6.0
    assert plan.cut_share_of_flexible == pytest.approx(250 / 1500)


def test_backup_plan_infeasible_when_cut_exceeds_flexible_pool():
    plan = backup_plan(row(B=1000.0, flexible_median=100.0), LAID_OFF_EI, target_months=6)
    assert not plan.feasible and plan.monthly_cut_needed > 100


def test_goal_plan_months_to_target():
    g = goal_plan(row(B=12000.0), target_months=6)  # target 24000, surplus 1000
    assert g.shortfall == 12000 and g.months_to_target == 12.0
    assert goal_plan(row(I=3000.0)).months_to_target is None  # spends more than earns


# --------------------------------------------- against the real track data

needs_data = pytest.mark.skipif(not (DATA_DIR / "monthly_summary.csv").exists(), reason="track data not present")


@pytest.fixture(scope="module")
def metrics():
    return baseline_metrics(load_monthly(), load_loans())


@needs_data
def test_metrics_cover_all_accounts(metrics):
    assert len(metrics) == 4500
    assert metrics[["I", "F", "S", "B", "H", "P"]].notna().all().all()


@needs_data
def test_metrics_match_an_independent_recompute(metrics):
    ms = pd.read_csv(DATA_DIR / "monthly_summary.csv")
    acct = 20143
    m = ms[ms.account_id == acct].sort_values("month")
    assert metrics.loc[acct, "I"] == pytest.approx(m.money_in.median())
    assert metrics.loc[acct, "S"] == pytest.approx(m.money_out.median())
    assert metrics.loc[acct, "B"] == pytest.approx(m.avg_daily_balance.iloc[-6:].mean())
    assert metrics.loc[acct, "F"] == pytest.approx((m.household_bills + m.insurance + m.loan_payments).median())


@needs_data
def test_loan_payment_only_for_running_loans(metrics):
    loans = load_loans()
    finished = loans[loans.status.isin(["A", "B"])].account_id
    running = loans[loans.status.isin(["C", "D"])].set_index("account_id").monthly_payment
    assert (metrics.loc[finished, "P"] == 0).all()
    assert np.allclose(metrics.loc[running.index, "P"], running)


@needs_data
def test_vectorised_runway_matches_single_account_path(metrics):
    vec = portfolio_runway(metrics, DOUBLE_WHAMMY)
    for acct in metrics.sample(200, random_state=0).index:
        single = apply_shock(metrics.loc[acct], DOUBLE_WHAMMY)
        expected = math.inf if single.no_shortfall else single.months
        assert vec[acct] == expected, acct


@needs_data
def test_ei_six_month_failure_count(metrics):
    # independent research recompute (research/tangerine-profile.txt): 1,578 accounts < 6 months
    ei = portfolio_runway(metrics, LAID_OFF_EI)
    assert int((ei < 6).sum()) == 1578


def test_ei_2026_cap_is_729_a_week_as_a_month():
    assert EI_2026_MAX_MONTHLY == pytest.approx(3159.0)


@needs_data
def test_capped_ei_counts(metrics):
    # with the 2026 cap, more accounts fall under 6 months than under the judges' uncapped formula
    capped = portfolio_runway(metrics, LAID_OFF_EI_CAPPED)
    assert int((capped < 6).sum()) == 2304
    assert int((metrics["I"] * 0.55 > EI_2026_MAX_MONTHLY).sum()) == 2574


# ------------------------------------------------- regressions from PR review

def test_goal_plan_never_says_done_while_money_is_missing():
    g = goal_plan(row(B=23990.0), target_months=6)  # 10 short of 24000, surplus 1000
    assert g.shortfall == pytest.approx(10.0) and g.months_to_target == 0.1


def test_backup_plan_when_one_off_wipes_the_buffer():
    r = row(B=3000.0, I=5000.0, S=4000.0, flexible_median=1500.0)
    plan = backup_plan(r, FURNACE, target_months=6)  # one-off 4000 > buffer 3000
    assert plan.buffer_wiped and not plan.feasible
    assert plan.cash_needed > 1000  # at least the hole in the buffer
    assert plan.after_cut.survives(6)


def test_backup_pool_excludes_a_cut_already_in_the_shock():
    shock = Shock(income_multiplier=0.55, flexible_cut_pct=1.0)
    plan = backup_plan(row(B=1000.0, flexible_median=300.0), shock, target_months=6)
    assert plan.flexible_pool == 0.0 and not plan.feasible


def test_scalar_and_vector_rounding_agree_on_halfway_values():
    m = pd.DataFrame({"I": [0.0], "F": [0.0], "S": [100.0], "B": [105.0], "H": [0.0],
                      "P": [0.0], "flexible_median": [0.0]}, index=[1])
    assert portfolio_runway(m, Shock())[1] == apply_shock(m.loc[1], Shock()).months


def test_cli_treats_income_zero_as_a_real_twist():
    import subprocess, sys
    if not (DATA_DIR / "monthly_summary.csv").exists():
        pytest.skip("track data not present")
    out = subprocess.run([sys.executable, "-m", "resilience", "20143", "--income", "0"],
                         capture_output=True, text=True, check=True).stdout
    assert "Custom twist" in out and "income $0" in out


# ------------------------------------------ reality checks, flags, ladder, goals

from resilience.core import (  # noqa: E402
    account_flags,
    backup_ladder,
    build_metrics,
    calendar_path,
    grey_zone_note,
    portfolio_calendar_path,
)


def test_reality_toggles_off_reproduce_the_judges_numbers():
    r = row(Pn=1000.0, S6=5000.0, H_SO=900.0, H=0.0)
    judge = apply_shock(r, LAID_OFF_EI)
    same = apply_shock(r, LAID_OFF_EI.with_(name="x"))
    assert judge == same and judge.income_after == pytest.approx(0.55 * 5000)


def test_pension_aware_keeps_the_pension():
    r = row(I=5000.0, Pn=2000.0)
    res = apply_shock(r, LAID_OFF_EI.with_(pension_aware=True))
    assert res.income_after == pytest.approx(0.55 * 3000 + 2000)


def test_waiting_week_costs_one_week_of_ei_and_only_on_job_loss():
    r = row(I=5200.0)
    res = apply_shock(r, LAID_OFF_EI.with_(waiting_week=True))
    assert res.one_off == pytest.approx(0.55 * 5200 * 12 / 52)
    assert apply_shock(r, FURNACE.with_(waiting_week=True)).one_off == pytest.approx(r["S"])


def test_s6_basis_and_bills_fallback():
    r = row(S6=4500.0, H=0.0, H_SO=800.0)
    assert apply_shock(r, LAID_OFF_EI.with_(spending_basis="S6")).spending_after == pytest.approx(4500)
    assert apply_shock(row(H=0.0), LAID_OFF_EI.with_(spending_basis="S6")).spending_after == pytest.approx(4000)
    bills = DOUBLE_WHAMMY.with_(bills_fallback=True)
    assert apply_shock(r, bills).spending_after == pytest.approx(4000 + 0.15 * 800)
    assert apply_shock(r, DOUBLE_WHAMMY).spending_after == pytest.approx(4000)


def test_ladder_stops_counting_at_first_sufficient_rung():
    r = row(B=6000.0, flexible_median=2000.0, bank_fees_median=10.0)
    lad = backup_ladder(r, LAID_OFF_EI, target_months=6)  # needs a 250 cut: 10 + 10% of 2000 = 210 < 250
    assert lad.first_sufficient == 2 and lad.rungs[2].reaches_target and not lad.rungs[1].reaches_target
    assert "25%" in lad.verdict


def test_ladder_needs_credit_when_cuts_cannot_reach_target():
    lad = backup_ladder(row(B=600.0, flexible_median=0.0), LAID_OFF_EI, target_months=6)
    assert lad.first_sufficient is None and lad.cash_or_credit_needed > 0
    assert "credit" in lad.verdict


def test_ei_proof_goal_is_exactly_the_buffer_that_passes():
    r = row(B=1000.0)
    g = goal_plan(r, 6, target_kind="ei_proof")  # 6 x (4000 - 2750) = 7500
    assert g.target_buffer == pytest.approx(7500)
    assert apply_shock(row(B=7500.0), LAID_OFF_EI).survives(6)


def test_grey_zone_note():
    assert "82%" in grey_zone_note(runway(7000, 0, 1000, 0))  # 7.0 months
    assert grey_zone_note(runway(13000, 0, 1000, 0)) is None


# --- against the real data: every number in research/IDEATION.md that the app shows

@pytest.fixture(scope="module")
def full():
    return build_metrics()


@needs_data
@pytest.mark.parametrize("acct, ei55, pension, s6, jan, cap", [
    (98952, 4.2, 23.4, 4.6, 5.3, 4.2),   # retiree: fails the judges' twist, fine once the pension is kept
    (88269, 11.3, 11.3, 4.6, 0.9, 11.3),  # looks safe on the judges' rule, isn't (median-month trap)
    (77743, 4.8, 4.8, 0.7, 0.6, 1.2),
    (20331, 5.1, 5.1, 3.2, 5.2, 2.4),
    (20143, 2.2, 2.2, 2.3, 3.2, 1.3),
])
def test_rehearsal_accounts(full, acct, ei55, pension, s6, jan, cap):
    r = full.loc[acct]
    assert apply_shock(r, LAID_OFF_EI).months == ei55
    assert apply_shock(r, LAID_OFF_EI.with_(pension_aware=True)).months == pension
    assert apply_shock(r, LAID_OFF_EI.with_(spending_basis="S6")).months == s6
    assert calendar_path(r, LAID_OFF_EI) == jan
    assert apply_shock(r, LAID_OFF_EI_CAPPED).months == cap


@needs_data
def test_flip_cases(full):
    assert not apply_shock(full.loc[98952], LAID_OFF_EI).survives(6)
    assert apply_shock(full.loc[98952], LAID_OFF_EI.with_(pension_aware=True)).survives(6)
    assert apply_shock(full.loc[88269], LAID_OFF_EI).survives(6)
    assert not apply_shock(full.loc[88269], LAID_OFF_EI.with_(spending_basis="S6")).survives(6)


@needs_data
def test_portfolio_reality_counts(full):
    fails = lambda s: int((portfolio_runway(full, s) < 6).sum())  # noqa: E731
    assert fails(LAID_OFF_EI.with_(spending_basis="S6")) == 2361
    assert fails(LAID_OFF_EI.with_(pension_aware=True)) == 1569
    assert fails(LAID_OFF_EI_CAPPED.with_(waiting_week=True)) == 2335
    judge = portfolio_runway(full, LAID_OFF_EI)
    s6 = portfolio_runway(full, LAID_OFF_EI.with_(spending_basis="S6"))
    assert int(((judge >= 6) & (s6 < 6)).sum()) == 783 and int(((judge < 6) & (s6 >= 6)).sum()) == 0
    band = (judge >= 6) & (judge < 8)
    assert round(float((s6[band] < 6).mean()), 3) == 0.819


@needs_data
def test_vector_and_single_calendar_paths_agree(full):
    vec = portfolio_calendar_path(full, LAID_OFF_EI)
    for acct in full.sample(60, random_state=1).index:
        assert calendar_path(full.loc[acct], LAID_OFF_EI) == vec[acct]


@needs_data
def test_pre_loan_overdraft_and_flags(full):
    lo = full[full.loan_status.notna()]
    bad = lo.loan_status.isin(["B", "D"])
    assert int((lo.pre_loan_negative & bad).sum()) == 27 and int((lo.pre_loan_negative & ~bad).sum()) == 0
    codes = [c for c, _ in account_flags(full.loc[98952])]
    assert "pension" in codes
    assert any(c == "overdrawn" for c, _ in account_flags(full.loc[32078]))


@needs_data
def test_ei_proof_goal_portfolio(full):
    t = pd.Series({a: goal_plan(full.loc[a], 6, target_kind="ei_proof").target_buffer for a in full.index})
    assert round(t.median()) == 18049 and round(float((full.B >= t).mean()), 3) == 0.645


@needs_data
def test_portfolio_tables_match_engine(full):
    from resilience.portfolio import build_all
    t = build_all(full)
    h = t["headlines"].iloc[0]
    assert (h.fail_6mo_ei55, h.fail_6mo_ei55_cap2026, h.fail_6mo_ei55_S6) == (1578, 2304, 2361)
    bands = t["income_bands"].set_index("income_band")
    assert bands.loc["< $2.5k", "fail_6mo_ei55_pct"] == 4.8 and bands.loc[">= $20k", "fail_6mo_ei55_cap2026_pct"] == 99.8
    assert int(t["s6_calibration"]["accounts"].sum()) == int((t["accounts"].runway_ei55 >= 6).sum())


# ------------------------------------------- regressions from the second review

def test_cli_income_cap_needs_a_job_loss_and_keeps_plan_consistent():
    import subprocess, sys
    if not (DATA_DIR / "monthly_summary.csv").exists():
        pytest.skip("track data not present")
    refused = subprocess.run([sys.executable, "-m", "resilience", "20143", "--income-cap", "1500"],
                             capture_output=True, text=True)
    assert refused.returncode != 0 and "--cap" in refused.stderr
    out = subprocess.run([sys.executable, "-m", "resilience", "20143", "--income", "0.55", "--income-cap", "1500"],
                         capture_output=True, text=True, check=True).stdout
    assert "DEPLETED" in out and "Survives without changes" not in out


@needs_data
def test_ei_proof_goal_agrees_with_rounded_verdict(full):
    g = goal_plan(full.loc[21271], 6, target_kind="ei_proof")
    assert apply_shock(full.loc[21271], LAID_OFF_EI).survives(6) and g.shortfall == 0
    mismatch = 0
    for a in full.index:
        r = full.loc[a]
        mismatch += (goal_plan(r, 6, target_kind="ei_proof").shortfall == 0) != apply_shock(r, LAID_OFF_EI).survives(6)
    assert mismatch == 0


def test_grey_zone_only_for_the_plain_ei_twist():
    res = runway(7000, 0, 1000, 0)
    assert grey_zone_note(res, LAID_OFF_EI.with_(name="Laid off: EI 55%")) is not None
    assert grey_zone_note(res, FURNACE) is None and grey_zone_note(res, DOUBLE_WHAMMY) is None


def test_ladder_pool_excludes_cut_already_in_shock():
    r = row(I=5000.0, S=6000.0, B=6000.0, flexible_median=2000.0, bank_fees_median=10.0)
    lad = backup_ladder(r, Shock(income_multiplier=0.55, flexible_cut_pct=1.0), target_months=6)
    assert all("non-fixed" not in x.step for x in lad.rungs)


@needs_data
def test_ladder_overdrawn_verdict_and_no_zero_rungs(full):
    assert backup_ladder(full.loc[32078], LAID_OFF_EI).verdict.startswith("Already overdrawn")
    lad = backup_ladder(full.loc[24791], LAID_OFF_EI)
    assert all(x.monthly_saving > 0 for x in lad.rungs)


def test_cli_rejects_percent_style_inputs_and_misused_cap():
    import subprocess, sys
    if not (DATA_DIR / "monthly_summary.csv").exists():
        pytest.skip("track data not present")
    run = lambda *a: subprocess.run([sys.executable, "-m", "resilience", *a], capture_output=True, text=True)  # noqa: E731
    assert run("30111", "--income", "55").returncode != 0
    assert run("30111", "--bills", "15").returncode != 0
    assert run("36427", "--one-off-x-s", "1", "--income-cap", "3159").returncode != 0
    assert run("30111", "--income", "0.55").returncode == 0


def test_job_loss_flag_controls_ei_checks():
    pay_cut = Shock(income_multiplier=0.7)
    assert not pay_cut.is_job_loss
    assert apply_shock(row(), pay_cut.with_(waiting_week=True)).one_off == 0
    assert LAID_OFF_EI.is_job_loss and DOUBLE_WHAMMY.is_job_loss and not FURNACE.is_job_loss


def test_cap_label_and_cli_income_cap_is_a_reality_check():
    import subprocess, sys
    assert runway(1_000_000, 0, 101, 100).label == "120.0 (cap)"
    if not (DATA_DIR / "monthly_summary.csv").exists():
        pytest.skip("track data not present")
    out = subprocess.run([sys.executable, "-m", "resilience", "79750", "--income", "0.55", "--income-cap", "3159"],
                         capture_output=True, text=True, check=True).stdout
    assert "runway 3.8 months" in out and "income cap $3,159/mo 3.0 months" in out  # judges' 3.8 stays first
    bad = lambda *a: subprocess.run([sys.executable, "-m", "resilience", *a], capture_output=True).returncode != 0  # noqa: E731
    assert bad("30111", "--extra", "nan") and bad("30111", "--target", "0") and bad("30111", "--one-off-x-s", "-1")
    assert bad("30111", "--pay-cut") and bad("30111", "--income", "0.55", "--cap", "--income-cap", "3000")
