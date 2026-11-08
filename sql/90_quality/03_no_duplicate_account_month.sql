-- Exactly one row per (account_id, month).
select account_id, month, count(*) as n
from staging.stg_monthly_summary
group by all having count(*) > 1;
