-- JUDGE_METRICS: the numbers the judges use, per account, exactly as the Tangerine track brief defines them.
-- The same file runs unchanged on Snowflake and on DuckDB (python -m resilience.warehouse local-parity).
--
--   I  typical monthly money in   = median(money_in)
--   F  typical fixed costs        = median(household_bills + insurance + loan_payments)
--   S  typical monthly spending   = median(money_out)
--   H  household bills            = median(household_bills)
--   B  buffer                     = mean(avg_daily_balance) over the last 6 rows of the account by month
--   P  loan payment               = loans.monthly_payment if status is C or D (running at the end of 2025), else 0
--
-- Portability rules for every file in warehouse/sql/:
--   * identifiers are unquoted, so Snowflake resolves them to the UPPER-case tables write_pandas
--     creates, and DuckDB matches them case-insensitively
--   * only functions both dialects document: MEDIAN, AVG, ROW_NUMBER() OVER, CAST, COALESCE,
--     NULLIF, LEAST, ROUND, CASE, SUM, COUNT
--   * money, and every constant mixed with it in COALESCE, LEAST or CASE, is cast to DOUBLE, so both
--     engines use IEEE double arithmetic like pandas (a Snowflake NUMBER would otherwise pull the
--     result into fixed-point maths)
--
-- MEDIAN of an even count is the mean of the two middle values in Snowflake, DuckDB and pandas.
-- month is text in YYYY-MM form, so ordering it as text is chronological. One row per account per month.

CREATE OR REPLACE VIEW JUDGE_METRICS AS
WITH ranked AS (
    SELECT account_id,
           CAST(avg_daily_balance AS DOUBLE) AS avg_daily_balance,
           ROW_NUMBER() OVER (PARTITION BY account_id ORDER BY month DESC) AS rn
    FROM monthly_summary
),
buffers AS (
    SELECT account_id, AVG(avg_daily_balance) AS b
    FROM ranked
    WHERE rn <= 6
    GROUP BY account_id
),
medians AS (
    SELECT account_id,
           MEDIAN(CAST(money_in AS DOUBLE)) AS i,
           MEDIAN(CAST(household_bills AS DOUBLE) + CAST(insurance AS DOUBLE)
                  + CAST(loan_payments AS DOUBLE)) AS f,
           MEDIAN(CAST(money_out AS DOUBLE)) AS s,
           MEDIAN(CAST(household_bills AS DOUBLE)) AS h
    FROM monthly_summary
    GROUP BY account_id
),
running_loans AS (
    SELECT account_id, CAST(monthly_payment AS DOUBLE) AS p
    FROM loans
    WHERE status IN ('C', 'D')
)
SELECT med.account_id AS ACCOUNT_ID,
       med.i AS I,
       med.f AS F,
       med.s AS S,
       med.h AS H,
       buf.b AS B,
       COALESCE(rl.p, CAST(0 AS DOUBLE)) AS P
FROM medians med
JOIN buffers buf ON buf.account_id = med.account_id
LEFT JOIN running_loans rl ON rl.account_id = med.account_id;
