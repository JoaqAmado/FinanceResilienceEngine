-- staging.stg_account_owner — the owner of each account, with their gender and age.
-- Grain: one row per account_id (a quality check enforces exactly one owner per account).
create schema if not exists staging;
create or replace table staging.stg_account_owner as
select
    d.account_id,
    d.client_id           as owner_client_id,
    c.gender              as owner_gender,
    c.age_years           as owner_age_years,
    c.home_district_id    as owner_home_district_id
from staging.stg_dispositions d
join staging.stg_clients c using (client_id)
where d.role = 'owner';
