# [Tangerine] Resilience Rewired

Tangerine Track · Sheridan Datathon 2026 · November 7-8

Build a financial resilience engine for real bank customers.

This track is powered by Tangerine. At judging, a judge will pick a customer and a scenario, and you will run your engine live.

---

## The data

`data/` holds real, anonymized data from a bank: 4,500 accounts, about 1.06 million transactions and 682 loans and how each one is going.

---

## The challenge

Build a tool that does three things. It can be a dashboard, an app, a notebook, an AI agent or anything else.

1. **Know the customer.** Take any `account_id` and show their income, bills and fixed costs, savings buffer, and months of runway.
2. **Take a shock.** Apply a shock and recalculate, for example a job loss with EI, higher rent or household bills, a surprise repair, or a mix. Let the user change the size of the shock.
3. **Make a plan.** Give that customer a goal plan, like building an emergency fund, and a backup plan for if the shock hits, both based on their own numbers.

---

## How judging works

**Discovery 35%, Data Use 25%, Communication 25%, Impact 15%**.

You get about 5 minutes:

| Time | What happens |
| :-- | :-- |
| 1 min | **Pitch:** show your engine and your biggest finding |
| 3 min | **Live twist:** a judge picks an `account_id` and reads a twist card. You run it live and explain the new numbers and plan |
| 1 min | **Questions** from the judges |

&nbsp;

Example twists:
- "This customer was laid off. EI pays 55% of their usual income for 6 months. Do they make it?"
- "The furnace dies, and the repair costs a full month of their typical spending."
- "They lose their job (EI at 55%) and their household bills go up 15% in the same month."

---

## How judges calculate the numbers

Judges have answers worked out with these definitions, from `monthly_summary.csv`:

| Number | Definition |
| :-- | :-- |
| **Typical monthly money in** (I) | Median of `money_in` |
| **Typical fixed costs** (F) | Median of `household_bills + insurance + loan_payments` (shown in part 1, not used in runway) |
| **Typical monthly spending** (S) | Median of `money_out` |
| **Buffer** (B) | Mean of `avg_daily_balance` over the account's last 6 rows, sorted by month |
| **Household bills** (H) | Median of `household_bills` (rent and utility shocks change this) |
| **Loan payment** (P) | `monthly_payment` in `loans.csv` if the loan is still running at the end of 2025, otherwise 0 |

**Runway** (months) = buffer left after one-off costs ÷ monthly shortfall:

```
buffer_left = B - one_off_costs
gap         = spending_after_shock - income_after_shock
if buffer_left <= 0:  runway = 0
elif gap <= 0:        runway = "no shortfall (120+)"
else:                 runway = min(buffer_left / gap, 120)
```

Runway is rounded to 1 decimal. A shock changes income or spending in this formula: for example, a job loss with EI at 55% means income = 0.55 × I, and household bills up 15% means spending = S + 0.15 × H.

You can use your own definitions instead. If your numbers differ from these, be ready to explain why.

---

## Using AI

Use any tools you want, including AI.

---

## What to submit (on Devpost)

1. **Demo video** (2 to 3 minutes) of your engine running.
2. **Code repo** (public link or zip).
3. **Short write-up:** what your engine does and your biggest finding.
4. **Sources:** links to every outside data source you used.

---

## Data dictionary

All files are in `data/` and link through the ID columns. **All money columns are in Canadian dollars.**

```
districts ──< accounts ──< transactions
                │    ├──< monthly_summary
                │    ├──< standing_orders
                │    └──< loans
                └──< dispositions >── clients
                          └──< cards
```

### `monthly_summary.csv` (185,326 rows)
One row per account per month, built from `transactions.csv`, from the account's first transaction month to its last (quiet months included). Balances are end-of-day balances, carried forward on days with no activity.

| Column | Meaning |
| :-- | :-- |
| `account_id`, `month` | Account and month (`YYYY-MM`) |
| `money_in`, `money_out` | Total money in and total money out (positive numbers) |
| `cash_deposits`, `transfers_in`, `pension_in`, `interest_in` | Parts of `money_in` (`transfers_in` excludes pensions); they add up to `money_in` |
| `household_bills`, `insurance`, `loan_payments`, `bank_fees`, `cash_withdrawals_genuine`, `card_withdrawals`, `transfers_out_other` | Parts of `money_out` (`transfers_out_other` = unlabelled transfers out); they add up to `money_out` |
| `month_end_balance` | End-of-day balance on the last day of the month |
| `min_balance`, `avg_daily_balance` | Lowest and average end-of-day balance in the month (the first month counts from the first transaction) |
| `days_below_zero` | Days in the month that ended with a negative balance |

### `transactions.csv` (1,056,320 rows, about 100 MB)
| Column | Meaning |
| :-- | :-- |
| `transaction_id`, `account_id` | Transaction and its account |
| `date` | Date (2020-01-01 to 2025-12-31) |
| `direction` | `credit (money in)` or `debit (money out)` |
| `operation` | `cash deposit`, `cash withdrawal`, `card withdrawal`, `transfer in from another bank`, `transfer out to another bank`, `bill payment`, `bank fee`, `interest` |
| `purpose` | When known: `household bills`, `insurance`, `loan payment`, `pension`, `interest credited`, `statement fee`, `penalty interest (negative balance)`. Blank = not labelled |
| `amount` | Amount, always positive |
| `signed_amount` | Positive = money in, negative = money out |
| `balance` | Account balance after the transaction. Rows within the same day are not in time order |
| `partner_bank`, `partner_account` | For transfers: the other bank (two-letter code) and the account number at that bank (not an `account_id` here). Blank or 0 when not a transfer. Read `partner_bank` as text |

`bank fee` = statement fees and penalty interest. `bill payment` = household bills or insurance paid at the bank.

### `loans.csv` (682 rows)
| Column | Meaning |
| :-- | :-- |
| `loan_id`, `account_id` | Loan and the account that took it (one loan per account) |
| `loan_start` | Date the loan was granted |
| `amount`, `duration_months`, `monthly_payment` | Size, length in months, and monthly payment (`amount` = `duration_months` × `monthly_payment`) |
| `status`, `status_meaning` | A = finished, repaid; B = finished, NOT repaid (default); C = running, OK so far; D = running, client in debt |
| `defaulted` | 1 if B or D, 0 if A or C |

### Other files
| File | Rows | Columns and notes |
| :-- | --: | :-- |
| `accounts.csv` | 4,500 | `account_id`, `district_id` (branch), `frequency` (statement frequency), `account_opened` |
| `clients.csv` | 5,369 | `client_id`, `gender`, `birth_date`, `district_id` (home) |
| `dispositions.csv` | 5,369 | `disposition_id`, `client_id`, `account_id`, `type` (`owner` or `authorized user`) |
| `cards.csv` | 892 | `card_id`, `disposition_id`, `card_type` (junior, classic, gold), `issued` |
| `standing_orders.csv` | 6,471 | `order_id`, `account_id`, `to_bank`, `to_account`, `amount`, `purpose` (household bills, insurance, leasing, loan payment; blank = other). Undated end-of-data snapshot |
| `districts.csv` | 77 | `district_id`, `district_name`, `region`, `inhabitants`, `municipalities_under_500`, `municipalities_500_1999`, `municipalities_2000_9999`, `municipalities_over_10000`, `num_cities`, `urban_ratio_pct`, `average_salary` (monthly, CAD), `unemployment_rate_2022`, `unemployment_rate_2023`, `entrepreneurs_per_1000`, `crimes_2022`, `crimes_2023`. These are the bank's original regions. District 69 has no 2022 unemployment or crime values |

---

## Canadian sources for sizing shocks

Link any you use.
- **Consumer Price Index:** https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=1810000401
- **CMHC average rents** by city: https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=3410013301
- **Labour Force Survey** (unemployment): https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=1410028701
- **Employment Insurance regular benefits:** https://www.canada.ca/en/services/benefits/ei/ei-regular-benefit.html
  EI typically pays 55% of average insurable earnings, up to a weekly maximum.
- **Average weekly earnings** (Table 14-10-0223-01): https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=1410022301

---

## Credits

Credit the data in your submission:
- **PKDD'99 Discovery Challenge Financial dataset** (real anonymized bank data), from the CTU Prague Relational Dataset Repository: https://relational.fel.cvut.cz/dataset/Financial
- **Statistics Canada** and **Government of Canada** sources, if you use them.

Questions? Ask in ┃ask-a-mentor on the Discord. Good luck!
