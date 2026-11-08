-- staging.stg_districts — the bank's 77 original regions (a district is a branch area or a home area).
-- Grain: one row per district_id. District 69 keeps its NULL 2022 unemployment / crime values.
create schema if not exists staging;
create or replace table staging.stg_districts as
select
    district_id::integer             as district_id,
    district_name,
    region,
    inhabitants::integer             as inhabitants,
    urban_ratio_pct::double          as urban_ratio_pct,
    average_salary::double           as average_monthly_salary,
    unemployment_rate_2022::double   as unemployment_rate_2022,
    unemployment_rate_2023::double   as unemployment_rate_2023,
    entrepreneurs_per_1000::integer  as entrepreneurs_per_1000,
    crimes_2022::integer             as crimes_2022,
    crimes_2023::integer             as crimes_2023
from raw.districts;
