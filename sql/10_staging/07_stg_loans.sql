-- staging.stg_loans — at most one loan per account.
-- Status: A = finished, repaid | B = finished, defaulted | C = running, OK | D = running, in debt.
-- "Still running at end of 2025" = status C or D (verified identical to loan_start + duration > 2025-12-31).
-- Grain: one row per loan_id.
create schema if not exists staging;
create or replace table staging.stg_loans as
select
    loan_id::integer                                              as loan_id,
    account_id::integer                                           as account_id,
    loan_start::date                                              as loan_start_date,
    strftime(loan_start::date, '%Y-%m')                           as loan_start_month,
    (loan_start::date + to_months(duration_months::integer))::date as loan_end_date,
    amount::double                                                as loan_amount,
    duration_months::integer                                      as duration_months,
    monthly_payment::double                                       as monthly_payment,
    status                                                        as loan_status,
    status_meaning                                                as loan_status_meaning,
    status in ('C', 'D')                                          as is_running,
    defaulted = 1                                                 as is_defaulted
from raw.loans;
