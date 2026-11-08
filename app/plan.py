"""The resilience plan shown after a shock test, in two parts:

1. Look back: the account's last 6 months (from marts.fact_account_month) and what they teach about
   facing this shock.
2. Next 12 months: what to do month by month, with balance checkpoints from the engine's simulation
   (no cuts vs. the backup plan's cuts).

No new financial math lives here: runways, plans and balance paths come from `engine.run()`, the
monthly history is the mart's own columns. This module only sums/averages those 6 months and writes
the steps in plain language.
"""
from __future__ import annotations

from statistics import mean
from typing import Any

SPENDING_CATEGORIES = {
    "cash_withdrawals_genuine": "Cash withdrawals",
    "card_withdrawals": "Card spending",
    "transfers_out_other": "Other transfers out",
}


def _money(x: float | None) -> str:
    if x is None:
        return "-"
    return f"{'-' if x < 0 else ''}${abs(x):,.0f}"


def _pct(x: float | None) -> str:
    return "-" if x is None else f"{x:.0%}"


def _item(title: str, detail: str, tag: str = "info") -> dict[str, str]:
    return {"title": title, "detail": detail, "tag": tag}


# ── 1. Look back ─────────────────────────────────────────────────────────────
def build_look_back(result: dict[str, Any], months: list[dict[str, Any]]) -> dict[str, Any]:
    """Six-month table, summary numbers and lessons for this shock."""
    p, plan, judge = result["profile"], result["plan"], result["judge_runway"]
    if not months:
        return {"months": [], "stats": {}, "lessons": [_item("No recent history", "This account has no monthly data.")]}

    n = len(months)
    avg_in = mean(m["money_in"] for m in months)
    avg_out = mean(m["money_out"] for m in months)
    total_net = sum(m["net_cash_flow"] for m in months)
    deficit_months = sum(m["net_cash_flow"] < 0 for m in months)
    lean_months = sum(m["is_lean_month"] for m in months)
    overdraft_days = sum(m["days_below_zero"] for m in months)
    avg_fixed = mean(m["fixed_costs"] for m in months)
    avg_disc = mean(m["discretionary_spending"] for m in months)
    bal_start, bal_end = months[0]["avg_daily_balance"], months[-1]["avg_daily_balance"]
    cat_avg = {label: mean(m[col] for m in months) for col, label in SPENDING_CATEGORIES.items()}
    top_cat, top_avg = max(cat_avg.items(), key=lambda kv: kv[1])
    lowest_in = min(months, key=lambda m: m["money_in"])

    lessons: list[dict[str, str]] = []
    period = f"{months[0]['month']} to {months[-1]['month']}"

    if n < 6:
        lessons.append(_item(f"Only {n} recent months", "The lessons below rest on less than half a year of data."))

    # Cash flow
    saved = f"saved {_money(total_net)}" if total_net >= 0 else f"drew {_money(-total_net)} from savings"
    if deficit_months == 0:
        lessons.append(_item("More came in than went out, every month",
                             f"Over {period} the account {saved}. That habit is the base the plan builds on.", "good"))
    else:
        lessons.append(_item(f"Spent more than came in, in {deficit_months} of {n} months",
                             f"Over {period} the account {saved}. A shock makes every one of those months worse.",
                             "warn" if total_net < 0 else "info"))

    # Balance trend
    if bal_start > 0 and bal_end < 0.8 * bal_start:
        lessons.append(_item(f"Savings shrank {1 - bal_end / bal_start:.0%}",
                             f"Average balance fell from {_money(bal_start)} to {_money(bal_end)}. "
                             "The shock would start from an already falling cushion.", "warn"))
    elif bal_start > 0 and bal_end > 1.1 * bal_start:
        lessons.append(_item(f"Savings grew {bal_end / bal_start - 1:.0%}",
                             f"Average balance rose from {_money(bal_start)} to {_money(bal_end)}.", "good"))

    # Fixed costs against the shocked income
    income_after = judge["income_after"]
    if result["shock"]["income_factor"] < 1 and not p["is_pensioner"]:
        if income_after <= 0:
            lessons.append(_item("No income left to cover fixed costs",
                                 f"Fixed costs averaged {_money(avg_fixed)}/month; under this shock the whole amount "
                                 "comes out of savings.", "urgent"))
        else:
            share = avg_fixed / income_after
            lessons.append(_item(f"On reduced income, fixed costs would take {_pct(share)} of it",
                                 f"Fixed costs (bills, insurance, loan) averaged {_money(avg_fixed)}/month against "
                                 f"{_money(income_after)} coming in after the shock.",
                                 "urgent" if share >= 1 else "warn" if share >= 0.6 else "info"))
    elif avg_in > 0:
        lessons.append(_item(f"Fixed costs take {_pct(avg_fixed / avg_in)} of income",
                             f"Fixed costs averaged {_money(avg_fixed)}/month against {_money(avg_in)} coming in."))

    # Biggest lever
    if top_avg > 0:
        cut = plan["backup_discretionary_cut_pct"]
        share_out = top_avg / avg_out if avg_out > 0 else None
        lessons.append(_item(f"{top_cat} are the biggest lever",
                             f"{top_cat} averaged {_money(top_avg)}/month"
                             f"{f' ({_pct(share_out)} of spending)' if share_out else ''}. That's where the backup "
                             f"plan's {_pct(cut)} cut of discretionary spending should start.", "info"))

    D = p["typical_discretionary_spending"]
    if D > 0 and avg_disc > 1.25 * D:
        lessons.append(_item(f"Discretionary spending ran {avg_disc / D - 1:.0%} above usual",
                             f"{_money(avg_disc)}/month recently versus a typical {_money(D)}. Bringing it back to "
                             "normal is a cut that costs nothing new.", "warn"))

    if lean_months:
        lessons.append(_item(f"{lean_months} lean month{'s' if lean_months > 1 else ''} already",
                             f"The lowest month brought only {_money(lowest_in['money_in'])} ({lowest_in['month']}). "
                             "Income is irregular, so plan from the lean month, not the typical one.", "warn"))

    if overdraft_days:
        lessons.append(_item(f"Overdrawn on {overdraft_days} day{'s' if overdraft_days > 1 else ''}",
                             "The strongest warning sign in the data: all 27 loan customers who were overdrawn "
                             "before their loan went on to default.", "urgent"))

    if p["is_pensioner"]:
        lessons.append(_item("Pension income is steady",
                             f"{_pct(p['pension_income_share'])} of income is pension, so a job loss mostly doesn't "
                             "apply. Bills and repairs are the real risks.", "good"))

    table = [{
        "month": m["month"], "money_in": round(m["money_in"], 2), "money_out": round(m["money_out"], 2),
        "net": round(m["net_cash_flow"], 2), "avg_balance": round(m["avg_daily_balance"], 2),
        "days_below_zero": m["days_below_zero"], "is_lean_month": m["is_lean_month"],
    } for m in months]

    stats = {
        "months": n, "period": period, "avg_money_in": round(avg_in, 2), "avg_money_out": round(avg_out, 2),
        "total_net": round(total_net, 2), "deficit_months": deficit_months, "lean_months": lean_months,
        "overdraft_days": overdraft_days, "avg_fixed_costs": round(avg_fixed, 2),
        "avg_discretionary": round(avg_disc, 2), "top_category": top_cat, "top_category_avg": round(top_avg, 2),
    }
    return {"months": table, "stats": stats, "lessons": lessons}


# ── 2. Next 12 months ────────────────────────────────────────────────────────
def build_next_12_months(result: dict[str, Any], look_back: dict[str, Any]) -> dict[str, Any]:
    """Four phases of actions over the year after the shock, with balance checkpoints."""
    p, plan, shock = result["profile"], result["plan"], result["shock"]
    judge, stress = result["judge_runway"], result["stress_runway"]
    D, F, H = p["typical_discretionary_spending"], p["typical_fixed_costs"], p["typical_household_bills"]
    cut = plan["backup_discretionary_cut_pct"]
    job_loss = shock["income_factor"] < 1
    duration = shock["duration_months"]
    top_cat = look_back.get("stats", {}).get("top_category")

    rows = result["simulation"]["rows"]
    path = {(r["scenario"], r["month"]): r["balance"] for r in rows}

    def checkpoint(month: int) -> dict[str, Any]:
        return {"month": month, "without_cuts": path.get(("shocked", month)),
                "with_plan": path.get(("with_plan", month))}

    # Month 1 · React
    react = []
    if judge["one_off_cost"] > 0:
        if judge["buffer_left"] > 0:
            react.append(_item(f"Pay the {_money(judge['one_off_cost'])} cost from savings",
                               f"That leaves {_money(judge['buffer_left'])}. Avoid putting it on credit if savings "
                               "cover it."))
        else:
            react.append(_item(f"Savings can't cover the {_money(judge['one_off_cost'])} cost",
                               f"Savings are {_money(p['buffer'])}. Ask the bank about a payment plan or a small "
                               "low-rate loan before reaching for high-interest credit.", "urgent"))
    if job_loss and not p["is_pensioner"]:
        react.append(_item("Apply for EI in the first week",
                           "It pays about 55% of usual earnings, up to a weekly maximum. Every week of delay is "
                           "paid from savings.", "urgent"))
    elif job_loss:
        react.append(_item("Pension continues", "Most income is pension, so the job-loss part mostly doesn't apply.",
                           "good"))
    if D > 0:
        start = f" Start with {top_cat.lower()}, the biggest category in the last 6 months." if top_cat else ""
        react.append(_item(f"Cut discretionary spending by {_pct(cut)}",
                           f"That frees {_money(cut * D)}/month.{start}"))
    else:
        react.append(_item("Nothing discretionary to cut",
                           "Almost all spending is fixed (bills, insurance, loan), so the levers are lowering fixed "
                           "costs and adding income.", "warn"))
    if p["running_loan_payment"] > 0:
        react.append(_item("Call the bank about the loan",
                           f"Ask about deferral or a longer term for the {_money(p['running_loan_payment'])}/month "
                           "payment before any payment is missed.", "urgent"))
    react.append(_item("Keep fixed payments current",
                       "Bills, insurance and loan payments come first: missed fixed payments cost the most."))

    # Months 2–3 · Hold the line
    hold = []
    monthly_gap = plan["backup_spending"] - judge["income_after"]
    if monthly_gap > 0:
        hold.append(_item(f"Live on {_money(plan['backup_spending'])}/month",
                          f"With {_money(judge['income_after'])} coming in, savings still drop {_money(monthly_gap)}"
                          f"/month. Runway with the cuts: {plan['backup_runway_label']}.",
                          "warn"))
    else:
        hold.append(_item(f"Live on {_money(plan['backup_spending'])}/month",
                          f"With the cuts, income covers spending (surplus {_money(-monthly_gap)}/month).", "good"))
    hold.append(_item("Check the balance every week",
                      f"Set a low-balance alert at one month of fixed costs ({_money(F)}) to catch a dip early."))
    need = plan["backup_cut_needed_for_goal_runway_pct"]
    if need is not None and need > cut:
        hold.append(_item(f"Deepen the cut to {_pct(need)} if it isn't enough",
                          "That's what it takes to reach 6 months of runway.", "urgent"))
    elif need is None and judge["buffer_left"] > 0 and judge["months"] is not None:
        hold.append(_item("Cuts alone won't reach 6 months of runway",
                          "Add income (part-time work, benefits) or lower fixed costs.", "urgent"))
    if stress["months"] is not None and (judge["months"] is None or stress["months"] < judge["months"]):
        hold.append(_item("Watch for a lean month",
                          f"If income dips to a lean month, runway is {stress['label']} instead of {judge['label']}.",
                          "warn"))

    # Months 4–6 · Adjust
    adjust = []
    if job_loss and duration and duration <= 6:
        adjust.append(_item(f"Income returns after month {duration}",
                            "Lift the emergency cuts gradually and switch saving back on.", "good"))
    elif job_loss:
        adjust.append(_item("Still on reduced income? Lower the fixed base",
                            f"Review household bills ({_money(H)}/month), insurance and the loan term. A lower fixed "
                            "base makes every month of the shock cheaper.", "warn"))
        adjust.append(_item("Add income where possible", "Part-time work, benefits, or selling unused items."))
    else:
        adjust.append(_item("Absorb the shock into the budget",
                            "Fold the higher costs into the monthly plan and keep the cuts that worked."))

    # Months 7–12 · Rebuild
    rebuild = []
    status = plan["goal_status"]
    target = f"{plan['target_buffer_months']}-month emergency fund ({_money(plan['target_buffer'])})"
    if status == "saving":
        rebuild.append(_item(f"Save {_money(plan['monthly_saving'])}/month",
                             f"Rebuild toward a {target}: about {plan['months_to_goal']} months from today's buffer "
                             "once income is back to normal."))
    elif status == "needs_cuts":
        rebuild.append(_item(f"Keep discretionary {_pct(plan['goal_discretionary_cut_pct'])} lower",
                             f"Spending is above income in a typical month, so the {target} has to come from cuts.",
                             "warn"))
    elif status == "not_reachable":
        rebuild.append(_item("Close the everyday gap first",
                             f"Spending is above income by {_money(p['typical_spending'] - p['typical_income'])}/month "
                             f"in a typical month; the {target} needs more income or lower fixed costs.", "urgent"))
    else:
        rebuild.append(_item("Top the fund back up", f"Return savings to the {target} the account already had.", "good"))
    rebuild.append(_item("Re-run the shock test at month 12",
                         "Check the runway grew. If not, revisit the cuts and fixed costs."))

    if D <= 0:  # no cuts possible: the "with plan" line is the same as "without cuts"
        hold = [s for s in hold if not s["title"].startswith(("Deepen the cut", "Cuts alone"))]

    return {
        "runway_without_cuts": judge["label"],
        "runway_with_plan": plan["backup_runway_label"],
        "phases": [
            {"when": "Month 1", "title": "React", "steps": react},
            {"when": "Months 2–3", "title": "Hold the line", "steps": hold, "checkpoint": checkpoint(3)},
            {"when": "Months 4–6", "title": "Adjust", "steps": adjust, "checkpoint": checkpoint(6)},
            {"when": "Months 7–12", "title": "Rebuild", "steps": rebuild, "checkpoint": checkpoint(12)},
        ],
    }
