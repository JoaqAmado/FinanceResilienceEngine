-- staging.stg_transactions — single transactions, for drill-downs on one account only.
-- Same-day rows are NOT in time order. Grain: one row per transaction_id.
create schema if not exists staging;
create or replace table staging.stg_transactions as
select
    transaction_id::bigint            as transaction_id,
    account_id::integer               as account_id,
    "date"::date                      as transaction_date,
    strftime("date"::date, '%Y-%m')   as month,
    direction,
    operation,
    coalesce(purpose, '')             as purpose,          -- blank = not labelled
    amount::double                    as amount,           -- always positive
    signed_amount::double             as signed_amount,    -- + money in, - money out
    balance::double                   as balance_after,
    partner_bank,
    partner_account
from raw.transactions;
