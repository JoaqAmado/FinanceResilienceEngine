-- raw.cards — the official cards.csv, loaded as-is (no transformations).
-- Grain: one row per row of the CSV.
create schema if not exists raw;
create or replace table raw.cards as
select * from read_csv('{{DATA_DIR}}/cards.csv', header = true, types = {'issued': 'DATE'});
