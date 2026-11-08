-- raw.transactions — transactions.csv, read from the Parquet copy the pipeline makes once
-- (warehouse/transactions.parquet). Only used for single-account drill-downs, never for metrics.
-- Grain: one row per transaction.
create schema if not exists raw;
create or replace table raw.transactions as
select * from read_parquet('{{TRANSACTIONS_PARQUET}}');
