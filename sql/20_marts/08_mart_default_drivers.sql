-- marts.mart_default_drivers — default rate by quartile of each pre-loan driver.
-- Quartiles are cut on the rank (ties broken by account_id), which gives the same groups as
-- pandas.qcut(x.rank(method="first")): 171 / 170 / 170 / 171 loans. Quartile 1 = lowest value.
-- Note: many loans tie at runway = 120 ("no shortfall"), so the Q3/Q4 split of the runway
-- drivers depends on the tie-break. Q1 (the risky group) does not.
-- Grain: one row per (driver, group).
create or replace table marts.mart_default_drivers as
with long as (
    select account_id, is_defaulted, 'pre_loan_income_cv' as driver, pre_loan_income_cv as value from marts.mart_loan_preloan
    union all
    select account_id, is_defaulted, 'payment_to_income',            payment_to_income            from marts.mart_loan_preloan
    union all
    select account_id, is_defaulted, 'buffer_months',                buffer_months                from marts.mart_loan_preloan
    union all
    select account_id, is_defaulted, 'judge_ei55_runway_with_loan',  judge_ei55_runway_with_loan  from marts.mart_loan_preloan
    union all
    select account_id, is_defaulted, 'stress_runway_with_loan',      stress_runway_with_loan      from marts.mart_loan_preloan
),
ranked as (
    select *,
        row_number() over (partition by driver order by value, account_id) as rnk,
        count(*)     over (partition by driver)                         as n
    from long
    where value is not null
),
bucketed as (
    select *,
        case
            when rnk <= 1 + 0.25 * (n - 1) then 1
            when rnk <= 1 + 0.50 * (n - 1) then 2
            when rnk <= 1 + 0.75 * (n - 1) then 3
            else 4
        end as quartile
    from ranked
)
select
    driver,
    'Q' || quartile || case quartile when 1 then ' (lowest)' when 4 then ' (highest)' else '' end as group_label,
    quartile                         as group_order,
    count(*)                         as loans,
    sum(is_defaulted::integer)       as defaults,
    avg(is_defaulted::integer)       as default_rate,
    min(value)                       as min_value,
    max(value)                       as max_value
from bucketed
group by driver, quartile

union all

select
    'pre_loan_was_overdrawn'          as driver,
    case when pre_loan_was_overdrawn then 'went below zero before the loan' else 'never below zero before the loan' end,
    case when pre_loan_was_overdrawn then 2 else 1 end,
    count(*),
    sum(is_defaulted::integer),
    avg(is_defaulted::integer),
    null, null
from marts.mart_loan_preloan
group by pre_loan_was_overdrawn
order by driver, group_order;

comment on table marts.mart_default_drivers is 'Default rate by quartile of each pre-loan driver (Q1 = lowest value), plus by "went below zero before the loan".';
comment on column marts.mart_default_drivers.driver is 'Column of mart_loan_preloan being tested.';
comment on column marts.mart_default_drivers.group_label is 'Quartile label (Q1 lowest ... Q4 highest) or yes/no group.';
comment on column marts.mart_default_drivers.group_order is 'Sort order of the groups.';
comment on column marts.mart_default_drivers.loans is 'Number of loans in the group.';
comment on column marts.mart_default_drivers.defaults is 'Number of defaulted loans (status B or D) in the group.';
comment on column marts.mart_default_drivers.default_rate is 'defaults / loans (0-1).';
comment on column marts.mart_default_drivers.min_value is 'Smallest driver value in the group.';
comment on column marts.mart_default_drivers.max_value is 'Largest driver value in the group.';
