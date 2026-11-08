"""The machine-learning benchmark (resilience/benchmark.py): its counts pinned, no leakage, deterministic, and kept out
of both apps."""
import re

import numpy as np
import pandas as pd
import pytest
from sklearn.ensemble import HistGradientBoostingClassifier

from resilience import benchmark as B
from resilience import evidence as E
from resilience import warning as W
from resilience.core import DATA_DIR, load_loans, load_monthly

ROOT = DATA_DIR.parent
needs_data = pytest.mark.skipif(not (DATA_DIR / "monthly_summary.csv").exists(), reason="track data not present")


# ------------------------------------------------------------- toy data, no track data needed

def test_model_order_ranks_highest_score_first_then_lowest_account_id():
    score = pd.Series([0.2, 0.9, 0.2, 0.5], index=pd.Index([14, 11, 12, 13], name="account_id"))
    assert list(B.model_order(score)) == [11, 13, 12, 14]


def test_versus_words_the_difference():
    """Review fix: a 47 = 47 tie and 59 against 55 read as exact or as a win; both splits are noise."""
    assert B.versus(47, 47, 9, 9) == "about as many overdrafts as"
    assert B.versus(59, 55, 13, 9) == "about as many overdrafts as"
    assert B.versus(60, 45, 20, 5) == "15 more overdrafts than"
    assert B.versus(45, 60, 5, 20) == "15 fewer overdrafts than"


def test_sign_test_on_the_overdrafts_only_one_list_catches():
    assert B.sign_test_p(9, 9) == 1.0 and B.sign_test_p(0, 0) == 1.0
    assert round(B.sign_test_p(13, 9), 2) == 0.52 and B.sign_test_p(9, 13) == B.sign_test_p(13, 9)
    assert B.sign_test_p(6, 0) == 2 / 2 ** 6 < B.SIGN_TEST_ALPHA


def test_the_apps_do_not_import_the_benchmark():
    """The apps ship the rules; scikit-learn is needed only to rerun the benchmark."""
    paths = [ROOT / "app.py", *(p for p in sorted((ROOT / "resilience").glob("*.py")) if p.name != "benchmark.py")]
    for path in paths:
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"sklearn|benchmark import|import benchmark|resilience\.benchmark", text), path.name


# ------------------------------------------------------------- the track data

@pytest.fixture(scope="module")
def monthly():
    return load_monthly()


@pytest.fixture(scope="module")
def loans():
    return load_loans()


@pytest.fixture(scope="module")
def bench():
    return B.cached_benchmark()


@needs_data
def test_train_and_test_populations(bench):
    tr, te = bench.train, bench.test
    assert (tr.snapshot, tr.label_year, len(tr.X), int(tr.y.sum())) == ("2023-12", "2024", 2747, 49)
    assert (te.snapshot, te.label_year, len(te.X), int(te.y.sum())) == ("2024-12", "2025", 3847, 75)
    for s in (tr, te):
        assert list(s.X.columns) == list(B.FEATURES) and len(B.FEATURES) == 13
        assert s.X.index.equals(s.scores.index) and s.X.index.is_monotonic_increasing
        assert not s.X.isna().any().any() and np.isfinite(s.X.to_numpy()).all()


@needs_data
def test_the_test_year_is_the_evidence_backtest(bench, monthly, loans):
    pd.testing.assert_frame_equal(bench.test.scores, E.snapshot_scores(monthly, loans))
    lift = E.lift_table(bench.test.scores).set_index("list_pct").loc[E.HEADLINE_LIST_PCT]
    head = bench.row(B.HEADLINE_BUDGET)
    for col in ("list_accounts", *E.RANKINGS, "events"):
        assert head[col] == lift[col], col
    for col in B.LIGHT_COLUMNS:                                        # the light's own rule inputs, unchanged
        assert np.array_equal(bench.test.X[col], W.backtest_frame(monthly)[col])


@needs_data
def test_counts_on_both_flag_budgets(bench):
    assert bench.table.to_dict("records") == [
        {"budget": "10% watch-list", "list_accounts": 385, "gradient_boosting": 47, "light": 47, "ei55_runway": 25,
         "buffer_months": 29, "gradient_boosting_only": 9, "light_only": 9, "events": 75, "train_accounts": 2747,
         "train_events": 49},
        {"budget": "light 2+ points", "list_accounts": 624, "gradient_boosting": 59, "light": 55, "ei55_runway": 30,
         "buffer_months": 36, "gradient_boosting_only": 13, "light_only": 9, "events": 75, "train_accounts": 2747,
         "train_events": 49},
    ]
    s = bench.test.scores
    y, model, light = bench.test.y, B.model_order(bench.score), E.risk_order(s, "light")
    for r in bench.table.itertuples():                                 # the overdrafts on one list and not the other
        on_model, on_light = set(model[:r.list_accounts]), set(light[:r.list_accounts])
        assert r.gradient_boosting_only == int(y.reindex(sorted(on_model - on_light)).sum())
        assert r.light_only == int(y.reindex(sorted(on_light - on_model)).sum())
        assert r.gradient_boosting - r.light == r.gradient_boosting_only - r.light_only
    flagged = s["points"] >= E.WATCH_POINTS                            # the light's budget is exactly its 2+ points
    assert int(flagged.sum()) == 624 and int(s.loc[flagged, "went_overdrawn"].sum()) == 55


@needs_data
def test_no_feature_or_label_crosses_the_snapshot(bench):
    tr, te = bench.train, bench.test
    for s in (tr, te):
        first, last = s.feature_months
        assert first < last == s.snapshot                              # features end at the snapshot, not after
        lo, hi = s.label_months
        assert s.snapshot < lo and lo.startswith(s.label_year) and hi.startswith(s.label_year)
    assert tr.label_months == ("2024-01", "2024-12") and te.label_months == ("2025-01", "2025-12")
    assert tr.label_months[1] <= te.snapshot                           # trained only on what was known at the test snapshot


@needs_data
@pytest.mark.parametrize("which", ["train", "test"])
def test_later_rows_change_no_feature(bench, monthly, loans, which):
    """Rewrite every money and balance figure after the snapshot (keeping days_below_zero, so the outcome stays):
    the features must not move."""
    s = getattr(bench, which)
    later = monthly["month"] > s.snapshot
    tampered = monthly.copy()
    cols = [c for c in monthly.select_dtypes("number").columns if c not in ("account_id", "days_below_zero")]
    tampered.loc[later, cols] = tampered.loc[later, cols] * 3 + 1000
    again = B.sample(tampered, loans, s.snapshot, s.label_year)
    pd.testing.assert_frame_equal(again.X, s.X)
    assert again.y.equals(s.y)


@needs_data
def test_two_fits_give_identical_scores(bench):
    again = B.model_score(B.fit(bench.train), bench.test)
    assert np.array_equal(again.to_numpy(), bench.score.to_numpy()) and again.index.equals(bench.score.index)


@needs_data
def test_early_stopping_stays_off_so_the_seed_changes_nothing(bench):
    """Review fix: the findings said the fixed random_state makes runs repeat. On this few training accounts early
    stopping stays off ('auto' switches it on above 10,000), so no random_state is ever used."""
    model = B.fit(bench.train)
    assert len(bench.train.X) <= 10_000 and not model.do_early_stopping_
    assert model.n_iter_ == B.GBM_PARAMS["max_iter"]
    other = HistGradientBoostingClassifier(**{**B.GBM_PARAMS, "random_state": 12345}).fit(
        bench.train.X, bench.train.y.astype(int))
    assert np.array_equal(B.model_score(other, bench.test).to_numpy(), bench.score.to_numpy())


@needs_data
def test_benchmark_line(bench):
    assert B.benchmark_line(bench) == (
        "Gradient boosting on 13 features, trained on 2024's outcomes (2,747 accounts, 49 went overdrawn), catches 47 "
        "of the 75 accounts that went overdrawn in 2025 on a 10% watch-list of the light's size (385 accounts): about "
        "as many overdrafts as the light's 4 rules (47; 9 only on the model's list, 9 only on the light's). On as many "
        "accounts as the light flags with 2+ points (624), it catches 59 and the light 55 (13 and 9 only on one list): "
        "about as many overdrafts as the light. The product ships the rules, which a customer can read.")


@needs_data
def test_cached_benchmark_is_fitted_once(bench):
    assert B.cached_benchmark() is bench


@needs_data
def test_artifact_matches_the_engine(bench):
    path = ROOT / "artifacts" / f"{B.ARTIFACT_FILE}.csv"
    if not path.exists():
        pytest.skip("artifact not written (python -m resilience.benchmark)")
    pd.testing.assert_frame_equal(pd.read_csv(path), bench.table, check_dtype=False)
