# FinanceResilienceEngine: Twin Runway

Sheridan Datathon 2026 · Tangerine track "Resilience Rewired".

For any of Tangerine's 4,500 accounts: **how many months does this customer last after a shock, and what should they do?**
The judges' runway comes first, computed exactly as the track brief defines it. Labelled reality checks sit beside it.

## Findings (every number is pinned by `tests/`)

| | |
|---|---|
| Can't last 6 months on EI at 55% (judges' formula) | **1,578 of 4,500 (35.1%)** |
| **The more money comes in, the thinner the cushion:** fail rate by monthly money in | 4.8% under $2.5k → 75.6% over $20k. Buffers: 8.9 → 1.6 months of spending |
| …stress test with the real 2026 EI maximum ($729/week ≈ $3,159/month) | 2,304 (51.2%) |
| **A typical month isn't a typical half-year:** "safe" on the formula, but under 6 months on the account's own half-year spending | 783 of 2,922 (560, or 1 in 5, with the same window on income too). Spending peaks in January and June |
| Failing customers who get back to 6 months by cutting a quarter of spending or less | 3 in 4 (1,192 of 1,555 with a positive buffer); only 121 can't cut their way there |
| Overdrawn before the loan → defaulted | 27 of 27 in this data (none of the 606 repaying borrowers ever went negative), so it's shown as a flag, not a model |

## Data and limits

- **Checks:** the monthly components add up exactly to money in and money out, on all 185,326 rows.
- **Provenance:** PKDD'99 Czech bank data, re-dated to 2020–2025 and expressed in CAD. That's why the EI-cap view is a stress test, not a forecast.
- **What the columns hold:** "money in" is all inflows (74.9% cash deposits), and 76.4% of spending is cash withdrawals of unknown purpose, so the plans call it *non-fixed*, not *discretionary*.
- **Edge cases are flagged on the customer card, not hidden:**
  - negative buffer (23 accounts)
  - zero median income (14)
  - zero median spending (77)
  - no recorded household bills (1,225)
  - accounts that stop before Dec 2025 (76)

## App: Twin Runway

```bash
.venv/bin/streamlit run app.py
```

- **Live twist tab:** type any `account_id` or click a rehearsal account, pick a twist card or set the sliders.
  The judges' number shows first, then reality checks (2026 EI cap, waiting week, pension kept, half-year
  spending, bills by standing order), then a job-loss-proof goal and a minimum-pain backup ladder. Runs offline.
- **Portfolio tab:** the four findings, computed by the same engine.

## Engine (`resilience/`)

Deterministic core: every number comes from `data/` using the judges' definitions
(I, F, S, B, H, P and the runway formula from the track brief). No LLM in the core.

```bash
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest -q                      # unit + real-data checks
.venv/bin/python -m resilience 20143               # baseline + the 3 README twists
.venv/bin/python -m resilience 20143 --income 0.55 --bills 0.15 --one-off-x-s 1 --target 6
.venv/bin/python -m resilience 98952 --income 0.55 --pension-aware --cap --waiting-week
.venv/bin/python -m resilience.portfolio               # chart tables -> artifacts/*.csv
```

The judges' number always comes first. Reality checks sit next to it, each a labelled option on `Shock`:
2026 EI cap ($729/week, canada.ca), the one-week EI waiting period, pension-aware job loss,
typical half-year spending (`S6`), a month-by-month path that starts in January, and household
bills paid by standing order. Plans: an EI-proof emergency-fund goal (`goal_plan(..., target_kind="ei_proof")`)
and a minimum-pain backup ladder (`backup_ladder`: fees, non-fixed spending -10%/-25%, pause other
standing orders, defer the running loan, -50%, else credit).

```python
from resilience import build_metrics, apply_shock, backup_ladder, goal_plan, Shock, LAID_OFF_EI
m = build_metrics()                                         # one row per account_id
apply_shock(m.loc[20143], Shock(income_multiplier=0.55))    # RunwayResult(months=2.2, ...)
```

## Snowflake

The judges' numbers also exist as plain SQL in `warehouse/sql/`: `JUDGE_METRICS` (I, F, S, H, B, P per account),
`EI55_RUNWAY` and `PORTFOLIO_SUMMARY`. The same files run unchanged in Snowflake and, offline, in DuckDB.
The Python engine stays the source of every number in the app; the warehouse is a check on it.

```bash
.venv/bin/python -m resilience.warehouse local-parity   # DuckDB over data/*.csv, no account needed
.venv/bin/python -m resilience.warehouse load           # upload 8 tables (not transactions) and create the views
.venv/bin/python -m resilience.warehouse verify         # Snowflake vs the engine on all 4,500 accounts, counts only
```

`local-parity` matches the engine on all 4,500 accounts and gives the same 1,578 under 6 months (`tests/test_warehouse.py`).
`load` creates the database and schema if they are missing and replaces the tables; add `--with-transactions` for
the 100 MB transactions file. Credentials come from the environment or `.env`, which is gitignored:
`SNOWFLAKE_ACCOUNT`, `SNOWFLAKE_USER`, `SNOWFLAKE_PASSWORD`, and optionally `SNOWFLAKE_WAREHOUSE` (default `COMPUTE_WH`),
`SNOWFLAKE_DATABASE` (`TANGERINE`), `SNOWFLAKE_SCHEMA` (`PUBLIC`) and `SNOWFLAKE_ROLE`. With them set, the app's
Method tab shows the `verify` result under "Computed in Snowflake". Without them, the app never touches the network.

## Sources
- PKDD'99 Discovery Challenge Financial dataset, CTU Prague Relational Dataset Repository: https://relational.fel.cvut.cz/dataset/Financial (provided by Tangerine for the track)
- Government of Canada, EI benefit amount (55%, $729/week maximum in 2026): https://www.canada.ca/en/services/benefits/ei/ei-regular-benefit/benefit-amount.html
