"""Keyless command-line fallback for the live twist.

    python -m resilience 20143                       # baseline + the 3 README twists
    python -m resilience 20143 --income 0.55 --bills 0.15 --one-off-x-s 1 --target 6
    python -m resilience 98952 --income 0.55 --pension-aware --cap --waiting-week

Works offline with no API keys, so the demo survives if the UI or network fails.
The judges' number always comes first; reality checks are printed next to it.
"""
from __future__ import annotations

import argparse
import math

from .core import (
    EI_2026_MAX_MONTHLY,
    README_TWISTS,
    Shock,
    account_flags,
    apply_shock,
    credit_advice,
    backup_ladder,
    build_metrics,
    calendar_path,
    goal_plan,
    goal_shock_for,
    grey_zone_note,
)


def money(x: float) -> str:
    x = 0.0 if abs(x) < 0.5 else x
    return f"-${-x:,.0f}" if x < 0 else f"${x:,.0f}"


def months_text(res) -> str:
    if res.no_shortfall:
        return res.label
    return f"{res.months:.1f} months (cap)" if res.capped else f"{res.label} months"


def path_text(x: float) -> str:
    return "no shortfall (120+)" if math.isinf(x) else f"{x:.1f} months"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("account_id", type=int)
    ap.add_argument("--income", type=float, help="income multiplier after the shock, e.g. 0.55 for EI")
    ap.add_argument("--income-cap", type=float,
                    help="reality check: monthly EI ceiling in CAD (a custom --cap); never changes the judges' number")
    ap.add_argument("--bills", type=float, help="household bills increase, e.g. 0.15")
    ap.add_argument("--extra", type=float, help="extra monthly cost (CAD)")
    ap.add_argument("--one-off", type=float, help="one-off cost (CAD)")
    ap.add_argument("--one-off-x-s", type=float, help="one-off cost as a multiple of S")
    ap.add_argument("--target", type=float, default=6.0, help="months the customer must survive")
    ap.add_argument("--pay-cut", action="store_true",
                    help="the --income drop is a pay cut or reduced hours, not a layoff on EI")
    ap.add_argument("--cap", action="store_true", help=f"plans use the 2026 EI cap (${EI_2026_MAX_MONTHLY:,.0f}/mo)")
    ap.add_argument("--waiting-week", action="store_true", help="plans include one unpaid EI week")
    ap.add_argument("--pension-aware", action="store_true", help="plans keep pension income on a job loss")
    ap.add_argument("--bills-fallback", action="store_true", help="plans count household bills paid by standing order")
    args = ap.parse_args()
    # fail loudly on inputs that would print a confident but wrong runway
    for flag in ("income", "income_cap", "bills", "extra", "one_off", "one_off_x_s", "target"):
        v = getattr(args, flag)
        if v is not None and not math.isfinite(v):
            ap.error(f"--{flag.replace('_', '-')} must be a number")
    if args.target <= 0:
        ap.error("--target must be above 0 months")
    if args.one_off_x_s is not None and args.one_off_x_s < 0:
        ap.error("--one-off-x-s can't be negative; for a windfall use a negative --one-off")
    if args.pay_cut and (args.income is None or args.income >= 1):
        ap.error("--pay-cut needs --income below 1 (e.g. --income 0.7 --pay-cut)")
    if args.cap and args.income_cap is not None:
        ap.error("use either --cap (the 2026 EI maximum) or --income-cap, not both")
    if args.income is not None and not 0 <= args.income <= 2:
        ap.error(f"--income {args.income:g} looks like a percent; pass a fraction, e.g. 0.55 for EI at 55%")
    if args.bills is not None and not 0 <= args.bills <= 1:
        ap.error(f"--bills {args.bills:g} looks like a percent; pass a fraction, e.g. 0.15 for +15%")
    if args.income_cap is not None and (args.income_cap < 0 or args.income is None or args.income >= 1 or args.pay_cut):
        ap.error("--income-cap only applies to a job loss (--income below 1). For the 2026 EI cap use --cap")

    metrics = build_metrics()
    if args.account_id not in metrics.index:
        raise SystemExit(f"account {args.account_id} not found")
    r = metrics.loc[args.account_id]
    N = args.target

    print(f"\nAccount {args.account_id}  ({int(r.months_of_data)} months: {r.first_month} to {r.last_month})")
    print("1. Know the customer")
    print(f"   I money in {money(r.I)}/mo   S spending {money(r.S)}/mo   F fixed {money(r.F)}/mo")
    print(f"   H household bills {money(r.H)}/mo   P loan payment {money(r.P)}/mo   B buffer {money(r.B)}")
    base = apply_shock(r, Shock())
    cushion = f"   buffer = {r.B / r.S:.1f} months of spending" if r.S > 0 else ""
    print(f"   Baseline runway: {months_text(base)}{cushion}")
    for _, note in account_flags(r):
        print(f"   ! {note}")

    shocks = list(README_TWISTS)
    custom = (args.income, args.income_cap, args.bills, args.extra, args.one_off, args.one_off_x_s)
    if any(v is not None for v in custom):  # 0 is a real value (e.g. --income 0)
        income = args.income if args.income is not None else 1.0
        shocks = [Shock(income_multiplier=income, bills_increase_pct=args.bills or 0.0,
                        extra_monthly_cost=args.extra or 0.0, one_off_cost=args.one_off or 0.0,
                        one_off_multiple_of_S=args.one_off_x_s or 0.0,
                        job_loss=income < 1 and not args.pay_cut, name="Custom twist")]

    print("2. Take a shock (judges' formula first, then reality checks)")
    for s in shocks:
        res = apply_shock(r, s)
        verdict = "SURVIVES" if res.survives(N) else "DEPLETED"
        print(f"   {s.name}: runway {months_text(res)} -> {verdict} {N:g} months"
              f"  (income {money(res.income_after)}, spending {money(res.spending_after)},"
              f" buffer left {money(res.buffer_left)})")
        note = grey_zone_note(res, s)
        if note:
            print(f"     ~ {note}")
        checks = [("typical half-year spending", s.with_(spending_basis="S6"))]
        if s.is_job_loss:
            if args.income_cap is not None:
                checks.append((f"income cap ${args.income_cap:,.0f}/mo", s.with_(income_cap_monthly=args.income_cap)))
            checks += [("2026 EI cap", s.with_(income_cap_monthly=EI_2026_MAX_MONTHLY)),
                       ("cap + waiting week", s.with_(income_cap_monthly=EI_2026_MAX_MONTHLY, waiting_week=True))]
            if r.Pn > 0:
                checks.append(("pension-aware", s.with_(pension_aware=True)))
        if s.bills_increase_pct and r.H == 0 and r.get("H_SO", 0) > 0:
            checks.append(("bills paid by standing order", s.with_(bills_fallback=True)))
        reality = "; ".join(f"{name} {months_text(apply_shock(r, sh))}" for name, sh in checks)
        print(f"     reality: {reality}; starting in January {path_text(calendar_path(r, s))}")

    def plan_shock(s: Shock) -> Shock:
        # reality options apply to job losses only, exactly as the app gates its toggles
        jl = s.is_job_loss
        cap = (EI_2026_MAX_MONTHLY if args.cap else args.income_cap) if jl else None
        return s.with_(income_cap_monthly=cap, waiting_week=args.waiting_week and jl,
                       pension_aware=args.pension_aware and jl and r.Pn > 0, bills_fallback=args.bills_fallback)

    print("3. Make a plan" + (" (with your reality options)" if (args.cap or args.income_cap is not None
                                                                or args.waiting_week or args.pension_aware
                                                                or args.bills_fallback) else ""))
    g = goal_plan(r, target_months=N, target_kind="ei_proof", shock=goal_shock_for(plan_shock(shocks[0])))
    conv = goal_plan(r, target_months=3, target_kind="months_of_S")
    when = "already there" if g.shortfall == 0 else (
        f"{g.months_to_target} months at {money(g.monthly_surplus)}/mo surplus" if g.months_to_target
        else "not reachable from the current surplus")
    print(f"   Goal plan: job-loss-proof fund for {N:g} months = {money(g.target_buffer)}"
          f" (3 months of spending = {money(conv.target_buffer)}); gap {money(g.shortfall)}; {when}")
    if g.shortfall == 0 and g.target_buffer - g.current_buffer >= 0.5:
        print(f"     within rounding: {money(g.target_buffer - g.current_buffer)} under the exact target")
    for s in shocks:
        s2 = plan_shock(s)
        lad = backup_ladder(r, s2, target_months=N)
        print(f"   Backup ({s2.name}): {lad.verdict}")
        if lad.rungs:
            stop = lad.first_sufficient if lad.first_sufficient is not None else len(lad.rungs) - 1
            for rung in lad.rungs[: stop + 1]:
                mark = "OK" if rung.reaches_target else "  "
                print(f"     {mark} {rung.step}: save {money(rung.monthly_saving)}/mo -> {months_text(rung.result)}")
        if lad.cash_or_credit_needed:
            print(f"     {credit_advice(r, lad.cash_or_credit_needed, job_loss=s2.is_job_loss)}")


if __name__ == "__main__":
    main()
