-- money_out must equal the sum of its seven parts (to the cent).
select account_id, month, money_out
from staging.stg_monthly_summary
where abs(money_out - (household_bills + insurance + loan_payments + bank_fees
                       + cash_withdrawals_genuine + card_withdrawals + transfers_out_other)) > 0.01;
