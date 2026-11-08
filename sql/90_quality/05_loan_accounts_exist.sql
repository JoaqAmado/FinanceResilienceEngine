-- Every loan belongs to a known account, and no account has two loans.
select l.account_id, 'unknown account' as problem
from staging.stg_loans l
where not exists (select 1 from staging.stg_accounts a where a.account_id = l.account_id)
union all
select account_id, 'more than one loan' from staging.stg_loans group by account_id having count(*) > 1;
