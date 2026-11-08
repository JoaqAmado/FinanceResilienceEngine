-- marts.fact_account_month — every monthly measure for every account (star-schema fact).
-- Grain: one row per (account_id, month). 185,326 rows.
create or replace table marts.fact_account_month as
with t as (
    select max(threshold_value) filter (where threshold_name = 'lean_month_income_ratio') as lean_ratio
    from marts.config_thresholds
)
select
    m.*,
    row_number() over (partition by m.account_id order by m.month)        as month_number,
    row_number() over (partition by m.account_id order by m.month desc)   as months_from_end,
    m.money_in < t.lean_ratio * median(m.money_in) over (partition by m.account_id) as is_lean_month,
    m.days_below_zero > 0                                                  as was_overdrawn
from staging.stg_monthly_summary m
cross join t;

comment on table marts.fact_account_month is 'One row per account per month, from the first to the last transaction month (quiet months included). All money in CAD.';
comment on column marts.fact_account_month.account_id is 'Bank account ID.';
comment on column marts.fact_account_month.month is 'Calendar month as text, YYYY-MM.';
comment on column marts.fact_account_month.month_date is 'First day of the month, as a date.';
comment on column marts.fact_account_month.money_in is 'Total money in this month = cash_deposits + transfers_in + pension_in + interest_in.';
comment on column marts.fact_account_month.money_out is 'Total money out this month = household_bills + insurance + loan_payments + bank_fees + cash_withdrawals_genuine + card_withdrawals + transfers_out_other.';
comment on column marts.fact_account_month.cash_deposits is 'Cash paid into the account.';
comment on column marts.fact_account_month.transfers_in is 'Transfers in from other banks (pensions excluded).';
comment on column marts.fact_account_month.pension_in is 'Pension payments received.';
comment on column marts.fact_account_month.interest_in is 'Interest credited by the bank.';
comment on column marts.fact_account_month.household_bills is 'Household bills paid (rent, utilities).';
comment on column marts.fact_account_month.insurance is 'Insurance payments.';
comment on column marts.fact_account_month.loan_payments is 'Loan repayments.';
comment on column marts.fact_account_month.bank_fees is 'Statement fees and penalty interest.';
comment on column marts.fact_account_month.cash_withdrawals_genuine is 'Cash taken out.';
comment on column marts.fact_account_month.card_withdrawals is 'Card withdrawals / payments.';
comment on column marts.fact_account_month.transfers_out_other is 'Unlabelled transfers out to other banks.';
comment on column marts.fact_account_month.month_end_balance is 'Balance at the end of the last day of the month.';
comment on column marts.fact_account_month.min_balance is 'Lowest end-of-day balance in the month.';
comment on column marts.fact_account_month.avg_daily_balance is 'Average end-of-day balance in the month (the buffer B uses this).';
comment on column marts.fact_account_month.days_below_zero is 'Days in the month that ended with a negative balance.';
comment on column marts.fact_account_month.fixed_costs is 'household_bills + insurance + loan_payments (the monthly part of the judges'' F).';
comment on column marts.fact_account_month.discretionary_spending is 'cash_withdrawals_genuine + card_withdrawals + transfers_out_other — spending a customer could cut.';
comment on column marts.fact_account_month.net_cash_flow is 'money_in - money_out. Negative = the month ate into savings.';
comment on column marts.fact_account_month.month_number is '1 for the account''s first month, 2 for the second, ...';
comment on column marts.fact_account_month.months_from_end is '1 for the account''s last month, 2 for the one before, ... (B = mean of avg_daily_balance where this is 1-6).';
comment on column marts.fact_account_month.is_lean_month is 'True if money_in is below 55% of the account''s own typical (median) income — what a month on EI would look like.';
comment on column marts.fact_account_month.was_overdrawn is 'True if at least one day this month ended below zero.';
