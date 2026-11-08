"""The SQL warehouse must reproduce the judges' numbers for all 4,500 accounts.

Compared against tangerine.judge_reference, an independent pandas implementation that reads the CSVs.
"""
import numpy as np
import pandas as pd
import pytest

from tangerine import judge_reference

JUDGE_COLUMNS = ["typical_income", "typical_fixed_costs", "typical_spending",
                 "typical_household_bills", "buffer", "running_loan_payment"]
RUNWAY_COLUMNS = {
    "no_shock": "runway_no_shock",
    "job_loss_ei55": "runway_job_loss_ei55",
    "bills_up_15": "runway_bills_up_15",
    "furnace_1_month": "runway_furnace_1_month",
    "job_loss_plus_bills": "runway_job_loss_plus_bills",
}


@pytest.fixture(scope="module")
def warehouse_profile(con):
    return con.execute("select * from marts.mart_customer_profile").df().set_index("account_id").sort_index()


@pytest.fixture(scope="module")
def oracle():
    return judge_reference.judge_numbers().sort_index()


def test_same_4500_accounts(warehouse_profile, oracle):
    assert len(warehouse_profile) == 4500
    assert warehouse_profile.index.equals(oracle.index)


@pytest.mark.parametrize("column", JUDGE_COLUMNS)
def test_judge_number_matches_oracle(warehouse_profile, oracle, column):
    diff = (warehouse_profile[column] - oracle[column]).abs()
    worst = diff.idxmax()
    assert diff.max() < 0.01, (f"{column}: worst account {worst} warehouse={warehouse_profile.at[worst, column]} "
                               f"oracle={oracle.at[worst, column]}")


def test_running_loan_status_rule_equals_date_rule(warehouse_profile, oracle):
    """P from status C/D (SQL) == P from loan_start + duration > 2025-12-31 (oracle)."""
    assert (warehouse_profile["running_loan_payment"] == oracle["running_loan_payment"]).all()


def test_shock_runways_match_oracle(con):
    sql = con.execute("select * from marts.mart_shock_runways").df().set_index("account_id").sort_index()
    ref = judge_reference.twist_runways().sort_index()
    for twist, column in RUNWAY_COLUMNS.items():
        a, b = sql[column], ref[twist]
        same_null = a.isna() == b.isna()
        assert same_null.all(), f"{twist}: no-shortfall mismatch for {list(a.index[~same_null][:5])}"
        # Rounding to 1 dp can differ by one step only when a value sits exactly on a .x5 boundary.
        close = np.isclose(a.fillna(-1), b.fillna(-1), atol=0.1 + 1e-9)
        assert close.all(), f"{twist}: {(~close).sum()} accounts differ"
        assert (a.fillna(-1) == b.fillna(-1)).mean() > 0.999, f"{twist}: too many rounding differences"
