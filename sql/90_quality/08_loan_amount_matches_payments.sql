-- loan amount = duration_months x monthly_payment (within $1).
select loan_id, loan_amount, duration_months, monthly_payment
from staging.stg_loans
where abs(loan_amount - duration_months * monthly_payment) >= 1;
