-- Raw tables have the row counts stated in the official brief.
select * from (
    select 'monthly_summary' as t, (select count(*) from raw.monthly_summary) as n, 185326 as expected union all
    select 'transactions',    (select count(*) from raw.transactions),    1056320 union all
    select 'accounts',        (select count(*) from raw.accounts),        4500 union all
    select 'clients',         (select count(*) from raw.clients),         5369 union all
    select 'dispositions',    (select count(*) from raw.dispositions),    5369 union all
    select 'cards',           (select count(*) from raw.cards),           892 union all
    select 'loans',           (select count(*) from raw.loans),           682 union all
    select 'standing_orders', (select count(*) from raw.standing_orders), 6471 union all
    select 'districts',       (select count(*) from raw.districts),       77
) where n <> expected;
