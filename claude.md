# CLAUDE.md — Tangerine "Resilience Rewired" (Sheridan Datathon 2026) · EDA

Context file for Claude Code. Covers the **exploratory data analysis (EDA) phase**: what the data is, the exact judge formulas, verified data facts, findings so far, and the EDA work still to do. Read this before writing any analysis code.

---

## 1. Project in one paragraph

Build a **financial resilience engine** on real, anonymized bank data (PKDD'99 Czech bank dataset, money converted to CAD, dates shifted to 2020–2025). For any `account_id` the engine must:
1. **Know the customer** — income, fixed costs, spending, buffer, months of runway.
2. **Take a shock** — job loss + EI, rent/bills increase, surprise repair, or a mix; shock size adjustable.
3. **Make a plan** — a goal plan (e.g. emergency fund) + a backup plan if the shock hits.

**Judging:** Discovery 35% · Data Use 25% · Communication 25% · Impact 15%.
**Demo format (~5 min):** 1 min pitch + biggest finding → 3 min live twist (judge picks an `account_id` and a twist card) → 1 min Q&A.
**Submit on Devpost:** 2–3 min demo video, code repo, short write-up, links to every outside source.

The goal of EDA is (a) reproduce the judges' numbers exactly, and (b) find a **Discovery** — a non-obvious, data-backed insight we can pitch with a clear analogy.

---

## 2. Repo layout

```
Tangerine/                  # (at repo root, NOT data/Tangerine)
  README.md                 # official brief — source of truth
  data/
    monthly_summary.csv     # 185,326 rows — PRIMARY table for all judge metrics
    transactions.csv        # 1,056,320 rows, ~100 MB — only for drill-downs
    accounts.csv  clients.csv  dispositions.csv  cards.csv
    loans.csv  standing_orders.csv  districts.csv
sql/                        # 00_raw → 10_staging → 20_marts (DuckDB), 90_quality checks (must return 0 rows)
src/tangerine/              # config, pipeline, engine, judge_reference (oracle), findings
tests/                      # quality, judge parity (all 4,500 accounts), engine
notebooks/01_eda.ipynb      # narrative EDA; imports from tangerine, no copied logic
reports/                    # findings.md, showcase.md, data_dictionary.md, figures/ (generated)
warehouse/                  # tangerine.duckdb + transactions.parquet (generated, git-ignored)
```
The old `work/` notebooks were replaced by this structure (spec: `project prottotype.md`); see README.md.
Run order: `python -m tangerine.pipeline` → `pytest` → `python -m tangerine.findings` (with `PYTHONPATH=src`).
Column names are descriptive: I = `typical_income`, F = `typical_fixed_costs`, S = `typical_spending`,
H = `typical_household_bills`, B = `buffer`, P = `running_loan_payment` (in `marts.mart_customer_profile`).

Raw files in `Tangerine/data/` are **read-only**. Everything derived goes to `warehouse/` or `reports/`.

---

## 3. Data model

```
districts ──< accounts ──< transactions
                │    ├──< monthly_summary
                │    ├──< standing_orders
                │    └──< loans          (max one loan per account)
                └──< dispositions >── clients
                          └──< cards
```

| File | Rows | Key notes |
|---|--:|---|
| `monthly_summary.csv` | 185,326 | One row per account per month, first→last transaction month, quiet months included. `month` is `YYYY-MM` text |
| `transactions.csv` | 1,056,320 | 2020-01-01 → 2025-12-31. `amount` always positive; use `signed_amount` for direction. Same-day rows are NOT in time order |
| `accounts.csv` | 4,500 | `district_id` = branch, `account_opened` |
| `clients.csv` | 5,369 | `gender`, `birth_date`, home `district_id` |
| `dispositions.csv` | 5,369 | `type` = `owner` or `authorized user`. Join to get the account owner |
| `cards.csv` | 892 | `card_type` junior/classic/gold — joins via `disposition_id` |
| `loans.csv` | 682 | Status A = repaid, B = default (finished), C = running OK, D = running in debt. `defaulted` = B or D |
| `standing_orders.csv` | 6,471 | Undated end-of-data snapshot of recurring payments |
| `districts.csv` | 77 | Original Czech regions; `average_salary` monthly CAD; district 69 missing 2022 unemployment/crime |

**Money columns — all CAD.** In `monthly_summary`:
- `money_in` = `cash_deposits + transfers_in + pension_in + interest_in`
- `money_out` = `household_bills + insurance + loan_payments + bank_fees + cash_withdrawals_genuine + card_withdrawals + transfers_out_other`
- Verified: both identities hold to < 1e-10; no NaNs; no duplicate (account_id, month).

---

## 4. Judge definitions — MUST match exactly

All from `monthly_summary.csv`, per account:

| Symbol | Definition |
|---|---|
| **I** typical money in | `median(money_in)` |
| **F** fixed costs | `median(household_bills + insurance + loan_payments)` — shown only, NOT in runway |
| **S** typical spending | `median(money_out)` |
| **B** buffer | `mean(avg_daily_balance)` over the account's **last 6 rows sorted by month** |
| **H** household bills | `median(household_bills)` — rent/utility shocks scale this |
| **P** loan payment | `loans.monthly_payment` if loan running at end of 2025, else 0 |

**P rule (verified):** "running at end of 2025" ⇔ `status in {C, D}`. Using start + duration months gives an identical split (A/B all ended, C/D all running). Use the status column.

**Runway:**
```python
buffer_left = B - one_off_costs
gap = spending_after_shock - income_after_shock
if buffer_left <= 0:   runway = 0
elif gap <= 0:         runway = "no shortfall (120+)"
else:                  runway = min(buffer_left / gap, 120)
runway = round(runway, 1)
```

**Shock translations (judge examples):**
| Twist | Change |
|---|---|
| Job loss, EI 55% | income = 0.55 × I |
| Bills +15% | spending = S + 0.15 × H |
| Furnace = one month of spending | one_off_costs = S |
| Job loss + bills +15% | income = 0.55 × I, spending = S + 0.15 × H |

Rules for code:
- Medians are over **all** months of the account, including quiet zero months.
- Sort by `month` before taking the last 6 rows for B.
- Keep the judge number and any "our" adjusted number **side by side** — never replace the judge number.
- Return the string `"no shortfall (120+)"` (or a flag) for gap ≤ 0, not `inf`.

---

## 5. Verified data facts

- Accounts have 12–72 months of history (median 36). 4,424 of 4,500 end in 2025-12.
- Distribution (I / S / B medians): ≈ $7,568 / $7,389 / $22,325.
- 14 accounts have median income 0 (10 of them also median spending 0 = dormant); 23 have a negative buffer (runway = 0 under any shock).
- 682 loans: A 203, B 31, C 403, D 45 → 76 defaulted (11.1%).
- 288 accounts ever had a day below zero; 76 of those had a loan and **all 76 defaulted**.
- 740 accounts (16%) get > 30% of income from pensions — median owner age ≈ 72 vs ≈ 39 for others.
- `cash_deposits` is the dominant income channel (median 99% of income for non-pensioners) → income is often irregular.

---

## 6. Findings so far (candidate "Discovery")

| # | Finding | Numbers |
|---|---|---|
| 1 | **Pre-loan overdraft = default.** The bank had a perfect red flag | 27 accounts went negative *before* the loan was granted → 27/27 defaulted |
| 2 | **Income volatility beats buffer size.** | Pre-loan income CV top quartile: 22.8% default vs 4.1% bottom (5.6×). Pre-loan buffer: 1.86 vs 2.03 months of spending — almost no difference |
| 3 | **Payment burden.** | Payment / income top quartile: 19.9% default vs 4.1% bottom |
| 4 | **Early warning window ~2–3 months.** | Avg balance as % of trailing-12-month peak before first overdraft: ~65% steady → 58% (3 mo) → 43% (2 mo) → 24% (1 mo) |
| 5 | **EI twist at population level.** | With EI 55% (judge-rounded runway): 435 accounts run out in < 3 months, 1,578 (35%) in < 6. (Old 454 used unrounded runway.) With no shock 3,315 have no shortfall |
| 6 | **Medians hide lean months.** | 19% of accounts already have ≥ 20% of months with income below 0.55 × their own median |
| 7 | **Pensioners break the job-loss twist.** | EI does not apply; their EI-runway median is 35 months vs 7 for others. Engine should detect and say so |
| 8 | Card holders are wealthier | Median I $13.6k vs $5.8k; B $35.8k vs $19.1k |
| 9 | Region barely matters | 7–12% of accounts under 3 months of EI runway across all 8 regions |
| 10 | **Stress runway beats judge runway (headline candidate).** Judge formula with income = own 25th-pct month, + loan payment, PRE-LOAN data only | AUC for default: stress 0.752 vs judge 0.639 vs buffer-months 0.593. Paired bootstrap diff +0.113 [+0.049, +0.179]. Bottom stress-runway quartile 26.9% default vs 2.9% in Q3. Rebuilt in `findings.py`: 0.752 vs 0.639, diff +0.113 [+0.044, +0.181]; buffer-months AUC 0.559 with the spec's all-pre-loan-months buffer |
| 11 | Committed obligations | Standing orders (bills + insurance + leasing + loan) = median 34% of I; 1,318 accounts commit > 50% |

**Working pitch analogy:** *the judges' runway is a fuel gauge; we add a check-engine light* — volatility + overdraft history + balance slide predict trouble the median-based runway can't see.

**Caveats to state honestly:**
- Finding 1 extended to "all defaulters had negative days" is partly leakage (status D = currently in debt). The **pre-loan** version (27/27) is clean.
- Sample sizes are small (76 defaults). Report counts alongside rates.

---

## 7. EDA still to do

- [x] One row per account with judge numbers, runways and risk features → `marts.mart_customer_profile` + `marts.mart_shock_runways`.
- [x] Judge-formula parity: all 4,500 accounts match the independent oracle (`tests/test_judge_parity.py`).
- [x] Stress-adjusted runway vs judge runway (the "check-engine light") → F10.
- [x] Standing orders as committed obligations → `marts.mart_committed_obligations`, F11.
- [x] District `unemployment_rate_2023` vs share under 3 months of EI runway: correlation −0.10 across 77 districts, so not useful for scaling job-loss probability (notebook §6).
- [x] Showcase accounts → `reports/showcase.md` (pensioner, volatile cash earner, defaulter with slide, comfortable saver, negative buffer).
- [x] Pitch charts → `reports/figures/`.
- [ ] Pull and cite Canadian sources (EI max weekly benefit, CPI, CMHC rent) if used to size shocks.

---

## 8. Conventions

- Python 3, pandas, numpy. Run scripts that read `data/` with `python3 -I`.
- Load `monthly_summary.csv` with `dtype={'month': str}`. Read `partner_bank` as text.
- Do **not** load `transactions.csv` for metrics — `monthly_summary` already aggregates it. Use transactions only for single-account drill-downs (filter by `account_id` with `usecols`/chunks).
- Derived tables live in the DuckDB warehouse (`warehouse/tangerine.duckdb`); the engine caches `mart_customer_profile` in memory so the live demo answers any `account_id` in ~3 ms.
- Round money to 2 decimals and runway to 1 decimal in outputs.
- Every chart and number used in the pitch must trace to a mart or `findings.py` output (`reports/findings.md`).
- New columns: descriptive snake_case names plus a `comment on column` in the SQL (feeds `reports/data_dictionary.md`).

## 9. Credits (required in submission)

- PKDD'99 Discovery Challenge Financial dataset — https://relational.fel.cvut.cz/dataset/Financial
- Statistics Canada / Government of Canada sources, if used (links listed in `data/Tangerine/README.md`).
