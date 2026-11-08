-- Every account has monthly_summary rows.
select a.account_id
from staging.stg_accounts a
where not exists (select 1 from staging.stg_monthly_summary m where m.account_id = a.account_id);
