"""Backtest evidence for the portfolio: who went overdrawn in 2025, and what each score said at the end of 2024.

    python -m resilience.evidence      # prints the lines, writes data/derived/backtest_*.csv and s6_halfyear_check.csv

Population and outcome are the early-warning light's backtest (resilience.warning.backtest_frame): the rules taken
at the 2024-12 snapshot on the accounts rated then and still active in 2025; an account went overdrawn when it has
any day below zero in a 2025 row. None of them had been below zero before, so it is their first overdraft.

Every score at the snapshot reads the rows the light reads: each account's full months up to the snapshot (the
opening month is partial and left out).
    light          points 0-4 (resilience.warning)
    EI runway      the judges' runway on the EI 55% twist (core.LAID_OFF_EI), on the judges' I, S and B computed by
                   core.baseline_metrics over those months. It passes when the published runway (rounded to
                   1 decimal, core.portfolio_runway) is PASS_MONTHS or more.
    buffer months  B / S over those months (no spending -> never runs out)

1. Watch-lists. A list of p% of the population holds round(p% x accounts) accounts (halves round up), highest
   risk first:
       light          most points first; within the same points, the lowest balance relative to spending first:
                      score = points - LIGHT_TIE_BREAK x min_bal_over_S (the light's rule-1 input after clipping)
       EI runway      shortest runway first, before the 1-decimal rounding, so a rounding tie never decides who
                      makes the list
       buffer months  fewest months first
   Ties left after that: lowest account_id first. For each list: how many of the accounts that went overdrawn
   are on it.
2. Passed but overdrawn: of the accounts that went overdrawn, how many passed the judges' EI test at the
   snapshot, and how many of those the light had flagged (WATCH_POINTS or more, where both apps show the light
   as a warning).
3. Irregular money in: the light's rule 3 (std / mean of money in over its 6 months > 0.5) x passes / fails the
   judges' EI test -> the share that went overdrawn, with a Wilson 95% interval. A second, small-n finding.
4. Half-year spending, checked forward: at each as-of month t0 in S6_ORIGINS, for the accounts with a row at least
   S6_HISTORY months before t0 and all S6_HORIZON months after it. Inputs are core.baseline_metrics on the rows up
   to t0 only (I, S, B, S6). The 6-month EI test is B - (6-month spending - 6 x 0.55 x I) < 0. A real fail uses
   the money out that actually followed; the median-month check uses 6 x S; the half-year check uses 6 x S6.
   All three are unrounded, so the S check is not the judges' published (rounded) runway.
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd

from .core import LAID_OFF_EI, RUNWAY_CAP_MONTHS, baseline_metrics, load_loans, load_monthly, portfolio_runway, shock_terms
from .warning import BACKTEST_LABEL_YEAR, BACKTEST_SNAPSHOT, backtest_frame, usable_months

PASS_MONTHS = 6.0                    # the judges' six-month test: a runway of 6 months or more passes
WATCH_POINTS = 2                     # the light is shown as a warning from this many points (app.py, web card)
LIGHT_TIE_BREAK = 1e-6               # within the same points, lower min balance / spending ranks first
LIST_PCTS = tuple(range(1, 31))      # watch-list sizes, % of the backtest population
HEADLINE_LIST_PCT = 10
WILSON_Z = 1.96
S6_ORIGINS = ("2023-12", "2024-06", "2024-12", "2025-06")
S6_HISTORY = 12                      # the account has a row at least this many months before t0
S6_HORIZON = 6                       # ... and every one of the 6 months after it
RANKINGS = ("light", "ei55_runway", "buffer_months")


# ---------------------------------------------------------------- scores at the snapshot

def score_frame(pop: pd.DataFrame, metrics: pd.DataFrame) -> pd.DataFrame:
    """Per account of `pop` (backtest_frame rows): the light, the judges' EI runway and buffer months from
    `metrics` (baseline_metrics columns I, S, B), the judges' pass, and the outcome."""
    m = metrics.reindex(pop.index)
    income, addons, one_off, base = shock_terms(m, LAID_OFF_EI)
    buffer_left = m["B"] - one_off
    gap = base + addons - income
    with np.errstate(divide="ignore", invalid="ignore"):
        exact = np.minimum(buffer_left / gap, RUNWAY_CAP_MONTHS)
    out = pd.DataFrame(index=pop.index)
    out["points"] = pop["points"].astype(int)
    out["min_bal_over_S"] = pop["min_bal_over_S"].astype(float)
    out["irregular"] = pop["fires_inc_cv"].astype(bool)
    out["I"], out["S"], out["B"] = m["I"], m["S"], m["B"]
    out["runway_ei55"] = portfolio_runway(m, LAID_OFF_EI)                 # published: rounded, inf = no shortfall
    out["runway_ei55_exact"] = np.where(buffer_left <= 0, 0.0, np.where(gap <= 0, np.inf, exact))
    out["buffer_months"] = (m["B"] / m["S"].replace(0, np.nan)).fillna(np.inf)
    out["passes_ei55"] = out["runway_ei55"] >= PASS_MONTHS
    out["went_overdrawn"] = pop["went_overdrawn"].astype(bool)
    return out


def snapshot_scores(monthly: pd.DataFrame, loans: pd.DataFrame, snapshot: str = BACKTEST_SNAPSHOT,
                    label_year: str = BACKTEST_LABEL_YEAR) -> pd.DataFrame:
    """score_frame for the backtest population, with I, S, B on the same full months the light reads."""
    pop = backtest_frame(monthly, snapshot, label_year)
    rows = usable_months(monthly)
    rows = rows[(rows["month"] <= snapshot) & rows["account_id"].isin(pop.index)]
    return score_frame(pop, baseline_metrics(rows, loans))


# ---------------------------------------------------------------- 1. watch-lists

def list_size(pct: int, accounts: int) -> int:
    """round(pct% x accounts), halves up, in integers."""
    return (2 * pct * accounts + 100) // 200


def risk_order(scores: pd.DataFrame, ranking: str) -> pd.Index:
    """account_ids, highest risk first, for one of RANKINGS; remaining ties by lowest account_id."""
    s = scores.sort_index()
    ids = s.index.to_numpy()
    if ranking == "light":
        key = -(s["points"].to_numpy(float) - LIGHT_TIE_BREAK * s["min_bal_over_S"].to_numpy(float))
    elif ranking == "ei55_runway":
        key = s["runway_ei55_exact"].to_numpy(float)
    elif ranking == "buffer_months":
        key = s["buffer_months"].to_numpy(float)
    else:
        raise ValueError(f"unknown ranking {ranking!r}")
    return pd.Index(ids[np.lexsort((ids, key))], name="account_id")


def lift_table(scores: pd.DataFrame, pcts: tuple[int, ...] = LIST_PCTS) -> pd.DataFrame:
    """For each watch-list size: accounts on the list, and how many that went overdrawn each ranking puts on it."""
    y = scores["went_overdrawn"]
    n, events = len(scores), int(y.sum())
    caught = {r: np.concatenate([[0], y.reindex(risk_order(scores, r)).to_numpy(int).cumsum()]) for r in RANKINGS}
    rows = []
    for p in pcts:
        k = list_size(p, n)
        rows.append({"list_pct": p, "list_accounts": k, **{r: int(caught[r][k]) for r in RANKINGS}, "events": events})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- 2. passed but overdrawn

def summary(scores: pd.DataFrame, snapshot: str = BACKTEST_SNAPSHOT, label_year: str = BACKTEST_LABEL_YEAR) -> dict:
    ev = scores[scores["went_overdrawn"]]
    passed = ev["passes_ei55"]
    return {"snapshot": snapshot, "label_year": label_year, "accounts": len(scores), "went_overdrawn": len(ev),
            "passed_ei55": int(passed.sum()),
            "passed_and_flagged": int((passed & (ev["points"] >= WATCH_POINTS)).sum()),
            "watch_points": WATCH_POINTS}


# ---------------------------------------------------------------- 3. irregular money in

def wilson(k: int, n: int, z: float = WILSON_Z) -> tuple[float, float]:
    """Wilson score interval for k of n."""
    if n == 0:
        return (math.nan, math.nan)
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (c - h, c + h)


def irregular_table(scores: pd.DataFrame) -> pd.DataFrame:
    """The 2x2: irregular money in (yes / no) x the judges' EI test (passes / fails)."""
    rows = []
    for irr in (True, False):
        for passes in (True, False):
            cell = scores[(scores["irregular"] == irr) & (scores["passes_ei55"] == passes)]
            k, n = int(cell["went_overdrawn"].sum()), len(cell)
            lo, hi = wilson(k, n)
            rows.append({"irregular_money_in": "yes" if irr else "no", "judges_ei55": "passes" if passes else "fails",
                         "accounts": n, "went_overdrawn": k, "rate": k / n if n else math.nan,
                         "ci_low": lo, "ci_high": hi})
    return pd.DataFrame(rows)


def irregular_cell(table: pd.DataFrame, irregular: str, judges: str) -> pd.Series:
    t = table[(table["irregular_money_in"] == irregular) & (table["judges_ei55"] == judges)]
    return t.iloc[0]


# ---------------------------------------------------------------- 4. half-year spending, checked forward

def s6_halfyears(monthly: pd.DataFrame, loans: pd.DataFrame, origins: tuple[str, ...] = S6_ORIGINS) -> pd.DataFrame:
    """One row per (as-of month, account): the judges' I, S, B and the engine's S6 from the rows up to t0, and the
    money out of the S6_HORIZON months that followed."""
    span = monthly.groupby("account_id")["month"].agg(["min", "max"])
    frames = []
    for t0 in origins:
        p0 = pd.Period(t0, "M")
        start, end = str(p0 - S6_HISTORY), str(p0 + S6_HORIZON)
        ids = span.index[(span["min"] <= start) & (span["max"] >= end)]
        m = baseline_metrics(monthly[(monthly["month"] <= t0) & monthly["account_id"].isin(ids)], loans).reindex(ids)
        nxt = monthly[(monthly["month"] > t0) & (monthly["month"] <= end) & monthly["account_id"].isin(ids)]
        g = nxt.groupby("account_id")["money_out"]
        if not (g.size().reindex(ids) == S6_HORIZON).all():
            raise ValueError(f"{t0}: an account is missing one of the {S6_HORIZON} months after it")
        frames.append(pd.DataFrame({"origin": t0, "account_id": ids, "B": m["B"].to_numpy(), "I": m["I"].to_numpy(),
                                    "S": m["S"].to_numpy(), "S6": m["S6"].to_numpy(),
                                    "next_spending": g.sum().reindex(ids).to_numpy()}))
    return pd.concat(frames, ignore_index=True)


def s6_check(halfyears: pd.DataFrame) -> pd.DataFrame:
    """The 6-month EI test on S and on S6 against the real outcome: flags, missed real fails, false alarms."""
    ei = S6_HORIZON * LAID_OFF_EI.income_multiplier * halfyears["I"]
    real = halfyears["B"] - (halfyears["next_spending"] - ei) < 0
    rows = []
    for basis in ("S", "S6"):
        flag = halfyears["B"] - (S6_HORIZON * halfyears[basis] - ei) < 0     # an undefined S6 never flags
        rows.append({"spending_basis": basis, "account_halfyears": len(halfyears), "real_fails": int(real.sum()),
                     "flagged": int(flag.sum()), "missed_real_fails": int((~flag & real).sum()),
                     "false_alarms": int((flag & ~real).sum())})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- everything, and the lines the apps show

def build_evidence(monthly: pd.DataFrame | None = None, loans: pd.DataFrame | None = None) -> dict:
    monthly = load_monthly() if monthly is None else monthly
    loans = load_loans() if loans is None else loans
    scores = snapshot_scores(monthly, loans)
    halfyears = s6_halfyears(monthly, loans)
    return {"scores": scores, "lift": lift_table(scores), "summary": summary(scores),
            "irregular": irregular_table(scores), "halfyears": halfyears, "s6": s6_check(halfyears)}


def _pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def _interval(lo: float, hi: float) -> str:
    return f"{lo * 100:.1f}–{hi * 100:.1f}%"


def passed_line(s: dict) -> str:
    return (f"{s['passed_ei55']:,} of the {s['went_overdrawn']:,} accounts that first went overdrawn in "
            f"{s['label_year']} had passed the judges' EI 55% test at the {s['snapshot']} snapshot; the light had "
            f"flagged {s['passed_and_flagged']:,} of them ({s['watch_points']}+ points).")


def lift_line(lift: pd.DataFrame, s: dict, pct: int = HEADLINE_LIST_PCT) -> str:
    r = lift[lift["list_pct"] == pct].iloc[0]
    return (f"On a {pct}% watch-list ({int(r['list_accounts']):,} accounts), the light (most points first, then "
            f"lowest balance against spending) catches {int(r['light']):,} of the {int(r['events']):,} accounts "
            f"that went overdrawn in {s['label_year']}; the judges' EI 55% runway catches {int(r['ei55_runway']):,} "
            f"and buffer months {int(r['buffer_months']):,}.")


def irregular_line(table: pd.DataFrame, s: dict) -> str:
    a, b = irregular_cell(table, "yes", "passes"), irregular_cell(table, "no", "fails")
    return (f"Accounts with irregular money in that pass the judges' EI 55% test: {int(a['went_overdrawn']):,} of "
            f"{int(a['accounts']):,} went overdrawn in {s['label_year']} ({_pct(a['rate'])}, 95% interval "
            f"{_interval(a['ci_low'], a['ci_high'])}). Accounts with steady money in that fail it: "
            f"{int(b['went_overdrawn']):,} of {int(b['accounts']):,} ({_pct(b['rate'])}, "
            f"{_interval(b['ci_low'], b['ci_high'])}).")


def irregular_caveat(table: pd.DataFrame) -> str:
    a, b = irregular_cell(table, "yes", "passes"), irregular_cell(table, "no", "fails")
    return (f"A second finding with small numbers: it rests on {int(a['went_overdrawn']):,} and "
            f"{int(b['went_overdrawn']):,} overdrafts. It shows who to watch, not why they went overdrawn.")


def s6_line(check: pd.DataFrame, origins: tuple[str, ...] = S6_ORIGINS) -> str:
    S = check[check["spending_basis"] == "S"].iloc[0]
    S6 = check[check["spending_basis"] == "S6"].iloc[0]
    return (f"Checked forward at {len(origins)} as-of months from {origins[0]} to {origins[-1]} "
            f"({int(S['account_halfyears']):,} account half-years, each using only the data up to its month): of "
            f"the {int(S['real_fails']):,} half-years that fail the 6-month EI test on the money out that actually "
            f"followed, the same test on the median month S misses {int(S['missed_real_fails']):,} and on half-year "
            f"spending S6 misses {int(S6['missed_real_fails']):,}; S6 raises {int(S6['false_alarms']):,} false "
            f"alarms against {int(S['false_alarms']):,} for S.")


def lines(ev: dict) -> dict[str, str]:
    s = ev["summary"]
    return {"passed": passed_line(s), "lift": lift_line(ev["lift"], s), "irregular": irregular_line(ev["irregular"], s),
            "irregular_caveat": irregular_caveat(ev["irregular"]), "s6": s6_line(ev["s6"])}


ARTIFACT_FILES = ("backtest_summary", "backtest_lift", "backtest_irregular", "s6_halfyear_check")


def main(out_dir: Path | None = None) -> None:
    from .portfolio import ARTIFACTS
    out_dir = ARTIFACTS if out_dir is None else out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    ev = build_evidence()
    for text in lines(ev).values():
        print(text)
    tables = {"backtest_summary": pd.DataFrame([ev["summary"]]), "backtest_lift": ev["lift"],
              "backtest_irregular": ev["irregular"], "s6_halfyear_check": ev["s6"]}
    for name in ARTIFACT_FILES:
        path = out_dir / f"{name}.csv"
        tables[name].to_csv(path, index=False)
        print(f"wrote {path.relative_to(out_dir.parent)} ({len(tables[name])} rows)")


if __name__ == "__main__":
    from .portfolio import parse_out_dir
    main(parse_out_dir("resilience.evidence", __doc__))
