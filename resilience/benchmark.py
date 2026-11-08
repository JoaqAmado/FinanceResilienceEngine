"""Machine-learning benchmark: gradient boosting on 13 features against the early-warning light's 4 rules.

    python -m resilience.benchmark     # prints the comparison, writes artifacts/ml_benchmark.csv

The product ships no trained model: both apps show the light's 4 transparent rules. This module only checks whether a
model trained on the same data would have caught more of the 2025 overdrafts. Neither app imports it.

Train  the light's backtest one year earlier (warning.backtest_frame at TRAIN_SNAPSHOT 2023-12): the accounts rated
       then and still active in TRAIN_LABEL_YEAR 2024; an account went overdrawn when it has any day below zero
       in a 2024 row.
Test   the 2025 backtest of resilience.evidence, unchanged (evidence.snapshot_scores at the 2024-12 snapshot): the
       same accounts, outcome, light ranking and watch-list sizes as the lift chart (evidence.risk_order, list_size).

Each feature reads only the account's full months up to the snapshot (the opening month is partial and left out).
"The window" is the last 6 of those months, the light's window. I, S and B are the judges' numbers on those months.
    buffer_months_capped    B / S, capped at BUFFER_CAP_MONTHS (no spending -> the cap)
    min_bal_over_S          the light's rule 1 input: lowest balance / the window's median money out
    cash_share              rule 2: cash withdrawals / money out over the window
    inc_cv                  rule 3: std / mean of money in over the window
    bal_trend               rule 4: the balance's monthly slope / the window's median money out
    spend_ratio             money out / money in over the window, capped at RATIO_CAP (no money in -> 1)
    fixed_share             (household bills + insurance) / money in over the window, capped (no money in -> 0)
    loan_share              loan payments / money in over the window, capped (no money in -> 0)
    fees_per_month          mean bank fees per month over the window
    log_money_in            log(1 + I), with I floored at 0
    cash_deposit_share      cash deposits / money in over the window (no money in -> 0)
    runway_ei55_capped      the judges' EI 55% runway before rounding; no shortfall -> RUNWAY_CAP_MONTHS
    runway_no_shock_capped  the judges' runway with no shock (spending S, money in I), the same way

Model: scikit-learn's HistGradientBoostingClassifier with GBM_PARAMS. random_state is fixed and the training set is
too small for early stopping to switch on, so two fits give the same scores. Ranking: highest model score first,
remaining ties by lowest account_id (the tie rule of evidence.risk_order).

Two flag budgets on the test year; at each, how many of the accounts that went overdrawn each ranking flags:
    HEADLINE_BUDGET   the evidence.HEADLINE_LIST_PCT watch-list: gradient boosting, light, EI runway, buffer months
    LIGHT_BUDGET      as many accounts as the light shows as a warning (evidence.WATCH_POINTS or more points)
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier

from .core import DATA_DIR, RUNWAY_CAP_MONTHS, load_loans, load_monthly
from .evidence import HEADLINE_LIST_PCT, RANKINGS, WATCH_POINTS, list_size, risk_order, snapshot_scores
from .warning import BACKTEST_LABEL_YEAR, BACKTEST_SNAPSHOT, RULES, WINDOW_ROWS, backtest_frame, usable_months

TRAIN_SNAPSHOT = "2023-12"           # the model learns from each account's months up to here ...
TRAIN_LABEL_YEAR = "2024"            # ... and who went overdrawn in the year after, all known by the test snapshot
BUFFER_CAP_MONTHS = 24.0             # buffer months above this count as this (and no spending counts as this)
RATIO_CAP = 3.0                      # spend_ratio, fixed_share and loan_share above this count as this
GBM_PARAMS = dict(max_depth=3, learning_rate=0.05, max_iter=300, l2_regularization=1.0, min_samples_leaf=40,
                  random_state=0)
LIGHT_COLUMNS = tuple(r.code for r in RULES)       # the light's 4 rule inputs, reused from warning.light_table
FEATURES = ("buffer_months_capped", "min_bal_over_S", "cash_share", "inc_cv", "bal_trend", "spend_ratio",
            "fixed_share", "loan_share", "fees_per_month", "log_money_in", "cash_deposit_share",
            "runway_ei55_capped", "runway_no_shock_capped")
MODEL = "gradient_boosting"
HEADLINE_BUDGET = f"{HEADLINE_LIST_PCT}% watch-list"
LIGHT_BUDGET = f"light {WATCH_POINTS}+ points"
ARTIFACT_FILE = "ml_benchmark"
assert set(LIGHT_COLUMNS) <= set(FEATURES)


# ---------------------------------------------------------------- one snapshot: features and outcome

@dataclass(frozen=True, eq=False)
class Sample:
    """The accounts of one backtest snapshot: their features, the evidence scores, and which months each side reads."""
    snapshot: str
    label_year: str
    X: pd.DataFrame                    # FEATURES, one row per account, by account_id
    scores: pd.DataFrame               # evidence.snapshot_scores: light, EI runway, buffer months, went_overdrawn
    feature_months: tuple[str, str]    # first and last month of the rows the features read
    label_months: tuple[str, str]      # first and last month of the rows the outcome reads

    @property
    def y(self) -> pd.Series:
        return self.scores["went_overdrawn"]


def features(seen: pd.DataFrame, scores: pd.DataFrame, light: pd.DataFrame) -> pd.DataFrame:
    """FEATURES for the accounts of `scores`, from `seen` (their full months up to the snapshot), the judges' I, S, B
    and EI runway in `scores`, and the light's rule inputs in `light` (warning.light_table columns)."""
    ids = scores.index
    w = seen.sort_values(["account_id", "month"], kind="stable").groupby("account_id", sort=True).tail(WINDOW_ROWS)
    window = w.groupby("account_id", sort=True)
    total = lambda col: window[col].sum().reindex(ids)  # noqa: E731  (sum over the window)
    money_in = total("money_in").replace(0, np.nan)     # no money in: the shares below are undefined

    X = pd.DataFrame(index=ids)
    X["buffer_months_capped"] = scores["buffer_months"].clip(upper=BUFFER_CAP_MONTHS)   # no spending (inf) -> cap
    for col in LIGHT_COLUMNS:
        X[col] = light[col].reindex(ids)                       # clipped and filled, as the rules use them
    X["spend_ratio"] = (total("money_out") / money_in).clip(upper=RATIO_CAP).fillna(1.0)
    bills = (w["household_bills"] + w["insurance"]).groupby(w["account_id"]).sum().reindex(ids)
    X["fixed_share"] = (bills / money_in).clip(upper=RATIO_CAP).fillna(0.0)
    X["loan_share"] = (total("loan_payments") / money_in).clip(upper=RATIO_CAP).fillna(0.0)
    X["fees_per_month"] = window["bank_fees"].mean().reindex(ids)
    X["log_money_in"] = np.log1p(scores["I"].clip(lower=0))
    X["cash_deposit_share"] = (total("cash_deposits") / money_in).fillna(0.0)
    X["runway_ei55_capped"] = scores["runway_ei55_exact"].clip(upper=RUNWAY_CAP_MONTHS)  # no shortfall (inf) -> cap
    B, gap = scores["B"], scores["S"] - scores["I"]                                      # no shock: spend S, money in I
    with np.errstate(divide="ignore", invalid="ignore"):
        months = np.minimum(B / gap, RUNWAY_CAP_MONTHS)
    X["runway_no_shock_capped"] = np.where(B <= 0, 0.0, np.where(gap <= 0, RUNWAY_CAP_MONTHS, months))
    return X[list(FEATURES)]


def sample(monthly: pd.DataFrame, loans: pd.DataFrame, snapshot: str, label_year: str) -> Sample:
    """The backtest population at `snapshot` (warning.backtest_frame), its evidence scores and its features."""
    scores = snapshot_scores(monthly, loans, snapshot, label_year)
    light = backtest_frame(monthly, snapshot, label_year)
    ids = scores.index
    if not light.index.equals(ids):
        raise ValueError("the light's population and the evidence scores differ")
    rows = usable_months(monthly)
    rows = rows[rows["account_id"].isin(ids)]
    seen = rows[rows["month"] <= snapshot]
    later = rows[(rows["month"] > snapshot) & rows["month"].str.startswith(label_year)]
    # no leakage: every feature row is at or before the snapshot, the light's window ends there, and the outcome is
    # exactly "any day below zero" in the later rows
    if not (seen["month"].max() <= snapshot and (light["last_month"] <= snapshot).all()):
        raise ValueError(f"a feature reads a month after {snapshot}")
    went = later.groupby("account_id")["days_below_zero"].sum().reindex(ids, fill_value=0) > 0
    if not np.array_equal(went.to_numpy(), scores["went_overdrawn"].to_numpy()):
        raise ValueError("the outcome does not come from the rows after the snapshot")
    return Sample(snapshot, label_year, features(seen, scores, light), scores,
                  (str(seen["month"].min()), str(seen["month"].max())),
                  (str(later["month"].min()), str(later["month"].max())))


# ---------------------------------------------------------------- the model and its ranking

def fit(train: Sample) -> HistGradientBoostingClassifier:
    return HistGradientBoostingClassifier(**GBM_PARAMS).fit(train.X, train.y.astype(int))


def model_score(model: HistGradientBoostingClassifier, test: Sample) -> pd.Series:
    """The model's score (its probability of the positive class) for each test account; higher = more at risk."""
    return pd.Series(model.predict_proba(test.X)[:, 1], index=test.X.index, name=MODEL)


def model_order(score: pd.Series) -> pd.Index:
    """account_ids, highest score first; remaining ties by lowest account_id."""
    s = score.sort_index()
    ids = s.index.to_numpy()
    return pd.Index(ids[np.lexsort((ids, -s.to_numpy(float)))], name="account_id")


# ---------------------------------------------------------------- the comparison

def comparison(train: Sample, test: Sample, score: pd.Series) -> pd.DataFrame:
    """One row per flag budget: accounts flagged, and how many that went overdrawn each ranking flags."""
    s, y = test.scores, test.y
    orders = {MODEL: model_order(score), **{r: risk_order(s, r) for r in RANKINGS}}
    budgets = {HEADLINE_BUDGET: list_size(HEADLINE_LIST_PCT, len(s)),
               LIGHT_BUDGET: int((s["points"] >= WATCH_POINTS).sum())}
    return pd.DataFrame([{"budget": name, "list_accounts": k,
                          **{r: int(y.reindex(o[:k]).sum()) for r, o in orders.items()},
                          "events": int(y.sum()), "train_accounts": len(train.X), "train_events": int(train.y.sum())}
                         for name, k in budgets.items()])


@dataclass(frozen=True, eq=False)
class Benchmark:
    train: Sample
    test: Sample
    score: pd.Series          # the model's score for each test account
    table: pd.DataFrame       # comparison(): artifacts/ml_benchmark.csv

    def row(self, budget: str) -> pd.Series:
        return self.table.set_index("budget").loc[budget]


def build_benchmark(monthly: pd.DataFrame | None = None, loans: pd.DataFrame | None = None) -> Benchmark:
    monthly = load_monthly() if monthly is None else monthly
    loans = load_loans() if loans is None else loans
    train = sample(monthly, loans, TRAIN_SNAPSHOT, TRAIN_LABEL_YEAR)
    test = sample(monthly, loans, BACKTEST_SNAPSHOT, BACKTEST_LABEL_YEAR)
    if not train.label_months[1] <= test.snapshot:
        raise ValueError("the model would learn from outcomes after the test snapshot")
    score = model_score(fit(train), test)
    return Benchmark(train, test, score, comparison(train, test, score))


@lru_cache(maxsize=4)
def cached_benchmark(data_dir: str = str(DATA_DIR)) -> Benchmark:
    """The benchmark on the track data, fitted once per process."""
    return build_benchmark(load_monthly(data_dir), load_loans(data_dir))


# ---------------------------------------------------------------- the line

def versus(model: int, rules: int) -> str:
    """The model's catches against the rules': "as many overdrafts as", "4 more overdrafts than", or
    "1 fewer overdraft than"."""
    if model == rules:
        return "as many overdrafts as"
    d = abs(model - rules)
    return f"{d:,} {'more' if model > rules else 'fewer'} overdraft{'' if d == 1 else 's'} than"


def benchmark_line(b: Benchmark) -> str:
    head, light = b.row(HEADLINE_BUDGET), b.row(LIGHT_BUDGET)
    g, lt = int(head[MODEL]), int(head["light"])
    return (f"Gradient boosting on {len(FEATURES)} features, trained on {b.train.label_year}'s outcomes "
            f"({len(b.train.X):,} accounts, {int(b.train.y.sum()):,} went overdrawn), catches {g:,} of the "
            f"{int(head['events']):,} accounts that went overdrawn in {b.test.label_year} on the same "
            f"{HEADLINE_LIST_PCT}% watch-list ({int(head['list_accounts']):,} accounts): {versus(g, lt)} the light's "
            f"{len(RULES)} rules. On as many accounts as the light flags with {WATCH_POINTS}+ points "
            f"({int(light['list_accounts']):,}), it catches {int(light[MODEL]):,} and the light {int(light['light']):,}. "
            f"The product ships the rules, which a customer can read.")


def main(out_dir: Path | None = None) -> None:
    from .portfolio import ARTIFACTS
    out_dir = ARTIFACTS if out_dir is None else out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    b = cached_benchmark()
    print(benchmark_line(b))
    print(b.table.to_string(index=False))
    path = out_dir / f"{ARTIFACT_FILE}.csv"
    b.table.to_csv(path, index=False)
    print(f"wrote {path.relative_to(out_dir.parent)} ({len(b.table)} rows)")


if __name__ == "__main__":
    from .portfolio import parse_out_dir
    main(parse_out_dir("resilience.benchmark", __doc__))
