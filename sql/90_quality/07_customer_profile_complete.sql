-- mart_customer_profile has exactly 4,500 rows and no NULL judge numbers.
select 'row count is ' || count(*) as problem from marts.mart_customer_profile having count(*) <> 4500
union all
select 'NULL judge number for account ' || account_id
from marts.mart_customer_profile
where typical_income is null or typical_spending is null or typical_fixed_costs is null
   or typical_household_bills is null or buffer is null or running_loan_payment is null;
