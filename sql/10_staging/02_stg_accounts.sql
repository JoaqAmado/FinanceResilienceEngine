-- staging.stg_accounts — one bank account.
-- Grain: one row per account_id.
create schema if not exists staging;
create or replace table staging.stg_accounts as
select
    account_id::integer     as account_id,
    district_id::integer    as branch_district_id,   -- branch where the account is held
    frequency               as statement_frequency,
    account_opened::date    as account_opened_date
from raw.accounts;
