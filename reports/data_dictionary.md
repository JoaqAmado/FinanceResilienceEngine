# Data dictionary — `marts` schema

_Generated from the column comments stored in the warehouse (`select * from duckdb_columns() where schema_name = 'marts'`)._

**JUDGE** = exact official definition from the brief · **OURS** = our own metric, always shown beside the judge number · **FLAG** = true/false warning. Money is CAD.

## `marts.config_thresholds`

Every threshold our flags and plans use, copied from src/tangerine/config.py so SQL and Python agree.

| Column | Type | Meaning |
|---|---|---|
| `threshold_name` | VARCHAR | Name used in config.THRESHOLDS. |
| `threshold_value` | DOUBLE | The value. |
| `meaning` | VARCHAR | What the threshold controls, in plain English. |

## `marts.dim_account`

One row per account: branch, owner, card and loan details.

| Column | Type | Meaning |
|---|---|---|
| `account_id` | INTEGER | Bank account ID — the ID a judge picks in the live demo. |
| `branch_district_id` | INTEGER | District of the branch that holds the account. |
| `branch_region` | VARCHAR | Region of the branch (8 regions). |
| `account_opened_date` | DATE | Date the account was opened. |
| `statement_frequency` | VARCHAR | How often statements are issued. |
| `owner_client_id` | INTEGER | Client ID of the account owner. |
| `owner_gender` | VARCHAR | Owner gender (M / F). |
| `owner_age_years` | INTEGER | Owner age in whole years on 2025-12-31. |
| `n_account_users` | BIGINT | Number of people linked to the account (owner + authorized users). |
| `has_card` | BOOLEAN | True if anyone on the account holds a card. |
| `best_card_type` | VARCHAR | Best card on the account: gold > classic > junior, or none. |
| `has_loan` | BOOLEAN | True if the account ever took a loan (max one loan per account). |
| `loan_id` | INTEGER | Loan ID, NULL if no loan. |
| `loan_status` | VARCHAR | A = finished, repaid; B = finished, defaulted; C = running, OK; D = running, in debt. |
| `loan_status_meaning` | VARCHAR | Plain-English loan status. |
| `loan_amount` | DOUBLE | Loan size, CAD. |
| `loan_monthly_payment` | DOUBLE | Loan monthly payment, CAD (whatever the loan status). |
| `loan_start_date` | DATE | Date the loan was granted. |
| `loan_end_date` | DATE | Loan start date + duration. |
| `loan_is_running` | BOOLEAN | True if the loan is still running at the end of 2025 (status C or D). |
| `loan_is_defaulted` | BOOLEAN | True if the loan defaulted (status B or D). |

## `marts.dim_district`

One row per district (the bank's original Czech regions): population, salary, unemployment, crime.

| Column | Type | Meaning |
|---|---|---|
| `district_id` | INTEGER | District ID (joins to dim_account.branch_district_id). |
| `district_name` | VARCHAR | District name. |
| `region` | VARCHAR | One of 8 larger regions the district belongs to. |
| `inhabitants` | INTEGER | Population of the district. |
| `urban_ratio_pct` | DOUBLE | Share of inhabitants living in cities, in percent. |
| `average_monthly_salary` | DOUBLE | Average monthly salary in the district, CAD. |
| `unemployment_rate_2022` | DOUBLE | Unemployment rate 2022, percent. NULL for district 69. |
| `unemployment_rate_2023` | DOUBLE | Unemployment rate 2023, percent. |
| `entrepreneurs_per_1000` | INTEGER | Entrepreneurs per 1,000 inhabitants. |
| `crimes_2022` | INTEGER | Number of crimes committed in 2022. NULL for district 69. |
| `crimes_2023` | INTEGER | Number of crimes committed in 2023. |

## `marts.fact_account_month`

One row per account per month, from the first to the last transaction month (quiet months included). All money in CAD.

| Column | Type | Meaning |
|---|---|---|
| `account_id` | INTEGER | Bank account ID. |
| `month` | VARCHAR | Calendar month as text, YYYY-MM. |
| `month_date` | DATE | First day of the month, as a date. |
| `money_in` | DOUBLE | Total money in this month = cash_deposits + transfers_in + pension_in + interest_in. |
| `money_out` | DOUBLE | Total money out this month = household_bills + insurance + loan_payments + bank_fees + cash_withdrawals_genuine + card_withdrawals + transfers_out_other. |
| `cash_deposits` | DOUBLE | Cash paid into the account. |
| `transfers_in` | DOUBLE | Transfers in from other banks (pensions excluded). |
| `pension_in` | DOUBLE | Pension payments received. |
| `interest_in` | DOUBLE | Interest credited by the bank. |
| `household_bills` | DOUBLE | Household bills paid (rent, utilities). |
| `insurance` | DOUBLE | Insurance payments. |
| `loan_payments` | DOUBLE | Loan repayments. |
| `bank_fees` | DOUBLE | Statement fees and penalty interest. |
| `cash_withdrawals_genuine` | DOUBLE | Cash taken out. |
| `card_withdrawals` | DOUBLE | Card withdrawals / payments. |
| `transfers_out_other` | DOUBLE | Unlabelled transfers out to other banks. |
| `month_end_balance` | DOUBLE | Balance at the end of the last day of the month. |
| `min_balance` | DOUBLE | Lowest end-of-day balance in the month. |
| `avg_daily_balance` | DOUBLE | Average end-of-day balance in the month (the buffer B uses this). |
| `days_below_zero` | INTEGER | Days in the month that ended with a negative balance. |
| `fixed_costs` | DOUBLE | household_bills + insurance + loan_payments (the monthly part of the judges' F). |
| `discretionary_spending` | DOUBLE | cash_withdrawals_genuine + card_withdrawals + transfers_out_other — spending a customer could cut. |
| `net_cash_flow` | DOUBLE | money_in - money_out. Negative = the month ate into savings. |
| `month_number` | BIGINT | 1 for the account's first month, 2 for the second, ... |
| `months_from_end` | BIGINT | 1 for the account's last month, 2 for the one before, ... (B = mean of avg_daily_balance where this is 1-6). |
| `is_lean_month` | BOOLEAN | True if money_in is below 55% of the account's own typical (median) income — what a month on EI would look like. |
| `was_overdrawn` | BOOLEAN | True if at least one day this month ended below zero. |

## `marts.mart_balance_slide`

For every defaulted loan account: average balance vs its trailing 12-month peak in each of the 12 months before its first overdraft.

| Column | Type | Meaning |
|---|---|---|
| `account_id` | INTEGER | Defaulted loan account. |
| `first_overdraft_month` | VARCHAR | First month with a day below zero, YYYY-MM. |
| `months_before_first_overdraft` | BIGINT | 1 = the month just before the first overdraft, 12 = a year before. |
| `month` | VARCHAR | Calendar month of this row, YYYY-MM. |
| `avg_daily_balance` | DOUBLE | Average end-of-day balance that month, CAD. |
| `trailing_12m_peak_balance` | DOUBLE | Highest monthly average balance in the 12 months up to and including this one, CAD. |
| `balance_vs_12m_peak` | DOUBLE | avg_daily_balance / trailing_12m_peak_balance (1 = at peak). |

## `marts.mart_balance_slide_summary`

Median balance-vs-peak across defaulted accounts, for each of the 12 months before the first overdraft.

| Column | Type | Meaning |
|---|---|---|
| `months_before_first_overdraft` | BIGINT | 1 = the month just before the first overdraft. |
| `accounts` | BIGINT | Defaulted accounts with data that many months before their first overdraft. |
| `median_balance_vs_12m_peak` | DOUBLE | Median of balance_vs_12m_peak (0.24 = balance at 24% of its recent peak). |
| `mean_balance_vs_12m_peak` | DOUBLE | Mean of balance_vs_12m_peak. |

## `marts.mart_committed_obligations`

Monthly amounts each account has committed through standing orders, by purpose, and as a share of typical income.

| Column | Type | Meaning |
|---|---|---|
| `account_id` | INTEGER | Bank account ID. |
| `typical_income` | DOUBLE | JUDGE I — median money_in, CAD/month. |
| `n_standing_orders` | BIGINT | Number of standing orders on the account. |
| `standing_order_household_bills` | DOUBLE | Standing orders for household bills, CAD/month. |
| `standing_order_insurance` | DOUBLE | Standing orders for insurance, CAD/month. |
| `standing_order_leasing` | DOUBLE | Standing orders for leasing, CAD/month. |
| `standing_order_loan_payment` | DOUBLE | Standing orders for loan payments, CAD/month. |
| `standing_order_other` | DOUBLE | Standing orders with no stated purpose, CAD/month (not counted as committed). |
| `committed_monthly_obligations` | DOUBLE | Household bills + insurance + leasing + loan standing orders, CAD/month. |
| `committed_share_of_income` | DOUBLE | committed_monthly_obligations / typical_income. 0.4 = 40% of a typical month is already spoken for. NULL if income is 0. |

## `marts.mart_customer_profile`

One row per account: the judges' numbers (I, F, S, H, B, P), our context numbers, risk features and flags. The engine reads only this table.

| Column | Type | Meaning |
|---|---|---|
| `account_id` | INTEGER | Bank account ID. |
| `typical_income` | DOUBLE | JUDGE I — typical monthly money in = median of money_in over all months (quiet months included). CAD/month. |
| `typical_fixed_costs` | DOUBLE | JUDGE F — typical fixed costs = median of (household_bills + insurance + loan_payments). Shown only, not used in runway. CAD/month. |
| `typical_spending` | DOUBLE | JUDGE S — typical monthly spending = median of money_out. CAD/month. |
| `typical_household_bills` | DOUBLE | JUDGE H — typical household bills = median of household_bills. Rent / utility shocks scale this. CAD/month. |
| `buffer` | DOUBLE | JUDGE B — savings buffer = mean of avg_daily_balance over the account's last 6 months. CAD. |
| `running_loan_payment` | DOUBLE | JUDGE P — loan monthly payment if the loan is still running at end of 2025 (status C or D), else 0. CAD/month. |
| `typical_discretionary_spending` | DOUBLE | OURS (D) — median of cash withdrawals + card withdrawals + unlabelled transfers out: the spending a customer could cut. CAD/month. |
| `lean_month_income_p25` | DOUBLE | OURS — income in a lean month = 25th percentile of the account's own monthly money_in. Used by the stress runway. CAD/month. |
| `typical_monthly_surplus` | DOUBLE | typical_income - typical_spending. Positive = saves money in a typical month. CAD/month. |
| `buffer_months_of_spending` | DOUBLE | buffer / typical_spending: how many typical months of spending the buffer covers. NULL if spending is 0. |
| `months_of_history` | BIGINT | Number of months of data for the account (12-72). |
| `first_month` | VARCHAR | First month with data, YYYY-MM. |
| `last_month` | VARCHAR | Last month with data, YYYY-MM. |
| `income_volatility_cv` | DOUBLE | How unsteady income is: standard deviation / mean of monthly money_in. 0 = same every month. NULL if income is always 0. |
| `lean_month_share` | DOUBLE | Share of months where money_in was below 55% of the typical income (0-1). |
| `pension_income_share` | DOUBLE | Share of all money in that came from pensions (0-1). |
| `cash_income_share` | DOUBLE | Share of all money in that came as cash deposits (0-1). |
| `ever_overdrawn` | BOOLEAN | True if any day in the history ended below zero. |
| `total_days_overdrawn` | INTEGER | Total days in the history that ended below zero. |
| `days_overdrawn_last_6_months` | INTEGER | Days below zero in the last 6 months. |
| `balance_vs_12m_peak` | DOUBLE | Last month's average balance divided by the highest monthly average balance in the last 12 months (1 = at its peak, 0.3 = down 70%). |
| `owner_age_years` | INTEGER | Owner age in whole years on 2025-12-31. |
| `owner_gender` | VARCHAR | Owner gender (M / F). |
| `branch_region` | VARCHAR | Region of the branch. |
| `has_card` | BOOLEAN | True if anyone on the account holds a card. |
| `best_card_type` | VARCHAR | gold > classic > junior, or none. |
| `has_loan` | BOOLEAN | True if the account ever took a loan. |
| `loan_status` | VARCHAR | A repaid, B defaulted, C running OK, D running in debt; NULL if no loan. |
| `loan_monthly_payment` | DOUBLE | Loan monthly payment whatever the status, CAD. NULL if no loan. |
| `loan_end_date` | DATE | Date the loan ends (start + duration). NULL if no loan. |
| `is_volatile_income` | BOOLEAN | FLAG — income_volatility_cv above the volatile_income_cv threshold (0.45, top quartile). |
| `is_pensioner` | BOOLEAN | FLAG — more than 30% of income from pensions. A job-loss / EI shock may not apply. |
| `has_overdraft_history` | BOOLEAN | FLAG — has been below zero at least once. |
| `is_balance_sliding` | BOOLEAN | FLAG — balance_vs_12m_peak below 0.50: savings are draining. |
| `has_loan_in_debt` | BOOLEAN | FLAG — loan status D (running, client in debt). |
| `has_short_history` | BOOLEAN | FLAG — fewer than 18 months of data; medians are less reliable. |
| `is_stale_account` | BOOLEAN | FLAG — data ends before 2025-12, so the buffer is older than the others. |
| `has_negative_buffer` | BOOLEAN | FLAG — buffer is 0 or below: runway is 0 under any shock. |
| `has_zero_income` | BOOLEAN | FLAG — typical income is 0 (dormant or irregular account). |

## `marts.mart_default_drivers`

Default rate by quartile of each pre-loan driver (Q1 = lowest value), plus by "went below zero before the loan".

| Column | Type | Meaning |
|---|---|---|
| `driver` | VARCHAR | Column of mart_loan_preloan being tested. |
| `group_label` | VARCHAR | Quartile label (Q1 lowest ... Q4 highest) or yes/no group. |
| `group_order` | INTEGER | Sort order of the groups. |
| `loans` | BIGINT | Number of loans in the group. |
| `defaults` | HUGEINT | Number of defaulted loans (status B or D) in the group. |
| `default_rate` | DOUBLE | defaults / loans (0-1). |
| `min_value` | DOUBLE | Smallest driver value in the group. |
| `max_value` | DOUBLE | Largest driver value in the group. |

## `marts.mart_findings`

Every headline number in the pitch, one row per metric, with its sample size and the mart it came from.

| Column | Type | Meaning |
|---|---|---|
| `finding_id` | VARCHAR | F1-F11 (F10, the AUC test, is computed in findings.py). |
| `finding` | VARCHAR | The finding as a one-line takeaway. |
| `metric` | VARCHAR | What exactly was measured. |
| `value` | DOUBLE | The number. Shares are 0-1. |
| `unit` | VARCHAR | Unit of value: share, accounts, loans, months, years, CAD. |
| `n` | BIGINT | Sample size behind the number. |
| `source` | VARCHAR | Mart the number was computed from. |

## `marts.mart_loan_preloan`

One row per loan, with features computed ONLY from the months before the loan was granted (leakage-free). Used for all default analysis.

| Column | Type | Meaning |
|---|---|---|
| `loan_id` | INTEGER | Loan ID. |
| `account_id` | INTEGER | Account that took the loan. |
| `loan_start_month` | VARCHAR | Month the loan was granted, YYYY-MM. Features use months strictly before this. |
| `loan_status` | VARCHAR | A repaid, B defaulted, C running OK, D running in debt. |
| `is_defaulted` | BOOLEAN | Outcome: True if status B or D. |
| `monthly_payment` | DOUBLE | Loan monthly payment, CAD. |
| `loan_amount` | DOUBLE | Loan size, CAD. |
| `duration_months` | INTEGER | Loan length in months. |
| `pre_loan_months` | BIGINT | Months of history before the loan (3-23). |
| `pre_loan_typical_income` | DOUBLE | Median money_in before the loan, CAD/month. |
| `pre_loan_typical_spending` | DOUBLE | Median money_out before the loan, CAD/month. |
| `pre_loan_lean_month_income_p25` | DOUBLE | 25th-percentile money_in before the loan (a lean month), CAD/month. |
| `pre_loan_avg_balance` | DOUBLE | Mean avg_daily_balance over all months before the loan, CAD. |
| `pre_loan_buffer_last_6_months` | DOUBLE | Judge-style buffer before the loan: mean avg_daily_balance over the last 6 pre-loan months, CAD. |
| `pre_loan_lowest_balance` | DOUBLE | Lowest end-of-day balance before the loan, CAD. |
| `pre_loan_days_overdrawn` | INTEGER | Days below zero before the loan. |
| `pre_loan_was_overdrawn` | BOOLEAN | True if the account went below zero at least once before the loan. |
| `pre_loan_income_cv` | DOUBLE | Income volatility before the loan: std / mean of monthly money_in. |
| `payment_to_income` | DOUBLE | Loan payment / pre-loan typical income. 0.2 = the payment eats 20% of a typical month. |
| `buffer_months` | DOUBLE | Pre-loan average balance / pre-loan typical spending: months of spending the savings covered. |
| `judge_runway_with_loan` | DOUBLE | Judge runway formula on pre-loan data with the loan payment added to spending. 120 = no shortfall. |
| `judge_ei55_runway_with_loan` | DOUBLE | Same, with income = 0.55 x pre-loan typical income (job loss with EI). |
| `stress_runway_with_loan` | DOUBLE | OURS — same formula with income = pre-loan lean month (25th percentile). Lower = riskier. |

## `marts.mart_shock_runways`

Months of runway per account under the judges' example twists (judge formula) and our stress-adjusted version. NULL = no shortfall (120+).

| Column | Type | Meaning |
|---|---|---|
| `account_id` | INTEGER | Bank account ID. |
| `runway_no_shock` | DOUBLE | JUDGE runway with no shock: buffer / (S - I). NULL = no shortfall (120+). |
| `runway_job_loss_ei55` | DOUBLE | JUDGE runway, job loss with EI at 55%: income = 0.55 x I. |
| `runway_bills_up_15` | DOUBLE | JUDGE runway, household bills +15%: spending = S + 0.15 x H. |
| `runway_furnace_1_month` | DOUBLE | JUDGE runway, surprise repair costing one month of spending: one-off cost = S. |
| `runway_job_loss_plus_bills` | DOUBLE | JUDGE runway, job loss (EI 55%) and bills +15% in the same month. |
| `stress_runway_no_shock` | DOUBLE | OURS — judge formula but income = a lean month (25th percentile of own money_in). |
| `stress_runway_job_loss_ei55` | DOUBLE | OURS — stress runway with EI: income = 0.55 x lean-month income. |

## Thresholds (`marts.config_thresholds`, set in `src/tangerine/config.py`)

| Name | Value | Meaning |
|---|---:|---|
| `volatile_income_cv` | 0.45 | Income is 'volatile' when its coefficient of variation (std / mean of monthly money in) is above this. 0.45 is roughly the top-quartile cut across all accounts. |
| `pensioner_income_share` | 0.3 | An account is a 'pensioner' when more than this share of all money in came from pensions. |
| `lean_month_income_ratio` | 0.55 | A 'lean month' is a month whose money in is below this fraction of the account's own typical income (same size as the EI job-loss shock). |
| `balance_slide_ratio` | 0.5 | Balance is 'sliding' when last month's average balance is below this fraction of the highest monthly average balance in the 12 months before it. |
| `short_history_months` | 18 | History is 'short' when the account has fewer than this many months of data. |
| `target_buffer_months_steady` | 3 | Emergency-fund goal, in months of typical spending, for customers with steady income. |
| `target_buffer_months_volatile` | 6 | Emergency-fund goal, in months of typical spending, for customers with volatile income. |
| `backup_plan_discretionary_cut` | 0.3 | Default share of discretionary spending the backup plan cuts when a shock hits. |
| `backup_plan_runway_goal_months` | 6 | The backup plan reports the discretionary cut needed to reach this many months of runway. |
| `savings_share_of_surplus` | 0.5 | Goal plan: save this share of the monthly surplus (money in minus spending)... |
| `savings_share_of_discretionary` | 0.1 | ...plus this share of discretionary spending, capped at the full surplus. |
| `goal_plan_deadline_months` | 12 | Goal plan when there is no surplus: the discretionary cut needed to reach the target within this many months. |
