-- money_in must equal cash_deposits + transfers_in + pension_in + interest_in (to the cent).
select account_id, month, money_in, cash_deposits + transfers_in + pension_in + interest_in as parts
from staging.stg_monthly_summary
where abs(money_in - (cash_deposits + transfers_in + pension_in + interest_in)) > 0.01;
