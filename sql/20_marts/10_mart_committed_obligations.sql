-- marts.mart_committed_obligations — money already promised away every month by standing orders.
-- standing_orders.csv is an undated end-of-data snapshot, so this is "what is committed today".
-- Grain: one row per account_id (4,500 rows; accounts with no standing orders have zeros).
create or replace table marts.mart_committed_obligations as
with so as (
    select
        account_id,
        sum(monthly_amount) filter (where purpose = 'household bills') as standing_order_household_bills,
        sum(monthly_amount) filter (where purpose = 'insurance')       as standing_order_insurance,
        sum(monthly_amount) filter (where purpose = 'leasing')         as standing_order_leasing,
        sum(monthly_amount) filter (where purpose = 'loan payment')    as standing_order_loan_payment,
        sum(monthly_amount) filter (where purpose = 'other')           as standing_order_other,
        count(*)                                                       as n_standing_orders
    from staging.stg_standing_orders
    group by account_id
)
select
    p.account_id,
    p.typical_income,
    coalesce(so.n_standing_orders, 0)                 as n_standing_orders,
    coalesce(so.standing_order_household_bills, 0)    as standing_order_household_bills,
    coalesce(so.standing_order_insurance, 0)          as standing_order_insurance,
    coalesce(so.standing_order_leasing, 0)            as standing_order_leasing,
    coalesce(so.standing_order_loan_payment, 0)       as standing_order_loan_payment,
    coalesce(so.standing_order_other, 0)              as standing_order_other,
    coalesce(so.standing_order_household_bills, 0) + coalesce(so.standing_order_insurance, 0)
      + coalesce(so.standing_order_leasing, 0) + coalesce(so.standing_order_loan_payment, 0)
                                                      as committed_monthly_obligations,
    (coalesce(so.standing_order_household_bills, 0) + coalesce(so.standing_order_insurance, 0)
      + coalesce(so.standing_order_leasing, 0) + coalesce(so.standing_order_loan_payment, 0))
      / nullif(p.typical_income, 0)                   as committed_share_of_income
from marts.mart_customer_profile p
left join so using (account_id);

comment on table marts.mart_committed_obligations is 'Monthly amounts each account has committed through standing orders, by purpose, and as a share of typical income.';
comment on column marts.mart_committed_obligations.account_id is 'Bank account ID.';
comment on column marts.mart_committed_obligations.typical_income is 'JUDGE I — median money_in, CAD/month.';
comment on column marts.mart_committed_obligations.n_standing_orders is 'Number of standing orders on the account.';
comment on column marts.mart_committed_obligations.standing_order_household_bills is 'Standing orders for household bills, CAD/month.';
comment on column marts.mart_committed_obligations.standing_order_insurance is 'Standing orders for insurance, CAD/month.';
comment on column marts.mart_committed_obligations.standing_order_leasing is 'Standing orders for leasing, CAD/month.';
comment on column marts.mart_committed_obligations.standing_order_loan_payment is 'Standing orders for loan payments, CAD/month.';
comment on column marts.mart_committed_obligations.standing_order_other is 'Standing orders with no stated purpose, CAD/month (not counted as committed).';
comment on column marts.mart_committed_obligations.committed_monthly_obligations is 'Household bills + insurance + leasing + loan standing orders, CAD/month.';
comment on column marts.mart_committed_obligations.committed_share_of_income is 'committed_monthly_obligations / typical_income. 0.4 = 40% of a typical month is already spoken for. NULL if income is 0.';
