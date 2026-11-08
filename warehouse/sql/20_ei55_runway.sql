-- EI55_RUNWAY: the runway from the track brief under its first twist, laid off with EI paying 55% of usual income.
--   income_after   = 0.55 * I
--   spending_after = S            (no bills change, no one-off cost)
--   buffer_left    = B            (B minus a one-off of 0)
--   gap            = spending_after - income_after
--   buffer_left <= 0  ->  0 months
--   gap <= 0          ->  no shortfall (120+): RUNWAY_MONTHS is NULL and NO_SHORTFALL is TRUE
--   otherwise         ->  ROUND(LEAST(buffer_left / gap, 120), 1)
-- NULLIF only guards the division: some engines evaluate a CASE branch they do not return.
--
-- Unavoidable difference: SQL ROUND sends a tie (a ratio whose x10 ends in .5) away from zero, while
-- the Python engine (numpy) rounds a tie to even. tests/test_warehouse.py pins that no account comes
-- within 1e-9 of a tie under this twist, so every rounding rule gives the same 1-decimal runway here,
-- and `verify` compares the runway of every account, so a flip would show.
--
-- PORTFOLIO_SUMMARY: one row of counts over all accounts. UNDER_6_MONTHS counts runway < 6
-- (a runway of 0 included, no shortfall excluded), the same test that gives the engine 1,578 of 4,500.

CREATE OR REPLACE VIEW EI55_RUNWAY AS
WITH twist AS (
    SELECT ACCOUNT_ID,
           0.55 * I AS INCOME_AFTER,
           S AS SPENDING_AFTER,
           B AS BUFFER_LEFT,
           S - 0.55 * I AS GAP
    FROM JUDGE_METRICS
)
SELECT ACCOUNT_ID,
       INCOME_AFTER,
       SPENDING_AFTER,
       BUFFER_LEFT,
       GAP,
       CASE WHEN BUFFER_LEFT > 0 AND GAP <= 0 THEN TRUE ELSE FALSE END AS NO_SHORTFALL,
       CASE WHEN BUFFER_LEFT <= 0 THEN CAST(0 AS DOUBLE)
            WHEN GAP <= 0 THEN NULL
            ELSE ROUND(LEAST(BUFFER_LEFT / NULLIF(GAP, 0), CAST(120 AS DOUBLE)), 1)
       END AS RUNWAY_MONTHS
FROM twist;

CREATE OR REPLACE VIEW PORTFOLIO_SUMMARY AS
SELECT CAST(COUNT(*) AS BIGINT) AS ACCOUNTS,
       CAST(SUM(CASE WHEN BUFFER_LEFT <= 0 THEN 1 ELSE 0 END) AS BIGINT) AS BUFFER_GONE,
       CAST(SUM(CASE WHEN RUNWAY_MONTHS < 6 THEN 1 ELSE 0 END) AS BIGINT) AS UNDER_6_MONTHS,
       ROUND(100.0 * SUM(CASE WHEN RUNWAY_MONTHS < 6 THEN 1 ELSE 0 END) / COUNT(*), 1) AS UNDER_6_MONTHS_PCT,
       CAST(SUM(CASE WHEN NO_SHORTFALL THEN 1 ELSE 0 END) AS BIGINT) AS NO_SHORTFALL_ACCOUNTS
FROM EI55_RUNWAY;
