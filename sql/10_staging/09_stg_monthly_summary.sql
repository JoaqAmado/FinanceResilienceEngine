-- staging.stg_monthly_summary — one account in one month. ALL judge numbers come from this table.
-- Source columns keep their official names; we only add helper columns at the end.
-- Quiet months (all zeros) are kept on purpose: the judge medians include them.
-- Grain: one row per (account_id, month).
create schema if not exists staging;
create or replace table staging.stg_monthly_summary as
select
    account_id::integer                                   as account_id,
    month,                                                -- 'YYYY-MM' text
    strptime(month || '-01', '%Y-%m-%d')::date            as month_date,
    money_in, money_out,
    cash_deposits, transfers_in, pension_in, interest_in,
    household_bills, insurance, loan_payments, bank_fees,
    cash_withdrawals_genuine, card_withdrawals, transfers_out_other,
    month_end_balance, min_balance, avg_daily_balance,
    days_below_zero,
    household_bills + insurance + loan_payments                        as fixed_costs,
    cash_withdrawals_genuine + card_withdrawals + transfers_out_other  as discretionary_spending,
    money_in - money_out                                               as net_cash_flow
from raw.monthly_summary;
