-- marts.judge_runway(...) — the judges' runway formula from Tangerine/README.md, written once.
--
--   buffer_left = buffer - one_off_cost
--   gap         = spending_after_shock - income_after_shock
--   buffer_left <= 0 -> 0
--   gap <= 0         -> NULL   (means "no shortfall (120+)")
--   otherwise        -> min(buffer_left / gap, 120), rounded to 1 decimal
--
-- marts.judge_runway_or_cap(...) is the same, but returns 120 instead of NULL so it can be
-- averaged, ranked or bucketed in statistics.
create schema if not exists marts;

create or replace macro marts.judge_runway(buffer, income_after_shock, spending_after_shock, one_off_cost) as
    case
        when buffer - one_off_cost <= 0 then 0.0
        when spending_after_shock - income_after_shock <= 0 then null
        else round(least((buffer - one_off_cost) / (spending_after_shock - income_after_shock), 120.0), 1)
    end;

create or replace macro marts.judge_runway_or_cap(buffer, income_after_shock, spending_after_shock, one_off_cost) as
    coalesce(marts.judge_runway(buffer, income_after_shock, spending_after_shock, one_off_cost), 120.0);
