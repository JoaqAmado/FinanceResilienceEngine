"""Every figure in README.md and docs/ is recomputed here by the engine, and the data dictionary matches the CSVs.

A figure is pinned twice: the sentence that quotes it must appear in its doc, and every number left in a doc's
prose (code blocks and `code` spans aside) must be either a pinned figure or a definition taken from the code.
"""
import calendar
import re
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from resilience import benchmark as BM
from resilience import evidence as E
from resilience import warehouse
from resilience import warning as W
from resilience.core import (
    DATA_DIR,
    DATA_END_MONTH,
    DOUBLE_WHAMMY,
    EI_2026_MAX_MONTHLY,
    EI_2026_MAX_WEEKLY,
    FURNACE,
    LAID_OFF_EI,
    NO_SHORTFALL_LABEL,
    RUNWAY_CAP_MONTHS,
    WAITING_WEEK_LABEL,
    WEEKS_PER_MONTH,
    Shock,
    account_flags,
    apply_shock,
    backup_ladder,
    baseline_metrics,
    build_metrics,
    load_loans,
    load_monthly,
    portfolio_runway,
    runway,
)
from resilience.portfolio import INCOME_LABELS, QUARTER_CUT_PCT, REALISTIC_CUT_PCTS, build_all

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
ARTIFACTS = ROOT / "data" / "derived"
TARGET = 6  # the six-month test on the judges' EI twist

needs_data = pytest.mark.skipif(not (DATA_DIR / "monthly_summary.csv").exists(), reason="track data not present")

CODE = re.compile(r"```.*?```|`[^`\n]*`", re.S)
NUMBER = re.compile(r"(?<![\w'.])(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?")


def read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def numbers(text: str) -> set[str]:
    return set(NUMBER.findall(text))


def prose_numbers(md: str) -> set[str]:
    """Numbers outside fenced code blocks and `code` spans."""
    return numbers(CODE.sub(" ", md))


def readme_intro() -> str:
    """The README up to its first section: the only part that quotes figures."""
    return read("README.md").split("\n## ", 1)[0]


# Definitions taken from the code, which docs may quote without a computed figure.
assert abs(WEEKS_PER_MONTH - 52 / 12) < 1e-12 and EI_2026_MAX_MONTHLY == EI_2026_MAX_WEEKLY * 52 / 12
EI_PCT = f"{LAID_OFF_EI.income_multiplier:.0%}"[:-1]
BILLS_PCT = f"{DOUBLE_WHAMMY.bills_increase_pct:.0%}"[:-1]
DEFINITIONS = {
    str(TARGET), EI_PCT, f"{LAID_OFF_EI.income_multiplier:g}",
    "2026", f"{EI_2026_MAX_WEEKLY:,.0f}", f"{EI_2026_MAX_MONTHLY:,.0f}", "52", "12",  # the 2026 EI maximum
    *numbers(INCOME_LABELS[0] + " " + INCOME_LABELS[-1]),                            # the end bands
    DATA_END_MONTH[:4],
}


def ladder_step_numbers() -> set[str]:
    """The percentages in backup_ladder's step names, read off a ladder where every step applies."""
    r = pd.Series(dict(I=0.0, F=0.0, S=1e6, B=1.0, H=0.0, P=100.0, flexible_median=1000.0, bank_fees_median=10.0,
                       so_other=100.0, transfers_out_other_median=100.0, loan_payments_median=100.0))
    lad = backup_ladder(r, LAID_OFF_EI)
    assert len(lad.rungs) == 6
    return numbers(" ".join(x.step for x in lad.rungs))


METHOD_DEFINITIONS = DEFINITIONS | ladder_step_numbers() | numbers(WAITING_WEEK_LABEL) | {
    BILLS_PCT, f"{DOUBLE_WHAMMY.bills_increase_pct:g}", f"{FURNACE.one_off_multiple_of_S:g}",
    f"{RUNWAY_CAP_MONTHS:g}", f"{runway(0, 0, 1, 0).months:g}", str(W.WINDOW_ROWS), str(W.MAX_POINTS),
    *numbers(W.BACKTEST_SNAPSHOT + " " + W.BACKTEST_LABEL_YEAR),
    *numbers(" ".join(r.label + " " + r.fires_when for r in W.RULES)),
}


# ------------------------------------------------------------- the figures

@pytest.fixture(scope="module")
def m():
    return build_metrics()


@pytest.fixture(scope="module")
def figures(m):
    """Each doc's figures, as the sentences that quote them, all computed from data/raw/."""
    t = build_all(m)
    acc, h = t["accounts"], t["headlines"].iloc[0]
    n, fail, cap = int(h["accounts"]), int(h["fail_6mo_ei55"]), int(h["fail_6mo_ei55_cap2026"])

    bands = t["income_bands"].set_index("income_band")
    low, high = bands.loc[INCOME_LABELS[0]], bands.loc[INCOME_LABELS[-1]]

    judge, s6 = acc["runway_ei55"], acc["runway_ei55_S6"]
    safe = judge >= TARGET
    ms = load_monthly()
    rows = ms[ms.groupby("account_id").cumcount() > 0]  # opening month excluded, as for S6
    roll = rows.groupby("account_id")["money_in"].rolling(6).sum().dropna()
    i6 = (roll.groupby(level=0).median() / 6).reindex(m.index).fillna(m["I"])  # money in on S6's window
    both = portfolio_runway(m.assign(I=i6), LAID_OFF_EI.with_(spending_basis="S6"))
    flips, flips_both = int((safe & (s6 < TARGET)).sum()), int((safe & (both < TARGET)).sum())
    cal = m[[f"cal_{k:02d}" for k in range(1, 13)]].div(m["S"].replace(0, np.nan), axis=0).median()
    peaks = " and ".join(calendar.month_name[int(c[4:])] for c in sorted(cal.nlargest(2).index))

    failing = judge < TARGET
    cuts = t["cut_histogram"].set_index("cut_as_share_of_spending")["accounts"]
    quarter = int(cuts["<= 10%"] + cuts["10-25%"])
    positive = int((failing & (acc["B"] > 0)).sum())
    assert positive == int(cuts.drop("already overdrawn (B <= 0)").sum())
    rc = t["realistic_cuts"].set_index("max_cut_pct")
    assert int(rc.loc[QUARTER_CUT_PCT, "accounts"]) == quarter and set(rc["failing_with_buffer"]) == {positive}
    lo_cut, hi_cut = (rc.loc[k] for k in REALISTIC_CUT_PCTS)
    k = lambda x: f"${x / 1000:.1f}k"  # noqa: E731
    no_rung = sum(backup_ladder(m.loc[a], LAID_OFF_EI).first_sufficient is None for a in acc.index[failing])

    pre = t["preloan_overdraft"].set_index("overdrawn_before_loan")
    repaying = acc["loan_status"].isin(["A", "C"])
    assert int(acc.loc[repaying, "ever_negative"].sum()) == 0  # "none ... ever went negative"

    parts_in = ms[["cash_deposits", "transfers_in", "pension_in", "interest_in"]].sum(axis=1)
    parts_out = ms[["household_bills", "insurance", "loan_payments", "bank_fees", "cash_withdrawals_genuine",
                    "card_withdrawals", "transfers_out_other"]].sum(axis=1)
    assert (parts_in - ms["money_in"]).abs().max() < 0.005 and (parts_out - ms["money_out"]).abs().max() < 0.005
    assert str(ms["month"].max()) == DATA_END_MONTH
    flags = pd.Series([c for a in m.index for c, _ in account_flags(m.loc[a])]).value_counts()
    assert int(flags["no_bills"] + flags["bills_by_standing_order"]) == int((m["H"] == 0).sum())
    end = f"{calendar.month_abbr[int(DATA_END_MONTH[5:])]} {DATA_END_MONTH[:4]}"
    mb = round((DATA_DIR / "transactions.csv").stat().st_size / 1e6, -2)

    loans = load_loans()
    ev = E.build_evidence(ms, loans)
    es, lift = ev["summary"], ev["lift"].set_index("list_pct").loc[E.HEADLINE_LIST_PCT]
    irr_a = E.irregular_cell(ev["irregular"], "yes", "passes")
    irr_b = E.irregular_cell(ev["irregular"], "no", "fails")
    s6 = ev["s6"].set_index("spending_basis")
    rate = lambda c: f"{c['rate'] * 100:.1f}%, "  # noqa: E731
    span = lambda c: f"{c['ci_low'] * 100:.1f}–{c['ci_high'] * 100:.1f}%"  # noqa: E731
    pop = W.backtest_frame(ms)  # the same population with the partial opening month kept in I, S and B
    kept = E.score_frame(pop, baseline_metrics(ms[ms["month"] <= es["snapshot"]], loans))
    ks, kl = E.summary(kept), E.lift_table(kept).set_index("list_pct").loc[E.HEADLINE_LIST_PCT]
    org = E.S6_ORIGINS
    bm = BM.cached_benchmark()
    bh, bl, btr = bm.row(BM.HEADLINE_BUDGET), bm.row(BM.LIGHT_BUDGET), bm.train
    assert int(bh.light) == int(lift.light) and int(bh.list_accounts) == int(lift.list_accounts)  # the same lists
    split = lambda r: (int(r.gradient_boosting_only), int(r.light_only))  # noqa: E731  (overdrafts on one list only)
    assert min(BM.sign_test_p(*split(r)) for r in (bh, bl)) >= BM.SIGN_TEST_ALPHA  # "can't tell the two apart"
    vs = lambda r: BM.versus(int(r.gradient_boosting), int(r.light), *split(r))  # noqa: E731
    versus_rules = f"{vs(bh)} the light's {len(W.RULES)} rules"

    return {
        "readme": [
            f"Tangerine's {n:,} accounts",
            f"**{fail:,} of {n:,} accounts ({fail / n:.1%})**",
        ],
        "docs/findings.md": [
            f"**{fail:,} of {n:,} ({fail / n:.1%})**",
            f"{low['fail_6mo_ei55_pct']:.1f}% under {INCOME_LABELS[0][2:]} → "
            f"{high['fail_6mo_ei55_pct']:.1f}% over {INCOME_LABELS[-1][3:]}",
            f"Buffers: {low['median_buffer_months']:.1f} → {high['median_buffer_months']:.1f} months of spending",
            f"median buffer {k(low['median_B'])} → {k(high['median_B'])}, median monthly spending "
            f"{k(low['median_S'])} → {k(high['median_S'])}",
            f"(${EI_2026_MAX_WEEKLY:,.0f}/week ≈ ${EI_2026_MAX_MONTHLY:,.0f}/month) | {cap:,} ({cap / n:.1%})",
            f"{flips:,} of {int(safe.sum()):,} ({flips_both:,}, or 1 in {round(safe.sum() / flips_both)}, "
            f"with the same window on money in too)",
            f"Calendar caveat: spending peaks in {peaks}",
            f"{round(4 * quarter / positive)} in 4 ({quarter:,} of {positive:,} with a positive buffer); "
            f"only {no_rung:,} can't cut their way there",
            f"(about {REALISTIC_CUT_PCTS[0]}–{REALISTIC_CUT_PCTS[1]}% of spending)",
            f"{REALISTIC_CUT_PCTS[1]}% or less: {int(hi_cut.accounts):,} of {positive:,} ({hi_cut.share_pct:.1f}%) · "
            f"{REALISTIC_CUT_PCTS[0]}% or less: {int(lo_cut.accounts):,} ({lo_cut.share_pct:.1f}%)",
            f"{int(pre.loc['yes', 'defaulted (B/D)'])} of {int(pre.loc['yes'].sum())} in this data "
            f"(none of the {int(repaying.sum()):,} repaying borrowers ever went negative)",
            # the 2025 backtest (resilience/evidence.py)
            f"every score taken at the {es['snapshot']} snapshot, on the {es['accounts']:,} accounts rated then",
            f"and still active in {es['label_year']}, of which {es['went_overdrawn']} first went overdrawn in "
            f"{es['label_year']}.",
            f"| Of those {es['went_overdrawn']}, passed the judges' EI {EI_PCT}% test at the snapshot | "
            f"{es['passed_ei55']} (the light had flagged {es['passed_and_flagged']} of them, {es['watch_points']}+ points) |",
            f"| Overdrafts caught by a {E.HEADLINE_LIST_PCT}% watch-list ({int(lift.list_accounts):,} accounts) | "
            f"light (most points, then lowest balance) {lift.light} · judges' EI {EI_PCT}% runway {lift.ei55_runway} · buffer months {lift.buffer_months} |",
            f"went overdrawn in {es['label_year']} | irregular money in that passes the EI test: "
            f"{irr_a.went_overdrawn} of {irr_a.accounts:,} ({rate(irr_a)}95% interval {span(irr_a)}) · steady money in "
            f"that fails it: {irr_b.went_overdrawn} of {irr_b.accounts:,} ({rate(irr_b)}{span(irr_b)}) |",
            f"({len(org)} as-of months, {s6.loc['S', 'account_halfyears']:,} account half-years): of the "
            f"{s6.loc['S', 'real_fails']:,} that fail the {E.S6_HORIZON}-month EI test",
            f"| the same test on the median month S: {s6.loc['S', 'missed_real_fails']:,} · on half-year S6: "
            f"{s6.loc['S6', 'missed_real_fails']:,} (false alarms: S {s6.loc['S', 'false_alarms']:,} · "
            f"S6 {s6.loc['S6', 'false_alarms']:,}) |",
            f"those had {E.WATCH_POINTS}+ points on the light",
            f"I, S and B, as the live card does, {ks['passed_ei55']} of the {ks['went_overdrawn']} had passed, the light "
            f"flagged {ks['passed_and_flagged']} of them, and the EI runway",
            f"catches {kl.ei55_runway} on the {E.HEADLINE_LIST_PCT}% list",
            f"watch-lists of {E.LIST_PCTS[0]}–{E.LIST_PCTS[-1]}% of the backtest population",
            f"the light's own rule ({W.RULES[2].fires_when} over its {W.WINDOW_ROWS}",
            f"It rests on {irr_a.went_overdrawn} and {irr_b.went_overdrawn}",
            f"at each of {', '.join(org[:-1])} and {org[-1]}, every",
            f"account with a row {E.S6_HISTORY} months earlier and all {E.S6_HORIZON} months after it",
            # the gradient-boosting benchmark (resilience/benchmark.py)
            f"| Gradient boosting on {len(BM.FEATURES)} features, trained on {btr.label_year}'s outcomes "
            f"({len(btr.X):,} accounts, {int(btr.y.sum())} went overdrawn), on watch-lists of the same size | "
            f"{E.HEADLINE_LIST_PCT}% watch-list: {int(bh.gradient_boosting)}, {versus_rules} ({int(bh.light)}) · as "
            f"many accounts as the light flags with {E.WATCH_POINTS}+ points ({int(bl.list_accounts):,}): "
            f"{int(bl.gradient_boosting)}, {vs(bl)} the light ({int(bl.light)}). The lists catch different "
            f"overdrafts: {split(bh)[0]} only on the model's and {split(bh)[1]} only on the light's on the "
            f"{E.HEADLINE_LIST_PCT}% list, {split(bl)[0]} and {split(bl)[1]} at {int(bl.list_accounts):,}, so this data "
            f"can't tell the two rankings apart |",
            f"the {len(btr.X):,} accounts rated at the {btr.snapshot} snapshot and still active in {btr.label_year}",
            f"On {len(btr.X):,} training accounts early stopping stays off, so every run gives the same scores whatever "
            f"the `random_state`",
            "`versus()` words the model's count \"about as many\" unless an exact two-sided sign test on",
            f"is below `SIGN_TEST_ALPHA` (`{BM.SIGN_TEST_ALPHA:g}`); at both sizes it is not",
            f"ranks the same {len(bm.test.X):,} accounts as the watch-lists",
            f"Its {len(BM.FEATURES)} features read only the months up to each snapshot: the light's {len(W.RULES)} rule "
            f"inputs",
            f"over the light's {W.WINDOW_ROWS} months",
        ],
        "docs/model_card.md": [
            f"re-dated to {str(ms['month'].min())[:4]}–{DATA_END_MONTH[:4]}",
            # at a glance: the backtest's time-based split and base rate (resilience/evidence.py)
            f"every score uses only data up to the {es['snapshot']} snapshot",
            f"**Base rate:** {es['went_overdrawn']} of {es['accounts']:,} accounts "
            f"({es['went_overdrawn'] / es['accounts']:.1%}) first went overdrawn in {es['label_year']}.",
            f"on all {len(ms):,} rows",
            f"({ms['cash_deposits'].sum() / ms['money_in'].sum():.1%} cash deposits)",
            f"{ms['cash_withdrawals_genuine'].sum() / ms['money_out'].sum():.1%} of spending is cash",
            f"negative buffer ({int(flags['overdrawn'])} accounts)",
            f"zero median money in ({int(flags['no_income'])})",
            f"zero median spending ({int(flags['no_spending'])})",
            f"no recorded household bills ({int((m['H'] == 0).sum()):,})",
            f"accounts that stop before {end} ({int(flags['stale'])})",
            # evaluation: the gradient-boosting benchmark (resilience/benchmark.py)
            f"on the {E.HEADLINE_LIST_PCT}% watch-list it catches {versus_rules}",
        ],
        "docs/warehouse.md": [
            f"matches the engine on all {n:,} accounts and gives the same {fail:,} under {TARGET} months",
            f"the {mb:.0f} MB transactions file",
        ],
    }


def allowed(figures, name: str) -> set[str]:
    return set().union(*(numbers(s) for s in figures[name]))


@needs_data
@pytest.mark.parametrize("name", ["docs/findings.md", "docs/model_card.md", "docs/warehouse.md"])
def test_each_doc_quotes_the_engine_figures(figures, name):
    text = read(name)
    for sentence in figures[name]:
        assert sentence in text, f"{name}: {sentence!r}"


@needs_data
@pytest.mark.parametrize("name", ["docs/findings.md", "docs/model_card.md", "docs/warehouse.md"])
def test_no_number_in_a_doc_is_hand_typed(figures, name):
    stray = prose_numbers(read(name)) - allowed(figures, name) - DEFINITIONS
    assert not stray, f"{name}: numbers not computed by the engine: {sorted(stray)}"


@needs_data
def test_readme_headline_is_pinned_and_matches_the_findings(figures):
    intro = readme_intro()
    for sentence in figures["readme"]:
        assert sentence in intro, sentence
    quoted = prose_numbers(intro) - DEFINITIONS
    assert quoted and quoted <= allowed(figures, "readme")
    assert quoted <= prose_numbers(read("docs/findings.md"))  # the README repeats the findings, never adds one


@needs_data
def test_method_doc_matches_the_code(m):
    text = read("docs/method.md")
    for rule in W.RULES:
        assert f"| {rule.label} | {rule.fires_when} |" in text, rule.code
    for sentence in (
        f"min(buffer_left / gap, {RUNWAY_CAP_MONTHS:g})", f'"{NO_SHORTFALL_LABEL}"',
        f"income = {LAID_OFF_EI.income_multiplier:g} × I", f"one-off = {FURNACE.one_off_multiple_of_S:g} × S",
        f"household bills +{BILLS_PCT}%, so spending = S + {DOUBLE_WHAMMY.bills_increase_pct:g} × H",
        f"(${EI_2026_MAX_WEEKLY:,.0f}/week, canada.ca)", f"0 to {W.MAX_POINTS} points",
        f"until {WAITING_WEEK_LABEL.split('until ', 1)[1]}",  # the waiver end date, as both apps label it
        f"the rules taken at {W.BACKTEST_SNAPSHOT}", f"any day below zero in {W.BACKTEST_LABEL_YEAR}",
        f"RunwayResult(months={apply_shock(m.loc[20143], Shock(income_multiplier=0.55)).months:g}, ...)",
    ):
        assert sentence in text, sentence
    stray = prose_numbers(text) - METHOD_DEFINITIONS
    assert not stray, f"docs/method.md: numbers not taken from the code: {sorted(stray)}"
    ids = {int(x) for x in re.findall(r"resilience (\d{5})\b", text)}
    assert ids and ids <= set(m.index)


def test_warehouse_doc_lists_the_settings_the_code_reads():
    text = read("docs/warehouse.md")
    for name in (*warehouse.REQUIRED, *warehouse.SECRETS, *warehouse.DEFAULTS):
        assert f"`{name}`" in text, name
    for name, default in warehouse.DEFAULTS.items():
        if default:
            assert f"| `{name}` | optional, default `{default}` |" in text, name
    assert f"upload {len(warehouse.TABLES)} tables (not transactions)" in text
    assert [p.name for p in warehouse.sql_files()] and warehouse.SQL_DIR == ROOT / "sql"


# --------------------------------------------------------- data dictionary

def dictionary() -> dict[str, list[str]]:
    """Section heading -> the column names listed in its table (a `a` … `b` row lists both ends)."""
    sections: dict[str, list[str]] = {}
    current = None
    for line in read("docs/data_dictionary.md").splitlines():
        head = re.match(r"#{2,3} (.+)$", line)
        if head:
            current = head.group(1).strip()
            sections[current] = []
            continue
        cell = re.match(r"\| `([^`]+)`(?: … `([^`]+)`)? \|", line)
        if current and cell:
            sections[current] += [c for c in cell.groups() if c]
    return sections


@pytest.mark.parametrize("folder", [DATA_DIR, ARTIFACTS], ids=["raw", "derived"])
def test_data_dictionary_matches_every_csv_header(folder):
    files = sorted(folder.glob("*.csv"))
    if not files:
        pytest.skip(f"no CSV files in {folder.relative_to(ROOT).as_posix()}/")
    d = dictionary()
    for path in files:
        key = f"`{folder.relative_to(ROOT).as_posix()}/{path.name}`"
        assert key in d, f"{key} is missing from docs/data_dictionary.md"
        assert d[key] == list(pd.read_csv(path, nrows=0).columns), key


@needs_data
def test_data_dictionary_lists_exactly_the_engine_columns(m):
    listed = dictionary()["Engine metric columns"]
    ranges = re.findall(r"`(\w+?)(\d+)` … `\w+?(\d+)`", read("docs/data_dictionary.md"))
    for stem, lo, hi in ranges:
        listed += [f"{stem}{k:0{len(lo)}d}" for k in range(int(lo), int(hi) + 1)]
    assert set(listed) == set(m.columns)


def test_data_dictionary_quotes_no_figures():
    assert not prose_numbers(read("docs/data_dictionary.md"))
