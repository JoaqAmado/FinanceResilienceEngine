"""Deterministic resilience engine for the Tangerine "Resilience Rewired" track.

Every number here is computed from the track data with the judges' published
definitions (README of the Tangerine dataset). No LLM calls happen in this
module: any narrative layer must sit on top of these results.

Judges' definitions, from monthly_summary.csv, per account:
    I  typical monthly money in    = median(money_in)
    F  typical fixed costs         = median(household_bills + insurance + loan_payments)
    S  typical monthly spending    = median(money_out)
    B  buffer                      = mean(avg_daily_balance) over the last 6 rows by month
    H  household bills             = median(household_bills)
    P  loan payment                = loans.monthly_payment if the loan is still
                                     running at the end of 2025 (status C or D), else 0

Runway (months):
    buffer_left = B - one_off_costs
    gap         = spending_after_shock - income_after_shock
    buffer_left <= 0 -> 0
    gap <= 0         -> "no shortfall (120+)"
    else             -> min(buffer_left / gap, 120), rounded to 1 decimal
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

RUNWAY_CAP_MONTHS = 120.0
NO_SHORTFALL_LABEL = "no shortfall (120+)"
RUNNING_LOAN_STATUSES = ("C", "D")
FLEXIBLE_COLUMNS = ("card_withdrawals", "cash_withdrawals_genuine", "transfers_out_other")

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


# ---------------------------------------------------------------- loading

def load_monthly(data_dir: Path | str = DATA_DIR) -> pd.DataFrame:
    ms = pd.read_csv(Path(data_dir) / "monthly_summary.csv")
    return ms.sort_values(["account_id", "month"], kind="stable").reset_index(drop=True)


def load_loans(data_dir: Path | str = DATA_DIR) -> pd.DataFrame:
    return pd.read_csv(Path(data_dir) / "loans.csv")


# ------------------------------------------------------------- baseline

def baseline_metrics(monthly: pd.DataFrame, loans: pd.DataFrame) -> pd.DataFrame:
    """Per-account I, F, S, B, H, P plus the flexible-spending medians.

    `monthly` must hold every month row of each account; it is re-sorted by
    (account_id, month) here so "last 6 rows" is always by month.
    """
    ms = monthly.sort_values(["account_id", "month"], kind="stable")
    g = ms.groupby("account_id", sort=True)
    fixed = ms["household_bills"] + ms["insurance"] + ms["loan_payments"]

    out = pd.DataFrame({
        "I": g["money_in"].median(),
        "F": fixed.groupby(ms["account_id"]).median(),
        "S": g["money_out"].median(),
        "B": g.tail(6).groupby("account_id")["avg_daily_balance"].mean(),
        "H": g["household_bills"].median(),
    })
    running = loans[loans["status"].isin(RUNNING_LOAN_STATUSES)]
    out["P"] = running.set_index("account_id")["monthly_payment"].reindex(out.index).fillna(0.0)

    for col in FLEXIBLE_COLUMNS:
        out[f"{col}_median"] = g[col].median()
    out["flexible_median"] = out[[f"{c}_median" for c in FLEXIBLE_COLUMNS]].sum(axis=1)
    out["pension_median"] = g["pension_in"].median()
    out["months_of_data"] = g.size()
    out["first_month"] = g["month"].first()
    out["last_month"] = g["month"].last()
    out.index.name = "account_id"
    return out


# ---------------------------------------------------------------- shocks

@dataclass(frozen=True)
class Shock:
    """A scenario applied to one account's typical month.

    income_multiplier   share of I still coming in (0.55 = EI at 55%).
    income_cap_monthly  optional ceiling on the post-shock income (e.g. the EI
                        maximum benefit converted to a month). None = no cap.
    bills_increase_pct  household bills rise by this share of H (0.15 = +15%).
    extra_monthly_cost  any other new monthly cost, in CAD.
    one_off_cost        a one-time cost taken from the buffer, in CAD.
    one_off_multiple_of_S  a one-time cost expressed as a multiple of S
                        (1.0 = "a full month of their typical spending").
    flexible_cut_pct    share of the flexible-spending median the customer
                        cuts (backup-plan lever). 0 = no cut.
    """

    income_multiplier: float = 1.0
    income_cap_monthly: float | None = None
    bills_increase_pct: float = 0.0
    extra_monthly_cost: float = 0.0
    one_off_cost: float = 0.0
    one_off_multiple_of_S: float = 0.0
    flexible_cut_pct: float = 0.0
    name: str = "custom"


# Canadian reality check (opt-in; the judges' formula has no cap).
# "This means that you can receive a maximum amount of $729 per week." and
# "As of January 1, 2026, the maximum yearly insurable earnings amount is $68,900."
# Source: https://www.canada.ca/en/services/benefits/ei/ei-regular-benefit/benefit-amount.html
# EI benefits are taxable, so this is a gross amount.
EI_2026_MAX_WEEKLY = 729.0
EI_2026_MAX_MONTHLY = EI_2026_MAX_WEEKLY * 52 / 12  # 3,159.00

BASELINE = Shock(name="Baseline (no shock)")
LAID_OFF_EI = Shock(income_multiplier=0.55, name="Laid off: EI at 55% of usual income")
LAID_OFF_EI_CAPPED = Shock(income_multiplier=0.55, income_cap_monthly=EI_2026_MAX_MONTHLY,
                           name="Laid off: EI at 55%, capped at the 2026 maximum ($729/week)")
FURNACE = Shock(one_off_multiple_of_S=1.0, name="Furnace dies: repair = 1 month of typical spending")
DOUBLE_WHAMMY = Shock(income_multiplier=0.55, bills_increase_pct=0.15,
                      name="Job loss (EI 55%) + household bills +15%")
README_TWISTS = (LAID_OFF_EI, FURNACE, DOUBLE_WHAMMY)


@dataclass(frozen=True)
class RunwayResult:
    months: float | None          # None when there is no shortfall
    no_shortfall: bool
    buffer_left: float
    gap: float
    income_after: float
    spending_after: float
    one_off: float

    @property
    def label(self) -> str:
        if self.no_shortfall:
            return NO_SHORTFALL_LABEL
        return f"{self.months:.1f}"

    def survives(self, months: float) -> bool:
        return self.no_shortfall or (self.months is not None and self.months >= months)


def runway(buffer: float, one_off: float, spending_after: float, income_after: float) -> RunwayResult:
    """The judges' runway formula, exactly as published."""
    buffer_left = buffer - one_off
    gap = spending_after - income_after
    if buffer_left <= 0:
        return RunwayResult(0.0, False, buffer_left, gap, income_after, spending_after, one_off)
    if gap <= 0:
        return RunwayResult(None, True, buffer_left, gap, income_after, spending_after, one_off)
    months = float(np.round(min(buffer_left / gap, RUNWAY_CAP_MONTHS), 1))  # same rounding as portfolio_runway
    return RunwayResult(months, False, buffer_left, gap, income_after, spending_after, one_off)


def apply_shock(row: pd.Series, shock: Shock) -> RunwayResult:
    """Runway for one account (a row of baseline_metrics) under a shock."""
    income = shock.income_multiplier * row["I"]
    if shock.income_cap_monthly is not None:
        income = min(income, shock.income_cap_monthly)
    spending = (row["S"]
                + shock.bills_increase_pct * row["H"]
                + shock.extra_monthly_cost
                - shock.flexible_cut_pct * row["flexible_median"])
    one_off = shock.one_off_cost + shock.one_off_multiple_of_S * row["S"]
    return runway(row["B"], one_off, spending, income)


def portfolio_runway(metrics: pd.DataFrame, shock: Shock) -> pd.Series:
    """Vectorised runway for every account. no-shortfall is encoded as +inf."""
    income = shock.income_multiplier * metrics["I"]
    if shock.income_cap_monthly is not None:
        income = income.clip(upper=shock.income_cap_monthly)
    spending = (metrics["S"] + shock.bills_increase_pct * metrics["H"]
                + shock.extra_monthly_cost - shock.flexible_cut_pct * metrics["flexible_median"])
    buffer_left = metrics["B"] - (shock.one_off_cost + shock.one_off_multiple_of_S * metrics["S"])
    gap = spending - income
    with np.errstate(divide="ignore", invalid="ignore"):
        finite = np.round(np.minimum(buffer_left / gap, RUNWAY_CAP_MONTHS), 1)
    out = np.where(buffer_left <= 0, 0.0, np.where(gap <= 0, np.inf, finite))
    return pd.Series(out, index=metrics.index, name=shock.name)


# ------------------------------------------------------------------ plans

@dataclass(frozen=True)
class GoalPlan:
    target_buffer: float          # emergency-fund target in CAD
    current_buffer: float
    shortfall: float              # how much is missing (0 if already there)
    monthly_surplus: float        # I - S in normal times (can be <= 0)
    months_to_target: float | None  # None when the surplus can't close the gap


def goal_plan(row: pd.Series, target_months: float = 6.0, save_share: float = 1.0) -> GoalPlan:
    """Emergency fund of `target_months` x typical spending S.

    save_share: share of the normal-times surplus (I - S) the customer commits.
    """
    target = target_months * row["S"]
    shortfall = max(target - row["B"], 0.0)
    surplus = row["I"] - row["S"]
    saving = save_share * surplus
    if shortfall == 0:
        months = 0.0
    elif saving > 0:
        months = math.ceil(shortfall / saving * 10) / 10  # round up: 0.0 only when already there
    else:
        months = None
    return GoalPlan(target, row["B"], shortfall, surplus, months)


@dataclass(frozen=True)
class BackupPlan:
    target_months: float
    shocked: RunwayResult
    monthly_cut_needed: float     # CAD per month of spending to cut (0 if already safe)
    flexible_pool: float          # flexible spending still left to cut after the shock
    cut_share_of_flexible: float | None
    feasible: bool                # cut fits inside the flexible pool
    after_cut: RunwayResult
    buffer_wiped: bool            # a one-off cost used up the whole buffer
    cash_needed: float            # when the buffer is wiped: cash (e.g. financing the
                                  # one-off) needed to get back to target_months after the cut
    normal_surplus: float         # I - S, to say how fast a wiped buffer rebuilds


def backup_plan(row: pd.Series, shock: Shock, target_months: float = 6.0) -> BackupPlan:
    """Monthly spending cut that brings runway back to >= target under the shock.

    The cut is sized on the unrounded runway, so it can exceed the strict minimum
    by a few dollars; it never falls short of the target.
    If a one-off cost wipes the buffer, the published formula gives 0 months
    whatever the spending, so the plan reports the cash needed instead.
    """
    shocked = apply_shock(row, shock)
    pool = float((1.0 - shock.flexible_cut_pct) * row["flexible_median"])
    surplus = float(row["I"] - row["S"])
    wiped = shocked.buffer_left <= 0
    cut = 0.0
    cash = 0.0
    if wiped:
        cut = min(max(shocked.gap, 0.0), pool)  # cut what the pool allows, then
        cash = -shocked.buffer_left + target_months * max(shocked.gap - cut, 0.0) + 0.01
        cash = math.ceil(cash * 100) / 100       # the rest has to come from cash or credit
    elif not shocked.survives(target_months):
        allowed_gap = shocked.buffer_left / target_months
        cut = math.ceil((shocked.gap - allowed_gap) * 100) / 100  # round up to the cent
    cut_share = (cut / pool) if pool > 0 else None
    feasible = (not wiped) and cut <= pool
    after = runway(shocked.buffer_left + shocked.one_off + cash, shocked.one_off,
                   shocked.spending_after - cut, shocked.income_after)
    return BackupPlan(target_months, shocked, cut, pool, cut_share, feasible, after,
                      wiped, cash, surplus)
