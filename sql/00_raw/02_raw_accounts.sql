-- raw.accounts — the official accounts.csv, loaded as-is (no transformations).
-- Grain: one row per row of the CSV.
create schema if not exists raw;
create or replace table raw.accounts as
select * from read_csv('{{DATA_DIR}}/accounts.csv', header = true, types = {'account_opened': 'DATE'});
