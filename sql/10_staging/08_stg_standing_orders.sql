-- staging.stg_standing_orders — recurring payment instructions (an undated, end-of-data snapshot).
-- A blank purpose becomes 'other'. Grain: one row per order_id.
create schema if not exists staging;
create or replace table staging.stg_standing_orders as
select
    order_id::integer                              as order_id,
    account_id::integer                            as account_id,
    to_bank,
    to_account,
    amount::double                                 as monthly_amount,
    coalesce(nullif(trim(purpose), ''), 'other')   as purpose
from raw.standing_orders;
