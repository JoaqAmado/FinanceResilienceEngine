"""Turn one engine result into a 90-day action plan.

No new financial math lives here: every dollar figure and runway is read from `engine.run()`
(profile, judge/stress runway, plan, simulation). This module only orders those numbers into
weeks and writes them as plain-language steps. The only arithmetic is adding the engine's own
monthly saving to the buffer for the "prevent" checkpoints, and reading the engine's simulated
balance for the "survive" checkpoints.
"""
from __future__ import annotations

from typing import Any


def _money(x: float | None) -> str:
    if x is None:
        return "-"
    sign = "-" if x < 0 else ""
    return f"{sign}${abs(x):,.0f}"


def _pct(x: float | None) -> str:
    return "-" if x is None else f"{x:.0%}"


def _step(week: str, title: str, detail: str, tag: str = "action") -> dict[str, str]:
    return {"week": week, "title": title, "detail": detail, "tag": tag}


def _prevent(result: dict[str, Any]) -> dict[str, Any]:
    """Before the shock: steady the base and build the emergency fund."""
    p, plan = result["profile"], result["plan"]
    I, S, F = p["typical_income"], p["typical_spending"], p["typical_fixed_costs"]
    B, D = p["buffer"], p["typical_discretionary_spending"]
    saving = plan["monthly_saving"]
    status = plan["goal_status"]
    steps: list[dict[str, str]] = []

    if p["has_negative_buffer"]:
        steps.append(_step("Week 1", "Get out of overdraft first",
                           f"The buffer is {_money(B)}. Every dollar of runway starts at zero, so clearing the "
                           "overdraft comes before any savings goal.", "urgent"))

    steps.append(_step("Week 1", "Know your numbers",
                       f"A typical month brings {_money(I)} in and sends {_money(S)} out. "
                       f"{_money(F)} of that is fixed (bills, insurance, loan) and {_money(D)} is discretionary."))

    if status == "saving":
        steps.append(_step("Week 2", f"Automate {_money(saving)}/month into savings",
                           f"Set a payday transfer to a separate savings pocket. Goal: {plan['target_buffer_months']} "
                           f"months of spending ({_money(plan['target_buffer'])}) in about {plan['months_to_goal']} months."))
    elif status == "needs_cuts":
        steps.append(_step("Week 2", f"Trim discretionary spending by {_pct(plan['goal_discretionary_cut_pct'])}",
                           "Spending is above income in a typical month, so the fund has to come from cuts. "
                           f"Then move {_money(saving)}/month to savings.", "urgent"))
    elif status == "not_reachable":
        steps.append(_step("Week 2", f"Close the {_money(S - I)}/month gap",
                           "Cutting discretionary spending alone can't build the fund. Review fixed costs "
                           "(bills, insurance, loan terms) or add income before setting a savings target.", "urgent"))
    else:  # goal_met
        steps.append(_step("Week 2", "Protect the fund you already have",
                           f"Your {_money(B)} buffer already meets the {plan['target_buffer_months']}-month goal. "
                           "Keep it in a separate account so it isn't spent by accident.", "good"))

    if p["is_volatile_income"]:
        steps.append(_step("Week 3", "Budget from your lean month, not your typical one",
                           f"In a lean month only {_money(p['lean_month_income_p25'])} comes in, versus a typical "
                           f"{_money(I)}. Fixed costs of {_money(F)} should fit inside the lean month."))
    else:
        steps.append(_step("Week 3", "Review the fixed costs",
                           f"Fixed costs are {_money(F)}/month. Check bills and insurance for anything to renegotiate; "
                           "a lower fixed base makes every shock smaller."))

    steps.append(_step("Week 4", "Day 30 checkpoint", "Compare the balance with the Day 30 target below.", "checkpoint"))

    if p["running_loan_payment"] > 0:
        end = f" until {p['loan_end_date']}" if p.get("loan_end_date") else ""
        steps.append(_step("Week 5–6", "Plan around the loan payment",
                           f"{_money(p['running_loan_payment'])}/month goes to the loan{end}. Keep it current; ask about "
                           "options early if a shock looks likely."))

    steps.append(_step("Week 6–7", "Write down the backup plan now",
                       "Decide in advance which costs you keep (bills, insurance, loan) and which you cut "
                       "(discretionary). The 'If the shock hits' column is that list."))

    if p["is_balance_sliding"] and p.get("balance_vs_12m_peak") is not None and B > 0:
        steps.append(_step("Week 7", "Watch the slide weekly",
                           f"The balance is at {_pct(p['balance_vs_12m_peak'])} of its 12-month peak. Customers who "
                           "defaulted fell to ~43% two months before their first overdraft.", "urgent"))

    steps.append(_step("Week 8", "Day 60 checkpoint", "Compare the balance with the Day 60 target below.", "checkpoint"))

    if p["has_overdraft_history"]:
        steps.append(_step("Week 9–10", "Set a low-balance alert",
                           f"This account has gone below zero before. Set an alert at one month of fixed costs "
                           f"({_money(F)}) so the next dip is caught early."))

    if p["is_pensioner"]:
        steps.append(_step("Week 11–12", "Keep a repair fund",
                           f"Pension income continues, so job loss isn't the main risk. A surprise repair is: keep "
                           f"one month of spending ({_money(S)}) ready for it."))
    else:
        steps.append(_step("Week 11–12", "Get EI-ready",
                           "Know where your employment records are and how to apply for EI, so a job loss "
                           "costs days, not weeks."))

    steps.append(_step("Week 13", "Day 90 review",
                       "Re-run the shock test. If the runway grew, keep going; if not, revisit the cuts.", "checkpoint"))

    checkpoints: list[dict[str, Any]] = []
    if saving:
        for month, day in ((1, 30), (2, 60), (3, 90)):
            checkpoints.append({"day": day, "balance": round(B + month * saving, 2),
                                "label": f"if {_money(saving)}/month is saved"})
    elif status == "goal_met":
        for day in (30, 60, 90):
            checkpoints.append({"day": day, "balance": round(B, 2), "label": "keep at least this"})
    else:  # no savings target yet: checkpoints check the gap instead of a balance
        for s in steps:
            if s["tag"] == "checkpoint" and s["week"] in ("Week 4", "Week 8"):
                s["detail"] = "Check whether the monthly gap is closing: money in versus money out."

    return {"goal_status": status, "summary": plan["goal_summary"], "steps": steps, "checkpoints": checkpoints}


def _survive(result: dict[str, Any]) -> dict[str, Any]:
    """If the shock hits: protect the fixed costs, cut the rest, buy time."""
    p, plan, shock = result["profile"], result["plan"], result["shock"]
    judge, stress = result["judge_runway"], result["stress_runway"]
    D = p["typical_discretionary_spending"]
    cut = plan["backup_discretionary_cut_pct"]
    job_loss = shock["income_factor"] < 1
    steps: list[dict[str, str]] = []

    if judge["one_off_cost"] > 0:
        steps.append(_step("Day 1", f"Pay the {_money(judge['one_off_cost'])} one-off cost from the buffer",
                           f"That leaves {_money(judge['buffer_left'])}. Don't put it on credit if the buffer covers it.",
                           "urgent" if judge["buffer_left"] <= 0 else "action"))

    if job_loss and not p["is_pensioner"]:
        steps.append(_step("Week 1", "Apply for EI",
                           "Apply in the first week: it pays about 55% of usual earnings, up to a weekly maximum.",
                           "urgent"))
    elif job_loss and p["is_pensioner"]:
        steps.append(_step("Week 1", "Pension continues",
                           "Most of this income is pension, so a job-loss shock mostly doesn't apply. "
                           "Focus on bills and repairs.", "good"))

    steps.append(_step("Week 1", f"Cut discretionary spending by {_pct(cut)}",
                       f"That frees {_money(cut * D)}/month from cash, card and other transfers."))

    if p["running_loan_payment"] > 0:
        steps.append(_step("Week 1–2", "Call the bank about the loan",
                           f"Ask about deferral or a longer term for the {_money(p['running_loan_payment'])}/month "
                           "payment before any payment is missed.", "urgent"))

    steps.append(_step("Week 2", "Keep fixed payments current",
                       "Bills, insurance and loan payments come first: missed fixed payments cost the most."))

    steps.append(_step("Week 4", "Day 30 checkpoint",
                       f"Losing {_money(judge['gap'])}/month without cuts; with the cuts, runway is "
                       f"{plan['backup_runway_label']}.", "checkpoint"))

    need = plan["backup_cut_needed_for_goal_runway_pct"]
    if need is not None and need > cut:
        steps.append(_step("Week 5–8", f"Deepen the cut to {_pct(need)} if the shock lasts",
                           "That's what it takes to reach 6 months of runway.", "urgent"))
    elif need is None and judge["buffer_left"] > 0 and judge["months"] is not None:
        steps.append(_step("Week 5–8", "Cuts alone won't reach 6 months",
                           "Look for income (part-time work, benefits) or lower fixed costs.", "urgent"))

    if stress["months"] is not None and (judge["months"] is None or stress["months"] < judge["months"]):
        steps.append(_step("Week 5–8", "Plan for the lean month",
                           f"If income dips to a lean month, runway is {stress['label']} instead of {judge['label']}. "
                           "Use the lean number when deciding how deep to cut."))

    steps.append(_step("Week 8", "Day 60 checkpoint", "Compare the balance with the Day 60 line below.", "checkpoint"))
    steps.append(_step("Week 13", "Day 90 review",
                       "If income is back, rebuild the buffer with the 'Prevent' plan. If not, repeat the cuts "
                       "and review fixed costs again.", "checkpoint"))

    shocked = {r["month"]: r["balance"] for r in result["simulation"]["rows"] if r["scenario"] == "shocked"}
    checkpoints = [{"day": day, "balance": shocked.get(month), "label": "without cuts"}
                   for month, day in ((1, 30), (2, 60), (3, 90))]

    return {
        "summary": plan["backup_summary"],
        "runway_without_cuts": judge["label"],
        "runway_with_cuts": plan["backup_runway_label"],
        "steps": steps,
        "checkpoints": checkpoints,
    }


def build_90_day_plan(result: dict[str, Any]) -> dict[str, Any]:
    """The 'prevent' and 'survive' halves of the 90-day plan for one engine result."""
    return {"prevent": _prevent(result), "survive": _survive(result)}
