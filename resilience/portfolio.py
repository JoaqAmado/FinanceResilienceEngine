"""Portfolio tables behind the discovery charts.

    python -m resilience.portfolio            # writes artifacts/*.csv

Every table is computed from the engine, so the charts and the live demo can
never disagree. Shares are of all 4,500 accounts unless a table says otherwise.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

from .core import (
    DOUBLE_WHAMMY,
    EI_2026_MAX_MONTHLY,
    FURNACE,
    LAID_OFF_EI,
    LAID_OFF_EI_CAPPED,
    build_metrics,
    portfolio_calendar_path,
    portfolio_runway,
)

ARTIFACTS = Path(__file__).resolve().parent.parent / "artifacts"
INCOME_BANDS = [0, 2500, 5000, 7500, 10000, 15000, 20000, np.inf]
INCOME_LABELS = ["< $2.5k", "$2.5k-5k", "$5k-7.5k", "$7.5k-10k", "$10k-15k", "$15k-20k", ">= $20k"]


def per_account(m: pd.DataFrame) -> pd.DataFrame:
    """One row per account: judges' numbers, runways under each scenario, flags."""
    out = m[["I", "F", "S", "B", "H", "P", "Pn", "S6", "flexible_median", "months_of_data", "last_month",
             "loan_status", "pre_loan_negative", "ever_negative", "owner_age", "H_SO"]].copy()
    out["buffer_months"] = m["B"] / m["S"].replace(0, np.nan)
    scen = {
        "runway_base": LAID_OFF_EI.with_(income_multiplier=1.0),
        "runway_ei55": LAID_OFF_EI,
        "runway_ei55_cap2026": LAID_OFF_EI_CAPPED,
        "runway_ei55_cap2026_waitweek": LAID_OFF_EI_CAPPED.with_(waiting_week=True),
        "runway_ei55_pension_aware": LAID_OFF_EI.with_(pension_aware=True),
        "runway_ei55_S6": LAID_OFF_EI.with_(spending_basis="S6"),
        "runway_furnace": FURNACE,
        "runway_double_whammy": DOUBLE_WHAMMY,
    }
    for col, shock in scen.items():
        out[col] = portfolio_runway(m, shock)
    out["runway_ei55_january_path"] = portfolio_calendar_path(m, LAID_OFF_EI)
    gap = m["S"] - 0.55 * m["I"]
    need = np.where((m["B"] > 0) & (out["runway_ei55"] < 6), gap - m["B"] / 6, 0.0)
    out["ei55_min_cut_to_6mo"] = np.maximum(need, 0.0)
    out["ei55_min_cut_pct_of_S"] = out["ei55_min_cut_to_6mo"] / m["S"].replace(0, np.nan)
    return out


def income_bands(acc: pd.DataFrame) -> pd.DataFrame:
    """Finding #1: the higher the income, the thinner the cushion."""
    band = pd.cut(acc["I"], INCOME_BANDS, right=False, labels=INCOME_LABELS)
    g = acc.groupby(band, observed=False)
    return pd.DataFrame({
        "accounts": g.size(),
        "fail_6mo_ei55_pct": (g["runway_ei55"].apply(lambda s: (s < 6).mean()) * 100).round(1),
        "fail_6mo_ei55_cap2026_pct": (g["runway_ei55_cap2026"].apply(lambda s: (s < 6).mean()) * 100).round(1),
        "median_buffer_months": g["buffer_months"].median().round(2),
        "median_I": g["I"].median().round(0),
    }).rename_axis("income_band").reset_index()


def s6_calibration(acc: pd.DataFrame) -> pd.DataFrame:
    """Finding #2: the median-month trap. Judge EI55 runway band vs share failing on S6."""
    j, s6 = acc["runway_ei55"], acc["runway_ei55_S6"]
    rows = []
    for lo, hi, label in [(6, 8, "6-8"), (8, 10, "8-10"), (10, 12, "10-12"), (12, 20, "12-20"), (20, 120.01, "20-120"),
                          (np.inf, np.inf, "no shortfall (120+)")]:
        b = np.isinf(j) if np.isinf(lo) else (j >= lo) & (j < hi)
        rows.append({"judge_runway_months": label, "accounts": int(b.sum()),
                     "fail_6mo_on_S6_pct": round(float((s6[b] < 6).mean() * 100), 1) if b.any() else np.nan})
    return pd.DataFrame(rows)


def cut_histogram(acc: pd.DataFrame) -> pd.DataFrame:
    """Finding #4: how big a monthly cut gets an EI55-failing customer back to 6 months."""
    fail = acc[acc["runway_ei55"] < 6]
    pct = fail["ei55_min_cut_pct_of_S"] * 100
    bins = [("<= 10%", (pct <= 10)), ("10-25%", (pct > 10) & (pct <= 25)), ("25-50%", (pct > 25) & (pct <= 50)),
            ("50-100%", (pct > 50) & (pct <= 100)), ("> 100%", pct > 100)]
    rows = [{"cut_as_share_of_spending": k, "accounts": int((mask & (fail["B"] > 0)).sum())} for k, mask in bins]
    rows.append({"cut_as_share_of_spending": "already overdrawn (B <= 0)", "accounts": int((fail["B"] <= 0).sum())})
    return pd.DataFrame(rows)


def preloan_overdraft(acc: pd.DataFrame) -> pd.DataFrame:
    """Finding #3: overdrawn before the loan vs loan outcome (2x2)."""
    lo = acc[acc["loan_status"].notna()].copy()
    lo["outcome"] = np.where(lo["loan_status"].isin(["B", "D"]), "defaulted (B/D)", "repaid or on track (A/C)")
    lo["overdrawn_before_loan"] = np.where(lo["pre_loan_negative"], "yes", "no")
    return pd.crosstab(lo["overdrawn_before_loan"], lo["outcome"]).reset_index()


def headline_numbers(acc: pd.DataFrame) -> dict:
    n = len(acc)
    f = lambda c: int((acc[c] < 6).sum())  # noqa: E731
    return {
        "accounts": n,
        "fail_6mo_ei55": f("runway_ei55"),
        "fail_6mo_ei55_cap2026": f("runway_ei55_cap2026"),
        "fail_6mo_ei55_S6": f("runway_ei55_S6"),
        "fail_6mo_ei55_pension_aware": f("runway_ei55_pension_aware"),
        "fail_6mo_ei55_january_path": f("runway_ei55_january_path"),
        "fail_6mo_furnace": f("runway_furnace"),
        "fail_6mo_double_whammy": f("runway_double_whammy"),
        "ei_cap_monthly_2026": round(EI_2026_MAX_MONTHLY, 2),
        "median_min_cut_failing": round(float(acc.loc[(acc.runway_ei55 < 6) & (acc.B > 0), "ei55_min_cut_to_6mo"].median()), 0),
    }


def build_all(m: pd.DataFrame | None = None) -> dict[str, pd.DataFrame]:
    m = build_metrics() if m is None else m
    acc = per_account(m)
    return {
        "accounts": acc,
        "income_bands": income_bands(acc),
        "s6_calibration": s6_calibration(acc),
        "cut_histogram": cut_histogram(acc),
        "preloan_overdraft": preloan_overdraft(acc),
        "headlines": pd.DataFrame([headline_numbers(acc)]),
    }


def main(out_dir: Path = ARTIFACTS) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, df in build_all().items():
        path = out_dir / f"{name}.csv"
        df.to_csv(path, index=(name == "accounts"))
        print(f"wrote {path.relative_to(out_dir.parent)} ({len(df)} rows)")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else ARTIFACTS)
