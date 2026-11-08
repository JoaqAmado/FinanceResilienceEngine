-- marts.mart_customer_profile — everything the engine needs to know about one customer.
-- THE ENGINE READS ONLY THIS TABLE.
-- Grain: one row per account_id (4,500 rows).
--
-- Judge numbers (exact official definitions, Tangerine/README.md):
--   typical_income           = I = median(money_in)                                  over ALL months
--   typical_fixed_costs      = F = median(household_bills + insurance + loan_payments)
--   typical_spending         = S = median(money_out)
--   typical_household_bills  = H = median(household_bills)
--   buffer                   = B = mean(avg_daily_balance) over the LAST 6 rows by month
--   running_loan_payment     = P = loans.monthly_payment if status C or D, else 0
create or replace table marts.mart_customer_profile as
with t as (
    select
        max(threshold_value) filter (where threshold_name = 'volatile_income_cv')      as volatile_cv,
        max(threshold_value) filter (where threshold_name = 'pensioner_income_share')  as pensioner_share,
        max(threshold_value) filter (where threshold_name = 'balance_slide_ratio')     as slide_ratio,
        max(threshold_value) filter (where threshold_name = 'short_history_months')    as short_months
    from marts.config_thresholds
),
per_account as (
    select
        account_id,
        median(money_in)                                     as typical_income,
        median(fixed_costs)                                  as typical_fixed_costs,
        median(money_out)                                    as typical_spending,
        median(household_bills)                              as typical_household_bills,
        avg(avg_daily_balance) filter (where months_from_end <= 6) as buffer,
        median(discretionary_spending)                       as typical_discretionary_spending,
        quantile_cont(money_in, 0.25)                        as lean_month_income_p25,
        count(*)                                             as months_of_history,
        min(month)                                           as first_month,
        max(month)                                           as last_month,
        stddev_samp(money_in) / nullif(avg(money_in), 0)     as income_volatility_cv,
        avg(is_lean_month::integer)                          as lean_month_share,
        coalesce(sum(pension_in) / nullif(sum(money_in), 0), 0)     as pension_income_share,
        coalesce(sum(cash_deposits) / nullif(sum(money_in), 0), 0)  as cash_income_share,
        sum(days_below_zero)::integer                        as total_days_overdrawn,
        coalesce(sum(days_below_zero) filter (where months_from_end <= 6), 0)::integer as days_overdrawn_last_6_months,
        max(avg_daily_balance) filter (where months_from_end = 1)   as last_month_avg_balance,
        max(avg_daily_balance) filter (where months_from_end <= 12) as peak_avg_balance_last_12_months
    from marts.fact_account_month
    group by account_id
)
select
    p.account_id,

    -- ── Judge numbers ────────────────────────────────────────────────────
    p.typical_income,
    p.typical_fixed_costs,
    p.typical_spending,
    p.typical_household_bills,
    p.buffer,
    case when a.loan_is_running then a.loan_monthly_payment else 0.0 end   as running_loan_payment,

    -- ── Context for the plan and the stress test ─────────────────────────
    p.typical_discretionary_spending,
    p.lean_month_income_p25,
    p.typical_income - p.typical_spending                                  as typical_monthly_surplus,
    p.buffer / nullif(p.typical_spending, 0)                               as buffer_months_of_spending,
    p.months_of_history,
    p.first_month,
    p.last_month,

    -- ── Risk features ────────────────────────────────────────────────────
    p.income_volatility_cv,
    p.lean_month_share,
    p.pension_income_share,
    p.cash_income_share,
    p.total_days_overdrawn > 0                                             as ever_overdrawn,
    p.total_days_overdrawn,
    p.days_overdrawn_last_6_months,
    p.last_month_avg_balance / nullif(p.peak_avg_balance_last_12_months, 0) as balance_vs_12m_peak,

    -- ── Who / where ──────────────────────────────────────────────────────
    a.owner_age_years,
    a.owner_gender,
    a.branch_region,
    a.has_card,
    a.best_card_type,
    a.has_loan,
    a.loan_status,
    a.loan_monthly_payment,
    a.loan_end_date,

    -- ── Flags (thresholds in marts.config_thresholds) ────────────────────
    coalesce(p.income_volatility_cv > t.volatile_cv, false)                as is_volatile_income,
    p.pension_income_share > t.pensioner_share                             as is_pensioner,
    p.total_days_overdrawn > 0                                             as has_overdraft_history,
    coalesce(p.last_month_avg_balance / nullif(p.peak_avg_balance_last_12_months, 0) < t.slide_ratio, false)
                                                                           as is_balance_sliding,
    coalesce(a.loan_status = 'D', false)                                   as has_loan_in_debt,
    p.months_of_history < t.short_months                                   as has_short_history,
    p.last_month < '{{LAST_DATA_MONTH}}'                                   as is_stale_account,
    p.buffer <= 0                                                          as has_negative_buffer,
    p.typical_income = 0                                                   as has_zero_income
from per_account p
join marts.dim_account a using (account_id)
cross join t;

comment on table marts.mart_customer_profile is 'One row per account: the judges'' numbers (I, F, S, H, B, P), our context numbers, risk features and flags. The engine reads only this table.';
comment on column marts.mart_customer_profile.account_id is 'Bank account ID.';
comment on column marts.mart_customer_profile.typical_income is 'JUDGE I — typical monthly money in = median of money_in over all months (quiet months included). CAD/month.';
comment on column marts.mart_customer_profile.typical_fixed_costs is 'JUDGE F — typical fixed costs = median of (household_bills + insurance + loan_payments). Shown only, not used in runway. CAD/month.';
comment on column marts.mart_customer_profile.typical_spending is 'JUDGE S — typical monthly spending = median of money_out. CAD/month.';
comment on column marts.mart_customer_profile.typical_household_bills is 'JUDGE H — typical household bills = median of household_bills. Rent / utility shocks scale this. CAD/month.';
comment on column marts.mart_customer_profile.buffer is 'JUDGE B — savings buffer = mean of avg_daily_balance over the account''s last 6 months. CAD.';
comment on column marts.mart_customer_profile.running_loan_payment is 'JUDGE P — loan monthly payment if the loan is still running at end of 2025 (status C or D), else 0. CAD/month.';
comment on column marts.mart_customer_profile.typical_discretionary_spending is 'OURS (D) — median of cash withdrawals + card withdrawals + unlabelled transfers out: the spending a customer could cut. CAD/month.';
comment on column marts.mart_customer_profile.lean_month_income_p25 is 'OURS — income in a lean month = 25th percentile of the account''s own monthly money_in. Used by the stress runway. CAD/month.';
comment on column marts.mart_customer_profile.typical_monthly_surplus is 'typical_income - typical_spending. Positive = saves money in a typical month. CAD/month.';
comment on column marts.mart_customer_profile.buffer_months_of_spending is 'buffer / typical_spending: how many typical months of spending the buffer covers. NULL if spending is 0.';
comment on column marts.mart_customer_profile.months_of_history is 'Number of months of data for the account (12-72).';
comment on column marts.mart_customer_profile.first_month is 'First month with data, YYYY-MM.';
comment on column marts.mart_customer_profile.last_month is 'Last month with data, YYYY-MM.';
comment on column marts.mart_customer_profile.income_volatility_cv is 'How unsteady income is: standard deviation / mean of monthly money_in. 0 = same every month. NULL if income is always 0.';
comment on column marts.mart_customer_profile.lean_month_share is 'Share of months where money_in was below 55% of the typical income (0-1).';
comment on column marts.mart_customer_profile.pension_income_share is 'Share of all money in that came from pensions (0-1).';
comment on column marts.mart_customer_profile.cash_income_share is 'Share of all money in that came as cash deposits (0-1).';
comment on column marts.mart_customer_profile.ever_overdrawn is 'True if any day in the history ended below zero.';
comment on column marts.mart_customer_profile.total_days_overdrawn is 'Total days in the history that ended below zero.';
comment on column marts.mart_customer_profile.days_overdrawn_last_6_months is 'Days below zero in the last 6 months.';
comment on column marts.mart_customer_profile.balance_vs_12m_peak is 'Last month''s average balance divided by the highest monthly average balance in the last 12 months (1 = at its peak, 0.3 = down 70%).';
comment on column marts.mart_customer_profile.owner_age_years is 'Owner age in whole years on 2025-12-31.';
comment on column marts.mart_customer_profile.owner_gender is 'Owner gender (M / F).';
comment on column marts.mart_customer_profile.branch_region is 'Region of the branch.';
comment on column marts.mart_customer_profile.has_card is 'True if anyone on the account holds a card.';
comment on column marts.mart_customer_profile.best_card_type is 'gold > classic > junior, or none.';
comment on column marts.mart_customer_profile.has_loan is 'True if the account ever took a loan.';
comment on column marts.mart_customer_profile.loan_status is 'A repaid, B defaulted, C running OK, D running in debt; NULL if no loan.';
comment on column marts.mart_customer_profile.loan_monthly_payment is 'Loan monthly payment whatever the status, CAD. NULL if no loan.';
comment on column marts.mart_customer_profile.loan_end_date is 'Date the loan ends (start + duration). NULL if no loan.';
comment on column marts.mart_customer_profile.is_volatile_income is 'FLAG — income_volatility_cv above the volatile_income_cv threshold (0.45, top quartile).';
comment on column marts.mart_customer_profile.is_pensioner is 'FLAG — more than 30% of income from pensions. A job-loss / EI shock may not apply.';
comment on column marts.mart_customer_profile.has_overdraft_history is 'FLAG — has been below zero at least once.';
comment on column marts.mart_customer_profile.is_balance_sliding is 'FLAG — balance_vs_12m_peak below 0.50: savings are draining.';
comment on column marts.mart_customer_profile.has_loan_in_debt is 'FLAG — loan status D (running, client in debt).';
comment on column marts.mart_customer_profile.has_short_history is 'FLAG — fewer than 18 months of data; medians are less reliable.';
comment on column marts.mart_customer_profile.is_stale_account is 'FLAG — data ends before 2025-12, so the buffer is older than the others.';
comment on column marts.mart_customer_profile.has_negative_buffer is 'FLAG — buffer is 0 or below: runway is 0 under any shock.';
comment on column marts.mart_customer_profile.has_zero_income is 'FLAG — typical income is 0 (dormant or irregular account).';
