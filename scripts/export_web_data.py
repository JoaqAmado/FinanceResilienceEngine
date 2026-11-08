"""Export the engine's inputs and expected outputs for the TypeScript port in web/.

    .venv/bin/python scripts/export_web_data.py

Writes
    web/public/data/accounts.json        every account's engine inputs (columnar: fields + rows)
    web/public/data/portfolio.json       headline numbers + the chart tables of resilience.portfolio
    web/public/data/history/<id>.json    monthly money_in, money_out, month_end_balance per account
    web/test/vectors.json                outputs of the PYTHON engine that web/test/parity.test.ts
                                         must reproduce exactly

Floats are written with repr (shortest round-trip), so the browser parses the very
same doubles the Python engine used. NaN is written as null.
"""
from __future__ import annotations

import json
import math
import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from resilience import core as C  # noqa: E402
from resilience.narrative import facts, template_story  # noqa: E402
from resilience.portfolio import build_all  # noqa: E402

WEB = ROOT / "web"
DATA_OUT = WEB / "public" / "data"
VECTORS = WEB / "test" / "vectors.json"

EDGE_IDS = (32078, 20578, 26939, 20303, 20866, 21903, 75489, 91609, 98952, 88269, 77743,
            20331, 20143, 30508, 20134)
SEED = 20261108
SAMPLE_SIZE = 600
STORY_SIZE = 200
TARGETS = (3, 6, 12)

ACCOUNT_FIELDS = ("id", "I", "F", "S", "B", "H", "P", "Pn", "S6", "flexible_median", "bank_fees_median",
                  "transfers_out_other_median", "loan_payments_median", "so_other", "H_SO", "months_of_data",
                  "first_month", "last_month", "loan_status", "pre_loan_negative", "ever_negative",
                  "owner_age", "owner_gender", "cal")
NULLABLE = {"S6", "loan_status", "owner_age", "owner_gender"}
STRINGS = {"first_month", "last_month", "loan_status", "owner_gender"}
BOOLS = {"pre_loan_negative", "ever_negative"}

# Shocks the vectors cover. Keys are stable names the TS test uses.
SHOCKS = {
    "baseline": C.BASELINE,
    "ei55": C.LAID_OFF_EI,
    "ei55_cap": C.LAID_OFF_EI_CAPPED,
    "ei55_cap_ww": C.LAID_OFF_EI_CAPPED.with_(waiting_week=True),
    "ei55_pension": C.LAID_OFF_EI.with_(pension_aware=True),
    "ei55_s6": C.LAID_OFF_EI.with_(spending_basis="S6"),
    "furnace": C.FURNACE,
    "double_whammy": C.DOUBLE_WHAMMY,
    "pay_cut_70": C.Shock(income_multiplier=0.7, job_loss=False, name="Pay cut: income kept 70%"),
    "pay_cut_70_ww": C.Shock(income_multiplier=0.7, waiting_week=True, job_loss=False,
                             name="Pay cut 70% with the waiting week on (must be ignored)"),
    "custom_400_6000": C.Shock(extra_monthly_cost=400.0, one_off_cost=6000.0,
                               name="Custom: +$400/mo, one-off $6,000"),
    "bills_fallback": C.DOUBLE_WHAMMY.with_(bills_fallback=True),
    "kitchen_sink": C.Shock(income_multiplier=0.55, income_cap_monthly=C.EI_2026_MAX_MONTHLY,
                            bills_increase_pct=0.15, extra_monthly_cost=250.0, one_off_cost=1500.0,
                            one_off_multiple_of_S=0.5, flexible_cut_pct=0.2, waiting_week=True,
                            pension_aware=True, spending_basis="S6", bills_fallback=True, job_loss=True,
                            name="Everything at once"),
}
CALENDAR_SHOCKS = ("ei55", "furnace", "double_whammy", "kitchen_sink")
PLAN_SHOCKS = ("ei55", "furnace", "double_whammy", "pay_cut_70", "kitchen_sink")
GREY_SHOCKS = ("ei55", "ei55_s6", "furnace")
BALANCE_SHOCKS = ("ei55", "furnace", "double_whammy")
BALANCE_MONTHS = 12

# The app's twist cards (app.py PRESETS) as the shocks they apply.
PRESET_SHOCKS = {
    "Laid off: EI 55%": C.Shock(income_multiplier=55 / 100, job_loss=True, name="Laid off: EI 55%"),
    "Furnace dies: 1× spending": C.Shock(one_off_multiple_of_S=1.0, name="Furnace dies: 1× spending"),
    "Job loss + bills +15%": C.Shock(income_multiplier=55 / 100, bills_increase_pct=15 / 100, job_loss=True,
                                     name="Job loss + bills +15%"),
    "Custom": C.Shock(name="Custom: no shock"),
}
STORY_PRESETS = ("Laid off: EI 55%", "Furnace dies: 1× spending", "Job loss + bills +15%")
# reality toggles (cap, waiting week, pension kept, half-year spending, bills by standing order)
STORY_TOGGLES = ((False, False, False, False, False), (True, True, False, False, False),
                 (False, False, True, True, False), (True, True, True, True, True))


# ------------------------------------------------------------------ encoders

def fnum(v) -> float | None:
    if v is None:
        return None
    f = float(v)
    return None if math.isnan(f) else f


def finite_or_none(v: float) -> float | None:
    """Calendar paths: +inf (never runs out) is written as null."""
    return None if math.isinf(v) else float(v)


def account_row(acct: int, r: pd.Series) -> list:
    out = []
    for f in ACCOUNT_FIELDS:
        if f == "id":
            out.append(int(acct))
        elif f == "cal":
            out.append([fnum(r[f"cal_{m:02d}"]) for m in range(1, 13)])
        elif f in BOOLS:
            out.append(bool(r[f]))
        elif f == "months_of_data":
            out.append(int(r[f]))
        elif f in STRINGS:
            v = r[f]
            out.append(None if v is None or (isinstance(v, float) and math.isnan(v)) else str(v))
        else:
            out.append(fnum(r[f]))
        if out[-1] is None and f not in NULLABLE and f != "cal":
            raise ValueError(f"account {acct}: {f} is missing but the TS engine treats it as a number")
    return out


def shock_js(s: C.Shock) -> dict:
    return {"incomeMultiplier": s.income_multiplier, "incomeCapMonthly": s.income_cap_monthly,
            "billsIncreasePct": s.bills_increase_pct, "extraMonthlyCost": s.extra_monthly_cost,
            "oneOffCost": s.one_off_cost, "oneOffMultipleOfS": s.one_off_multiple_of_S,
            "flexibleCutPct": s.flexible_cut_pct, "waitingWeek": bool(s.waiting_week),
            "pensionAware": bool(s.pension_aware), "spendingBasis": s.spending_basis,
            "billsFallback": bool(s.bills_fallback), "jobLoss": bool(s.job_loss), "name": s.name}


def res_js(r: C.RunwayResult) -> list:
    """[months, noShortfall, bufferLeft, gap, incomeAfter, spendingAfter, oneOff, capped]"""
    return [fnum(r.months), bool(r.no_shortfall), float(r.buffer_left), float(r.gap), float(r.income_after),
            float(r.spending_after), float(r.one_off), bool(r.capped)]


def goal_js(g: C.GoalPlan) -> list:
    """[targetBuffer, currentBuffer, shortfall, monthlySurplus, monthsToTarget, targetKind]"""
    return [float(g.target_buffer), float(g.current_buffer), float(g.shortfall), float(g.monthly_surplus),
            fnum(g.months_to_target), g.target_kind]


def backup_js(b: C.BackupPlan) -> dict:
    return {"targetMonths": b.target_months, "shocked": res_js(b.shocked), "monthlyCutNeeded": float(b.monthly_cut_needed),
            "flexiblePool": float(b.flexible_pool), "cutShareOfFlexible": fnum(b.cut_share_of_flexible),
            "feasible": bool(b.feasible), "afterCut": res_js(b.after_cut), "bufferWiped": bool(b.buffer_wiped),
            "cashNeeded": float(b.cash_needed), "normalSurplus": float(b.normal_surplus)}


def ladder_js(lad: C.Ladder) -> dict:
    return {"targetMonths": lad.target_months, "shocked": res_js(lad.shocked), "alreadySafe": bool(lad.already_safe),
            "bufferWiped": bool(lad.buffer_wiped), "overdrawn": bool(lad.overdrawn),
            "rungs": [[x.step, float(x.monthly_saving), res_js(x.result), bool(x.reaches_target)] for x in lad.rungs],
            "firstSufficient": lad.first_sufficient, "cashOrCreditNeeded": float(lad.cash_or_credit_needed),
            "verdict": lad.verdict}


def plan_path(lad: C.Ladder, months: int) -> list[float]:
    """The TS chart helper planPath, mirrored here so the port is checked against an independent copy.

    Balance month by month under the judges' constant-gap model once the backup plan is in place:
    already safe -> the shocked path; buffer wiped -> the cash or credit is added at month 0;
    otherwise the first rung that reaches the target (or the last rung plus the cash still needed).
    """
    s = lad.shocked
    if lad.already_safe:
        start, gap = s.buffer_left, s.gap
    elif lad.buffer_wiped or not lad.rungs:
        start, gap = s.buffer_left + lad.cash_or_credit_needed, s.gap
    else:
        i = lad.first_sufficient if lad.first_sufficient is not None else len(lad.rungs) - 1
        res = lad.rungs[i].result
        extra = 0.0 if lad.first_sufficient is not None else lad.cash_or_credit_needed
        start, gap = res.buffer_left + extra, res.gap
    return [float(start - gap * t) for t in range(months + 1)]


def records(df: pd.DataFrame) -> list[dict]:
    out = []
    for row in df.to_dict(orient="records"):
        rec = {}
        for k, v in row.items():
            if isinstance(v, (np.integer,)):
                v = int(v)
            elif isinstance(v, (np.floating, float)):
                v = None if math.isnan(v) else float(v)
            elif isinstance(v, (np.bool_,)):
                v = bool(v)
            elif v is not None and not isinstance(v, (int, str, bool)):
                v = str(v)
            rec[str(k)] = v
        out.append(rec)
    return out


def _np_default(o):
    """numpy scalars that slip through (e.g. a numpy bool from `r.Pn > 0`) as plain JSON values."""
    if isinstance(o, np.bool_):
        return bool(o)
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.floating):
        return float(o)
    raise TypeError(f"Object of type {type(o).__name__} is not JSON serializable")


def dump(path: Path, obj, indent: int | None = None) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(obj, allow_nan=False, ensure_ascii=False, separators=(",", ":") if indent is None else None,
                      indent=indent, default=_np_default)
    path.write_text(text, encoding="utf-8")
    return len(text.encode("utf-8"))


# ------------------------------------------------------------------ cases

def story_case(acct: int, r: pd.Series, preset: str, N: int, toggles: tuple) -> dict:
    """The app's live-twist pipeline (app.py), from twist card + toggles to the template story."""
    judge_shock = PRESET_SHOCKS[preset]
    cap, ww, pens, s6, bfb = toggles
    job_loss = judge_shock.is_job_loss
    can_pension = job_loss and r.Pn > 0
    can_bills = r.H == 0 and r.H_SO > 0
    cap, ww, pens, bfb = cap and job_loss, ww and job_loss, pens and can_pension, bfb and can_bills
    real_shock = judge_shock.with_(income_cap_monthly=C.EI_2026_MAX_MONTHLY if cap else None, waiting_week=ww,
                                   pension_aware=pens, spending_basis="S6" if s6 else "S", bills_fallback=bfb)
    judge = C.apply_shock(r, judge_shock)
    jan = C.calendar_path(r, judge_shock)
    active = [name for name, on in (("2026 EI cap", cap), ("waiting week", ww), ("pension kept", pens),
                                    ("half-year spending", s6), ("bills by standing order", bfb)) if on]
    g = C.goal_plan(r, target_months=N, target_kind="ei_proof", shock=C.goal_shock_for(real_shock))
    lad = C.backup_ladder(r, real_shock, target_months=N)
    f = facts(int(acct), r, judge_shock, judge,
              {"half-year spending": C.apply_shock(r, judge_shock.with_(spending_basis="S6")),
               "starting in January": jan}, lad, g.target_buffer, g.shortfall, g.months_to_target, N,
              plan_basis=", ".join(active))
    return {"id": int(acct), "preset": preset, "target": N, "judgeShock": shock_js(judge_shock),
            "realShock": shock_js(real_shock), "planBasis": ", ".join(active), "facts": f,
            "story": template_story(f)}


def format_cases(m: pd.DataFrame, rng: np.random.Generator) -> list[list]:
    """Python's own formatting and rounding on ties, extremes and real account values."""
    xs = [0.0, -0.0, 0.5, 1.5, 2.5, -2.5, 0.25, 0.75, 1.25, 0.125, 0.375, 2.675, 1.005, 0.05, 0.15, 0.35,
          23.4, 99.95, 119.95, 120.0, 999999.5, 123456.5, 1234565.0, 1234567.8, 1e16, 1e-5, 0.00012345,
          0.819, 0.423, 0.231, 3159.0, 1e6, 12.0, 6.0, 0.1, 12345.678, -1234.5, -0.4, -0.6]
    xs += [k + 0.5 for k in range(-6, 40)]
    xs += [k / 4 for k in range(-12, 60)]
    xs += [k / 8 for k in range(0, 40)]
    for col in ("I", "S", "B", "H", "S6", "flexible_median", "owner_age"):
        xs += [float(v) for v in m[col].dropna().sample(40, random_state=SEED).to_numpy()]
    xs += [float(v) for v in rng.uniform(-50000, 50000, 200)]
    xs += [float(v) for v in rng.uniform(0, 130, 200)]
    out = []
    for x in xs:
        out.append([x, f"{x:,.0f}", f"{x:.0f}", f"{x:.1f}", f"{x:g}", round(x, 2), float(np.round(x, 1)),
                    f"{x:.0%}"])
    return out


def main() -> None:
    m = C.build_metrics()
    monthly = C.load_monthly()
    ids = [int(i) for i in m.index]
    rows = {a: m.loc[a] for a in ids}
    missing = [a for a in EDGE_IDS if a not in rows]
    if missing:
        raise SystemExit(f"edge accounts missing from the data: {missing}")
    for name, s in PRESET_SHOCKS.items():  # the app divides slider percents by 100
        assert s.income_multiplier in (1.0, 0.55) and s.bills_increase_pct in (0.0, 0.15), name

    # ------------------------------------------------ public data
    DATA_OUT.mkdir(parents=True, exist_ok=True)
    acc_bytes = dump(DATA_OUT / "accounts.json",
                     {"version": 1, "fields": list(ACCOUNT_FIELDS), "rows": [account_row(a, rows[a]) for a in ids]})

    tables = build_all(m)
    acc_table = tables.pop("accounts")
    headlines = records(tables.pop("headlines"))[0]
    port = {"version": 1, "headlines": headlines, **{k: records(v) for k, v in tables.items()},
            "runway_columns": [c for c in acc_table.columns if c.startswith("runway_")]}
    port_bytes = dump(DATA_OUT / "portfolio.json", port)

    hist_dir = DATA_OUT / "history"
    if hist_dir.exists():
        shutil.rmtree(hist_dir)
    hist_dir.mkdir(parents=True)
    hist_bytes = 0
    for a, h in monthly.groupby("account_id", sort=True):
        hist_bytes += dump(hist_dir / f"{int(a)}.json", {
            "id": int(a), "month": h["month"].astype(str).tolist(),
            "money_in": [float(v) for v in h["money_in"]], "money_out": [float(v) for v in h["money_out"]],
            "month_end_balance": [float(v) for v in h["month_end_balance"]]})

    # ------------------------------------------------ samples
    rng = np.random.default_rng(SEED)
    sample: list[int] = list(EDGE_IDS)
    flag_codes = {a: [c for c, _ in C.account_flags(rows[a])] for a in ids}
    for code in sorted({c for cs in flag_codes.values() for c in cs}):  # a few of every flag
        have = [a for a in ids if code in flag_codes[a] and a not in sample]
        for a in rng.permutation(have)[:5]:
            sample.append(int(a))
    rest = [a for a in ids if a not in set(sample)]
    sample += [int(a) for a in rng.choice(rest, SAMPLE_SIZE - len(sample), replace=False)]
    assert len(sample) == len(set(sample)) == SAMPLE_SIZE
    story_ids = list(EDGE_IDS) + [int(a) for a in rng.choice([a for a in sample if a not in EDGE_IDS],
                                                             STORY_SIZE - len(EDGE_IDS), replace=False)]

    # ------------------------------------------------ vectors
    vec: dict = {"meta": {"seed": SEED, "numpy": np.__version__, "pandas": pd.__version__,
                          "accounts": len(ids), "sample": SAMPLE_SIZE, "story_accounts": STORY_SIZE,
                          "edge_ids": list(EDGE_IDS), "targets": list(TARGETS),
                          "result_layout": "[months, noShortfall, bufferLeft, gap, incomeAfter, spendingAfter, oneOff, capped]",
                          "goal_layout": "[targetBuffer, currentBuffer, shortfall, monthlySurplus, monthsToTarget, targetKind]"},
           "constants": {"RUNWAY_CAP_MONTHS": C.RUNWAY_CAP_MONTHS, "EI_2026_MAX_MONTHLY": C.EI_2026_MAX_MONTHLY,
                         "EI_2026_MAX_WEEKLY": C.EI_2026_MAX_WEEKLY, "WEEKS_PER_MONTH": C.WEEKS_PER_MONTH,
                         "NO_SHORTFALL_LABEL": C.NO_SHORTFALL_LABEL},
           "named_shocks": {"BASELINE": shock_js(C.BASELINE), "LAID_OFF_EI": shock_js(C.LAID_OFF_EI),
                            "LAID_OFF_EI_CAPPED": shock_js(C.LAID_OFF_EI_CAPPED), "FURNACE": shock_js(C.FURNACE),
                            "DOUBLE_WHAMMY": shock_js(C.DOUBLE_WHAMMY)},
           "presets": {k: shock_js(v) for k, v in PRESET_SHOCKS.items()},
           "shocks": {k: shock_js(v) for k, v in SHOCKS.items()},
           "ids": ids}

    vec["applyShock"] = {k: [res_js(C.apply_shock(rows[a], s)) for a in ids] for k, s in SHOCKS.items()}
    vec["flags"] = [C.account_flags(rows[a]) for a in ids]
    vec["loanInTrouble"] = [C.loan_in_trouble(rows[a]) for a in ids]
    vec["greyZone"] = {k: [C.grey_zone_note(C.apply_shock(rows[a], SHOCKS[k]), SHOCKS[k]) for a in ids]
                       for k in GREY_SHOCKS}
    vec["greyZoneNoShock"] = [C.grey_zone_note(C.apply_shock(rows[a], SHOCKS["ei55_s6"])) for a in ids]

    cal = []
    for a in sample:
        for k in CALENDAR_SHOCKS:
            cal.append([a, k, 1, finite_or_none(C.calendar_path(rows[a], SHOCKS[k], 1))])
        start = a % 12 + 1
        cal.append([a, "ei55", start, finite_or_none(C.calendar_path(rows[a], SHOCKS["ei55"], start))])
    vec["calendarPath"] = cal

    plans = []
    for a in sample:
        r = rows[a]
        for k in PLAN_SHOCKS:
            s = SHOCKS[k]
            gs = C.goal_shock_for(s)  # depends on the shock only: checked once in vec["goalShockFor"]
            for t in TARGETS:
                lad = C.backup_ladder(r, s, target_months=t)
                plans.append({
                    "id": a, "shock": k, "t": t,
                    "goalS": goal_js(C.goal_plan(r, target_months=t, target_kind="months_of_S")),
                    "goalEI": goal_js(C.goal_plan(r, target_months=t, target_kind="ei_proof", shock=gs)),
                    "backup": backup_js(C.backup_plan(r, s, target_months=t)),
                    "ladder": ladder_js(lad),
                    "credit": (C.credit_advice(r, lad.cash_or_credit_needed, job_loss=s.is_job_loss)
                               if lad.cash_or_credit_needed else None),
                    "planPath": plan_path(lad, BALANCE_MONTHS),
                })
    vec["plans"] = plans
    vec["goalShockFor"] = {k: shock_js(C.goal_shock_for(s)) for k, s in SHOCKS.items()}

    bal = []
    for a in sample:
        for k in BALANCE_SHOCKS:
            res = C.apply_shock(rows[a], SHOCKS[k])
            bal.append([a, k, BALANCE_MONTHS, [float(res.buffer_left - res.gap * t) for t in range(BALANCE_MONTHS + 1)]])
    vec["balancePath"] = bal

    stories = []
    for i, a in enumerate(story_ids):
        N = TARGETS[i % 3]
        toggles = STORY_TOGGLES[(i // 3) % len(STORY_TOGGLES)]
        for p in STORY_PRESETS:
            stories.append(story_case(a, rows[a], p, N, toggles))
    vec["stories"] = stories
    vec["format"] = format_cases(m, rng)

    vec["meta"]["counts"] = {
        "applyShock": len(ids) * len(SHOCKS), "flags": len(ids), "calendarPath": len(cal), "plans": len(plans),
        "balancePath": len(bal), "stories": len(stories), "format": len(vec["format"]),
    }
    vec_bytes = dump(VECTORS, vec)

    mb = lambda n: f"{n / 1e6:.1f} MB"  # noqa: E731
    print(f"accounts.json   {len(ids)} accounts, {mb(acc_bytes)}")
    print(f"portfolio.json  headlines + {len(tables)} tables, {mb(port_bytes)}")
    print(f"history/        {monthly['account_id'].nunique()} files, {mb(hist_bytes)}")
    print(f"vectors.json    {vec['meta']['counts']}, {mb(vec_bytes)}")


if __name__ == "__main__":
    main()
