"""Compute every headline number, draw the pitch charts, pick the showcase accounts.

    python -m tangerine.findings

Reads the warehouse (read-only) and writes:
    reports/findings.md          every headline number with its sample size and source mart
    reports/showcase.md          rehearsal accounts for the live twist, with the engine's output
    reports/data_dictionary.md   every mart table and column with its plain-English description
    reports/figures/*.png        the pitch charts
"""
from __future__ import annotations

import sys
from datetime import datetime

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from tangerine import config, engine  # noqa: E402
from tangerine.pipeline import connect  # noqa: E402

# ── Chart style (validated reference palette, light mode) ────────────────────
OURS = "#2a78d6"       # blue  — our stress-adjusted metric / the highlighted group
ALERT = "#eb6834"      # orange — the risky group
NEUTRAL = "#b9b8b1"    # grey  — comparison groups / the judge metric
INK = "#0b0b0b"
INK_2 = "#52514e"
SURFACE = "#fcfcfb"

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "figure.dpi": 110, "savefig.dpi": 160, "font.size": 10,
    "axes.edgecolor": "#d6d5cf", "axes.labelcolor": INK_2, "xtick.color": INK_2, "ytick.color": INK_2,
    "axes.titlesize": 13, "axes.titleweight": "bold", "axes.titlecolor": INK, "axes.titlelocation": "left",
    "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "axes.grid.axis": "y", "grid.color": "#ebeae5", "grid.linewidth": 0.8,
    "axes.axisbelow": True,
})


# ── AUC (rank-based, no sklearn) ─────────────────────────────────────────────
def auc(score, y) -> float:
    """P(a random defaulter scores riskier than a random non-defaulter). 0.5 = coin flip. Ties count half."""
    s = pd.Series(np.asarray(score, float))
    y = pd.Series(np.asarray(y)).astype(bool)
    ok = s.notna()
    s, y = s[ok], y[ok]
    ranks = s.rank()
    n1, n0 = int(y.sum()), int((~y).sum())
    return float((ranks[y].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def bootstrap_auc(scores: dict[str, pd.Series], y: pd.Series, n: int = 2000, seed: int = 0) -> dict[str, np.ndarray]:
    """Paired bootstrap: the SAME resampled loans for every score, so differences get honest intervals."""
    rng = np.random.default_rng(seed)
    yv = y.to_numpy().astype(int)
    arrays = {k: v.to_numpy(float) for k, v in scores.items()}
    out = {k: [] for k in scores}
    for _ in range(n):
        i = rng.integers(0, len(yv), len(yv))
        if 0 < yv[i].sum() < len(i):
            for k, a in arrays.items():
                out[k].append(auc(a[i], yv[i]))
    return {k: np.array(v) for k, v in out.items()}


# ── Data ─────────────────────────────────────────────────────────────────────
def load() -> dict[str, pd.DataFrame]:
    con = connect(read_only=True)
    try:
        tables = ["mart_findings", "mart_loan_preloan", "mart_default_drivers", "mart_balance_slide_summary",
                  "mart_customer_profile", "mart_shock_runways", "mart_balance_slide", "mart_committed_obligations"]
        # Fixed row order so every run picks the same showcase accounts (mart_findings keeps its written order).
        data = {t: con.execute(f"select * from marts.{t}" + ("" if t == "mart_findings" else " order by all")).df()
                for t in tables}
        data["columns"] = con.execute("""
            select c.table_name, c.column_name, c.data_type, coalesce(c.comment, '') as description,
                   coalesce(t.comment, '') as table_description
            from duckdb_columns() c join duckdb_tables() t using (database_name, schema_name, table_name)
            where c.schema_name = 'marts' order by c.table_name, c.column_index""").df()
        data["thresholds"] = con.execute("select * from marts.config_thresholds").df()
    finally:
        con.close()
    return data


# ── F10: does a stress runway flag defaulters better than the judge runway? ──
def stress_vs_judge(preloan: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    y = preloan["is_defaulted"].astype(int)
    # Higher score = riskier, so runways and buffers are negated.
    scores = {
        "Stress runway (lean-month income, + loan payment)": -preloan["stress_runway_with_loan"],
        "Judge runway (median income, + loan payment)": -preloan["judge_runway_with_loan"],
        "Judge EI-55% runway (+ loan payment)": -preloan["judge_ei55_runway_with_loan"],
        "Buffer in months of spending": -preloan["buffer_months"],
        "Income volatility (CV)": preloan["pre_loan_income_cv"],
        "Payment / income": preloan["payment_to_income"],
        "Lowest balance": -preloan["pre_loan_lowest_balance"],
        "Went below zero (yes/no)": preloan["pre_loan_was_overdrawn"].astype(float),
    }
    boot = bootstrap_auc(scores, y)
    table = pd.DataFrame({
        "AUC": {k: auc(s, y) for k, s in scores.items()},
        "CI low": {k: np.percentile(v, 2.5) for k, v in boot.items()},
        "CI high": {k: np.percentile(v, 97.5) for k, v in boot.items()},
        "n loans": {k: int(s.notna().sum()) for k, s in scores.items()},
    }).sort_values("AUC", ascending=False)

    stress, judge = "Stress runway (lean-month income, + loan payment)", "Judge runway (median income, + loan payment)"
    buffer = "Buffer in months of spending"
    diffs = {}
    for name, other in [("stress - judge runway", judge), ("stress - buffer months", buffer)]:
        d = boot[stress] - boot[other]
        diffs[name] = {"AUC difference": auc(scores[stress], y) - auc(scores[other], y),
                       "CI low": np.percentile(d, 2.5), "CI high": np.percentile(d, 97.5),
                       "share of draws <= 0": float((d <= 0).mean())}
    return table, pd.DataFrame(diffs).T


# ── Figures ──────────────────────────────────────────────────────────────────
def _bar_labels(ax, bars, defaults, loans):
    for b, d, n in zip(bars, defaults, loans):
        ax.text(b.get_x() + b.get_width() / 2, b.get_height() + 0.8, f"{b.get_height():.0f}%\n{int(d)}/{int(n)}",
                ha="center", va="bottom", fontsize=8.5, color=INK_2,
                bbox=dict(boxstyle="square,pad=0.1", fc=SURFACE, ec="none"))


def _finish(fig, name: str, note: str) -> str:
    fig.text(0.01, 0.01, note, fontsize=7.5, color=INK_2, ha="left", va="bottom")
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    path = config.FIGURES_DIR / name
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return f"figures/{name}"


def fig_volatility_vs_buffer(drivers: pd.DataFrame, overall: float) -> str:
    fig, axes = plt.subplots(1, 2, figsize=(10, 4), sharey=True)
    panels = [("pre_loan_income_cv", "Income volatility before the loan", ["Q1\nsteadiest", "Q2", "Q3", "Q4\nmost volatile"]),
              ("buffer_months", "Savings buffer before the loan", ["Q1\nsmallest", "Q2", "Q3", "Q4\nlargest"])]
    for ax, (driver, title, labels) in zip(axes, panels):
        t = drivers[drivers.driver == driver].sort_values("group_order")
        colors = [NEUTRAL] * 3 + [ALERT] if driver == "pre_loan_income_cv" else [NEUTRAL] * 4
        bars = ax.bar(labels, 100 * t.default_rate, color=colors, width=0.62)
        _bar_labels(ax, bars, t.defaults, t.loans)
        ax.axhline(100 * overall, color=INK_2, lw=1, ls=":")
        ax.set_title(title, fontsize=11, fontweight="normal", color=INK_2)
    axes[0].set_ylabel("Loans that defaulted (%)")
    axes[0].set_ylim(0, 30)
    axes[0].text(0.5, 100 * overall + 0.6, f"all loans {100 * overall:.1f}%", ha="center", fontsize=8, color=INK_2)
    fig.suptitle("Unsteady income, not small savings, predicts default", x=0.01, ha="left",
                 fontsize=13, fontweight="bold", color=INK)
    return _finish(fig, "f2_default_by_volatility_vs_buffer.png",
                   "682 loans, 76 defaults. Features use only months before the loan was granted. Labels: defaults/loans.")


def fig_auc(table: pd.DataFrame) -> str:
    t = table.sort_values("AUC")
    colors = [OURS if k.startswith("Stress") else ALERT if k.startswith("Judge") else NEUTRAL for k in t.index]
    fig, ax = plt.subplots(figsize=(10, 4.4))
    ax.barh(t.index, t.AUC - 0.5, left=0.5, color=colors, height=0.55)
    ax.errorbar(t.AUC, t.index, xerr=[t.AUC - t["CI low"], t["CI high"] - t.AUC], fmt="none",
                ecolor=INK_2, capsize=3, lw=1)
    for i, (v, hi) in enumerate(zip(t.AUC, t["CI high"])):
        ax.text(hi + 0.006, i, f"{v:.2f}", va="center", fontsize=9, color=INK)
    ax.axvline(0.5, color=INK_2, lw=1)
    ax.grid(axis="x"); ax.grid(axis="y", visible=False)
    ax.set_xlim(0.45, 0.92)
    ax.set_xlabel("AUC for spotting a future default (0.5 = coin flip, 1 = perfect)")
    fig.suptitle("A lean-month 'stress runway' spots defaulters better than the judge runway",
                 x=0.01, ha="left", fontsize=13, fontweight="bold", color=INK)
    return _finish(fig, "f10_auc_stress_vs_judge_runway.png",
                   "Pre-loan data only, 682 loans / 76 defaults. Bars = 95% bootstrap intervals (2,000 resamples). "
                   "Blue = ours, orange = judge formula.")


def fig_stress_quartiles(drivers: pd.DataFrame, overall: float) -> str:
    fig, axes = plt.subplots(1, 2, figsize=(10, 4), sharey=True)
    labels = ["Q1\nshortest", "Q2", "Q3", "Q4\nlongest"]
    for ax, driver, title, color in [
        (axes[0], "judge_ei55_runway_with_loan", "Judge EI-55% runway", ALERT),
        (axes[1], "stress_runway_with_loan", "Stress runway (ours)", OURS),
    ]:
        t = drivers[drivers.driver == driver].sort_values("group_order")
        bars = ax.bar(labels, 100 * t.default_rate, color=[color] + [NEUTRAL] * 3, width=0.62)
        _bar_labels(ax, bars, t.defaults, t.loans)
        ax.axhline(100 * overall, color=INK_2, lw=1, ls=":")
        ax.set_title(title, fontsize=11, fontweight="normal", color=INK_2)
    axes[0].set_ylabel("Loans that defaulted (%)")
    axes[0].set_ylim(0, 32)
    fig.suptitle("The shortest stress runways hold 46 of 76 defaults", x=0.01, ha="left",
                 fontsize=13, fontweight="bold", color=INK)
    return _finish(fig, "f10_default_by_runway_quartile.png",
                   "Quartiles of pre-loan runway with the loan payment added to spending. Labels: defaults/loans.")


def fig_balance_slide(summary: pd.DataFrame) -> str:
    s = summary.sort_values("months_before_first_overdraft")
    fig, ax = plt.subplots(figsize=(10, 4))
    x = -s.months_before_first_overdraft
    ax.plot(x, 100 * s.median_balance_vs_12m_peak, color=ALERT, lw=2, marker="o", ms=6,
            markeredgecolor=SURFACE, markeredgewidth=1.5)
    for k in (1, 2, 3, 4):
        row = s[s.months_before_first_overdraft == k].iloc[0]
        ax.annotate(f"{100 * row.median_balance_vs_12m_peak:.0f}%", (-k, 100 * row.median_balance_vs_12m_peak),
                    textcoords="offset points", xytext=(0, -16 if k == 1 else 9), ha="center", fontsize=9, color=INK)
    ax.axvspan(-3.5, -0.5, color=ALERT, alpha=0.07, lw=0)
    ax.text(-2, 92, "warning window", ha="center", fontsize=9, color=INK_2)
    ax.set_xticks(range(-12, 0), [f"{k}" for k in range(12, 0, -1)])
    ax.set_xlabel("Months before the first day below zero")
    ax.set_ylabel("Balance as % of its 12-month peak\n(median across defaulters)")
    ax.set_ylim(0, 100)
    ax.set_title("Savings slide for about three months before the first overdraft")
    return _finish(fig, "f4_balance_slide_before_overdraft.png",
                   "All 76 defaulted loan accounts. Each month: average balance / highest monthly average in the 12 months up to it.")


def fig_ei_runway(runways: pd.DataFrame) -> str:
    r = runways["runway_job_loss_ei55"].fillna(999)
    under6 = int((r < 6).sum())
    bins = np.arange(0, 25, 1)
    counts, _ = np.histogram(r.clip(upper=24 - 1e-9), bins=bins)
    fig, ax = plt.subplots(figsize=(10, 4))
    colors = [ALERT if b < 6 else NEUTRAL for b in bins[:-1]]
    ax.bar(bins[:-1] + 0.5, counts, width=0.9, color=colors)
    ax.text(3, counts.max() * 0.95, f"{under6:,} accounts ({under6 / len(r):.0%})\nrun out within 6 months",
            ha="center", va="top", fontsize=10, color=INK)
    ax.set_xticks([0, 3, 6, 9, 12, 18, 24], ["0", "3", "6", "9", "12", "18", "24+"])
    ax.set_xlabel("Months of runway after a job loss with EI at 55% (judge formula)")
    ax.set_ylabel("Accounts")
    ax.set_title("Job loss with EI: a third of customers run out within six months")
    return _finish(fig, "f5_ei_runway_distribution.png",
                   f"All 4,500 accounts. {int(runways['runway_job_loss_ei55'].isna().sum())} have no shortfall even on EI "
                   "(pooled in 24+ with long runways).")


def fig_preloan_overdraft(drivers: pd.DataFrame) -> str:
    t = drivers[drivers.driver == "pre_loan_was_overdrawn"].sort_values("group_order")
    fig, ax = plt.subplots(figsize=(7, 4))
    bars = ax.bar(["Never below zero\nbefore the loan", "Went below zero\nbefore the loan"],
                  100 * t.default_rate, color=[NEUTRAL, ALERT], width=0.5)
    _bar_labels(ax, bars, t.defaults, t.loans)
    ax.set_ylim(0, 115)
    ax.set_ylabel("Loans that defaulted (%)")
    ax.set_title("Every customer overdrawn before the loan defaulted")
    return _finish(fig, "f1_preloan_overdraft_default.png", "682 loans. Pre-loan months only.")


# ── Showcase accounts ────────────────────────────────────────────────────────
def pick_showcase(profile: pd.DataFrame, runways: pd.DataFrame, slide: pd.DataFrame) -> dict[str, tuple[int, str]]:
    """Deterministic picks: within each group, the account closest to the group's median of a key metric."""
    p = profile.merge(runways, on="account_id")
    current = p[(p.last_month == config.LAST_DATA_MONTH) & (p.months_of_history >= 24) & ~p.has_negative_buffer]

    def closest(df: pd.DataFrame, col: str) -> int:
        # Sort by account_id first so ties (two accounts equally close to the median) always resolve the same way.
        df = df.sort_values("account_id")
        return int(df.loc[(df[col] - df[col].median()).abs().sort_values(kind="stable").index[0], "account_id"])

    picks = {}
    pens = current[current.is_pensioner & (current.typical_income > 0)]
    picks["Pensioner"] = (closest(pens, "pension_income_share"),
                          "Most income is pension: the job-loss/EI twist mostly doesn't apply. Try bills +15% or the furnace.")
    vol = current[current.is_volatile_income & ~current.is_pensioner & (current.cash_income_share > 0.9)
                  & (current.typical_income > 0) & current.runway_job_loss_ei55.notna()]
    picks["Volatile cash earner"] = (closest(vol, "income_volatility_cv"),
                                     "Cash income that swings month to month: the stress runway is far shorter than the judge runway.")
    k1 = slide[slide.months_before_first_overdraft == 1].set_index("account_id")["balance_vs_12m_peak"]
    k3 = slide[slide.months_before_first_overdraft == 3].set_index("account_id")["balance_vs_12m_peak"]
    slid = (k3 - k1).dropna().sort_values(ascending=False)
    slid = slid[slid.index.isin(profile.loc[profile.has_loan_in_debt, "account_id"])]
    picks["Defaulter with a visible balance slide"] = (int(slid.index[0]),
                                                       "Loan in debt (status D). Balance fell from near its peak to near zero in the 3 months before the first overdraft.")
    saver = current[runways.set_index("account_id").loc[current.account_id, "runway_no_shock"].isna().values
                    & ~current.is_volatile_income & ~current.is_pensioner & ~current.has_loan
                    & (current.buffer_months_of_spending >= 6)]
    picks["Comfortable saver"] = (closest(saver, "buffer_months_of_spending"),
                                  "Steady income, no shortfall and 6+ months of spending saved: most shocks barely dent it.")
    neg = profile[profile.has_negative_buffer & (profile.last_month == config.LAST_DATA_MONTH)]
    neg = neg if len(neg) else profile[profile.has_negative_buffer]
    picks["Negative buffer"] = (closest(neg, "buffer"),
                                "Already below zero on average: runway is 0 under every shock; the plan starts with leaving overdraft.")
    return picks


def showcase_markdown(picks: dict[str, tuple[int, str]]) -> str:
    out = ["# Showcase accounts (rehearsal for the live twist)", "",
           "_Generated by `python -m tangerine.findings`. Runway in months; '-' = no shortfall (120+)._", ""]
    presets = ["no_shock", "job_loss_ei55", "ei55_6_months", "bills_up_15", "furnace_1_month", "job_loss_plus_bills"]
    out.append("| Persona | account_id | " + " | ".join(presets) + " |")
    out.append("|---|---:|" + "---:|" * len(presets))
    for persona, (acc, _) in picks.items():
        p = engine.get_profile(acc)
        cells = []
        for name in presets:
            m = engine.judge_runway(p, name).months
            cells.append("-" if m is None else f"{m:.1f}")
        out.append(f"| {persona} | {acc} | " + " | ".join(cells) + " |")
    out.append("")
    out.append("`ei55_6_months` uses the judge formula, which assumes the shock lasts for good; "
               "the engine's month-by-month simulation shows the 6-month version.")
    out.append("")
    for persona, (acc, why) in picks.items():
        result = engine.run(acc, "job_loss_plus_bills")
        m = result["simulation"]["months_until_zero_shocked"]
        sim = ("the balance stays above zero for all 24 months" if m is None
               else "the balance is already below zero" if m == 0
               else f"the balance first goes below zero in month {m}")
        out += [f"## {persona} — account {acc}", "", why, "", "```text", engine.summary_text(result), "```",
                f"Month-by-month simulation with the shock: {sim}.", ""]
    return "\n".join(out)


# ── Reports ──────────────────────────────────────────────────────────────────
def _fmt(value: float, unit: str) -> str:
    if unit == "share":
        return f"{100 * value:.1f}%"
    if unit == "CAD":
        return f"${value:,.0f}"
    if unit in ("accounts", "loans"):
        return f"{value:,.0f}"
    return f"{value:,.2f}" if abs(value) < 10 else f"{value:,.1f}"


def findings_markdown(f: pd.DataFrame, auc_table: pd.DataFrame, diffs: pd.DataFrame, figures: dict[str, str]) -> str:
    out = ["# Findings", "",
           f"_Generated by `python -m tangerine.findings` on {datetime.now():%Y-%m-%d %H:%M}. "
           "Every number comes from a mart in `warehouse/tangerine.duckdb` (column **source**). "
           "Shares are shown as percentages; **n** is the sample size behind the number._", ""]
    titles = f.drop_duplicates("finding_id").set_index("finding_id")["finding"]
    order = sorted(titles.index, key=lambda x: int(x[1:]))
    fig_for = {"F1": "f1", "F2": "f2", "F4": "f4", "F5": "f5"}
    for fid in order[:order.index("F9") + 1] + ["F10"] + order[order.index("F9") + 1:]:
        if fid == "F10":
            out += ["## F10 · A lean-month stress runway spots defaulters better than the judge runway (headline)", "",
                    "Pre-loan data only (what the bank knew when it said yes). Higher AUC = better at ranking future "
                    "defaulters above good payers; 0.5 = coin flip.", "",
                    "| Score | AUC | 95% CI | n loans |", "|---|---:|---:|---:|"]
            for name, r in auc_table.iterrows():
                out.append(f"| {name} | {r.AUC:.3f} | {r['CI low']:.3f} – {r['CI high']:.3f} | {int(r['n loans'])} |")
            out += ["", "Paired bootstrap (2,000 resamples of the same loans):", "",
                    "| Comparison | AUC difference | 95% CI | share of draws ≤ 0 |", "|---|---:|---:|---:|"]
            for name, r in diffs.iterrows():
                out.append(f"| {name} | {r['AUC difference']:+.3f} | {r['CI low']:+.3f} – {r['CI high']:+.3f} | "
                           f"{r['share of draws <= 0']:.3f} |")
            out += ["", f"![AUC]({figures['f10_auc']})", "", f"![Quartiles]({figures['f10_quartiles']})", "",
                    "Source: `mart_loan_preloan`, `mart_default_drivers`; AUC computed in `findings.py`.", ""]
            continue
        rows = f[f.finding_id == fid]
        out += [f"## {fid} · {titles[fid]}", "", "| Metric | Value | n | Source |", "|---|---:|---:|---|"]
        for _, r in rows.iterrows():
            out.append(f"| {r.metric} | {_fmt(r.value, r.unit)} | {int(r.n):,} | `{r.source}` |")
        if fid in fig_for:
            key = next(k for k in figures if k.startswith(fig_for[fid]))
            out += ["", f"![{fid}]({figures[key]})"]
        out.append("")
    out += ["## Caveats", "",
            "- 76 defaults is a small sample: every rate is shown with its count.",
            "- \"All defaulters had negative days\" is partly leakage (status D = currently in debt). "
            "The **pre-loan** version (F1: 27 of 27) is clean, and F2, F3 and F10 also use pre-loan months only.",
            "- Runway counts use the judge runway **rounded to 1 decimal**, as the brief specifies. Counting on the "
            "unrounded value gives slightly higher numbers (454 under 3 months, 1,587 under 6 on EI).",
            "- Runway quartiles: many loans tie at 120 months (no shortfall), so the Q3/Q4 split depends on the "
            "tie-break (account_id). The Q1 group, which carries the finding, does not.",
            "- 15 loans had a pre-loan typical spending of $0, so their buffer-in-months is undefined and left out "
            "of that AUC (n = 667).", ""]
    return "\n".join(out)


def data_dictionary_markdown(cols: pd.DataFrame, thresholds: pd.DataFrame) -> str:
    out = ["# Data dictionary — `marts` schema", "",
           "_Generated from the column comments stored in the warehouse "
           "(`select * from duckdb_columns() where schema_name = 'marts'`)._", "",
           "**JUDGE** = exact official definition from the brief · **OURS** = our own metric, always shown beside the "
           "judge number · **FLAG** = true/false warning. Money is CAD.", ""]
    for table, g in cols.groupby("table_name", sort=False):
        out += [f"## `marts.{table}`", "", g.table_description.iloc[0] or "", "",
                "| Column | Type | Meaning |", "|---|---|---|"]
        for _, r in g.iterrows():
            out.append(f"| `{r.column_name}` | {r.data_type} | {r.description.replace('|', '/')} |")
        out.append("")
    out += ["## Thresholds (`marts.config_thresholds`, set in `src/tangerine/config.py`)", "",
            "| Name | Value | Meaning |", "|---|---:|---|"]
    for _, r in thresholds.iterrows():
        out.append(f"| `{r.threshold_name}` | {r.threshold_value:g} | {r.meaning} |")
    return "\n".join(out) + "\n"


# ── F0: who the data lets us test (4,500 accounts → 682 loans → outcomes) ────
def loan_outcome_counts(profile: pd.DataFrame) -> dict[str, int]:
    status = profile.loc[profile.has_loan, "loan_status"].value_counts()
    counts = {
        "accounts": len(profile),
        "loans": int(profile.has_loan.sum()),
        "paid_back": int(status.get("A", 0)),       # A: finished, repaid
        "paying_ok": int(status.get("C", 0)),       # C: running, no problems
        "stopped_paying": int(status.get("B", 0)),  # B: finished, not repaid
        "behind": int(status.get("D", 0)),          # D: running, in debt
    }
    counts["no_loan"] = counts["accounts"] - counts["loans"]
    counts["defaulted"] = counts["stopped_paying"] + counts["behind"]
    return counts


def fig_loan_outcomes(c: dict[str, int]) -> str:
    LIGHT, DARK = "#e4e3dd", "#6f6e69"
    fig, ax = plt.subplots(figsize=(11, 3.9))
    ax.grid(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_visible(False)
    ax.set_xticks([]), ax.set_yticks([])
    h, y_top, y_bot = 0.42, 1.15, 0.0

    def seg(y, left, width, color, text, ink):
        ax.barh(y, width, left=left, height=h, color=color, edgecolor=SURFACE, linewidth=2)
        ax.text(left + width / 2, y, text, ha="center", va="center", fontsize=9.5, color=ink, linespacing=1.3)

    total, loans = c["accounts"], c["loans"]
    split = c["no_loan"] / total
    seg(y_top, 0, split, LIGHT, f"{c['no_loan']:,} accounts with no loan ({split:.0%})\n"
        "no repayment outcome, so they can't test a warning sign", INK_2)
    seg(y_top, split, 1 - split, DARK, f"{loans:,} took\na loan ({1 - split:.0%})", "white")

    # Zoom: the loan slice opens up into the full-width bar below
    ax.fill([split, 1, 1, 0], [y_top - h / 2, y_top - h / 2, y_bot + h / 2, y_bot + h / 2],
            color=DARK, alpha=0.08, lw=0)

    x = 0
    for n, color, text, ink in [
        (c["paid_back"], LIGHT, f"{c['paid_back']:,} paid back in full", INK),
        (c["paying_ok"], "#cfcec7", f"{c['paying_ok']:,} still paying, on time", INK),
        (c["defaulted"], ALERT, f"{c['defaulted']}\ndefaulted", INK),
    ]:
        seg(y_bot, x, n / loans, color, text, ink)
        x += n / loans
    # The default breakdown doesn't fit in the narrow segment: note it just below, right-aligned to it
    ax.text(1.0, y_bot - h / 2 - 0.06, f"{c['stopped_paying']} stopped paying · {c['behind']} behind on payments",
            ha="right", va="top", fontsize=9, color=INK_2)

    ax.text(-0.01, y_top, f"All {total:,}\naccounts", ha="right", va="center", fontsize=10, color=INK)
    ax.text(-0.01, y_bot, f"The {loans:,}\nloans", ha="right", va="center", fontsize=10, color=INK)
    ax.set_xlim(-0.11, 1.0)
    ax.set_ylim(y_bot - h / 2 - 0.22, y_top + h / 2 + 0.05)
    fig.suptitle(f"Who we can test: {loans:,} of {total:,} accounts took a loan, and {c['defaulted']} of them defaulted",
                 x=0.01, ha="left", fontsize=13, fontweight="bold", color=INK)
    return _finish(fig, "f0_accounts_loans_outcomes.png",
                   "A loan's repayment record is the only 'did they get into trouble?' outcome in the data, so the "
                   "682 loans are the test group for F1, F2, F3 and F10. Defaulted = loan status B or D.")


def loan_outcomes_markdown(c: dict[str, int], figure: str) -> list[str]:
    return [
        "## F0 · Who the data lets us test", "",
        "Only borrowers have a known outcome (did they repay?), so warning signs are tested on the loans.", "",
        "| Group | Accounts | Share | Source |", "|---|---:|---:|---|",
        f"| all accounts | {c['accounts']:,} | 100% | `mart_customer_profile` |",
        f"| no loan | {c['no_loan']:,} | {c['no_loan'] / c['accounts']:.1%} | `mart_customer_profile` |",
        f"| took a loan | {c['loans']:,} | {c['loans'] / c['accounts']:.1%} | `mart_customer_profile` |",
        f"| loans paid back in full (status A) | {c['paid_back']:,} | {c['paid_back'] / c['loans']:.1%} of loans | `mart_customer_profile` |",
        f"| loans still paying on time (status C) | {c['paying_ok']:,} | {c['paying_ok'] / c['loans']:.1%} of loans | `mart_customer_profile` |",
        f"| loans defaulted (status B or D) | {c['defaulted']:,} | {c['defaulted'] / c['loans']:.1%} of loans | `mart_customer_profile` |",
        "", f"![F0]({figure})", "",
    ]


def main() -> int:
    config.FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    d = load()
    preloan, drivers = d["mart_loan_preloan"], d["mart_default_drivers"]
    overall = preloan.is_defaulted.mean()

    auc_table, diffs = stress_vs_judge(preloan)
    outcomes = loan_outcome_counts(d["mart_customer_profile"])
    figures = {
        "f0": fig_loan_outcomes(outcomes),
        "f1": fig_preloan_overdraft(drivers),
        "f2": fig_volatility_vs_buffer(drivers, overall),
        "f4": fig_balance_slide(d["mart_balance_slide_summary"]),
        "f5": fig_ei_runway(d["mart_shock_runways"]),
        "f10_auc": fig_auc(auc_table),
        "f10_quartiles": fig_stress_quartiles(drivers, overall),
    }
    md = findings_markdown(d["mart_findings"], auc_table, diffs, figures)
    head, sep, rest = md.partition("\n## ")  # put F0 first: it explains every sample size that follows
    md = head + "\n" + "\n".join(loan_outcomes_markdown(outcomes, figures["f0"])) + "\n" + sep.lstrip("\n") + rest
    (config.REPORTS_DIR / "findings.md").write_text(md, encoding="utf-8")

    picks = pick_showcase(d["mart_customer_profile"], d["mart_shock_runways"], d["mart_balance_slide"])
    (config.REPORTS_DIR / "showcase.md").write_text(showcase_markdown(picks), encoding="utf-8")
    (config.REPORTS_DIR / "data_dictionary.md").write_text(
        data_dictionary_markdown(d["columns"], d["thresholds"]), encoding="utf-8")

    print(auc_table.round(3).to_string())
    print(diffs.round(3).to_string())
    print("Showcase:", {k: v[0] for k, v in picks.items()})
    print(f"Wrote reports/findings.md, reports/showcase.md, reports/data_dictionary.md and {len(figures)} figures.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
