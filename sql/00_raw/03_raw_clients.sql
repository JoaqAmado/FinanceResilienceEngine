-- raw.clients — the official clients.csv, loaded as-is (no transformations).
-- Grain: one row per row of the CSV.
create schema if not exists raw;
create or replace table raw.clients as
select * from read_csv('{{DATA_DIR}}/clients.csv', header = true, types = {'birth_date': 'DATE'});
