"""Every number on screen agrees with every other number and with the data.

    issues = check_view(row, shock, target, results)   # [] when the view is consistent

`check_view` runs on every rerun of the app and on test views. It re-derives each number the Live twist tab shows,
independently where it can (straight from data/raw/ with the judges' definitions, or with the runway formula
written out again here), and returns one Issue per broken invariant:

1 input -> shock         the engine's Shock = the one built from the levers = the chat's; the labels describe it
2 customer card -> data  I, F, S, B, H, P, Pn = build_metrics() = a recomputation from the raw CSVs (to $0.01)
3 runway -> formula      the judges' runway = runway(B - one-off, spending after - income after); labels agree
4 runway -> chart        the burn-down crosses $0 at the runway; the January path matches a month-by-month rerun
5 plan -> runway         the ladder rung marked as reaching the target does, the one before it doesn't;
                         the goal's target buffer passes; the shortfall is target buffer - B, floored
6 reality checks         each "check alone" runway is the engine with only that check on; disabled checks are off
7 narrative -> numbers   every number in the story is in the computed facts
9 flags -> data          each warning flag on the card is true in the raw data

Invariant 8 (portfolio -> engine -> data/derived -> README) is `check_portfolio`, run by the tests only.
"""
from __future__ import annotations

import csv
import math
import re
import statistics
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from .core import (
    DATA_DIR,
    DATA_END_MONTH,
    DEFAULTED_LOAN_STATUSES,
    EI_2026_MAX_MONTHLY,
    RUNNING_LOAN_STATUSES,
    RunwayResult,
    Shock,
    _get,
    apply_shock,
    calendar_path,
    runway,
)
from .narrative import numbers_ok
from .shock_parser import (
    STATE_KEYS,
    _checks_free,
    can_bills_fallback,
    describe_shock,
    same_shock,
    shock_from_state,
)

MONEY_TOL = 0.01
CARD_FIELDS = ("I", "F", "S", "B", "H", "P", "Pn")
ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Issue:
    check: str      # e.g. "2 customer card -> data"
    detail: str

    def __str__(self) -> str:
        return f"{self.check}: {self.detail}"


# ------------------------------------------------------------------ how the app writes numbers (one place)

def money(x: float) -> str:
    x = 0.0 if abs(x) < 0.5 else x
    return f"-${-x:,.0f}" if x < 0 else f"${x:,.0f}"


def rw_text(res: RunwayResult) -> str:
    if res.no_shortfall:
        return "No shortfall (120+)"
    return "120.0 mo (cap)" if res.months >= 120 else f"{res.months:.1f} mo"


def path_text(x: float) -> str:
    return "No shortfall (120+)" if math.isinf(x) else f"{x:.1f} mo"


def checks_alone(row, judge_shock: Shock) -> list[tuple[str, RunwayResult | float]]:
    """The "each check alone" rows: the judges' twist with exactly one reality check on."""
    rows: list[tuple[str, RunwayResult | float]] = [
        ("Half-year spending", apply_shock(row, judge_shock.with_(spending_basis="S6"))),
        ("Starting in January (month by month)", calendar_path(row, judge_shock))]
    if judge_shock.is_job_loss:
        rows += [("2026 EI cap", apply_shock(row, judge_shock.with_(income_cap_monthly=EI_2026_MAX_MONTHLY))),
                 ("2026 cap + waiting week, once the waiver ends",
                  apply_shock(row, judge_shock.with_(income_cap_monthly=EI_2026_MAX_MONTHLY, waiting_week=True)))]
        if float(_get(row, "Pn")) > 0:
            rows.append(("Pension kept", apply_shock(row, judge_shock.with_(pension_aware=True))))
    return rows


def verdict_kind(row, judge: RunwayResult, target: float) -> str:
    """Which verdict box the app shows under the judges' runway."""
    if judge.survives(target):
        return "survives"
    if float(row["B"]) <= 0:
        return "overdrawn"
    if judge.buffer_left <= 0:
        return "buffer_gone"
    return "runs_out"


# ------------------------------------------------------------------ independent recomputation from data/raw/

@lru_cache(maxsize=2)
def _raw(data_dir: str = str(DATA_DIR)) -> dict:
    """Per-account columns read with the csv module (no pandas, no engine code), and the loans and standing orders."""
    d = Path(data_dir)
    cols = ("month", "money_in", "money_out", "household_bills", "insurance", "loan_payments", "avg_daily_balance",
            "pension_in", "days_below_zero")
    by: dict[int, dict[str, list]] = {}
    with open(d / "monthly_summary.csv", newline="") as fh:
        for r in csv.DictReader(fh):
            a = by.setdefault(int(r["account_id"]), {c: [] for c in cols})
            for c in cols:
                a[c].append(r[c] if c == "month" else float(r[c]))
    for a in by.values():  # by month, as the judges' "last 6 rows" means
        order = sorted(range(len(a["month"])), key=lambda i: a["month"][i])
        for c in cols:
            a[c] = [a[c][i] for i in order]
    loans = {}
    with open(d / "loans.csv", newline="") as fh:
        for r in csv.DictReader(fh):
            loans[int(r["account_id"])] = {"status": r["status"], "monthly_payment": float(r["monthly_payment"]),
                                           "loan_start": r["loan_start"]}
    so_bills: dict[int, float] = {}
    with open(d / "standing_orders.csv", newline="") as fh:
        for r in csv.DictReader(fh):
            if r.get("purpose") == "household bills":
                so_bills[int(r["account_id"])] = so_bills.get(int(r["account_id"]), 0.0) + float(r["amount"])
    return {"monthly": by, "loans": loans, "so_bills": so_bills}


def raw_account(account_id: int, data_dir: Path | str = DATA_DIR) -> dict:
    """The judges' numbers and the flag facts for one account, recomputed from the raw CSVs."""
    raw = _raw(str(data_dir))
    a = raw["monthly"][int(account_id)]
    fixed = [h + i + lp for h, i, lp in zip(a["household_bills"], a["insurance"], a["loan_payments"])]
    loan = raw["loans"].get(int(account_id))
    P = loan["monthly_payment"] if loan and loan["status"] in RUNNING_LOAN_STATUSES else 0.0
    pre_loan_negative = False
    if loan:
        start = loan["loan_start"][:7]
        pre_loan_negative = any(m < start and z > 0 for m, z in zip(a["month"], a["days_below_zero"]))
    return {
        "I": statistics.median(a["money_in"]), "F": statistics.median(fixed), "S": statistics.median(a["money_out"]),
        "B": statistics.fmean(a["avg_daily_balance"][-6:]), "H": statistics.median(a["household_bills"]),
        "P": P, "Pn": statistics.median(a["pension_in"]),
        "last_month": a["month"][-1], "loan_status": loan["status"] if loan else None,
        "pre_loan_negative": pre_loan_negative, "H_SO": raw["so_bills"].get(int(account_id), 0.0),
    }


def _judges_formula(row, shock: Shock) -> RunwayResult:
    """The published runway, written out again with no engine code (judges' levers only, no reality checks)."""
    I, S, H, B = (float(_get(row, c)) for c in ("I", "S", "H", "B"))
    income_after = shock.income_multiplier * I
    spending_after = (S + shock.bills_increase_pct * H + shock.extra_monthly_cost
                      - shock.flexible_cut_pct * float(_get(row, "flexible_median")))
    one_off = shock.one_off_cost + shock.one_off_multiple_of_S * S
    buffer_left = B - one_off
    gap = spending_after - income_after
    if buffer_left <= 0:
        return RunwayResult(0.0, False, buffer_left, gap, income_after, spending_after, one_off)
    if gap <= 0:
        return RunwayResult(None, True, buffer_left, gap, income_after, spending_after, one_off)
    return RunwayResult(float(np.round(min(buffer_left / gap, 120.0), 1)), False, buffer_left, gap, income_after,
                        spending_after, one_off)


def _january_path(row, shock: Shock, start_month: int = 1, horizon: int = 120) -> float:
    """Month by month from January, each month costing that account's median spending for its calendar month."""
    I, S, H, B = (float(_get(row, c)) for c in ("I", "S", "H", "B"))
    income = shock.income_multiplier * I
    addons = shock.bills_increase_pct * H + shock.extra_monthly_cost - shock.flexible_cut_pct * float(
        _get(row, "flexible_median"))
    bal = B - (shock.one_off_cost + shock.one_off_multiple_of_S * S)
    if bal <= 0:
        return 0.0
    cal = []
    for m in range(1, 13):
        v = _get(row, f"cal_{m:02d}", S)
        cal.append(S if v is None or (isinstance(v, float) and math.isnan(v)) else float(v))
    for k in range(horizon):
        spend = cal[(start_month - 1 + k) % 12] + addons
        if bal + income - spend < 0:
            return float(np.round(k + bal / (spend - income), 1))
        bal += income - spend
    return math.inf


# ------------------------------------------------------------------ the view check

def _close(a: float, b: float, tol: float = MONEY_TOL) -> bool:
    return abs(float(a) - float(b)) <= tol + 1e-9


def check_view(row, shock: Shock, target: float, results: dict) -> list[Issue]:
    """Assert the invariants for the account and shock being shown. `shock` is the full Shock the engine runs (levers
    plus reality checks); `results` holds what the view displayed (any missing key skips the checks that need it)."""
    out: list[Issue] = []

    def bad(check: str, detail: str) -> None:
        out.append(Issue(check, detail))

    judge_shock = _checks_free(shock)

    # 1 input -> shock
    c1 = "1 input -> shock"
    state = results.get("state")
    if state is not None:
        built = shock_from_state(state, row)
        if not same_shock(built, shock):
            bad(c1, f"the engine ran {describe_shock(shock)!r} but the levers say {describe_shock(built)!r}")
    if "judge_shock" in results and not same_shock(results["judge_shock"], judge_shock):
        bad(c1, "the judges' runway was computed on a different twist than the levers")
    chat = results.get("chat")
    if chat and state is not None and chat.get("account_id") == results.get("account_id") and \
            chat.get("state") == {k: state.get(k) for k in STATE_KEYS}:
        if not same_shock(chat["shock"], shock):
            bad(c1, f"the chat produced {describe_shock(chat['shock'])!r} but the engine ran {describe_shock(shock)!r}")
        if "understood_as" in chat and chat["understood_as"] != describe_shock(shock, row, target):
            bad(c1, "the chat's 'understood as' line describes a different shock")
    if "understood_as" in results and results["understood_as"] != describe_shock(shock, row, target):
        bad(c1, f"the current-shock line {results['understood_as']!r} doesn't describe the engine's shock")
    if "twist_label" in results and results["twist_label"] != describe_shock(judge_shock):
        bad(c1, f"the twist label {results['twist_label']!r} doesn't describe the engine's shock")

    # 2 customer card -> data
    c2 = "2 customer card -> data"
    card = results.get("card")
    if card is not None:
        acct = results.get("account_id", getattr(row, "name", None))
        indep = raw_account(acct) if acct is not None else None
        for f in CARD_FIELDS:
            shown = float(card[f])
            if not _close(shown, float(row[f])):
                bad(c2, f"{f} shown {shown:,.2f} but build_metrics() has {float(row[f]):,.2f}")
            if indep is not None and not _close(shown, indep[f]):
                bad(c2, f"{f} shown {shown:,.2f} but the raw CSVs give {indep[f]:,.2f}")
            text = (results.get("card_text") or {}).get(f)
            if text is not None and indep is not None and text != money(indep[f]):
                bad(c2, f"{f} reads {text} but the raw CSVs give {money(indep[f])}")

    # 3 runway -> formula
    c3 = "3 runway -> formula"
    judge = results.get("judge")
    want = _judges_formula(row, judge_shock)
    if judge is not None:
        if (judge.no_shortfall, judge.months) != (want.no_shortfall, want.months):
            bad(c3, f"judges' runway {judge.label} but the formula gives {want.label}")
        for f in ("buffer_left", "gap", "income_after", "spending_after", "one_off"):
            if not _close(getattr(judge, f), getattr(want, f)):
                bad(c3, f"{f} {getattr(judge, f):,.2f} but the formula gives {getattr(want, f):,.2f}")
    if "judge_text" in results and results["judge_text"] != rw_text(want):
        bad(c3, f"the runway reads {results['judge_text']!r} but the formula gives {rw_text(want)!r}")
    if "verdict" in results:
        kind = verdict_kind(row, want, target)
        if results["verdict"] != kind:
            bad(c3, f"the verdict box says {results['verdict']!r} but the numbers say {kind!r}")
        if want.no_shortfall and not (want.gap <= 0 < want.buffer_left):
            bad(c3, "'no shortfall' shown without a non-positive gap and a buffer left")

    # 4 runway -> chart
    c4 = "4 runway -> chart"
    if not want.no_shortfall and want.months and 0 < want.months < 120:
        crossing = want.buffer_left - want.months * want.gap   # the burn-down's balance at the runway
        if abs(crossing) > 0.05 * want.gap + MONEY_TOL:
            bad(c4, f"the buffer is {crossing:,.2f} at month {want.months}, not $0 within one rounding step")
    if "jan" in results:
        ind = _january_path(row, judge_shock)
        shown = results["jan"]
        if not ((math.isinf(ind) and math.isinf(shown)) or (not math.isinf(ind) and not math.isinf(shown)
                                                           and abs(ind - shown) <= 0.1 + 1e-9)):
            bad(c4, f"January path {path_text(shown)} but a month-by-month rerun gives {path_text(ind)}")
    if "chart" in results:   # a balance path shown month by month: it must cross $0 at the displayed runway
        path = list(results["chart"])
        cross = next((i for i, v in enumerate(path) if v < 0), None)
        if want.no_shortfall or want.months is None:
            if cross is not None:
                bad(c4, "the chart goes below $0 but the runway says no shortfall")
        elif cross is not None and not (want.months - 1 <= cross <= math.ceil(want.months) + 1):
            bad(c4, f"the chart crosses $0 in month {cross} but the runway is {want.months}")

    # 5 plan -> runway
    c5 = "5 plan -> runway"
    lad = results.get("ladder")
    if lad is not None:
        shocked = apply_shock(row, shock)
        if lad.already_safe != shocked.survives(target):
            bad(c5, "the backup plan's 'survives without changes' disagrees with the runway")
        prev_ok = False
        for i, rung in enumerate(lad.rungs):
            again = apply_shock(row, shock.with_(extra_monthly_cost=shock.extra_monthly_cost - rung.monthly_saving))
            ok = again.survives(target)
            if ok != rung.reaches_target:
                bad(c5, f"rung {rung.step!r} is marked {'reaching' if rung.reaches_target else 'missing'} "
                        f"{target:g} months but re-applied it gives {again.label}")
            if lad.first_sufficient == i and prev_ok:
                bad(c5, f"rung {rung.step!r} is marked as the first to reach the target but an earlier one does")
            prev_ok = prev_ok or ok
        if lad.first_sufficient is not None and not lad.rungs[lad.first_sufficient].reaches_target:
            bad(c5, "the rung marked as reaching the target doesn't")
        if lad.first_sufficient is None and any(r.reaches_target for r in lad.rungs):
            bad(c5, "a rung reaches the target but none is marked")
    g, gs = results.get("goal"), results.get("goal_shock")
    if g is not None and gs is not None:
        passes_now = apply_shock(row, gs).survives(target)
        want_short = 0.0 if passes_now else max(g.target_buffer - float(row["B"]), 0.01)
        if not _close(g.shortfall, want_short):
            bad(c5, f"goal shortfall {money(g.shortfall)} but target buffer - B gives {money(want_short)}")
        funded = apply_shock(pd.Series({**row.to_dict(), "B": g.target_buffer}), gs)
        if funded.gap <= 0:
            # Known boundary (reported, not changed): with no monthly gap the target is exactly the one-off, and the
            # judges' formula gives 0 months when B - one-off is exactly 0. A cent above the target passes.
            funded = apply_shock(pd.Series({**row.to_dict(), "B": g.target_buffer + 0.01}), gs)
        if not funded.survives(target):
            bad(c5, f"a buffer of {money(g.target_buffer)} gives {funded.label} under the goal's shock, "
                    f"short of {target:g} months")

    # 6 reality checks -> toggles
    c6 = "6 reality checks -> toggles"
    jl = shock.is_job_loss
    if not jl and (shock.income_cap_monthly is not None or shock.waiting_week or shock.pension_aware):
        bad(c6, "an EI check is on without a job loss")
    if shock.pension_aware and not float(_get(row, "Pn")) > 0:
        bad(c6, "'keep pension' is on for an account with no pension")
    if shock.bills_fallback and not can_bills_fallback(row):
        bad(c6, "'bills by standing order' is on but H > 0 or there are no bill standing orders")
    if "checks_alone" in results:
        want_rows = [(n, path_text(v) if isinstance(v, float) else rw_text(v)) for n, v in checks_alone(row, judge_shock)]
        if list(results["checks_alone"]) != want_rows:
            bad(c6, f"'each check alone' shows {list(results['checks_alone'])} but the engine gives {want_rows}")
    if "real" in results:
        real = apply_shock(row, shock)
        if rw_text(results["real"]) != rw_text(real):
            bad(c6, f"'runway with selected checks' {rw_text(results['real'])} but the engine gives {rw_text(real)}")

    # 7 narrative -> numbers
    c7 = "7 narrative -> numbers"
    story, f = results.get("story"), results.get("facts")
    if story is not None and f is not None:
        if not numbers_ok(story, f):
            stray = sorted(set(re.findall(r"\d+(?:,\d{3})*(?:\.\d+)?", " ".join(map(str, story.values()))))
                           - set(re.findall(r"\d+(?:,\d{3})*(?:\.\d+)?", str(f))))
            bad(c7, f"the summary has numbers that aren't in the computed facts: {stray}")
        if judge is not None:
            from .narrative import _rw
            if f.get("judge_runway") != _rw(judge):
                bad(c7, "the summary's runway is not the judges' runway")

    # 9 flags -> data
    c9 = "9 flags -> data"
    if "flags" in results:
        acct = results.get("account_id", getattr(row, "name", None))
        d = raw_account(acct)
        shown = set(results["flags"])
        truth = {
            "overdrawn": d["B"] <= 0,
            "no_income": d["I"] == 0,
            "no_bills": d["H"] == 0 and not d["H_SO"] > 0,
            "bills_by_standing_order": d["H"] == 0 and d["H_SO"] > 0,
            "stale": d["last_month"] < DATA_END_MONTH,
            "loan_trouble": d["loan_status"] in DEFAULTED_LOAN_STATUSES,
            "pre_loan_overdraft": d["pre_loan_negative"],
        }
        for code, true in truth.items():
            if (code in shown) != bool(true):
                bad(c9, f"flag {code!r} is {'shown' if code in shown else 'missing'} but the raw data says "
                        f"{'yes' if true else 'no'}")
    return out


# ------------------------------------------------------------------ invariant 8: portfolio -> engine -> derived -> README

PORTFOLIO_TABLES = ("accounts", "income_bands", "s6_calibration", "cut_histogram", "realistic_cuts",
                    "preloan_overdraft", "headlines")


def _frames_equal(a: pd.DataFrame, b: pd.DataFrame) -> str | None:
    if list(a.columns) != list(b.columns):
        return f"columns differ: {list(a.columns)} vs {list(b.columns)}"
    if len(a) != len(b):
        return f"{len(a)} rows vs {len(b)}"
    for c in a.columns:
        x, y = a[c], b[c]
        if pd.api.types.is_numeric_dtype(x) and pd.api.types.is_numeric_dtype(y):
            xv, yv = x.to_numpy(float), y.to_numpy(float)
            same = (np.isclose(xv, yv, rtol=1e-9, atol=1e-6) | (np.isnan(xv) & np.isnan(yv))
                    | (np.isinf(xv) & np.isinf(yv) & (np.sign(xv) == np.sign(yv))))
            if not same.all():
                i = int(np.argmin(same))
                return f"column {c!r} row {i}: {xv[i]} vs {yv[i]}"
        else:
            same = (x.isna().to_numpy() & y.isna().to_numpy()) | (x.astype(str).to_numpy() == y.astype(str).to_numpy())
            if not same.all():
                xs, ys = x.astype(str), y.astype(str)
                i = int(np.argmin(same))
                return f"column {c!r} row {i}: {xs.iloc[i]!r} vs {ys.iloc[i]!r}"
    return None


def check_portfolio(P: dict[str, pd.DataFrame], derived_dir: Path | str = ROOT / "data" / "derived",
                    readme: str | None = None, findings: str | None = None,
                    tiles: list[str] | None = None) -> list[Issue]:
    """The portfolio tables (from resilience.portfolio.build_all, i.e. the engine) equal data/derived/*.csv, and the
    README / findings / the app's tiles quote those same values."""
    c8 = "8 portfolio -> engine -> README"
    out: list[Issue] = []
    d = Path(derived_dir)
    for name in PORTFOLIO_TABLES:
        path = d / f"{name}.csv"
        if not path.exists():
            out.append(Issue(c8, f"{path.name} is missing"))
            continue
        csv_df = pd.read_csv(path, index_col=0 if name == "accounts" else None)
        eng = P[name]
        if name == "accounts":
            csv_df.index.name = eng.index.name
            eng = eng.copy()
            for col in ("loan_status", "last_month"):
                if col in eng:
                    eng[col] = eng[col].astype(object)
        diff = _frames_equal(eng.reset_index(drop=name != "accounts"),
                             csv_df.reset_index(drop=name != "accounts"))
        if diff:
            out.append(Issue(c8, f"{path.name} differs from the engine: {diff}"))
    acc, h = P["accounts"], P["headlines"].iloc[0]
    n, fail, cap = int(h["accounts"]), int(h["fail_6mo_ei55"]), int(h["fail_6mo_ei55_cap2026"])
    safe = acc["runway_ei55"] >= 6
    flips = int((safe & (acc["runway_ei55_S6"] < 6)).sum())
    if int((acc["runway_ei55"] < 6).sum()) != fail:
        out.append(Issue(c8, "headlines.fail_6mo_ei55 doesn't count the accounts table"))
    if readme is not None:
        want = f"**{fail:,} of {n:,} accounts ({fail / n:.1%})**"
        if want not in readme:
            out.append(Issue(c8, f"README doesn't quote {want}"))
    if findings is not None:
        for want in (f"**{fail:,} of {n:,} ({fail / n:.1%})**", f"| {cap:,} ({cap / n:.1%}) |",
                     f"{flips:,} of {int(safe.sum()):,}"):
            if want not in findings:
                out.append(Issue(c8, f"docs/findings.md doesn't quote {want}"))
    if tiles is not None:
        for want in (f"({fail:,} of {n:,})", f"({cap:,})", f"({int(h['fail_6mo_ei55_S6']):,})"):
            if not any(want in t for t in tiles):
                out.append(Issue(c8, f"no portfolio tile shows {want}"))
    return out
