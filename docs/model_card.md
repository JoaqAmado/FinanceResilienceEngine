# Model card: Twin Runway engine

## At a glance

- **Data:** the PKDD'99 Czech bank dataset (CTU Prague), provided by Tangerine, re-dated to 2020–2025 and in CAD.
- **Label:** the early-warning backtest scores a first overdraft (any day below zero), a stand-in for financial
  stress. It is not loan default, and no output is a probability.
- **Time-based split:** every score uses only data up to the 2024-12 snapshot; the outcome is the year after.
- **Base rate:** 75 of 3,847 accounts (1.9%) first went overdrawn in 2025.
- **Limits:** few events; Czech bank behaviour from the original data, re-dated; loan labels are built from
  overdraft; money in is all inflows, not wages.

## What it is

A deterministic calculator, not a trained model. For any account it answers: **how many months does this customer
last after a shock, and what should they do?** The judges' runway comes first, computed exactly as the track brief
defines it ([method](method.md)). Labelled reality checks sit beside it, then a goal plan and a backup plan built
from the customer's own numbers. No LLM computes a number.

## Intended use

- Run a live twist for one account: job loss on EI, bills up, a one-off cost, or a mix, with the size of the shock
  set by the user.
- Show the reality checks next to the judges' number, so the gap between the formula and a real household is
  visible and labelled.
- Size an emergency-fund goal and a minimum-pain backup ladder from the account's own numbers.
- Read the portfolio: who can't last 6 months on the judges' formula, and what sets them apart
  ([findings](findings.md)).

## Out of scope

- **Not a credit decision and not a default model.** The engine gives no probabilities and no credit scores.
- **The overdraft-before-loan figure is a red flag, not evidence.** It is built into how this dataset labels loans:
  the CTU repository notes that `if min(trans.balance) >= 0 then good else bad` separates good loans from bad
  perfectly. It is shown on the customer card as a flag.
- **The early-warning light is a watch flag, not a credit score.** It never changes the judges' runway.
- **The 2026 EI cap view is a stress test, not a forecast** of anyone's EI benefit (see the limits below).

## Data

- **Source:** the track's `data/` folder, the PKDD'99 Discovery Challenge Financial dataset (CTU Prague), provided
  by Tangerine for the track. Columns: [data dictionary](data_dictionary.md).
- **Provenance:** PKDD'99 Czech bank data, re-dated to 2020–2025 and expressed in CAD. That's why the EI-cap view
  is a stress test, not a forecast.

## Data and limits

- **Checks:** the monthly components add up exactly to money in and money out, on all 185,326 rows.
- **What the columns hold:** "money in" is all inflows (74.9% cash deposits), and 76.4% of spending is cash
  withdrawals of unknown purpose, so the plans call it *non-fixed*, not *discretionary*.
- **Edge cases are flagged on the customer card, not hidden:**
  - negative buffer (23 accounts)
  - zero median money in (14)
  - zero median spending (77)
  - no recorded household bills (1,225)
  - accounts that stop before Dec 2025 (76)

## Evaluation

- **The judges' numbers:** the SQL in `sql/` reproduces I, F, S, H, B, P and the EI 55% runway on every account,
  in DuckDB offline and in Snowflake when configured (`tests/test_warehouse.py`, [warehouse](warehouse.md)).
- **The findings:** each figure is recomputed by `tests/test_docs.py` ([findings](findings.md)).
- **The early-warning light:** the backtest tier table is `artifacts/early_warning_tiers.csv`, recomputed by
  `python -m resilience.warning` and pinned by `tests/test_warning.py`.
- **The web app:** its TypeScript engine must match the Python engine exactly ([web/README.md](../web/README.md)).

## Wording

- **Money in**, for `money_in`: it is all inflows, not wages.
- **Non-fixed** spending, not *discretionary*: most of it is cash of unknown purpose.
- **High money-in** for the accounts at the top of the money-in bands.
- Flags are flags, not models, and no output is stated as a probability.
