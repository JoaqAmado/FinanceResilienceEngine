-- marts.mart_balance_slide — how savings drain in the months before a defaulter first goes below zero.
-- For each defaulted account: in each of the 12 months before its first overdrawn month, that month's
-- average balance divided by the highest monthly average balance in the 12 months up to and including it.
-- Grain: one row per (defaulted account, months_before_first_overdraft).
create or replace table marts.mart_balance_slide as
with m as (
    select
        f.account_id,
        f.month,
        f.month_number,
        f.avg_daily_balance,
        f.was_overdrawn,
        max(f.avg_daily_balance) over (
            partition by f.account_id order by f.month rows between 11 preceding and current row
        ) as trailing_12m_peak_balance
    from marts.fact_account_month f
    join staging.stg_loans l using (account_id)
    where l.is_defaulted
),
first_overdraft as (
    select account_id, min(month_number) as first_overdraft_month_number, min(month) as first_overdraft_month
    from m
    where was_overdrawn
    group by account_id
)
select
    m.account_id,
    fo.first_overdraft_month,
    fo.first_overdraft_month_number - m.month_number                  as months_before_first_overdraft,
    m.month,
    m.avg_daily_balance,
    m.trailing_12m_peak_balance,
    m.avg_daily_balance / nullif(m.trailing_12m_peak_balance, 0)      as balance_vs_12m_peak
from m
join first_overdraft fo using (account_id)
where fo.first_overdraft_month_number - m.month_number between 1 and 12;

comment on table marts.mart_balance_slide is 'For every defaulted loan account: average balance vs its trailing 12-month peak in each of the 12 months before its first overdraft.';
comment on column marts.mart_balance_slide.account_id is 'Defaulted loan account.';
comment on column marts.mart_balance_slide.first_overdraft_month is 'First month with a day below zero, YYYY-MM.';
comment on column marts.mart_balance_slide.months_before_first_overdraft is '1 = the month just before the first overdraft, 12 = a year before.';
comment on column marts.mart_balance_slide.month is 'Calendar month of this row, YYYY-MM.';
comment on column marts.mart_balance_slide.avg_daily_balance is 'Average end-of-day balance that month, CAD.';
comment on column marts.mart_balance_slide.trailing_12m_peak_balance is 'Highest monthly average balance in the 12 months up to and including this one, CAD.';
comment on column marts.mart_balance_slide.balance_vs_12m_peak is 'avg_daily_balance / trailing_12m_peak_balance (1 = at peak).';

-- marts.mart_balance_slide_summary — the median across accounts, per month before the first overdraft.
-- Grain: one row per months_before_first_overdraft (1-12).
create or replace table marts.mart_balance_slide_summary as
select
    months_before_first_overdraft,
    count(*)                            as accounts,
    median(balance_vs_12m_peak)         as median_balance_vs_12m_peak,
    avg(balance_vs_12m_peak)            as mean_balance_vs_12m_peak
from marts.mart_balance_slide
group by 1
order by 1;

comment on table marts.mart_balance_slide_summary is 'Median balance-vs-peak across defaulted accounts, for each of the 12 months before the first overdraft.';
comment on column marts.mart_balance_slide_summary.months_before_first_overdraft is '1 = the month just before the first overdraft.';
comment on column marts.mart_balance_slide_summary.accounts is 'Defaulted accounts with data that many months before their first overdraft.';
comment on column marts.mart_balance_slide_summary.median_balance_vs_12m_peak is 'Median of balance_vs_12m_peak (0.24 = balance at 24% of its recent peak).';
comment on column marts.mart_balance_slide_summary.mean_balance_vs_12m_peak is 'Mean of balance_vs_12m_peak.';
