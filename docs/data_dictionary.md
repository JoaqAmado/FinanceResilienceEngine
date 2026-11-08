# Data dictionary

The track's input files (`data/`), the columns the engine adds per account, and the generated chart tables
(`artifacts/`). All money is in Canadian dollars. Figures computed from these columns are on the
[findings](findings.md) page. `tests/test_docs.py` checks every table below against the file's header.

## Input files (`data/`)

The files link through their ID columns: an account has transactions, monthly rows, standing orders and at most
one loan; dispositions link clients to accounts, and cards hang off dispositions.

### `data/monthly_summary.csv`

One row per account per month, built from the transactions, from the account's first transaction month to its last
(quiet months included). Balances are end-of-day balances, carried forward on days with no activity. The judges'
numbers are computed from this file ([method](method.md)).

| Column | Meaning |
|---|---|
| `account_id` | the account |
| `month` | calendar month, as text `YYYY-MM` |
| `money_in` | total money in (a positive number) |
| `money_out` | total money out (a positive number) |
| `cash_deposits` | part of money in: cash paid into the account |
| `transfers_in` | part of money in: transfers in from other banks, pensions excluded |
| `pension_in` | part of money in: pension payments |
| `interest_in` | part of money in: interest credited by the bank |
| `household_bills` | part of money out: household bills paid |
| `insurance` | part of money out: insurance payments |
| `loan_payments` | part of money out: loan repayments |
| `bank_fees` | part of money out: statement fees and penalty interest |
| `cash_withdrawals_genuine` | part of money out: cash taken out |
| `card_withdrawals` | part of money out: card withdrawals and payments |
| `transfers_out_other` | part of money out: unlabelled transfers out to other banks |
| `month_end_balance` | end-of-day balance on the last day of the month |
| `min_balance` | lowest end-of-day balance in the month (the first month counts from the first transaction) |
| `avg_daily_balance` | average end-of-day balance in the month (the buffer B is built from this) |
| `days_below_zero` | days in the month that ended with a negative balance |

The parts of money in add up to `money_in`, and the parts of money out add up to `money_out`.

### `data/transactions.csv`

| Column | Meaning |
|---|---|
| `transaction_id` | the transaction |
| `account_id` | its account |
| `date` | transaction date |
| `direction` | `credit (money in)` or `debit (money out)` |
| `operation` | cash deposit, cash withdrawal, card withdrawal, transfer in from or out to another bank, bill payment, bank fee, interest |
| `purpose` | when known: household bills, insurance, loan payment, pension, interest credited, statement fee, penalty interest (negative balance). Blank = not labelled |
| `amount` | amount, always positive |
| `signed_amount` | positive = money in, negative = money out |
| `balance` | account balance after the transaction. Rows within the same day are not in time order |
| `partner_bank` | for transfers: the other bank, as a two-letter code. Read it as text |
| `partner_account` | for transfers: the account number at the other bank (not an `account_id` here) |

### `data/loans.csv`

| Column | Meaning |
|---|---|
| `loan_id` | the loan |
| `account_id` | the account that took it (one loan per account) |
| `loan_start` | date the loan was granted |
| `amount` | loan size (`duration_months` × `monthly_payment`) |
| `duration_months` | length of the loan in months |
| `monthly_payment` | monthly payment |
| `status` | A = finished, repaid; B = finished, not repaid (default); C = running, OK so far; D = running, client in debt |
| `status_meaning` | the status in words |
| `defaulted` | `1` if the status is B or D, `0` if A or C |

### `data/accounts.csv`

| Column | Meaning |
|---|---|
| `account_id` | the account |
| `district_id` | district of the branch that holds the account |
| `frequency` | statement frequency |
| `account_opened` | date the account was opened |

### `data/clients.csv`

| Column | Meaning |
|---|---|
| `client_id` | the client |
| `gender` | client gender |
| `birth_date` | date of birth |
| `district_id` | home district |

### `data/dispositions.csv`

| Column | Meaning |
|---|---|
| `disposition_id` | the link between a client and an account |
| `client_id` | the client |
| `account_id` | the account |
| `type` | `owner` or `authorized user` |

### `data/cards.csv`

| Column | Meaning |
|---|---|
| `card_id` | the card |
| `disposition_id` | the client-account link the card belongs to |
| `card_type` | junior, classic or gold |
| `issued` | date the card was issued |

### `data/standing_orders.csv`

An undated snapshot at the end of the data.

| Column | Meaning |
|---|---|
| `order_id` | the standing order |
| `account_id` | the account it is paid from |
| `to_bank` | the receiving bank, as a two-letter code |
| `to_account` | the account number at the receiving bank |
| `amount` | amount per payment |
| `purpose` | household bills, insurance, leasing or loan payment. Blank = other |

### `data/districts.csv`

The bank's original regions, one row per district.

| Column | Meaning |
|---|---|
| `district_id` | the district |
| `district_name` | district name |
| `region` | the larger region the district belongs to |
| `inhabitants` | population |
| `municipalities_under_500` | number of municipalities in the population band the column name gives |
| `municipalities_500_1999` | number of municipalities in the population band the column name gives |
| `municipalities_2000_9999` | number of municipalities in the population band the column name gives |
| `municipalities_over_10000` | number of municipalities in the population band the column name gives |
| `num_cities` | number of cities |
| `urban_ratio_pct` | share of inhabitants living in cities, percent |
| `average_salary` | district average monthly wage |
| `unemployment_rate_2022` | unemployment rate in the year the column name gives, percent (missing for one district) |
| `unemployment_rate_2023` | unemployment rate in the year the column name gives, percent |
| `entrepreneurs_per_1000` | entrepreneurs per thousand inhabitants |
| `crimes_2022` | crimes recorded in the year the column name gives (missing for one district) |
| `crimes_2023` | crimes recorded in the year the column name gives |

## Engine metric columns

One row per `account_id`, from `resilience.build_metrics()`. The judges' numbers first, then the columns the
reality checks, plans and flags use.

| Column | Meaning |
|---|---|
| `I` | judges': typical monthly money in, median of `money_in` |
| `F` | judges': typical fixed costs, median of `household_bills + insurance + loan_payments` |
| `S` | judges': typical monthly spending, median of `money_out` |
| `B` | judges': buffer, mean of `avg_daily_balance` over the account's last six rows by month |
| `H` | judges': household bills, median of `household_bills` |
| `P` | judges': loan payment, `monthly_payment` if the loan is still running (status C or D), else zero |
| `card_withdrawals_median` | median monthly `card_withdrawals` |
| `cash_withdrawals_genuine_median` | median monthly `cash_withdrawals_genuine` |
| `transfers_out_other_median` | median monthly `transfers_out_other` |
| `bank_fees_median` | median monthly `bank_fees` (the ladder's first step) |
| `loan_payments_median` | median monthly `loan_payments` |
| `insurance_median` | median monthly `insurance` |
| `flexible_median` | non-fixed spending: card plus cash withdrawal medians |
| `Pn` | median monthly `pension_in` (kept in full by the pension-aware check) |
| `pension_median` | same as `Pn` |
| `months_of_data` | number of monthly rows |
| `first_month` | first month of the account's rows |
| `last_month` | last month of the account's rows |
| `ever_negative` | any day below zero in any month |
| `S6` | typical half-year spending per month: median of sliding six-month sums of `money_out`, opening month excluded, divided by six |
| `cal_01` … `cal_12` | median spending in each calendar month, first and last month dropped as partial (the January path) |
| `loan_status` | the loan's status letter, empty without a loan |
| `loan_start` | the loan's start date |
| `pre_loan_negative` | any day below zero in a month before the loan started |
| `H_SO` | household bills paid by standing order, per month (the bills fallback) |
| `so_other` | standing orders with a blank purpose, per month (the ladder's pause step) |
| `owner_age` | the owner's age at the end of the data |
| `owner_gender` | the owner's gender |

## Generated chart tables (`artifacts/`)

Written by `python -m resilience.portfolio`, `python -m resilience.warning` (`early_warning_tiers.csv`) and
`python -m resilience.evidence` (`backtest_summary.csv`, `backtest_lift.csv`, `backtest_irregular.csv`,
`s6_halfyear_check.csv`). Runways use the engine's encoding: no shortfall is `inf`.

### `artifacts/accounts.csv`

One row per account. Engine columns are as defined above.

| Column | Meaning |
|---|---|
| `account_id` | the account |
| `I` | engine column |
| `F` | engine column |
| `S` | engine column |
| `B` | engine column |
| `H` | engine column |
| `P` | engine column |
| `Pn` | engine column |
| `S6` | engine column |
| `flexible_median` | engine column |
| `months_of_data` | engine column |
| `last_month` | engine column |
| `loan_status` | engine column |
| `pre_loan_negative` | engine column |
| `ever_negative` | engine column |
| `owner_age` | engine column |
| `H_SO` | engine column |
| `buffer_months` | B ÷ S |
| `runway_base` | judges' runway with no shock |
| `runway_ei55` | judges' runway on the EI twist (`LAID_OFF_EI`) |
| `runway_ei55_cap2026` | the EI twist with the EI cap (`LAID_OFF_EI_CAPPED`) |
| `runway_ei55_cap2026_waitweek` | the capped EI twist plus the waiting week |
| `runway_ei55_pension_aware` | the EI twist with the pension kept |
| `runway_ei55_S6` | the EI twist on half-year spending (`S6`) |
| `runway_furnace` | judges' runway on the furnace twist (`FURNACE`) |
| `runway_double_whammy` | judges' runway on job loss plus bills up (`DOUBLE_WHAMMY`) |
| `runway_ei55_january_path` | the EI twist, month by month from January (`calendar_path`) |
| `ei55_min_cut_to_6mo` | monthly cut that brings a failing account with a positive buffer back to six months, else zero |
| `ei55_min_cut_pct_of_S` | that cut as a share of S |

### `artifacts/headlines.csv`

One row: the portfolio's headline counts.

| Column | Meaning |
|---|---|
| `accounts` | number of accounts |
| `fail_6mo_ei55` | accounts failing the six-month test on the EI twist |
| `fail_6mo_ei55_cap2026` | the same with the EI cap |
| `fail_6mo_ei55_S6` | the same on half-year spending |
| `fail_6mo_ei55_pension_aware` | the same with the pension kept |
| `fail_6mo_ei55_january_path` | the same on the January path |
| `fail_6mo_furnace` | accounts failing the six-month test on the furnace twist |
| `fail_6mo_double_whammy` | accounts failing the six-month test on job loss plus bills up |
| `ei_cap_monthly_2026` | the EI cap per month (`EI_2026_MAX_MONTHLY`) |
| `median_min_cut_failing` | median `ei55_min_cut_to_6mo` over failing accounts with a positive buffer |

### `artifacts/income_bands.csv`

| Column | Meaning |
|---|---|
| `income_band` | band of I (typical monthly money in) |
| `accounts` | accounts in the band |
| `fail_6mo_ei55_pct` | percent failing the six-month test on the EI twist |
| `fail_6mo_ei55_cap2026_pct` | the same with the EI cap |
| `median_buffer_months` | median of `buffer_months` |
| `median_I` | median I |

### `artifacts/s6_calibration.csv`

| Column | Meaning |
|---|---|
| `judge_runway_months` | band of the judges' runway on the EI twist |
| `accounts` | accounts in the band |
| `fail_6mo_on_S6_pct` | percent of them under six months on half-year spending |

### `artifacts/cut_histogram.csv`

| Column | Meaning |
|---|---|
| `cut_as_share_of_spending` | band of `ei55_min_cut_pct_of_S`, plus a row for the already overdrawn |
| `accounts` | failing accounts in the band |

### `artifacts/preloan_overdraft.csv`

| Column | Meaning |
|---|---|
| `overdrawn_before_loan` | `yes` or `no`: any day below zero before the loan started |
| `defaulted (B/D)` | borrowers whose loan defaulted |
| `repaid or on track (A/C)` | borrowers whose loan was repaid or is on track |

### `artifacts/early_warning_tiers.csv`

The early-warning light's backtest ([method](method.md)).

| Column | Meaning |
|---|---|
| `points` | number of rules that fired |
| `accounts` | accounts in the backtest with that many points |
| `went_overdrawn` | of those, accounts with any day below zero in the outcome year |
| `rate` | `went_overdrawn` ÷ `accounts` |

### `artifacts/backtest_summary.csv`

One row: the backtest's population and the overdrafts the judges' test passed ([findings](findings.md)).

| Column | Meaning |
|---|---|
| `snapshot` | the month every score is taken at |
| `label_year` | the outcome year |
| `accounts` | accounts in the backtest |
| `went_overdrawn` | of those, accounts with any day below zero in the outcome year |
| `passed_ei55` | of those that went overdrawn, accounts that passed the judges' EI test at the snapshot |
| `passed_and_flagged` | of those that passed, accounts the light had flagged |
| `watch_points` | the points from which the light counts as flagged (`WATCH_POINTS`) |

### `artifacts/backtest_lift.csv`

One row per watch-list size.

| Column | Meaning |
|---|---|
| `list_pct` | the list's size, as a percent of the backtest population |
| `list_accounts` | accounts on the list |
| `light` | accounts that went overdrawn on the light's list |
| `ei55_runway` | the same for the judges' EI runway, shortest first |
| `buffer_months` | the same for buffer months, fewest first |
| `events` | accounts that went overdrawn in the whole backtest |

### `artifacts/backtest_irregular.csv`

The irregular-money-in two-by-two.

| Column | Meaning |
|---|---|
| `irregular_money_in` | `yes` when the light's irregular-money-in rule fires at the snapshot |
| `judges_ei55` | `passes` or `fails` the judges' EI test at the snapshot |
| `accounts` | accounts in the cell |
| `went_overdrawn` | of those, accounts with any day below zero in the outcome year |
| `rate` | `went_overdrawn` ÷ `accounts` |
| `ci_low` | lower end of the Wilson interval for `rate` |
| `ci_high` | upper end of that interval |

### `artifacts/s6_halfyear_check.csv`

The six-month EI test on the judges' S and on half-year S6, against the money out that followed.

| Column | Meaning |
|---|---|
| `spending_basis` | `S` (the judges' median month) or `S6` (typical half-year spending) |
| `account_halfyears` | account and as-of-month pairs checked |
| `real_fails` | of those, pairs that fail the test on the money out that actually followed |
| `flagged` | pairs that fail the test on this spending basis |
| `missed_real_fails` | real fails this basis did not flag |
| `false_alarms` | flags that were not real fails |
