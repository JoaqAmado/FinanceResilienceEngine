-- raw.standing_orders — the official standing_orders.csv, loaded as-is (no transformations).
-- Grain: one row per row of the CSV.
create schema if not exists raw;
create or replace table raw.standing_orders as
select * from read_csv('{{DATA_DIR}}/standing_orders.csv', header = true, types = {'to_bank': 'VARCHAR', 'to_account': 'VARCHAR', 'purpose': 'VARCHAR'});
