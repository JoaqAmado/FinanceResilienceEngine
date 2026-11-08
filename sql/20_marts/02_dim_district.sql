-- marts.dim_district — region facts for each district (star-schema dimension).
-- Grain: one row per district_id.
create or replace table marts.dim_district as
select * from staging.stg_districts;

comment on table marts.dim_district is 'One row per district (the bank''s original Czech regions): population, salary, unemployment, crime.';
comment on column marts.dim_district.district_id is 'District ID (joins to dim_account.branch_district_id).';
comment on column marts.dim_district.district_name is 'District name.';
comment on column marts.dim_district.region is 'One of 8 larger regions the district belongs to.';
comment on column marts.dim_district.inhabitants is 'Population of the district.';
comment on column marts.dim_district.urban_ratio_pct is 'Share of inhabitants living in cities, in percent.';
comment on column marts.dim_district.average_monthly_salary is 'Average monthly salary in the district, CAD.';
comment on column marts.dim_district.unemployment_rate_2022 is 'Unemployment rate 2022, percent. NULL for district 69.';
comment on column marts.dim_district.unemployment_rate_2023 is 'Unemployment rate 2023, percent.';
comment on column marts.dim_district.entrepreneurs_per_1000 is 'Entrepreneurs per 1,000 inhabitants.';
comment on column marts.dim_district.crimes_2022 is 'Number of crimes committed in 2022. NULL for district 69.';
comment on column marts.dim_district.crimes_2023 is 'Number of crimes committed in 2023.';
