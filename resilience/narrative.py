"""Plain-English story over numbers the engine already computed.

The template is deterministic and needs no key or network, so the live demo
never depends on an API. Any LLM layer must only rephrase `facts()` and is
rejected if it introduces a number that is not in the facts (see numbers_ok).
"""
from __future__ import annotations

import math
import re

from .core import Ladder, RunwayResult, Shock


def _m(x: float) -> str:
    return f"-${-x:,.0f}" if x < 0 else f"${x:,.0f}"


def _rw(res: RunwayResult) -> str:
    return "no shortfall (120+ months)" if res.no_shortfall else f"{res.months:.1f} months"


def facts(account_id: int, row, shock: Shock, judge: RunwayResult, reality: dict[str, RunwayResult | float],
          ladder: Ladder, goal_target: float, goal_gap: float, goal_months: float | None,
          target_months: float, plan_basis: str = "") -> dict:
    """Everything the narrative may mention, already formatted."""
    out = {
        "account_id": account_id,
        "shock": shock.name,
        "target_months": f"{target_months:g}",
        "judge_runway": _rw(judge),
        "judge_verdict": "survives" if judge.survives(target_months) else "runs out before",
        "income_after": _m(judge.income_after),
        "spending_after": _m(judge.spending_after),
        "monthly_gap": _m(max(judge.gap, 0.0)),
        "buffer_left": _m(judge.buffer_left),
        "goal_target": _m(goal_target),
        "goal_gap": _m(goal_gap),
        "goal_months": None if goal_months is None else f"{goal_months:g}",
        "ladder_verdict": ladder.verdict,
        "ladder_step": None,
        "ladder_saving": None,
        "cash_or_credit": _m(ladder.cash_or_credit_needed) if ladder.cash_or_credit_needed else None,
        "reality": {},
        "plan_basis": plan_basis,
    }
    if ladder.first_sufficient is not None:
        used = ladder.rungs[: ladder.first_sufficient + 1]
        out["ladder_step"] = ", then ".join(x.step.lstrip("+ ").strip() for x in used)
        out["ladder_saving"] = _m(used[-1].monthly_saving)
    for name, val in reality.items():
        if isinstance(val, RunwayResult):
            out["reality"][name] = _rw(val)
        else:
            out["reality"][name] = "no shortfall (120+ months)" if math.isinf(val) else f"{val:.1f} months"
    return out


def template_story(f: dict) -> dict:
    """Deterministic story: headline, what changed, plan steps, caveat."""
    headline = (f"Account {f['account_id']}: {f['judge_runway']} of runway after "
                f"\"{f['shock']}\", so it {f['judge_verdict']} the {f['target_months']}-month test.")
    if f["judge_runway"].startswith("no shortfall"):
        what = f"Income after the shock ({f['income_after']}/mo) still covers spending ({f['spending_after']}/mo)."
    else:
        what = (f"Income falls to {f['income_after']}/mo against {f['spending_after']}/mo of spending: "
                f"a {f['monthly_gap']}/mo gap drawn from a {f['buffer_left']} buffer.")
    reality = "; ".join(f"{k}: {v}" for k, v in f["reality"].items())
    steps = []
    if f.get("plan_basis"):
        steps.append(f"The plan below also assumes: {f['plan_basis']}.")
    if f["ladder_step"]:
        steps.append(f"If it hits: {f['ladder_step']} (together {f['ladder_saving']}/mo).")
    elif f["cash_or_credit"]:
        steps.append(f"If it hits: cuts alone aren't enough. Line up {f['cash_or_credit']} of credit while still employed.")
    else:
        steps.append(f"If it hits: {f['ladder_verdict'].lower()}.")
    if f["goal_gap"] == "$0":
        steps.append(f"Goal: the {f['goal_target']} job-loss-proof fund is already in place. Keep it in a separate savings account.")
    elif f["goal_months"]:
        steps.append(f"Goal: build a {f['goal_target']} job-loss-proof fund. {f['goal_gap']} to go, "
                     f"about {f['goal_months']} months with an automatic monthly transfer of the normal surplus.")
    else:
        steps.append(f"Goal: a {f['goal_target']} job-loss-proof fund is {f['goal_gap']} away, and the normal "
                     "surplus can't close it: start with the backup steps as a permanent budget change.")
    return {
        "headline": headline,
        "what_changed": what,
        "reality_check": reality,
        "plan_steps": steps,
        "caveat": "Runway uses the judges' formula; reality checks are our labelled assumptions.",
    }


_NUM = re.compile(r"\d[\d,]*\.?\d*")


def numbers_ok(story: dict, f: dict) -> bool:
    """True when every number in an (LLM-written) story already appears in the facts."""
    allowed = set(_NUM.findall(str(f)))
    allowed |= {a.replace(",", "") for a in allowed}
    text = " ".join(str(v) for v in story.values())
    return all(n in allowed or n.replace(",", "") in allowed for n in _NUM.findall(text))
