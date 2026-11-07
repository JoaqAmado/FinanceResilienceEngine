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
