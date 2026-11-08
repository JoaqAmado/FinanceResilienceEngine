# Copilot instructions for this repo

Read `README.md` first; `claude.md` has the EDA notes and `Tangerine/README.md` is the official brief.

## Project shape
- A DuckDB warehouse built from plain SQL (`sql/00_raw → 10_staging → 20_marts`, checks in `sql/90_quality`)
  by `src/tangerine/pipeline.py`, plus a Python engine (`src/tangerine/engine.py`).
- Raw CSVs in `Tangerine/data/` are read-only. Derived data goes to `warehouse/` (git-ignored) and `reports/`.
- `notebooks/01_eda.ipynb` is narrative only: it imports from `tangerine` and must not copy logic.

## Rules
- The judges' numbers (I, F, S, H, B, P and the runway formula) must match `Tangerine/README.md` exactly.
  Our own metrics sit beside them, never replace them.
- Column names are descriptive (`typical_income`, not `I`). Every new mart column gets a `comment on column`.
- Thresholds go in `src/tangerine/config.py` (mirrored to `marts.config_thresholds`), never hard-coded.
- Never load `transactions` for profile metrics; `monthly_summary` already aggregates it.

## Commands (PYTHONPATH=src)
- `python -m tangerine.pipeline` — rebuild the warehouse + quality checks
- `python -m pytest -q` — all tests
- `python -m tangerine.findings` — reports and figures
- `python -m tangerine.engine <account_id> --shock <preset>` — one account
