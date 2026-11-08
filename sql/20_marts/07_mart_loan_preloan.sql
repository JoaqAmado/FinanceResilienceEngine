-- marts.mart_loan_preloan — what the bank could see BEFORE it granted each loan.
-- Every feature uses only months strictly before the loan-start month, so there is no leakage
-- from the loan's own outcome (status D = "currently in debt" would otherwise show in the balances).
-- This is the table used for every default analysis.
-- Grain: one row per loan_id (682 rows, 76 defaults).
create or replace table marts.mart_loan_preloan as
with pre as (
    select
        m.*,
        row_number() over (partition by m.account_id order by m.month desc) as months_before_loan
    from marts.fact_account_month m
    join staging.stg_loans l using (account_id)
    where m.month < l.loan_start_month
),
agg as (
    select
        account_id,
        count(*)                                              as pre_loan_months,
        median(money_in)                                      as pre_loan_typical_income,
        median(money_out)                                     as pre_loan_typical_spending,
        quantile_cont(money_in, 0.25)                         as pre_loan_lean_month_income_p25,
        avg(avg_daily_balance)                                as pre_loan_avg_balance,
        avg(avg_daily_balance) filter (where months_before_loan <= 6) as pre_loan_buffer_last_6_months,
        min(min_balance)                                      as pre_loan_lowest_balance,
        sum(days_below_zero)::integer                         as pre_loan_days_overdrawn,
        stddev_samp(money_in) / nullif(avg(money_in), 0)      as pre_loan_income_cv
    from pre
    group by account_id
)
select
    l.loan_id,
    l.account_id,
    l.loan_start_month,
    l.loan_status,
    l.is_defaulted,
    l.monthly_payment,
    l.loan_amount,
    l.duration_months,
    a.pre_loan_months,
    a.pre_loan_typical_income,
    a.pre_loan_typical_spending,
    a.pre_loan_lean_month_income_p25,
    a.pre_loan_avg_balance,
    a.pre_loan_buffer_last_6_months,
    a.pre_loan_lowest_balance,
    a.pre_loan_days_overdrawn,
    a.pre_loan_days_overdrawn > 0                                   as pre_loan_was_overdrawn,
    a.pre_loan_income_cv,
    l.monthly_payment / nullif(a.pre_loan_typical_income, 0)       as payment_to_income,
    a.pre_loan_avg_balance / nullif(a.pre_loan_typical_spending, 0) as buffer_months,
    -- Judge runway formula on pre-loan data, with the new loan payment added to spending
    -- (the question the bank faced: can they carry this payment?). 120 = no shortfall / capped.
    marts.judge_runway_or_cap(a.pre_loan_buffer_last_6_months, a.pre_loan_typical_income,
                              a.pre_loan_typical_spending + l.monthly_payment, 0)          as judge_runway_with_loan,
    marts.judge_runway_or_cap(a.pre_loan_buffer_last_6_months, 0.55 * a.pre_loan_typical_income,
                              a.pre_loan_typical_spending + l.monthly_payment, 0)          as judge_ei55_runway_with_loan,
    marts.judge_runway_or_cap(a.pre_loan_buffer_last_6_months, a.pre_loan_lean_month_income_p25,
                              a.pre_loan_typical_spending + l.monthly_payment, 0)          as stress_runway_with_loan
from staging.stg_loans l
join agg a using (account_id);

comment on table marts.mart_loan_preloan is 'One row per loan, with features computed ONLY from the months before the loan was granted (leakage-free). Used for all default analysis.';
comment on column marts.mart_loan_preloan.loan_id is 'Loan ID.';
comment on column marts.mart_loan_preloan.account_id is 'Account that took the loan.';
comment on column marts.mart_loan_preloan.loan_start_month is 'Month the loan was granted, YYYY-MM. Features use months strictly before this.';
comment on column marts.mart_loan_preloan.loan_status is 'A repaid, B defaulted, C running OK, D running in debt.';
comment on column marts.mart_loan_preloan.is_defaulted is 'Outcome: True if status B or D.';
comment on column marts.mart_loan_preloan.monthly_payment is 'Loan monthly payment, CAD.';
comment on column marts.mart_loan_preloan.loan_amount is 'Loan size, CAD.';
comment on column marts.mart_loan_preloan.duration_months is 'Loan length in months.';
comment on column marts.mart_loan_preloan.pre_loan_months is 'Months of history before the loan (3-23).';
comment on column marts.mart_loan_preloan.pre_loan_typical_income is 'Median money_in before the loan, CAD/month.';
comment on column marts.mart_loan_preloan.pre_loan_typical_spending is 'Median money_out before the loan, CAD/month.';
comment on column marts.mart_loan_preloan.pre_loan_lean_month_income_p25 is '25th-percentile money_in before the loan (a lean month), CAD/month.';
comment on column marts.mart_loan_preloan.pre_loan_avg_balance is 'Mean avg_daily_balance over all months before the loan, CAD.';
comment on column marts.mart_loan_preloan.pre_loan_buffer_last_6_months is 'Judge-style buffer before the loan: mean avg_daily_balance over the last 6 pre-loan months, CAD.';
comment on column marts.mart_loan_preloan.pre_loan_lowest_balance is 'Lowest end-of-day balance before the loan, CAD.';
comment on column marts.mart_loan_preloan.pre_loan_days_overdrawn is 'Days below zero before the loan.';
comment on column marts.mart_loan_preloan.pre_loan_was_overdrawn is 'True if the account went below zero at least once before the loan.';
comment on column marts.mart_loan_preloan.pre_loan_income_cv is 'Income volatility before the loan: std / mean of monthly money_in.';
comment on column marts.mart_loan_preloan.payment_to_income is 'Loan payment / pre-loan typical income. 0.2 = the payment eats 20% of a typical month.';
comment on column marts.mart_loan_preloan.buffer_months is 'Pre-loan average balance / pre-loan typical spending: months of spending the savings covered.';
comment on column marts.mart_loan_preloan.judge_runway_with_loan is 'Judge runway formula on pre-loan data with the loan payment added to spending. 120 = no shortfall.';
comment on column marts.mart_loan_preloan.judge_ei55_runway_with_loan is 'Same, with income = 0.55 x pre-loan typical income (job loss with EI).';
comment on column marts.mart_loan_preloan.stress_runway_with_loan is 'OURS — same formula with income = pre-loan lean month (25th percentile). Lower = riskier.';
