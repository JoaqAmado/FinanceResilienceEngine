-- Exactly one owner per account.
select a.account_id, count(o.account_id) as owners
from staging.stg_accounts a
left join staging.stg_dispositions o on o.account_id = a.account_id and o.role = 'owner'
group by a.account_id having count(o.account_id) <> 1;
