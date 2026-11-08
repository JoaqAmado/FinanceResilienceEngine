# HANDOFF — project state for the next AI agent

Tangerine "Resilience Rewired" (Sheridan Datathon 2026). The data side is **done and verified**; the next step is the demo/communication layer.
Read `CLAUDE.md` (rules, judge formulas, verified facts) before changing anything. `project prottotype.md` is the original build spec.

## Status (verified 2026-11-07, in Docker)
- Pipeline builds `warehouse/tangerine.duckdb` in ~13 s; 10/10 SQL quality checks pass.
- `pytest`: **46/46 pass** (incl. judge parity for all 4,500 accounts, ~4 min).
- `findings.py` regenerates all reports and 6 figures. Headline: stress runway AUC 0.752 vs judge runway 0.639 (diff +0.113, CI [0.048, 0.180]).
- Git: repo https://github.com/JoaqAmado/FinanceResilienceEngine, our work is on branch `Jason` (team branches: main, joaquin, marco). Raw CSVs are tracked in `data/`; `Tangerine/data/` is a git-ignored local duplicate. No Docker image pushed to any registry.
- **Web app built** (90-day plan, FastAPI + plain HTML/JS): `app/main.py` (API), `app/plan90.py` (turns `engine.run()` into the prevent/survive plan, no new math), `app/static/` (page, CSS, JS, inline-SVG chart). Run `make app` or `docker compose up app` → http://localhost:8000. `tests/test_app.py` covers all 4,500 accounts × 6 presets; full suite now **57/57**.

## Folder map
| Path | Contents | Edit? |
|---|---|---|
| `Tangerine/README.md` | Official challenge brief — source of truth | No |
| `Tangerine/data/*.csv` | Raw data (9 files; `monthly_summary` is primary, `transactions` ~100 MB) | **Read-only** |
| `sql/00_raw/` | Load CSVs into DuckDB as-is | Rarely |
| `sql/10_staging/` | Typed/cleaned tables, `stg_account_owner` | Rarely |
| `sql/20_marts/` | Analysis tables. Key: `05_mart_customer_profile` (I, F, S, H, B, P + risk features, one row/account), `06_mart_shock_runways`, `07_mart_loan_preloan`, `08_mart_default_drivers`, `09_mart_balance_slide`, `10_mart_committed_obligations`, `11_mart_findings`. `01_macro_judge_runway` = runway formula in SQL | Add new marts here |
| `sql/90_quality/` | Checks that must return 0 rows | Add checks for new marts |
| `src/tangerine/config.py` | Paths + all thresholds/plan targets (with descriptions) | Tune here, not inline |
| `src/tangerine/pipeline.py` | Runs SQL layers in order + quality checks | — |
| `src/tangerine/engine.py` | **The product.** `run(account_id, shock)` → dict; `summary_text()`; `Shock`, `PRESETS`; CLI `python -m tangerine.engine <id> --shock <preset>` | UI should import this |
| `src/tangerine/judge_reference.py` | Independent pandas oracle of judge formulas (used by parity test) | Don't couple to engine |
| `src/tangerine/findings.py` | Builds `reports/*` + figures from marts | — |
| `tests/` | `test_quality`, `test_judge_parity`, `test_engine` | Keep green |
| `notebooks/01_eda.ipynb` | Narrative EDA, imports from `tangerine` | — |
| `reports/findings.md` | All findings F1–F11 with n + source mart | Generated — don't hand-edit |
| `reports/showcase.md` | 5 rehearsal accounts × 6 shocks (pensioner 61810, volatile 56404, defaulter 59243, saver 72641, negative buffer 66692) | Generated |
| `reports/data_dictionary.md`, `reports/figures/` | Generated from SQL comments / findings | Generated |
| `reports/devpost_writeup.md` | Devpost tagline + "About the project" (hand-written) | Yes |
| `warehouse/` | `tangerine.duckdb`, `transactions.parquet` (generated, git-ignore) | Generated |
| `work/discovery_auc.ipynb` | Legacy notebook, superseded | Archive/delete |
| `Dockerfile`, `docker-compose.yml`, `Makefile` | Services: pipeline, test, findings, engine, notebook (:8888). Image holds code only; data + warehouse are mounted | — |

## How to run
```bash
make all                                    # build → pipeline → test → findings (Docker)
make engine ID=20111 SHOCK=job_loss_plus_bills
# without Docker (PowerShell): $env:PYTHONPATH="src"; python -m tangerine.pipeline; pytest; python -m tangerine.findings
```
Shock presets: `no_shock, job_loss_ei55, ei55_6_months, bills_up_15, furnace_1_month, job_loss_plus_bills`.
Custom: `run(id, Shock(income_factor=0.55, bills_increase_pct=0.20, one_off_months_of_spending=1, one_off_cost=..., duration_months=...))`.

## Hard rules
1. Judge numbers (I, F, S, H, B, P, judge runway) must match `CLAUDE.md §4` exactly; show "our" numbers **beside** them, never instead.
2. Gap ≤ 0 → `"no shortfall (120+)"`, not `inf`. Round money 2 dp, runway 1 dp.
3. Every pitch number must trace to a mart or `findings.py` output.
4. Don't load `transactions.csv` for metrics; use `monthly_summary` / marts.
5. Any change → `pytest` must stay 46/46 green.

## Spec: 90-day resilience plan builder (CHOSEN app; supersedes the watchlist)

**Purpose:** after a shock test, show what to do *before* it hits (prevent) and *if* it hits (survive), as a 90-day checklist.
**Audience:** the customer, with a banker able to walk through it. Plain language, no blame.

**Flow (one screen, top to bottom):**
1. **Shock test:** account_id + preset or slider (job loss EI %, bills %, one-off cost). Shows judge runway and stress runway side by side (never replace the judge number).
2. **Warning signs:** `context_notes()` from the engine, e.g. "balance is sliding", "has gone below zero before".
3. **Prevent (Days 1–30):** from `Plan.goal_summary` and the goal plan: target buffer (3 or 6 months, `config.py`), monthly saving, discretionary cut %.
4. **Survive (if the shock hits):** from `Plan.backup_steps` and `backup_runway_label`: what to protect (bills, insurance, loan), what to cut and by how much, runway after the cut.
5. **90-day calendar:** Weeks 1–13, each with one action. Built from the plan numbers, e.g. "Week 1: cut discretionary spending by X% ($Y/month)", "Week 6: check balance vs target".
6. **Balance path:** 24-month chart from `engine.simulate()`, baseline vs shocked.

**Rules:**
- Every number comes from `engine.run()` / `make_plan()`. The app adds no new math.
- Gap ≤ 0 shows "no shortfall (120+)"; buffer ≤ 0 shows "Step 1: get out of overdraft" first.
- Pensioners: the job-loss step is replaced with a note that pension income continues (F7).
- Export the 90-day plan as a printable page or PDF.

**Acceptance:** all 4,500 accounts render for every preset without error; each plan step traces to an engine field; `tests/test_plan_app.py` checks that the calendar's monthly saving equals `Plan.monthly_saving`.

**Deferred:** the advisor watchlist (kept below for reference; not in scope now).

## Spec: Advisor early-warning watchlist (deferred)

**Purpose:** a bank advisor opens one screen and sees which accounts to call first, and why.
**Audience:** a Tangerine advisor, not the customer. Wording is neutral ("balance is sliding"), never blame.

**Data:** only existing marts, one row per account from `marts.mart_customer_profile` joined to `marts.mart_shock_runways` and `marts.mart_balance_slide`. No new raw reads, no `transactions.csv`.

**Flags (rule-based, transparent; no ML model):**

| Flag | Rule (column) | Why it matters |
|---|---|---|
| Balance sliding | `is_balance_sliding` | Early-warning window ~2–3 months (F4) |
| Overdrawn recently | `days_overdrawn_last_6_months > 0` | Current stress |
| Ever overdrawn | `has_overdraft_history` | Pre-loan red flag (F1) |
| Volatile income | `is_volatile_income` (CV) | Strongest pre-loan signal (F2) |
| Low runway, EI | `stress_runway_job_loss_ei55 < 3` | Lean-month stress (F10) |
| Loan in debt | `has_loan_in_debt` | Status D = already in arrears |
| Heavy payment | loan payment / typical income > 0.30 | Payment burden (F3) |

**Priority score:** count of flags, tie-break by `stress_runway_job_loss_ei55` ascending. Sort descending by flag count, then ascending by runway.

**Exclusions (must hold):** do **not** use `owner_age_years` or `owner_gender` in any flag or score. Pensioners are labelled with `is_pensioner` as context only, because EI does not apply to them (F7).

**Screen contents:**
1. Filter bar: region (`branch_region`), has loan, minimum flags, pensioner on/off.
2. Ranked table: account_id, flag count, flag chips, judge runway, stress runway, buffer months, balance vs 12-month peak.
3. Click a row → opens the customer what-if view (same engine call as tab 1) so the advisor sees the plan.
4. Header counts: "N accounts with ≥3 flags" and "N with stress runway < 3 months", each with a note that numbers are historical (2020–2025, anonymized).

**Judge rules still apply:** show judge runway beside stress runway; never replace it. Any headline number must trace to `reports/findings.md` or a mart.

**Acceptance:** all 4,500 accounts render without error; sort and filters work; one account's flags match `engine.run()` output; a `tests/test_watchlist.py` checks flag counts against the marts (no duplicates, all accounts present).

## Next steps (priority order)
1. **Demo UI** — Streamlit app (`app/streamlit_app.py`) importing `tangerine.engine.run`: account_id input, twist-card buttons + sliders for shock size, judge vs stress runway side by side, goal/backup plan, warning flags, 24-month balance path from `engine.simulate`. Add `streamlit` to requirements + an `app` compose service (port 8501). Must answer any of 4,500 accounts without error.
2. **Git repo** — `git init`, `.gitignore` (warehouse/, __pycache__, .ipynb_checkpoints, .pytest_cache), push public to GitHub (required for submission). Decide whether raw data may be committed (check brief/licence).
3. **Canadian sources** — EI max weekly benefit, CPI, CMHC rent; cite links in README + Devpost if used to size shocks.
4. **Pitch assets** — 1-min pitch script around F10 (fuel gauge vs check-engine light), 3-min live-twist script using `showcase.md` accounts, Q&A cheat sheet from caveats in `findings.md`; 2–3 min demo video.
5. Optional: push Docker image (Docker Hub/GHCR) — user must `docker login` and confirm registry; consider a demo image with the warehouse baked in.
6. Remove/archive `work/`.
