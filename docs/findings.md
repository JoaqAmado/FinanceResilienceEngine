# Findings

Every figure on this page is computed by the engine from `data/` and pinned by `tests/test_docs.py`.
The judges' formula comes first. Reality checks are labelled and sit beside it, never instead of it.

| | |
|---|---|
| Can't last 6 months on EI at 55% (judges' formula) | **1,578 of 4,500 (35.1%)** |
| **The more money comes in, the thinner the cushion:** fail rate by monthly money in | 4.8% under $2.5k → 75.6% over $20k. Buffers: 8.9 → 1.6 months of spending |
| …stress test with the real 2026 EI maximum ($729/week ≈ $3,159/month) | 2,304 (51.2%) |
| **A typical month isn't a typical half-year:** "safe" on the formula, but under 6 months on the account's own half-year spending | 783 of 2,922 (560, or 1 in 5, with the same window on money in too). Spending peaks in January and June |
| Failing customers who get back to 6 months by cutting a quarter of spending or less | 3 in 4 (1,192 of 1,555 with a positive buffer); only 121 can't cut their way there |
| Overdrawn before the loan → defaulted | 27 of 27 in this data (none of the 606 repaying borrowers ever went negative), so it's shown as a flag, not a model |

The chart tables behind these rows are in `artifacts/` (written by `python -m resilience.portfolio`).
The [method](method.md) page defines every term, and the [model card](model_card.md) lists the data's limits.

## How each figure is computed

All functions are in `resilience/`. "Failing" means a judges' runway under 6 months on the EI 55% twist
(`LAID_OFF_EI`: income = 0.55 × I), computed for every account by `core.portfolio_runway`.

- **Can't last 6 months on EI at 55%.** `portfolio.build_all()` → `headlines.fail_6mo_ei55`, out of
  `headlines.accounts`. The SQL in `sql/` gives the same count (`PORTFOLIO_SUMMARY`, see [warehouse](warehouse.md)).
- **The more money comes in, the thinner the cushion.** `portfolio.income_bands()` groups accounts by I (median
  monthly money in). Per band it gives `fail_6mo_ei55_pct` (share failing) and `median_buffer_months` (median of
  B ÷ S). The row quotes the lowest band (`< $2.5k`) and the highest (`>= $20k`). Table: `artifacts/income_bands.csv`.
- **Stress test with the 2026 EI maximum.** `LAID_OFF_EI_CAPPED` caps the EI part of income at
  `EI_2026_MAX_MONTHLY` (the weekly maximum × 52 ÷ 12) → `headlines.fail_6mo_ei55_cap2026`. Money in counts all
  inflows, not insurable earnings, so this is a stress test, not a forecast.
- **A typical month isn't a typical half-year.** The base is the accounts at 6 months or more on the judges'
  runway (`runway_ei55 >= 6`). The first count is those under 6 months with `spending_basis="S6"`: S6 is the
  median, over sliding 6-month windows, of total money out (opening month excluded), ÷ 6. The second count also
  puts money in on the same 6-month window and runs the same `portfolio_runway`. The peaks: across accounts, the
  median of each calendar month's spending ÷ S (`cal_01` … `cal_12` in `build_metrics()`) is highest in those two
  months. Band by band: `portfolio.s6_calibration()`, `artifacts/s6_calibration.csv`.
- **Cutting a quarter of spending or less.** `portfolio.cut_histogram()`: for each failing account with a positive
  buffer, the monthly cut that brings it back to 6 months (`ei55_min_cut_to_6mo` = gap − B ÷ 6), as a share of S.
  The count is the `<= 10%` and `10-25%` bins, out of all failing accounts with a positive buffer. The accounts that "can't
  cut their way there" are the failing accounts where `core.backup_ladder` reaches no rung, so they need cash or
  credit. The already overdrawn are among them. Table: `artifacts/cut_histogram.csv`.
- **Overdrawn before the loan.** `portfolio.preloan_overdraft()`: borrowers with any day below zero in a month
  before `loan_start`, against the loan outcome (B or D = defaulted, A or C = repaid or on track). The repaying
  borrowers are the A and C loans, and `ever_negative` is false for every one of them. On the customer card it is
  the `pre_loan_overdraft` flag (`core.account_flags`). Table: `artifacts/preloan_overdraft.csv`.
