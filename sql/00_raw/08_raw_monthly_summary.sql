-- raw.monthly_summary — the official monthly_summary.csv, loaded as-is (no transformations).
-- Grain: one row per row of the CSV.
create schema if not exists raw;
create or replace table raw.monthly_summary as
select * from read_csv('{{DATA_DIR}}/monthly_summary.csv', header = true, types = {'month': 'VARCHAR', 'days_below_zero': 'INTEGER'});
