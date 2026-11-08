# Findings

Every figure on this page is computed by the engine from `data/` and pinned by `tests/test_docs.py`.
The judges' formula comes first. Reality checks are labelled and sit beside it, never instead of it.

| | |
|---|---|
| Can't last 6 months on EI at 55% (judges' formula) | **1,578 of 4,500 (35.1%)** |
| **The more money comes in, the thinner the cushion:** fail rate by monthly money in | 4.8% under $2.5k → 75.6% over $20k. Buffers: 8.9 → 1.6 months of spending, though in dollars they grow: median buffer $13.9k → $38.9k, median monthly spending $1.4k → $23.0k |
| …stress test with the real 2026 EI maximum ($729/week ≈ $3,159/month) | 2,304 (51.2%) |
| **A typical month isn't a typical half-year:** spending is lumpy, so an account "safe" on the formula can be under 6 months on its own half-year spending | 783 of 2,922 (560, or 1 in 5, with the same window on money in too). Calendar caveat: spending peaks in January and June, a pattern already in the original PKDD'99 data, so it is not a Canadian season |
| Failing customers who get back to 6 months by cutting a quarter of spending or less | 3 in 4 (1,192 of 1,555 with a positive buffer); only 121 can't cut their way there |
| …held from the first month, at the cuts people who lose a job have made by about 6 months out of work (about 13–16% of spending) | 16% or less: 778 of 1,555 (50.0%) · 13% or less: 606 (39.0%) |
| Overdrawn before the loan → labelled defaulted | 27 of 27 in this data (none of the 606 repaying borrowers ever went negative). That is built into how this dataset labels loans (CTU's rule: a loan is good only if the balance never went below zero), so it's a red flag, not evidence |

The chart tables behind these rows are in `artifacts/` (written by `python -m resilience.portfolio`).
The [method](method.md) page defines every term, and the [model card](model_card.md) lists the data's limits.

## 2025 backtest: the judges' test misses people

The early-warning light's backtest: every score taken at the 2024-12 snapshot, on the 3,847 accounts rated then
and still active in 2025, of which 75 first went overdrawn in 2025.

| | |
|---|---|
| Of those 75, passed the judges' EI 55% test at the snapshot | 28 (the light had flagged 17 of them, 2+ points) |
| Overdrafts caught by a 10% watch-list (385 accounts) | light (most points, then lowest balance) 47 · judges' EI 55% runway 25 · buffer months 29 |
| Gradient boosting on 13 features, trained on 2024's outcomes (2,747 accounts, 49 went overdrawn), on watch-lists of the same size | 10% watch-list: 47, about as many overdrafts as the light's 4 rules (47) · as many accounts as the light flags with 2+ points (624): 59, about as many overdrafts as the light (55). The lists catch different overdrafts: 9 only on the model's and 9 only on the light's on the 10% list, 13 and 9 at 624, so this data can't tell the two rankings apart |
| Second finding, small numbers: went overdrawn in 2025 | irregular money in that passes the EI test: 14 of 376 (3.7%, 95% interval 2.2–6.2%) · steady money in that fails it: 17 of 1,072 (1.6%, 1.0–2.5%) |
| **Half-year spending, checked forward** (4 as-of months, 12,681 account half-years): of the 6,652 that fail the 6-month EI test on the money out that followed, missed by | the same test on the median month S: 2,406 · on half-year S6: 1,003 (false alarms: S 720 · S6 1,579) |

The tables are in `artifacts/` (written by `python -m resilience.evidence`); both apps chart them on the
Portfolio tab.

## How each figure is computed

All functions are in `resilience/`. "Failing" means a judges' runway under 6 months on the EI 55% twist
(`LAID_OFF_EI`: income = 0.55 × I), computed for every account by `core.portfolio_runway`.

- **Can't last 6 months on EI at 55%.** `portfolio.build_all()` → `headlines.fail_6mo_ei55`, out of
  `headlines.accounts`. The SQL in `sql/` gives the same count (`PORTFOLIO_SUMMARY`, see [warehouse](warehouse.md)).
- **The more money comes in, the thinner the cushion.** `portfolio.income_bands()` groups accounts by I (median
  monthly money in). Per band it gives `fail_6mo_ei55_pct` (share failing), `median_buffer_months` (median of
  B ÷ S), and the cushion in dollars: `median_B` (median buffer) and `median_S` (median monthly spending). The row
  quotes the lowest band (`< $2.5k`) and the highest (`>= $20k`). Table: `artifacts/income_bands.csv`.
- **Stress test with the 2026 EI maximum.** `LAID_OFF_EI_CAPPED` caps the EI part of income at
  `EI_2026_MAX_MONTHLY` (the weekly maximum × 52 ÷ 12) → `headlines.fail_6mo_ei55_cap2026`. Money in counts all
  inflows, not insurable earnings, so this is a stress test, not a forecast.
- **A typical month isn't a typical half-year.** The base is the accounts at 6 months or more on the judges'
  runway (`runway_ei55 >= 6`). The first count is those under 6 months with `spending_basis="S6"`: S6 is the
  median, over sliding 6-month windows, of total money out (opening month excluded), ÷ 6. The second count also
  puts money in on the same 6-month window and runs the same `portfolio_runway`. The peaks: across accounts, the
  median of each calendar month's spending ÷ S (`cal_01` … `cal_12` in `build_metrics()`) is highest in those two
  months. They are a caveat, not the finding: the PKDD'99 papers on the original data already report a January
  peak (Miksovsky et al.; Pijls) and a smaller June/July one (Miksovsky et al.), so the re-dating did not create
  them. Band by band: `portfolio.s6_calibration()`, `artifacts/s6_calibration.csv`.
- **Cutting a quarter of spending or less.** `portfolio.cut_histogram()`: for each failing account with a positive
  buffer, the monthly cut that brings it back to 6 months (`ei55_min_cut_to_6mo` = gap − B ÷ 6), as a share of S.
  The count is the `<= 10%` and `10-25%` bins, out of all failing accounts with a positive buffer. The accounts that "can't
  cut their way there" are the failing accounts where `core.backup_ladder` reaches no rung, so they need cash or
  credit. The already overdrawn are among them. Table: `artifacts/cut_histogram.csv`.
- **At the cuts people reach by about 6 months.** `portfolio.realistic_cuts()`: the same failing accounts with a
  positive buffer, counted at a cut of at most `REALISTIC_CUT_PCTS` of spending, held from the first month as in
  the histogram. The studies measure where cuts end up, not where they start: low-buffer families by the time
  UI ran out (JPMorgan Chase Institute, *Recovering from Job Loss*) and people still out of work at 6 months
  (Browning & Crossley, see the README sources). A cut that only builds up to those levels gets fewer back.
  Table: `artifacts/realistic_cuts.csv`.
- **Overdrawn before the loan.** `portfolio.preloan_overdraft()`: borrowers with any day below zero in a month
  before `loan_start`, against the loan outcome (B or D = defaulted, A or C = repaid or on track). The repaying
  borrowers are the A and C loans, and `ever_negative` is false for every one of them. That is how the dataset
  defines its labels: the CTU repository notes that `if min(trans.balance) >= 0 then good else bad` separates good
  loans from bad perfectly, so the result is guaranteed by the label, not evidence that an overdraft causes
  default. On the customer card it is the `pre_loan_overdraft` flag (`core.account_flags`), worded as a red flag.
  Table: `artifacts/preloan_overdraft.csv`.

### The 2025 backtest

All functions are in `resilience/evidence.py`. The population and the outcome are the early-warning light's
backtest (`warning.backtest_frame`). Every score reads the rows the light reads: each account's full months up to
the snapshot, with the partial opening month left out. The judges' I, S and B come from `core.baseline_metrics`
on those rows, and an account passes the judges' EI test when its published runway (`core.portfolio_runway`) is
6 months or more.

- **Passed the judges' test.** `summary()`: the 75 accounts that went overdrawn, how many passed, and how many of
  those had 2+ points on the light (where both apps show it as a warning). Keeping the partial opening month in
  I, S and B, as the live card does, 34 of the 75 had passed, the light flagged 22 of them, and the EI runway
  catches 23 on the 10% list, so leaving it out is the cautious choice. Table: `artifacts/backtest_summary.csv`.
- **Watch-lists.** `lift_table()`: watch-lists of 1–30% of the backtest population, highest risk first. The light
  ranks by points, then by the lowest balance relative to spending (`points - 1e-6 × min_bal_over_S`, as the
  backtest did). The runway ranks shortest first, before rounding. Buffer months rank fewest first. Remaining
  ties go to the lowest `account_id`. Table: `artifacts/backtest_lift.csv`.
- **Gradient boosting benchmark.** `resilience/benchmark.py` (`python -m resilience.benchmark`). The product has no
  trained model; this checks whether one would have caught more. It fits scikit-learn's
  `HistGradientBoostingClassifier` on the light's backtest one year earlier, outcome = any day below zero in 2024:
  the 2,747 accounts rated at the 2023-12 snapshot and still active in 2024.
  On 2,747 training accounts early stopping stays off, so every run gives the same scores whatever the `random_state`.
  It then ranks the same 3,847 accounts as the watch-lists, highest score first, ties to the lowest `account_id`.
  Its 13 features read only the months up to each snapshot: the light's 4 rule inputs,
  buffer months, the judges' EI runway and the runway with no shock, money in, and, over the light's 6 months,
  money out, household bills and insurance, loan payments and cash deposits as shares of money in, and bank fees.
  At each list size the table also counts the overdrafts on only one of the two lists (`gradient_boosting_only`,
  `light_only`), and `versus()` words the model's count "about as many" unless an exact two-sided sign test on
  those two counts is below `SIGN_TEST_ALPHA` (`0.05`); at both sizes it is not.
  The apps keep the rules: each rule that fires is named on the card. Table: `artifacts/ml_benchmark.csv`.
- **Irregular money in.** `irregular_table()`: the light's own rule (money in: std ÷ mean > 0.5 over its 6
  months) against passing or failing the judges' EI test, with Wilson 95% intervals. It rests on 14 and 17
  overdrafts and says who to watch, not why. Table: `artifacts/backtest_irregular.csv`.
- **Half-year spending, checked forward.** `s6_check()`: at each of 2023-12, 2024-06, 2024-12 and 2025-06, every
  account with a row 12 months earlier and all 6 months after it. I, S, B and S6 use only the rows up to that
  month. The test fails when B − (6 months of spending − 6 × 0.55 × I) is below zero: on the money out that
  actually followed (a real fail), on 6 × S and on 6 × S6. None of the three is rounded, so the S check is not
  the judges' published runway, which rounds to one decimal. Table: `artifacts/s6_halfyear_check.csv`.
