"""Everything the Live twist tab shows for one account and one lever state, computed by the engine in one place.

The app renders these values; resilience.consistency.check_view re-derives them independently.
"""
from __future__ import annotations

from .consistency import checks_alone, money, rw_text, verdict_kind
from .core import account_flags, apply_shock, backup_ladder, calendar_path, goal_plan, goal_shock_for
from .narrative import facts, template_story
from .shock_parser import STATE_KEYS, _checks_free, describe_shock, shock_from_state

CARD = ("I", "F", "S", "B", "H", "P", "Pn")


def active_checks(shock) -> list[str]:
    return [name for name, on in (("2026 EI cap", shock.income_cap_monthly is not None),
                                  ("waiting week", shock.waiting_week), ("pension kept", shock.pension_aware),
                                  ("half-year spending", shock.spending_basis == "S6"),
                                  ("bills by standing order", shock.bills_fallback)) if on]


def build_view(account_id: int, row, state: dict, chat: dict | None = None) -> dict:
    state = {k: state[k] for k in STATE_KEYS if k in state}
    target = int(state["target"])
    real_shock = shock_from_state(state, row)
    judge_shock = _checks_free(real_shock).with_(name=real_shock.name)
    judge = apply_shock(row, judge_shock)
    real = apply_shock(row, real_shock)
    jan = calendar_path(row, judge_shock)
    alone = checks_alone(row, judge_shock)
    active = active_checks(real_shock)
    goal_shock = goal_shock_for(real_shock)
    g = goal_plan(row, target_months=target, target_kind="ei_proof", shock=goal_shock)
    conv = goal_plan(row, target_months=3)
    lad = backup_ladder(row, real_shock, target_months=target)
    f = facts(int(account_id), row, judge_shock, judge,
              {"half-year spending": alone[0][1], "starting in January": jan}, lad, g.target_buffer, g.shortfall,
              g.months_to_target, target, plan_basis=", ".join(active))
    return {
        "account_id": int(account_id),
        "state": state,
        "target": target,
        "chat": chat,
        "engine_shock": real_shock,
        "judge_shock": judge_shock,
        "understood_as": describe_shock(real_shock, row, target),
        "twist_label": judge_shock.name,
        "card": {c: float(row[c]) for c in CARD},
        "card_text": {c: money(float(row[c])) for c in CARD},
        "flags": [code for code, _ in account_flags(row)],
        "flag_notes": account_flags(row),
        "judge": judge,
        "judge_text": rw_text(judge),
        "verdict": verdict_kind(row, judge, target),
        "real": real,
        "jan": jan,
        "checks_alone": [(n, (f"{v:.1f} mo" if v != float("inf") else "No shortfall (120+)")
                          if isinstance(v, float) else rw_text(v)) for n, v in alone],
        "active": active,
        "goal": g,
        "goal_shock": goal_shock,
        "conv": conv,
        "ladder": lad,
        "facts": f,
        "story": template_story(f),
    }
