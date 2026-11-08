-- raw.loans — the official loans.csv, loaded as-is (no transformations).
-- Grain: one row per row of the CSV.
create schema if not exists raw;
create or replace table raw.loans as
select * from read_csv('{{DATA_DIR}}/loans.csv', header = true, types = {'loan_start': 'DATE', 'status': 'VARCHAR'});
