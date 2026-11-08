-- marts.mart_findings — every headline number used in the pitch, computed from the marts.
-- findings.py adds the AUC / bootstrap numbers (easier in Python) and writes reports/findings.md.
-- Grain: one row per (finding_id, metric).
create or replace table marts.mart_findings (
    finding_id   varchar,
    finding      varchar,
    metric       varchar,
    value        double,
    unit         varchar,
    n            bigint,
    source       varchar
);

-- F1 · Overdraft before the loan -> default
insert into marts.mart_findings
select 'F1', 'Going below zero before the loan predicts default',
       'loans whose account went below zero before the loan', count(*), 'loans', count(*), 'mart_loan_preloan'
from marts.mart_loan_preloan where pre_loan_was_overdrawn
union all
select 'F1', 'Going below zero before the loan predicts default',
       'default rate of those loans', avg(is_defaulted::integer), 'share', count(*), 'mart_loan_preloan'
from marts.mart_loan_preloan where pre_loan_was_overdrawn
union all
select 'F1', 'Going below zero before the loan predicts default',
       'default rate of loans that never went below zero before', avg(is_defaulted::integer), 'share', count(*), 'mart_loan_preloan'
from marts.mart_loan_preloan where not pre_loan_was_overdrawn;

-- F2 · Volatility beats buffer size
insert into marts.mart_findings
select 'F2', 'Unsteady income, not small savings, predicts default',
       'default rate, ' || group_label || ' of pre-loan income volatility', default_rate, 'share', loans, 'mart_default_drivers'
from marts.mart_default_drivers where driver = 'pre_loan_income_cv' and group_order in (1, 4)
union all
select 'F2', 'Unsteady income, not small savings, predicts default',
       'median pre-loan buffer (months of spending), ' || case when is_defaulted then 'defaulters' else 'non-defaulters' end,
       median(buffer_months), 'months', count(*), 'mart_loan_preloan'
from marts.mart_loan_preloan group by is_defaulted;

-- F3 · Payment burden
insert into marts.mart_findings
select 'F3', 'A heavy loan payment raises default risk',
       'default rate, ' || group_label || ' of payment / income', default_rate, 'share', loans, 'mart_default_drivers'
from marts.mart_default_drivers where driver = 'payment_to_income' and group_order in (1, 4);

-- F4 · Balance slide before the first overdraft
insert into marts.mart_findings
select 'F4', 'Savings slide for ~3 months before the first overdraft',
       'median balance as share of 12-month peak, ' || months_before_first_overdraft || ' month(s) before first overdraft',
       median_balance_vs_12m_peak, 'share', accounts, 'mart_balance_slide_summary'
from marts.mart_balance_slide_summary where months_before_first_overdraft <= 4;

-- F5 · The EI twist across the whole bank (judge formula, judge-rounded runway)
insert into marts.mart_findings
select 'F5', 'Job loss with EI 55%: a third of customers run out within 6 months', metric, value, 'accounts', 4500, 'mart_shock_runways'
from (
    select 'accounts with runway 0 (buffer already gone)' as metric, count(*) filter (where runway_job_loss_ei55 = 0) as value, 1 as o from marts.mart_shock_runways
    union all select 'accounts that run out in under 3 months (incl. 0)', count(*) filter (where runway_job_loss_ei55 < 3), 2 from marts.mart_shock_runways
    union all select 'accounts that run out in under 6 months (incl. 0)', count(*) filter (where runway_job_loss_ei55 < 6), 3 from marts.mart_shock_runways
    union all select 'accounts with no shortfall even on EI', count(*) filter (where runway_job_loss_ei55 is null), 4 from marts.mart_shock_runways
    union all select 'accounts with no shortfall and no shock', count(*) filter (where runway_no_shock is null), 5 from marts.mart_shock_runways
) order by o;

-- F6 · Medians hide lean months
insert into marts.mart_findings
select 'F6', 'Medians hide lean months',
       'share of accounts where >= 20% of months had income below 55% of their own median',
       avg((lean_month_share >= 0.20)::integer), 'share', count(*), 'mart_customer_profile'
from marts.mart_customer_profile;

-- F7 · Pensioners break the job-loss twist
insert into marts.mart_findings
select 'F7', 'Pensioners break the job-loss twist', 'pensioner accounts (> 30% of income from pensions)',
       count(*) filter (where is_pensioner), 'accounts', count(*), 'mart_customer_profile'
from marts.mart_customer_profile
union all
select 'F7', 'Pensioners break the job-loss twist',
       'median owner age, ' || case when is_pensioner then 'pensioners' else 'others' end,
       median(owner_age_years), 'years', count(*), 'mart_customer_profile'
from marts.mart_customer_profile group by is_pensioner
union all
select 'F7', 'Pensioners break the job-loss twist',
       'median EI-55% runway (no shortfall = 120), ' || case when p.is_pensioner then 'pensioners' else 'others' end,
       median(coalesce(r.runway_job_loss_ei55, 120)), 'months', count(*), 'mart_shock_runways'
from marts.mart_customer_profile p join marts.mart_shock_runways r using (account_id) group by p.is_pensioner;

-- F8 · Card holders are wealthier
insert into marts.mart_findings
select 'F8', 'Card holders are wealthier',
       'median ' || x.what || ', ' || case when has_card then 'card holders' else 'no card' end,
       x.v, 'CAD', x.n, 'mart_customer_profile'
from (
    select has_card, 'typical income (I)' as what, median(typical_income) as v, count(*) as n from marts.mart_customer_profile group by has_card
    union all
    select has_card, 'buffer (B)', median(buffer), count(*) from marts.mart_customer_profile group by has_card
) x;

-- F9 · Region barely matters
insert into marts.mart_findings
with by_region as (
    select p.branch_region, avg((r.runway_job_loss_ei55 < 3)::integer) as share_under_3, count(*) as n
    from marts.mart_customer_profile p join marts.mart_shock_runways r using (account_id)
    group by p.branch_region
)
select 'F9', 'Region barely matters', 'lowest regional share under 3 months of EI runway', min(share_under_3), 'share', sum(n), 'mart_shock_runways'
from by_region
union all
select 'F9', 'Region barely matters', 'highest regional share under 3 months of EI runway', max(share_under_3), 'share', sum(n), 'mart_shock_runways'
from by_region;

-- F11 · Committed obligations (standing orders)
insert into marts.mart_findings
select 'F11', 'A slice of income is already spoken for',
       'median share of typical income committed by standing orders (accounts with income > 0)',
       median(committed_share_of_income), 'share', count(*), 'mart_committed_obligations'
from marts.mart_committed_obligations where committed_share_of_income is not null
union all
select 'F11', 'A slice of income is already spoken for',
       'accounts committing more than half their typical income',
       count(*) filter (where committed_share_of_income > 0.5), 'accounts', count(*), 'mart_committed_obligations'
from marts.mart_committed_obligations;

comment on table marts.mart_findings is 'Every headline number in the pitch, one row per metric, with its sample size and the mart it came from.';
comment on column marts.mart_findings.finding_id is 'F1-F11 (F10, the AUC test, is computed in findings.py).';
comment on column marts.mart_findings.finding is 'The finding as a one-line takeaway.';
comment on column marts.mart_findings.metric is 'What exactly was measured.';
comment on column marts.mart_findings.value is 'The number. Shares are 0-1.';
comment on column marts.mart_findings.unit is 'Unit of value: share, accounts, loans, months, years, CAD.';
comment on column marts.mart_findings.n is 'Sample size behind the number.';
comment on column marts.mart_findings.source is 'Mart the number was computed from.';
