"""Early-warning light: four transparent rules, 0-4 points, shown beside the judges' runway.

It is a watch flag, not a credit score, and it never changes the judges' runway number.

Per account, from monthly_summary.csv:
    rows used  every month after the account's opening month (the opening month is partial)
               up to the snapshot month T
    window w   the last 6 of those rows
    S6         median(money_out) over w; 0 counts as missing. This is the light's own "month of
               spending" (column recent_spending), not the card's S (median over all history) and not
               the engine's metrics S6 (rolling half-year spending); Light.spending_note says so on
               the card, with the dollar figure.

    Rule 1  lowest balance under half a month of spending
            min(min_balance over w) / S6, clipped to [-5, 24], missing -> 24     fires when < 0.5
    Rule 2  almost all spending is cash
            sum(cash_withdrawals_genuine) / sum(money_out) over w, missing -> 0  fires when > 0.95
    Rule 3  irregular money in
            std(money_in) / mean(money_in) over w (std with ddof=1), missing -> 0  fires when > 0.5
    Rule 4  balance sliding more than 10% of a month's spending per month
            least-squares slope of avg_daily_balance on k = 0..5 over w, / S6,
            clipped to [-3, 3], missing -> 0                                     fires when < -0.1

    points = number of rules that fire (0-4).

What the card shows for an account ("today" = snapshot T = the last month in the data):
    "rated"               6+ rows used, days_below_zero is 0 in every row used, and the last row used
                          is month T (the account is still active, so its window ends at T): points,
                          the rules that fired, and the 2025 backtest line for that number of points.
    "already_overdrawn"   6+ rows used but days_below_zero > 0 in at least one row used: points and
                          rules are still shown, but no backtest rate, because the backtest only
                          followed accounts that had never gone below zero.
    "stale"               6+ rows used, never below zero in them, but the account's activity stops
                          before T (its last row is earlier): points and rules from its last 6 rows,
                          but no backtest rate, because the backtest only followed accounts that were
                          still active (every account in it has a row at the snapshot and in 2025).
    "not_enough_history"  fewer than 6 rows used: no points, no rules, no backtest rate.
    Precedence: not_enough_history is checked first, then already_overdrawn, then stale, else rated.
    So a short history that also went below zero is "not_enough_history", and an account that
    went below zero and then stopped is "already_overdrawn".

Backtest (the evidence for each tier): snapshot T = 2024-12, the rules computed on rows up to T.
Population = accounts that are "rated" at T and have at least one row in 2025.
An account "went overdrawn" when days_below_zero > 0 in any of its 2025 rows.
For each number of points: accounts, how many went overdrawn, and the share.

    python -m resilience.warning          # prints the tier table, writes artifacts/early_warning_tiers.csv
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from .core import DATA_DIR, load_monthly

# Source for every constant below: the team's out-of-time backtest (rules taken at the end of 2024-12,
# label = first overdraft in 2025). This module recomputes the backtest table itself;
# tests/test_warning.py pins it.
WINDOW_ROWS = 6                      # w = the last 6 rows up to the snapshot
MIN_BAL_CUT = 0.5                    # Rule 1: min balance / S6 below this
MIN_BAL_CLIP = (-5.0, 24.0)
MIN_BAL_MISSING = 24.0
CASH_SHARE_CUT = 0.95                # Rule 2: cash share of spending above this
INCOME_CV_CUT = 0.5                  # Rule 3: income CV above this
BAL_TREND_CUT = -0.1                 # Rule 4: balance slope / S6 below this
BAL_TREND_CLIP = (-3.0, 3.0)
BACKTEST_SNAPSHOT = "2024-12"        # features use rows up to this month only
BACKTEST_LABEL_YEAR = "2025"         # outcome: any days_below_zero in this year
MAX_POINTS = 4

RATED = "rated"
ALREADY_OVERDRAWN = "already_overdrawn"
STALE = "stale"
NOT_ENOUGH_HISTORY = "not_enough_history"


@dataclass(frozen=True)
class Rule:
    code: str            # column in light_table
    label: str           # plain English, shown on the card
    fires_when: str      # plain English cut, shown in the rule list
    op: str              # "<" or ">"
    cut: float

    def fires(self, value: float) -> bool:
        return bool(value < self.cut) if self.op == "<" else bool(value > self.cut)

    def value_text(self, raw: float) -> str:
        """The account's own (unclipped) value for this rule, in words.

        Shown with 2 decimals, or more when 2 would round onto the cut (0.5025 -> "0.503", not "0.50").
        """
        if raw is None or (isinstance(raw, float) and math.isnan(raw)):
            return {"min_bal_over_S": "n/a (typical spending in the window is $0)",
                    "cash_share": "n/a (no spending in the window)",
                    "inc_cv": "n/a (no money in during the window)",
                    "bal_trend": "n/a (typical spending in the window is $0)"}[self.code]
        unit = {"min_bal_over_S": " months of spending", "cash_share": " of spending",
                "inc_cv": "", "bal_trend": " months of spending per month"}[self.code]
        if self.code == "cash_share":
            fmt = lambda x, d: f"{x:.{d - 1}%}"  # noqa: E731
        elif self.code == "bal_trend":
            fmt = lambda x, d: f"{x:+.{d}f}"  # noqa: E731
        else:
            fmt = lambda x, d: f"{x:.{d}f}"  # noqa: E731
        for d in (2, 3, 4, 5, 6):
            if fmt(raw, d) != fmt(self.cut, d):
                break
        return fmt(raw, d) + unit


RULES = (
    Rule("min_bal_over_S", "lowest balance under half a month of spending",
         "lowest balance < 0.5 months of spending", "<", MIN_BAL_CUT),
    Rule("cash_share", "almost all spending is cash",
         "cash > 95% of spending", ">", CASH_SHARE_CUT),
    Rule("inc_cv", "irregular money in",
         "money in: std ÷ mean > 0.5", ">", INCOME_CV_CUT),
    Rule("bal_trend", "balance sliding more than 10% of a month's spending per month",
         "balance trend < -0.10 months of spending per month", "<", BAL_TREND_CUT),
)


# ---------------------------------------------------------------- features

def usable_months(monthly: pd.DataFrame) -> pd.DataFrame:
    """Every row except each account's opening month (it starts mid-month)."""
    first = monthly.groupby("account_id")["month"].transform("min")
    return monthly[monthly["month"] != first]


def light_table(monthly: pd.DataFrame, snapshot: str | None = None) -> pd.DataFrame:
    """One row per account in `monthly`: rows used, the 4 rule inputs, which rules fire, points, status.

    `monthly` must hold every row of each account it covers. `snapshot` = T, the last month the
    rules may see (default: the last month in `monthly`). Columns ending in "_raw" are the
    account's own values before clipping and missing-value fills (NaN when undefined); the rules
    use the clipped and filled columns, exactly as the backtest did.
    """
    T = snapshot or str(monthly["month"].max())
    ids = pd.Index(sorted(monthly["account_id"].unique()), name="account_id")
    ms = usable_months(monthly)
    hist = ms[ms["month"] <= T].sort_values(["account_id", "month"], kind="stable")
    g = hist.groupby("account_id", sort=True)
    w = g.tail(WINDOW_ROWS)
    gw = w.groupby("account_id", sort=True)

    out = pd.DataFrame(index=ids)
    out["rows_used"] = g.size().reindex(ids).fillna(0).astype(int)
    out["days_below_zero"] = g["days_below_zero"].sum().reindex(ids).fillna(0.0)
    out["last_month"] = g["month"].max().reindex(ids)          # end of the window; NaN with no rows
    s6 = gw["money_out"].median().reindex(ids)
    s6nz = s6.replace(0, np.nan)
    out["recent_spending"] = s6                                # the rules' month of spending (not S, not metrics S6)

    min_bal = gw["min_balance"].min().reindex(ids) / s6nz
    out["min_bal_over_S_raw"] = min_bal
    out["min_bal_over_S"] = min_bal.clip(*MIN_BAL_CLIP).fillna(MIN_BAL_MISSING)

    cash = gw["cash_withdrawals_genuine"].sum().reindex(ids) / gw["money_out"].sum().reindex(ids).replace(0, np.nan)
    out["cash_share_raw"] = cash
    out["cash_share"] = cash.fillna(0.0)

    cv = gw["money_in"].std().reindex(ids) / gw["money_in"].mean().reindex(ids).replace(0, np.nan)
    out["inc_cv_raw"] = cv
    out["inc_cv"] = cv.fillna(0.0)

    # least-squares slope of avg_daily_balance on k = 0..n-1, closed form (same as the backtest)
    w = w.assign(k=w.groupby("account_id").cumcount())
    acct = w["account_id"]
    xy = (w["k"] * w["avg_daily_balance"]).groupby(acct).sum()
    sx = w.groupby("account_id")["k"].sum()
    sy = w.groupby("account_id")["avg_daily_balance"].sum()
    sxx = (w["k"] ** 2).groupby(acct).sum()
    nn = w.groupby("account_id").size()
    slope = ((nn * xy - sx * sy) / (nn * sxx - sx ** 2).replace(0, np.nan)).reindex(ids)
    trend = slope / s6nz
    out["bal_trend_raw"] = trend
    out["bal_trend"] = trend.clip(*BAL_TREND_CLIP).fillna(0.0)

    for rule in RULES:
        col = out[rule.code]
        out[f"fires_{rule.code}"] = (col < rule.cut) if rule.op == "<" else (col > rule.cut)
    points = sum(out[f"fires_{r.code}"].astype(int) for r in RULES)

    short = out["rows_used"] < WINDOW_ROWS
    stopped = out["last_month"] != T                           # activity stops before T
    out["status"] = np.where(short, NOT_ENOUGH_HISTORY, np.where(out["days_below_zero"] > 0, ALREADY_OVERDRAWN,
                                                                 np.where(stopped, STALE, RATED)))
    out["points"] = points.astype("Int64").mask(short)
    return out


# ---------------------------------------------------------------- backtest

@dataclass(frozen=True)
class Tier:
    points: int
    accounts: int
    went_overdrawn: int

    @property
    def rate(self) -> float:
        return self.went_overdrawn / self.accounts if self.accounts else float("nan")

    @property
    def rate_text(self) -> str:
        if not self.accounts:
            return "n/a"
        return f"{self.rate:.2%}" if self.rate < 0.01 else f"{self.rate:.1%}"

    def line(self, label_year: str = BACKTEST_LABEL_YEAR) -> str:
        pts = "point" if self.points == 1 else "points"
        return (f"In the {label_year} backtest, {self.went_overdrawn:,} of {self.accounts:,} accounts with "
                f"{self.points} {pts} went overdrawn ({self.rate_text}).")


@dataclass(frozen=True)
class Backtest:
    snapshot: str
    label_year: str
    tiers: tuple[Tier, ...]          # points 0..4

    @property
    def population(self) -> int:
        return sum(t.accounts for t in self.tiers)

    @property
    def events(self) -> int:
        return sum(t.went_overdrawn for t in self.tiers)

    def tier(self, points: int) -> Tier:
        return self.tiers[int(points)]

    def table(self) -> pd.DataFrame:
        return pd.DataFrame({"points": [t.points for t in self.tiers],
                             "accounts": [t.accounts for t in self.tiers],
                             "went_overdrawn": [t.went_overdrawn for t in self.tiers],
                             "rate": [t.rate for t in self.tiers]})


def backtest_frame(monthly: pd.DataFrame, snapshot: str = BACKTEST_SNAPSHOT,
                   label_year: str = BACKTEST_LABEL_YEAR) -> pd.DataFrame:
    """The backtest population: light_table rows at `snapshot` for the accounts rated then and still observed
    in `label_year`, plus `went_overdrawn` (any day below zero in a `label_year` row after the snapshot)."""
    lt = light_table(monthly, snapshot)
    ms = usable_months(monthly)
    fut = ms[(ms["month"] > snapshot) & ms["month"].str.startswith(label_year)]
    went = fut.groupby("account_id")["days_below_zero"].sum() > 0
    pop = lt[(lt["status"] == RATED) & lt.index.isin(fut["account_id"].unique())].copy()
    pop["went_overdrawn"] = went.reindex(pop.index, fill_value=False).astype(bool)
    return pop


def backtest(monthly: pd.DataFrame, snapshot: str = BACKTEST_SNAPSHOT,
             label_year: str = BACKTEST_LABEL_YEAR) -> Backtest:
    """Rules at `snapshot`, outcome = any days below zero in `label_year` (rows after the snapshot)."""
    pop = backtest_frame(monthly, snapshot, label_year)
    y = pop["went_overdrawn"]
    pts = pop["points"].astype(int)
    tiers = tuple(Tier(p, int((pts == p).sum()), int(((pts == p) & y).sum())) for p in range(MAX_POINTS + 1))
    return Backtest(snapshot, label_year, tiers)


@lru_cache(maxsize=4)
def cached_backtest(data_dir: str = str(DATA_DIR)) -> Backtest:
    """The backtest on the track data, computed once per process."""
    return backtest(load_monthly(data_dir))


# ---------------------------------------------------------------- one account

@dataclass(frozen=True)
class RuleResult:
    rule: Rule
    value: float          # clipped / filled value the rule tests
    raw: float            # the account's own value (NaN when undefined)
    fired: bool

    @property
    def value_text(self) -> str:
        return self.rule.value_text(self.raw)


@dataclass(frozen=True)
class Light:
    account_id: int
    status: str
    rows_used: int
    points: int | None
    rules: tuple[RuleResult, ...]     # empty when there is not enough history
    tier: Tier | None                 # only when status == "rated"
    last_month: str | None = None     # the last row used (the end of the window)
    recent_spending: float = float("nan")  # median money_out over the window: the rules' month of spending

    @property
    def fired(self) -> list[str]:
        return [r.rule.label for r in self.rules if r.fired]

    @property
    def badge(self) -> str:
        if self.points is None:
            return "Early-warning light: not enough history"
        return f"Early-warning light {self.points}/{MAX_POINTS}"

    @property
    def backtest_line(self) -> str:
        if self.status == RATED:
            return self.tier.line()
        if self.status == ALREADY_OVERDRAWN:
            return ("Already overdrawn before: this account has gone below zero in its history, so no backtest "
                    "rate is shown (the backtest only followed accounts that had never gone below zero).")
        if self.status == STALE:
            return (f"Activity stops in {self.last_month}: the points are from the account's last {WINDOW_ROWS} "
                    "months up to then, so no backtest rate is shown (the backtest only followed accounts that "
                    "were still active).")
        return (f"Not enough history: the light needs {WINDOW_ROWS} months after the opening month and this "
                f"account has {self.rows_used}, so no points or backtest rate.")

    @property
    def line(self) -> str:
        """The one line on the customer card."""
        if self.points is None:
            return f"Early-warning light: {self.backtest_line}"
        why = "; ".join(self.fired) if self.fired else "no rule fired"
        return f"{self.badge}: {why}. {self.backtest_line}"

    @property
    def spending_note(self) -> str | None:
        """What "a month of spending" means in rules 1 and 4, under the rule list (None without rules).

        It is the window's median money_out, not the card's S, so the months can differ from the Buffer's.
        """
        if self.points is None:
            return None
        head = ("In the lowest-balance and balance-trend rules, a month of spending is this account's median "
                f"money out over the same {WINDOW_ROWS} months: ${self.recent_spending:,.2f}")
        if self.recent_spending == 0:
            return f"{head}, so those two rules can't be measured and don't fire."
        return (f"{head}. That is not the card's S (the median over all history), so these months can differ "
                "from the Buffer's.")


def light_from_row(account_id: int, row: pd.Series, bt: Backtest) -> Light:
    """Build a Light from one row of light_table."""
    status = str(row["status"])
    rows_used = int(row["rows_used"])
    last = row["last_month"] if isinstance(row["last_month"], str) else None
    spend = float(row["recent_spending"])
    if status == NOT_ENOUGH_HISTORY:
        return Light(int(account_id), status, rows_used, None, (), None, last, spend)
    rules = tuple(RuleResult(r, float(row[r.code]), float(row[f"{r.code}_raw"]), bool(row[f"fires_{r.code}"]))
                  for r in RULES)
    points = int(row["points"])
    return Light(int(account_id), status, rows_used, points, rules, bt.tier(points) if status == RATED else None,
                 last, spend)


def account_light(monthly: pd.DataFrame, account_id: int, bt: Backtest, snapshot: str | None = None) -> Light:
    """The light for one account today (snapshot = last month in `monthly` unless given)."""
    T = snapshot or str(monthly["month"].max())
    rows = monthly[monthly["account_id"] == account_id]
    if rows.empty:
        raise KeyError(account_id)
    return light_from_row(account_id, light_table(rows, T).loc[account_id], bt)


# ---------------------------------------------------------------- artifact

def main(out_dir: Path | None = None) -> None:
    from .portfolio import ARTIFACTS
    out_dir = ARTIFACTS if out_dir is None else out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    bt = cached_backtest()
    table = bt.table()
    print(f"backtest snapshot {bt.snapshot}, outcome year {bt.label_year}: "
          f"{bt.population:,} accounts, {bt.events} went overdrawn")
    print(table.to_string(index=False))
    path = out_dir / "early_warning_tiers.csv"
    table.to_csv(path, index=False)
    print(f"wrote {path.relative_to(out_dir.parent)} ({len(table)} rows)")


if __name__ == "__main__":
    from .portfolio import parse_out_dir
    main(parse_out_dir("resilience.warning", __doc__))
