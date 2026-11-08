# Devpost submission text

## Elevator pitch (tagline)

The judges' runway is a fuel gauge, so we added a check-engine light: a resilience engine that stress-tests any customer against job loss, rising bills or a surprise repair, then builds the plan.

<!-- Shorter alternatives:
- A fuel gauge tells you how far you can go. We built the check-engine light.
- Median months lie. Lean months tell you who's really at risk.
-->

---

## About the project

## Inspiration

Every banking app can tell you your balance. Very few can answer the question people actually worry about: **"If something goes wrong next month, how long can I last?"**

The Resilience Rewired brief gave us a clean way to measure that: **runway**, the number of months your savings cover the gap between what you spend and what comes in after a shock. It works like a fuel gauge. While building it, we noticed something: the fuel gauge uses your *typical* (median) month, but trouble rarely arrives in a typical month. It comes in the lean ones. That led to our question:

> Does the official runway miss customers who are already in danger, and can the same data tell us who they are?

## What it does

For any `account_id`, the engine does three things in about 3 ms:

1. **Knows the customer.** It computes typical income $I$, fixed costs $F$, typical spending $S$, household bills $H$, buffer $B$ and running loan payment $P$, exactly as the judges define them.
2. **Takes a shock.** Job loss with EI at 55%, bills +15%, a furnace repair worth one month of spending, any mix of these, or a custom size.
3. **Makes a plan.** A **goal plan** (an emergency fund of 3 months of spending for steady earners, 6 months for volatile ones) and a **backup plan** (which costs to protect, how much discretionary spending to cut, and how many months of runway that buys).

Next to the official number, it shows our **stress runway** and plain-language warnings. Examples: *"income is volatile"*, *"has gone below zero before"*, *"balance is sliding: 44% of its 12-month peak"*, *"pension income: the job-loss twist mostly doesn't apply."*

### The math

The judge runway, which we reproduce exactly for all 4,500 accounts:

$$
\text{runway} =
\begin{cases}
0 & \text{if } B - \text{one-off} \le 0 \\
\text{no shortfall (120+)} & \text{if } S' - I' \le 0 \\
\min\!\left(\dfrac{B - \text{one-off}}{S' - I'},\ 120\right) & \text{otherwise}
\end{cases}
$$

Here $I'$ and $S'$ are income and spending after the shock. Job loss with EI gives $I' = 0.55\,I$, and bills +15% gives $S' = S + 0.15\,H$.

Our **stress runway** keeps the formula but swaps the median month for a lean one:

$$
I_{\text{stress}} = Q_{25}\big(\text{money\_in}\big)
$$

That is the customer's own 25th-percentile month of income, with the loan payment counted as a committed cost. Nothing is invented: it's the same formula, applied to a more honest month.

## Our Discovery

We tested both runways on the bank's 682 loans, **using only data from before each loan was granted**, which is what the bank knew when it said yes:

| Signal (pre-loan only) | AUC for predicting default |
|---|---:|
| **Stress runway (ours)** | **0.752** |
| Judge runway | 0.639 |
| Buffer size (months of spending) | 0.559 |

The paired bootstrap difference between stress and judge runway is $+0.113$, 95% CI $[+0.048,\ +0.180]$, so it stays above zero in every one of 2,000 resamples. Loans in the bottom quarter of stress runway defaulted **26.9%** of the time, compared with **2.9%** in the third quarter.

Supporting findings:

- **The bank had a perfect red flag.** 27 accounts went below zero *before* their loan was approved, and **27 of 27 defaulted**, compared with 7.5% of everyone else.
- **Unsteady income matters more than savings.** Defaulters and good payers had almost the same buffer (1.84 vs 2.01 months of spending). But the most volatile income quarter defaulted at **22.8%**, against **4.1%** for the steadiest quarter.
- **There is an early-warning window.** Before a first overdraft, the average balance slides from ~66% of its 12-month peak to 58%, 43% and then 24% over the final three months.
- **A third of customers are about 6 months from trouble.** With job loss and EI at 55%, **1,578 of 4,500 accounts (35%)** run out of money within 6 months, and 435 within 3.
- **One size doesn't fit all.** 740 accounts (16%) live mostly on pensions, with a median owner age of 71. EI doesn't apply to them, so the engine detects these accounts and says so.

## How we built it

- **Data:** the PKDD'99 Czech bank dataset (anonymized, converted to CAD and shifted to 2020–2025). It has 4,500 accounts, 1.06M transactions and 185k account-months.
- **Warehouse:** a layered **DuckDB** pipeline in SQL (`raw → staging → marts`). Every derived column carries a SQL comment, and those comments generate our data dictionary.
- **Quality gates:** 10 SQL checks that must return zero rows, plus **46 pytest tests**. The key one is a *judge-parity test*: an independent, plain-pandas copy of the official formulas has to match the engine to the cent for all 4,500 accounts.
- **Engine:** pure Python. It loads one customer-profile table into memory once, so the live demo answers instantly and can sit behind a CLI, a notebook or a UI.
- **Findings:** one script (`findings.py`) regenerates every number, chart and table in this write-up from the warehouse. Nothing in the pitch is typed by hand.
- **Reproducibility:** everything runs in **Docker** (`make all` rebuilds from the raw CSVs, tests it and regenerates the reports).

Stack: Python, pandas, NumPy, DuckDB, PyArrow, matplotlib, pytest, JupyterLab, Docker. AUC and bootstrap CIs are computed from scratch (rank-based, no ML library), so the method is fully transparent.

## Challenges we ran into

- **Matching the judges exactly.** Small details changed answers: medians must include quiet zero-income months, the buffer uses the *last six rows sorted by month*, and runway is rounded to one decimal *before* counting. Rounding alone moved our "under 3 months" count from 454 to 435. We built the parity test so we could stop arguing and start checking.
- **Avoiding leakage.** Our first result was *"every defaulter had overdraft days"*. It looked perfect, but loan status D literally means "currently in debt", so we were measuring the outcome. We rebuilt the analysis to use **pre-loan data only**, and the cleaner version (27/27) survived.
- **Small samples.** There are only 76 defaults, so we report counts next to every rate and bootstrap confidence intervals for the headline. Some findings that looked exciting, such as regional differences and district unemployment, didn't hold up, and we dropped them.
- **Customers the formula doesn't fit.** Pensioners, dormant accounts (14 with zero median income) and 23 accounts with a negative buffer all needed explicit handling rather than silently wrong numbers.
- **Messy timestamps.** Same-day transactions aren't in time order, so balance-path analysis had to work from daily and monthly aggregates instead of trusting row order.

## What we learned

- **Averages hide the risk.** 19% of accounts already have at least one in five months where income falls below 55% of their own median. For them a "job loss" shock has, in effect, already happened.
- **Volatility is a better warning than wealth.** How *steady* money arrives tells you more than how much is sitting in the account.
- **Trust comes from traceability.** Keeping the judge number and our number side by side, never replacing one with the other, made the insight easier to defend.

## What's next

- Use the ~2–3 month balance slide as a **proactive nudge**: alert the customer *before* the first overdraft, not after.
- Size shocks with Canadian reference data (EI maximum weekly benefit, CPI, CMHC rents).
- Validate on a larger, more recent loan book. 76 defaults is enough to see the signal but not to deploy it.

## Built with / sources

- PKDD'99 Discovery Challenge Financial dataset: https://relational.fel.cvut.cz/dataset/Financial
- Python · pandas · NumPy · DuckDB · matplotlib · pytest · Docker
