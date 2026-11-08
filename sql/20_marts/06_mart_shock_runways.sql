-- marts.mart_shock_runways — judge runway (and our stress runway) for every account under each example twist.
-- Runway columns are in months, rounded to 1 decimal. NULL = "no shortfall (120+)".
-- Grain: one row per account_id (4,500 rows).
create or replace table marts.mart_shock_runways as
with p as (
    select
        account_id,
        typical_income          as i,
        typical_spending        as s,
        typical_household_bills as h,
        buffer                  as b,
        lean_month_income_p25   as i_lean
    from marts.mart_customer_profile
)
select
    account_id,
    -- Judge formula
    marts.judge_runway(b, i,        s,            0) as runway_no_shock,
    marts.judge_runway(b, 0.55 * i, s,            0) as runway_job_loss_ei55,
    marts.judge_runway(b, i,        s + 0.15 * h, 0) as runway_bills_up_15,
    marts.judge_runway(b, i,        s,            s) as runway_furnace_1_month,
    marts.judge_runway(b, 0.55 * i, s + 0.15 * h, 0) as runway_job_loss_plus_bills,
    -- Our stress-adjusted version: same formula, but income = a lean (25th-percentile) month
    marts.judge_runway(b, i_lean,        s, 0)       as stress_runway_no_shock,
    marts.judge_runway(b, 0.55 * i_lean, s, 0)       as stress_runway_job_loss_ei55
from p;

comment on table marts.mart_shock_runways is 'Months of runway per account under the judges'' example twists (judge formula) and our stress-adjusted version. NULL = no shortfall (120+).';
comment on column marts.mart_shock_runways.account_id is 'Bank account ID.';
comment on column marts.mart_shock_runways.runway_no_shock is 'JUDGE runway with no shock: buffer / (S - I). NULL = no shortfall (120+).';
comment on column marts.mart_shock_runways.runway_job_loss_ei55 is 'JUDGE runway, job loss with EI at 55%: income = 0.55 x I.';
comment on column marts.mart_shock_runways.runway_bills_up_15 is 'JUDGE runway, household bills +15%: spending = S + 0.15 x H.';
comment on column marts.mart_shock_runways.runway_furnace_1_month is 'JUDGE runway, surprise repair costing one month of spending: one-off cost = S.';
comment on column marts.mart_shock_runways.runway_job_loss_plus_bills is 'JUDGE runway, job loss (EI 55%) and bills +15% in the same month.';
comment on column marts.mart_shock_runways.stress_runway_no_shock is 'OURS — judge formula but income = a lean month (25th percentile of own money_in).';
comment on column marts.mart_shock_runways.stress_runway_job_loss_ei55 is 'OURS — stress runway with EI: income = 0.55 x lean-month income.';
