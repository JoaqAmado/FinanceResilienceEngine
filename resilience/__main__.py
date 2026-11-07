"""Keyless command-line fallback for the live twist.

    python -m resilience 20143                       # baseline + the 3 README twists
    python -m resilience 20143 --income 0.55 --bills 0.15 --one-off-x-s 1 --target 6

Works offline with no API keys, so the demo survives if the UI or network fails.
"""
from __future__ import annotations

import argparse

from .core import (
    README_TWISTS,
    Shock,
    apply_shock,
    backup_plan,
    baseline_metrics,
    goal_plan,
    load_loans,
    load_monthly,
)


def money(x: float) -> str:
    return f"-${-x:,.0f}" if x < 0 else f"${x:,.0f}"


def months_text(res) -> str:
    return res.label if res.no_shortfall else f"{res.label} months"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("account_id", type=int)
    ap.add_argument("--income", type=float, help="income multiplier after the shock, e.g. 0.55 for EI")
    ap.add_argument("--income-cap", type=float, help="monthly ceiling on post-shock income (CAD)")
    ap.add_argument("--bills", type=float, help="household bills increase, e.g. 0.15")
    ap.add_argument("--extra", type=float, help="extra monthly cost (CAD)")
    ap.add_argument("--one-off", type=float, help="one-off cost (CAD)")
    ap.add_argument("--one-off-x-s", type=float, help="one-off cost as a multiple of S")
    ap.add_argument("--target", type=float, default=6.0, help="months the customer must survive")
    args = ap.parse_args()

    metrics = baseline_metrics(load_monthly(), load_loans())
    if args.account_id not in metrics.index:
        raise SystemExit(f"account {args.account_id} not found")
    r = metrics.loc[args.account_id]

    print(f"\nAccount {args.account_id}  ({int(r.months_of_data)} months: {r.first_month} to {r.last_month})")
    print("1. Know the customer")
    print(f"   I money in {money(r.I)}/mo   S spending {money(r.S)}/mo   F fixed {money(r.F)}/mo")
    print(f"   H household bills {money(r.H)}/mo   P loan payment {money(r.P)}/mo   B buffer {money(r.B)}")
    base = apply_shock(r, Shock())
    print(f"   Baseline runway: {months_text(base)}")

    shocks = list(README_TWISTS)
    custom = (args.income, args.income_cap, args.bills, args.extra, args.one_off, args.one_off_x_s)
    if any(v is not None for v in custom):  # 0 is a real value (e.g. --income 0)
        shocks = [Shock(income_multiplier=args.income if args.income is not None else 1.0,
                        income_cap_monthly=args.income_cap, bills_increase_pct=args.bills or 0.0,
                        extra_monthly_cost=args.extra or 0.0, one_off_cost=args.one_off or 0.0,
                        one_off_multiple_of_S=args.one_off_x_s or 0.0, name="Custom twist")]

    print("2. Take a shock")
    for s in shocks:
        res = apply_shock(r, s)
        verdict = "SURVIVES" if res.survives(args.target) else "DEPLETED"
        print(f"   {s.name}: runway {months_text(res)} -> {verdict} {args.target:g} months"
              f"  (income {money(res.income_after)}, spending {money(res.spending_after)},"
              f" buffer left {money(res.buffer_left)})")

    print("3. Make a plan")
    g = goal_plan(r, target_months=args.target)
    when = "already there" if g.shortfall == 0 else (
        f"{g.months_to_target} months at {money(g.monthly_surplus)}/mo surplus" if g.months_to_target
        else "not reachable from current surplus")
    print(f"   Goal plan: {args.target:g}-month emergency fund = {money(g.target_buffer)};"
          f" gap {money(g.shortfall)}; {when}")
    for s in shocks:
        b = backup_plan(r, s, target_months=args.target)
        if b.monthly_cut_needed == 0 and b.shocked.survives(args.target):
            print(f"   Backup ({s.name}): no cut needed")
            continue
        if b.buffer_wiped:
            rebuild = (f"; normal surplus {money(b.normal_surplus)}/mo rebuilds it in"
                       f" {b.cash_needed / b.normal_surplus:.1f} months" if b.normal_surplus > 0 else "")
            print(f"   Backup ({s.name}): the one-off wipes the buffer, so spending cuts alone can't help."
                  f" Cut {money(b.monthly_cut_needed)}/mo and cover {money(b.cash_needed)} from"
                  f" financing or credit -> runway {months_text(b.after_cut)}{rebuild}")
            continue
        share = f"{b.cut_share_of_flexible:.0%} of flexible spending" if b.cut_share_of_flexible is not None else "n/a"
        print(f"   Backup ({s.name}): cut {money(b.monthly_cut_needed)}/mo ({share};"
              f" pool {money(b.flexible_pool)}) -> runway {months_text(b.after_cut)}"
              f" {'(feasible)' if b.feasible else '(NOT feasible from flexible spending alone)'}")


if __name__ == "__main__":
    main()
