"""INDEPENDENT pandas re-implementation of the judge formulas — the test oracle.

Reads the raw CSVs directly and does NOT import the engine, the pipeline or any SQL, so if the
warehouse and this file agree, both are very likely right. Written straight from Tangerine/README.md:

    I = median(money_in)                                    typical monthly money in
    F = median(household_bills + insurance + loan_payments) typical fixed costs (display only)
    S = median(money_out)                                   typical monthly spending
    H = median(household_bills)                             household bills
    B = mean(avg_daily_balance) over the last 6 rows sorted by month
    P = loans.monthly_payment if the loan is still running at end of 2025, else 0

Runway = buffer_left / gap, with 0 if buffer_left <= 0, "no shortfall" if gap <= 0, cap 120, 1 decimal.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from tangerine.config import DATA_DIR

NO_SHORTFALL = None  # what runway() returns for "no shortfall (120+)"


@lru_cache(maxsize=1)
def judge_numbers(data_dir: Path = DATA_DIR) -> pd.DataFrame:
    """One row per account_id with the six judge numbers, using the same column names as the warehouse."""
    ms = pd.read_csv(Path(data_dir) / "monthly_summary.csv", dtype={"month": str})
    ms = ms.sort_values(["account_id", "month"], kind="stable")
    ms["fixed"] = ms["household_bills"] + ms["insurance"] + ms["loan_payments"]
    g = ms.groupby("account_id")
    out = pd.DataFrame({
        "typical_income": g["money_in"].median(),            # I
        "typical_fixed_costs": g["fixed"].median(),          # F
        "typical_spending": g["money_out"].median(),         # S
        "typical_household_bills": g["household_bills"].median(),  # H
        "buffer": g["avg_daily_balance"].apply(lambda s: s.iloc[-6:].mean()),  # B
    })
    # P: "still running at the end of 2025" from dates, NOT from the status column,
    # so this also cross-checks the status-based rule used in SQL.
    loans = pd.read_csv(Path(data_dir) / "loans.csv", parse_dates=["loan_start"])
    loan_end = loans.apply(lambda r: r["loan_start"] + pd.DateOffset(months=int(r["duration_months"])), axis=1)
    running = loans[loan_end > pd.Timestamp("2025-12-31")].set_index("account_id")["monthly_payment"]
    out["running_loan_payment"] = running.reindex(out.index).fillna(0.0)
    return out


def runway(buffer: float, income_after: float, spending_after: float, one_off: float = 0.0) -> float | None:
    """The judges' runway formula for one account."""
    buffer_left = buffer - one_off
    gap = spending_after - income_after
    if buffer_left <= 0:
        return 0.0
    if gap <= 0:
        return NO_SHORTFALL
    return round(min(buffer_left / gap, 120.0), 1)


# The judges' example twists as (income factor, bills increase, one-off in months of spending).
JUDGE_TWISTS = {
    "no_shock": (1.0, 0.0, 0.0),
    "job_loss_ei55": (0.55, 0.0, 0.0),
    "bills_up_15": (1.0, 0.15, 0.0),
    "furnace_1_month": (1.0, 0.0, 1.0),
    "job_loss_plus_bills": (0.55, 0.15, 0.0),
}


def twist_runways(data_dir: Path = DATA_DIR) -> pd.DataFrame:
    """Judge runway for every account under every twist. NaN = no shortfall (120+)."""
    j = judge_numbers(data_dir)
    out = {}
    for name, (income_factor, bills_pct, one_off_months) in JUDGE_TWISTS.items():
        out[name] = [
            runway(b, income_factor * i, s + bills_pct * h, one_off_months * s)
            for i, s, h, b in zip(j["typical_income"], j["typical_spending"],
                                  j["typical_household_bills"], j["buffer"])
        ]
    return pd.DataFrame(out, index=j.index).astype(float).replace({None: np.nan})
