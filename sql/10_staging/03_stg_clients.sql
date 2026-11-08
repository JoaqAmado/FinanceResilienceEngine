-- staging.stg_clients — one person. Age is measured on the last day of data (2025-12-31).
-- Grain: one row per client_id.
create schema if not exists staging;
create or replace table staging.stg_clients as
select
    client_id::integer      as client_id,
    gender,
    birth_date::date        as birth_date,
    district_id::integer    as home_district_id,
    date_part('year', age(date '{{REFERENCE_DATE}}', birth_date::date))::integer as age_years
from raw.clients;
