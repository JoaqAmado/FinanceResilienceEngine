# Method

The engine (`resilience/`) is deterministic: every number comes from `data/` using the judges' definitions
(I, F, S, B, H, P and the runway formula from the track brief). No LLM in the core. The optional story rewording
(`resilience/llm.py`) only rephrases numbers the engine already computed, and is rejected if it adds one.
Figures quoted from the data are on the [findings](findings.md) page; this page holds definitions only.

## The judges' numbers

Per account, from `monthly_summary.csv`:

| | Definition |
|---|---|
| I | typical monthly money in = median(`money_in`) |
| F | typical fixed costs = median(`household_bills + insurance + loan_payments`), shown but not used in the runway |
| S | typical monthly spending = median(`money_out`) |
| B | buffer = mean(`avg_daily_balance`) over the account's last 6 rows by month |
| H | household bills = median(`household_bills`) |
| P | loan payment = `loans.monthly_payment` if the loan is still running at the end of 2025 (status C or D), else 0 |

## Runway

```
buffer_left = B - one_off_costs
gap         = spending_after_shock - income_after_shock
buffer_left <= 0 -> 0
gap <= 0         -> "no shortfall (120+)"
else             -> min(buffer_left / gap, 120), rounded to 1 decimal
```

The track's example twists, as `Shock` presets in `resilience/core.py`:

- `LAID_OFF_EI`: laid off, EI at 55%, so income = 0.55 × I.
- `FURNACE`: a one-off repair of 1 month of typical spending, so one-off = 1 × S.
- `DOUBLE_WHAMMY`: job loss on EI at 55% and household bills +15%, so spending = S + 0.15 × H.

## Reality checks

The judges' number always comes first. Reality checks sit next to it, each a labelled option on `Shock`. They are
off by default, so the defaults reproduce the judges' answers.

| `Shock` option | Reality check |
|---|---|
| `income_cap_monthly` | the 2026 EI cap ($729/week, canada.ca) on the EI part of income |
| `waiting_week` | the one-week EI waiting period: one week of EI becomes a one-off cost |
| `pension_aware` | a job loss doesn't cut pension income (`Pn` is kept in full) |
| `spending_basis="S6"` | typical half-year spending (`S6`) instead of the median month |
| `bills_fallback` | household bills paid by standing order: max(H, `H_SO`) when H misses them |
| `job_loss` | the income drop is a layoff on EI, which turns the EI checks on. A pay cut or reduced hours is not a job loss |

`calendar_path` adds a month-by-month path that starts in January: each month costs that account's median
spending for that calendar month.

## Plans

- **Goal:** an EI-proof emergency-fund goal, `goal_plan(..., target_kind="ei_proof")`. The target is the buffer
  that passes the twist, and "already there" means exactly that the judges' rounded runway passes.
- **Backup:** a minimum-pain ladder, `backup_ladder`. It stops at the first cumulative step that reaches the target:
  fees, non-fixed spending -10%/-25%, pause other standing orders, defer the running loan, -50%, else credit.

## Early-warning light

Four transparent rules, 0 to 4 points, shown beside the judges' runway (`resilience/warning.py`). It is a watch
flag, not a credit score, and it never changes the judges' runway. The rules read each account's last 6 rows after
its opening month. A month of spending here is the median money out over those rows.

| Rule | Fires when |
|---|---|
| lowest balance under half a month of spending | lowest balance < 0.5 months of spending |
| almost all spending is cash | cash > 95% of spending |
| irregular money in | money in: std ÷ mean > 0.5 |
| balance sliding more than 10% of a month's spending per month | balance trend < -0.10 months of spending per month |

Each tier's evidence is a backtest: the rules taken at 2024-12, and the outcome is any day below zero in 2025.
`python -m resilience.warning` writes the tier table to `artifacts/early_warning_tiers.csv`.

## Command line

```bash
.venv/bin/python -m resilience 20143               # baseline + the 3 example twists
.venv/bin/python -m resilience 20143 --income 0.55 --bills 0.15 --one-off-x-s 1 --target 6
.venv/bin/python -m resilience 98952 --income 0.55 --pension-aware --cap --waiting-week
.venv/bin/python -m resilience.portfolio           # chart tables -> artifacts/*.csv
.venv/bin/python -m resilience.warning             # early-warning tiers -> artifacts/early_warning_tiers.csv
```

Use fractions (`--income 0.55`), not percentages. `--income-cap` is a reality check and needs a job loss.

## Python

```python
from resilience import build_metrics, apply_shock, backup_ladder, goal_plan, Shock, LAID_OFF_EI
m = build_metrics()                                         # one row per account_id
apply_shock(m.loc[20143], Shock(income_multiplier=0.55))    # RunwayResult(months=2.2, ...)
```

## The apps

- **Streamlit** (`app.py`, `.venv/bin/streamlit run app.py`):
  - **Live twist tab:** type any `account_id` or click a rehearsal account, pick a twist card or set the sliders.
    The judges' number shows first, then reality checks (2026 EI cap, waiting week, pension kept, half-year
    spending, bills by standing order), then a job-loss-proof goal and a minimum-pain backup ladder. Runs offline.
  - **Portfolio tab:** the findings, computed by the same engine.
- **Web** (`web/`): the same engine ported to TypeScript, checked against the Python engine. See
  [web/README.md](../web/README.md).
