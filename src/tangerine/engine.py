"""The resilience engine: know the customer, take a shock, make a plan.

Pure Python, no UI. Reads ONLY marts.mart_customer_profile, once, into memory, so every call
after the first is instant. A Streamlit app, a notebook or an AI agent can all call `run()`.

    from tangerine.engine import run, Shock, PRESETS
    result = run(20111, "job_loss_ei55")                       # a preset twist card
    result = run(20111, Shock(income_factor=0.55, bills_increase_pct=0.15))

Judge numbers (exact official definitions; see sql/20_marts/05_mart_customer_profile.sql):
    I typical_income · F typical_fixed_costs · S typical_spending · H typical_household_bills
    B buffer · P running_loan_payment
Our numbers sit beside them, clearly labelled, and never replace them.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from typing import Any

import pandas as pd

from tangerine import config


class UnknownAccount(KeyError):
    """Raised when an account_id is not in the data."""

    def __str__(self) -> str:  # KeyError would otherwise print the repr
        return str(self.args[0]) if self.args else "unknown account"


# ── Shocks ───────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Shock:
    """A twist card translated into numbers. The default Shock() is 'no shock'."""

    income_factor: float = 1.0
    """Share of typical income still coming in. 0.55 = job loss with EI at 55%."""
    duration_months: int | None = None
    """Months the income_factor lasts (e.g. 6 months of EI). None = forever, as in the judge formula.
    Only the month-by-month simulation uses this; the judge runway always assumes 'forever'."""
    income_after_months: float = 0.0
    """Share of typical income after duration_months ends (0 = no income once EI runs out)."""
    bills_increase_pct: float = 0.0
    """Household bills increase. 0.15 = +15%, applied to H: spending = S + 0.15 x H."""
    one_off_cost: float = 0.0
    """A one-off cost in dollars (e.g. a $4,000 repair), taken out of the buffer up front."""
    one_off_months_of_spending: float = 0.0
    """A one-off cost sized in months of typical spending (1 = the furnace twist: cost = S)."""

    def describe(self) -> str:
        parts = []
        if self.income_factor != 1.0:
            dur = "" if self.duration_months is None else (
                f" for {self.duration_months} months, then {self.income_after_months:.0%}")
            parts.append(f"income at {self.income_factor:.0%} of typical{dur}")
        if self.bills_increase_pct:
            parts.append(f"household bills {self.bills_increase_pct:+.0%}")
        if self.one_off_months_of_spending:
            parts.append(f"one-off cost of {self.one_off_months_of_spending:g} month(s) of spending")
        if self.one_off_cost:
            parts.append(f"one-off cost of ${self.one_off_cost:,.0f}")
        return ", ".join(parts) or "no shock"


PRESETS: dict[str, Shock] = {
    "no_shock": Shock(),
    "job_loss_ei55": Shock(income_factor=0.55),
    "ei55_6_months": Shock(income_factor=0.55, duration_months=6),
    "bills_up_15": Shock(bills_increase_pct=0.15),
    "furnace_1_month": Shock(one_off_months_of_spending=1),
    "job_loss_plus_bills": Shock(income_factor=0.55, bills_increase_pct=0.15),
}
"""The judges' example twist cards."""


def as_shock(shock: Shock | str | None) -> Shock:
    if shock is None:
        return Shock()
    if isinstance(shock, Shock):
        return shock
    try:
        return PRESETS[shock]
    except KeyError:
        raise ValueError(f"Unknown preset {shock!r}. Choose one of: {', '.join(PRESETS)}") from None


# ── Profiles ─────────────────────────────────────────────────────────────────
def _python_value(v: Any) -> Any:
    """numpy / pandas scalars -> plain Python; NaN -> None; dates -> ISO text."""
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    if v is pd.NaT:
        return None
    if hasattr(v, "isoformat"):
        return v.date().isoformat() if hasattr(v, "date") and callable(v.date) else v.isoformat()
    if hasattr(v, "item"):
        v = v.item()
        return None if isinstance(v, float) and math.isnan(v) else v
    return v


@lru_cache(maxsize=1)
def _profiles() -> dict[int, dict[str, Any]]:
    """Load mart_customer_profile once into {account_id: profile}."""
    from tangerine.pipeline import connect

    con = connect(read_only=True)
    try:
        df = con.execute("select * from marts.mart_customer_profile").df()
    finally:
        con.close()
    return {
        int(row["account_id"]): {k: _python_value(v) for k, v in row.items()}
        for row in df.to_dict("records")
    }


def account_ids() -> list[int]:
    """Every account_id the engine knows (4,500)."""
    return sorted(_profiles())


def get_profile(account_id: int | str) -> dict[str, Any]:
    """Judge numbers, context and flags for one account. Raises UnknownAccount."""
    try:
        key = int(account_id)
    except (TypeError, ValueError):
        raise UnknownAccount(f"account_id must be a number, got {account_id!r}") from None
    profiles = _profiles()
    if key not in profiles:
        raise UnknownAccount(f"account_id {key} is not in the data ({len(profiles):,} accounts known)")
    return dict(profiles[key])


# ── Runway (judge formula) ───────────────────────────────────────────────────
@dataclass
class RunwayResult:
    months: float | None
    """Months of runway, 1 decimal. None = no shortfall (120+)."""
    label: str
    income_after: float
    spending_after: float
    one_off_cost: float
    buffer_left: float
    gap: float
    """spending_after - income_after. Positive = losing this much each month."""
    method: str = "judge formula"


def runway_formula(buffer: float, income_after: float, spending_after: float, one_off: float = 0.0) -> float | None:
    """The judges' runway formula. Returns months (1 decimal), or None for 'no shortfall (120+)'."""
    buffer_left = buffer - one_off
    gap = spending_after - income_after
    if buffer_left <= 0:
        return 0.0
    if gap <= 0:
        return None
    return round(min(buffer_left / gap, config.RUNWAY_CAP_MONTHS), 1)


def runway_label(months: float | None, buffer_left: float) -> str:
    if buffer_left <= 0:
        return "0 months - buffer already gone"
    if months is None:
        return config.NO_SHORTFALL_LABEL
    if months >= config.RUNWAY_CAP_MONTHS:
        return "120 months (capped)"
    return f"{months:.1f} months"


def shocked_numbers(profile: dict, shock: Shock, income_base: float | None = None) -> tuple[float, float, float]:
    """(income_after, spending_after, one_off_cost) for a shock."""
    income = profile["typical_income"] if income_base is None else income_base
    income_after = income * shock.income_factor
    spending_after = profile["typical_spending"] + shock.bills_increase_pct * profile["typical_household_bills"]
    one_off = shock.one_off_cost + shock.one_off_months_of_spending * profile["typical_spending"]
    return income_after, spending_after, one_off


def _runway_result(profile: dict, shock: Shock, income_base: float | None, method: str) -> RunwayResult:
    income_after, spending_after, one_off = shocked_numbers(profile, shock, income_base)
    buffer_left = profile["buffer"] - one_off
    months = runway_formula(profile["buffer"], income_after, spending_after, one_off)
    return RunwayResult(
        months=months,
        label=runway_label(months, buffer_left),
        income_after=income_after,
        spending_after=spending_after,
        one_off_cost=one_off,
        buffer_left=buffer_left,
        gap=spending_after - income_after,
        method=method,
    )


def judge_runway(profile: dict, shock: Shock | str | None = None) -> RunwayResult:
    """Runway exactly as the judges calculate it."""
    return _runway_result(profile, as_shock(shock), None, "judge formula")


def stress_runway(profile: dict, shock: Shock | str | None = None) -> RunwayResult:
    """OUR 'check-engine light': the same formula, but income = a lean month
    (the account's own 25th-percentile month) instead of a median month."""
    return _runway_result(profile, as_shock(shock), profile["lean_month_income_p25"],
                          "stress-adjusted (lean-month income)")


# ── Month-by-month simulation ────────────────────────────────────────────────
def simulate(profile: dict, shock: Shock | str | None = None, horizon: int = 24) -> pd.DataFrame:
    """Balance path for the baseline (no shock) and the shocked case.

    Month 0 is today's buffer (minus any one-off cost in the shocked case). Each later month adds
    income and subtracts spending. Handles time-limited shocks (e.g. EI for 6 months, then nothing).
    Columns: scenario, month, income, spending, balance.
    """
    shock = as_shock(shock)
    I, S, H, B = (profile[k] for k in ("typical_income", "typical_spending", "typical_household_bills", "buffer"))
    rows = []
    for scenario in ("baseline", "shocked"):
        is_shocked = scenario == "shocked"
        _, spending, one_off = shocked_numbers(profile, shock) if is_shocked else (I, S, 0.0)
        balance = B - one_off
        rows.append((scenario, 0, 0.0, 0.0, balance))
        for month in range(1, horizon + 1):
            if not is_shocked:
                factor = 1.0
            elif shock.duration_months is None or month <= shock.duration_months:
                factor = shock.income_factor
            else:
                factor = shock.income_after_months
            income = I * factor
            balance += income - spending
            rows.append((scenario, month, income, spending, balance))
    return pd.DataFrame(rows, columns=["scenario", "month", "income", "spending", "balance"])


def months_until_zero(path: pd.DataFrame, scenario: str = "shocked") -> int | None:
    """First month the balance is below zero, or None if it never is within the horizon."""
    p = path[(path["scenario"] == scenario) & (path["balance"] < 0)]
    return None if p.empty else int(p["month"].iloc[0])


# ── Plans ────────────────────────────────────────────────────────────────────
@dataclass
class Plan:
    target_buffer_months: int
    target_buffer: float
    goal_status: str
    """'goal_met' | 'saving' | 'needs_cuts' | 'not_reachable'"""
    goal_summary: str
    monthly_saving: float | None = None
    months_to_goal: int | None = None
    goal_discretionary_cut_pct: float | None = None
    backup_discretionary_cut_pct: float = 0.0
    backup_spending: float = 0.0
    backup_runway_months: float | None = None
    backup_runway_label: str = ""
    backup_cut_needed_for_goal_runway_pct: float | None = None
    backup_summary: str = ""
    backup_steps: list[str] = field(default_factory=list)


def _round_to_10(x: float) -> float:
    return float(round(x / 10.0) * 10)


def make_plan(profile: dict, shock: Shock | str | None = None, discretionary_cut: float | None = None) -> Plan:
    """Goal plan (build an emergency fund in normal times) + backup plan (if the shock hits)."""
    shock = as_shock(shock)
    th = config.threshold
    I, S, B, D, F = (profile[k] for k in ("typical_income", "typical_spending", "buffer",
                                          "typical_discretionary_spending", "typical_fixed_costs"))
    cut = th("backup_plan_discretionary_cut") if discretionary_cut is None else discretionary_cut
    goal_runway = th("backup_plan_runway_goal_months")

    # ── Goal plan ──
    target_months = int(th("target_buffer_months_volatile") if profile["is_volatile_income"]
                        else th("target_buffer_months_steady"))
    target = S * target_months
    surplus = I - S
    plan = Plan(target_buffer_months=target_months, target_buffer=target, goal_status="", goal_summary="")
    still_needed = max(target - B, 0.0)
    why = "volatile income" if profile["is_volatile_income"] else "steady income"

    if S <= 0:
        plan.goal_status = "goal_met"
        plan.goal_summary = "No regular spending recorded, so there is nothing to cover. Keep the buffer as is."
    elif still_needed == 0:
        plan.goal_status = "goal_met"
        plan.goal_summary = (f"Goal already met: the ${B:,.0f} buffer covers {B / S:.1f} months of spending "
                             f"(target {target_months} months for {why}). Keep it there.")
    elif surplus > 0:
        saving = _round_to_10(min(surplus, th("savings_share_of_surplus") * surplus
                                  + th("savings_share_of_discretionary") * D))
        if saving <= 0:
            saving = round(surplus, 2)
        plan.goal_status = "saving"
        plan.monthly_saving = saving
        plan.months_to_goal = math.ceil(still_needed / saving)
        plan.goal_summary = (f"Save ${saving:,.0f}/month toward a {target_months}-month emergency fund "
                             f"(${target:,.0f}, because of {why}). ${still_needed:,.0f} to go: about "
                             f"{plan.months_to_goal} months.")
    else:
        deadline = th("goal_plan_deadline_months")
        needed_per_month = still_needed / deadline + (S - I)  # stop the bleed + build the fund
        pct = needed_per_month / D if D > 0 else math.inf
        if pct <= 1:
            plan.goal_status = "needs_cuts"
            plan.goal_discretionary_cut_pct = pct
            plan.monthly_saving = still_needed / deadline
            plan.goal_summary = (f"Spending is above income in a typical month, so saving needs a cut: trim "
                                 f"discretionary spending by {pct:.0%} (${needed_per_month:,.0f}/month) to reach "
                                 f"a {target_months}-month fund (${target:,.0f}) in {deadline:g} months.")
        else:
            plan.goal_status = "not_reachable"
            plan.goal_summary = (f"Spending is above income and cutting discretionary spending alone cannot build "
                                 f"a {target_months}-month fund in {deadline:g} months. First step: close the "
                                 f"${S - I:,.0f}/month gap (income or fixed costs).")

    # ── Backup plan: shock hits, fixed costs stay, discretionary spending is cut ──
    income_after, spending_after, one_off = shocked_numbers(profile, shock)
    buffer_left = B - one_off
    backup_spending = spending_after - cut * D
    backup_months = runway_formula(B, income_after, backup_spending, one_off)
    plan.backup_discretionary_cut_pct = cut
    plan.backup_spending = backup_spending
    plan.backup_runway_months = backup_months
    plan.backup_runway_label = runway_label(backup_months, buffer_left)

    if buffer_left <= 0:
        plan.backup_cut_needed_for_goal_runway_pct = None
        reach = "not reachable by cuts alone - the buffer is already gone"
    else:
        shortfall = spending_after - income_after - buffer_left / goal_runway
        if shortfall <= 0:
            plan.backup_cut_needed_for_goal_runway_pct = 0.0
            reach = f"already at least {goal_runway:g} months without cuts"
        elif D > 0 and shortfall / D <= 1:
            plan.backup_cut_needed_for_goal_runway_pct = shortfall / D
            reach = f"needs a {shortfall / D:.0%} cut of discretionary spending"
        else:
            plan.backup_cut_needed_for_goal_runway_pct = None
            reach = "not reachable by cuts alone"

    judge = runway_formula(B, income_after, spending_after, one_off)
    plan.backup_summary = (
        f"If the shock hits ({shock.describe()}): keep bills, insurance and loan payments "
        f"(~${F + shock.bills_increase_pct * profile['typical_household_bills']:,.0f}/month), cut discretionary "
        f"spending by {cut:.0%} (${cut * D:,.0f}/month). Runway goes from "
        f"{runway_label(judge, buffer_left)} to {plan.backup_runway_label}. "
        f"Reaching {goal_runway:g} months of runway: {reach}."
    )
    plan.backup_steps = [
        f"Cut discretionary spending (cash, card, other transfers) by {cut:.0%}: ${cut * D:,.0f}/month.",
        "Keep household bills, insurance and loan payments current - missed fixed payments cost the most.",
    ]
    if shock.income_factor < 1 and not profile["is_pensioner"]:
        plan.backup_steps.append("Apply for EI in the first week: it pays about 55% of usual earnings, up to a weekly maximum.")
    if profile["running_loan_payment"] > 0:
        plan.backup_steps.append(f"Call the bank early about the ${profile['running_loan_payment']:,.0f}/month loan "
                                 "payment (deferral or a longer term) before any payment is missed.")
    return plan


# ── Context notes ────────────────────────────────────────────────────────────
def context_notes(profile: dict, shock: Shock | str | None = None) -> list[str]:
    """Plain-English warnings a banker should say out loud."""
    shock = as_shock(shock)
    p = profile
    notes = []
    if p["has_negative_buffer"]:
        notes.append(f"Buffer is ${p['buffer']:,.0f} (at or below zero): runway is 0 under any shock. "
                     "Step 1 is getting out of overdraft.")
    if p["is_pensioner"]:
        msg = f"Pensioner: {p['pension_income_share']:.0%} of income is pension"
        if p["owner_age_years"] is not None:
            msg += f" (owner age {p['owner_age_years']})"
        msg += "."
        if shock.income_factor < 1:
            msg += " A job-loss / EI shock may not apply - try a bills or repair shock instead."
        notes.append(msg)
    if p["is_volatile_income"]:
        notes.append(f"Volatile income (variation {p['income_volatility_cv']:.2f}): a lean month brings only "
                     f"${p['lean_month_income_p25']:,.0f} vs a typical ${p['typical_income']:,.0f}. "
                     "The stress runway shows that case.")
    if p["has_zero_income"]:
        notes.append("Typical (median) income is $0 - most months have no money in. The account may be dormant.")
    if p["has_overdraft_history"]:
        notes.append(f"Has gone below zero before ({p['total_days_overdrawn']} days in total). Red flag: all 27 "
                     "loan customers who were overdrawn before getting their loan went on to default.")
    if p["is_balance_sliding"] and p["balance_vs_12m_peak"] is not None and p["buffer"] > 0:
        notes.append(f"Balance is sliding: last month's average is {p['balance_vs_12m_peak']:.0%} of its 12-month "
                     "peak. Defaulters fell to ~43% two months before their first overdraft.")
    if p["has_loan_in_debt"]:
        notes.append("Loan status D: the loan is running and the client is already in debt.")
    if p["running_loan_payment"] > 0 and p["loan_end_date"]:
        notes.append(f"Loan payment of ${p['running_loan_payment']:,.0f}/month ends on {p['loan_end_date']}; "
                     "after that this money is freed up.")
    if p["has_short_history"]:
        notes.append(f"Only {p['months_of_history']} months of history: the typical numbers are less reliable.")
    if p["is_stale_account"]:
        notes.append(f"Data ends in {p['last_month']}, before December 2025: the buffer may be out of date.")
    return notes


# ── One call for everything ──────────────────────────────────────────────────
_RATIO_FIELDS = {"income_volatility_cv", "lean_month_share", "pension_income_share", "cash_income_share",
                 "balance_vs_12m_peak", "buffer_months_of_spending",
                 "backup_discretionary_cut_pct", "backup_cut_needed_for_goal_runway_pct",
                 "goal_discretionary_cut_pct"}
_RUNWAY_FIELDS = {"months", "backup_runway_months"}


def _clean(obj: Any, key: str = "") -> Any:
    """Make output JSON-safe: round money to 2 dp, ratios to 3 dp, runway to 1 dp; never NaN / inf."""
    if isinstance(obj, dict):
        return {k: _clean(v, k) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v, key) for v in obj]
    obj = _python_value(obj)
    if isinstance(obj, bool) or obj is None:
        return obj
    if isinstance(obj, float):
        if not math.isfinite(obj):
            return None
        if key in _RUNWAY_FIELDS:
            return round(obj, 1)
        return round(obj, 3 if key in _RATIO_FIELDS else 2)
    return obj


def run(account_id: int | str, shock: Shock | str | None = "job_loss_ei55", horizon: int = 24,
        discretionary_cut: float | None = None) -> dict[str, Any]:
    """Everything for one account and one twist, as a JSON-serialisable dict."""
    profile = get_profile(account_id)
    shock = as_shock(shock)
    path = simulate(profile, shock, horizon)
    return _clean({
        "account_id": int(account_id),
        "shock": {**asdict(shock), "description": shock.describe()},
        "profile": profile,
        "judge_runway_no_shock": asdict(judge_runway(profile, Shock())),
        "judge_runway": asdict(judge_runway(profile, shock)),
        "stress_runway": asdict(stress_runway(profile, shock)),
        "simulation": {
            "horizon_months": horizon,
            "months_until_zero_baseline": months_until_zero(path, "baseline"),
            "months_until_zero_shocked": months_until_zero(path, "shocked"),
            "rows": path.to_dict("records"),
        },
        "plan": asdict(make_plan(profile, shock, discretionary_cut)),
        "notes": context_notes(profile, shock),
    })


def summary_text(result: dict[str, Any]) -> str:
    """A short text card for the terminal / demo, built from run()'s output."""
    p, j, s, plan = result["profile"], result["judge_runway"], result["stress_runway"], result["plan"]
    lines = [
        f"Account {result['account_id']} - shock: {result['shock']['description']}",
        f"  Typical income (I)      ${p['typical_income']:>12,.2f}/month",
        f"  Fixed costs (F)         ${p['typical_fixed_costs']:>12,.2f}/month",
        f"  Typical spending (S)    ${p['typical_spending']:>12,.2f}/month",
        f"  Household bills (H)     ${p['typical_household_bills']:>12,.2f}/month",
        f"  Buffer (B)              ${p['buffer']:>12,.2f}",
        f"  Running loan pmt (P)    ${p['running_loan_payment']:>12,.2f}/month",
        f"  Runway, no shock        {result['judge_runway_no_shock']['label']}",
        f"  Runway, judge formula   {j['label']}",
        f"  Runway, stress-adjusted {s['label']}   (lean month: ${p['lean_month_income_p25']:,.0f} in, "
        f"${s['income_after']:,.0f} after the shock)",
        f"  Goal plan:   {plan['goal_summary']}",
        f"  Backup plan: {plan['backup_summary']}",
    ]
    lines += [f"  ! {n}" for n in result["notes"]]
    return "\n".join(lines)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run the engine for one account.")
    parser.add_argument("account_id", type=int)
    parser.add_argument("--shock", default="job_loss_ei55", choices=list(PRESETS))
    args = parser.parse_args()
    print(summary_text(run(args.account_id, args.shock)))
