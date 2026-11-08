-- staging.stg_dispositions — links a client to an account with a role.
-- Grain: one row per disposition_id.
create schema if not exists staging;
create or replace table staging.stg_dispositions as
select
    disposition_id::integer  as disposition_id,
    client_id::integer       as client_id,
    account_id::integer      as account_id,
    "type"                   as role            -- 'owner' or 'authorized user'
from raw.dispositions;
