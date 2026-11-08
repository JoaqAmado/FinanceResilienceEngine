-- staging.stg_cards — the best card each account holds (gold > classic > junior).
-- Grain: one row per account_id that has at least one card.
create schema if not exists staging;
create or replace table staging.stg_cards as
with cards as (
    select
        d.account_id,
        c.card_type,
        c.issued::date as card_issued_date,
        case c.card_type when 'gold' then 3 when 'classic' then 2 when 'junior' then 1 else 0 end as card_rank
    from raw.cards c
    join staging.stg_dispositions d on d.disposition_id = c.disposition_id
)
select
    account_id,
    arg_max(card_type, card_rank)         as best_card_type,
    arg_max(card_issued_date, card_rank)  as best_card_issued_date,
    count(*)                              as n_cards
from cards
group by account_id;
