"""Paths and constants shared by the pipeline, the engine, the tests and the findings.

Every number that is a *choice* (a threshold, a cap, a default) lives here, so SQL and
Python agree. The pipeline copies THRESHOLDS into the table `marts.config_thresholds`
before the marts are built, and the SQL reads it from there.
"""
from __future__ import annotations

import os
from datetime import date
from pathlib import Path

# ── Paths ────────────────────────────────────────────────────────────────────
# Project root = the folder that holds src/, sql/, Tangerine/ (two levels above this file).
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# The official datathon CSVs. Read-only: nothing in this project writes here.
# The GitHub repo keeps them in data/; the original datathon pack unzips to Tangerine/data/. Use whichever exists.
_DEFAULT_DATA_DIR = next(
    (p for p in (PROJECT_ROOT / "data", PROJECT_ROOT / "Tangerine" / "data") if (p / "accounts.csv").exists()),
    PROJECT_ROOT / "data",
)
DATA_DIR = Path(os.environ.get("TANGERINE_DATA_DIR", _DEFAULT_DATA_DIR))

# Everything we build goes in warehouse/ (gitignored, rebuilt by the pipeline).
WAREHOUSE_DIR = Path(os.environ.get("TANGERINE_WAREHOUSE_DIR", PROJECT_ROOT / "warehouse"))
WAREHOUSE_PATH = WAREHOUSE_DIR / "tangerine.duckdb"
TRANSACTIONS_PARQUET = WAREHOUSE_DIR / "transactions.parquet"

SQL_DIR = PROJECT_ROOT / "sql"
SQL_BUILD_FOLDERS = ["00_raw", "10_staging", "20_marts"]  # run in this order
SQL_QUALITY_FOLDER = "90_quality"

REPORTS_DIR = PROJECT_ROOT / "reports"
FIGURES_DIR = REPORTS_DIR / "figures"

# ── Data facts ───────────────────────────────────────────────────────────────
REFERENCE_DATE = date(2025, 12, 31)  # last day of data; ages and "loan still running" are measured here
LAST_DATA_MONTH = "2025-12"

EXPECTED_RAW_ROW_COUNTS = {
    "monthly_summary": 185_326,
    "transactions": 1_056_320,
    "accounts": 4_500,
    "clients": 5_369,
    "dispositions": 5_369,
    "cards": 892,
    "loans": 682,
    "standing_orders": 6_471,
    "districts": 77,
}

# ── Judge formula constants (from Tangerine/README.md) ───────────────────────
RUNWAY_CAP_MONTHS = 120.0
NO_SHORTFALL_LABEL = "no shortfall (120+)"
EI_REPLACEMENT_RATE = 0.55  # EI pays 55% of usual income

# ── Thresholds for our risk flags and plans ──────────────────────────────────
# name -> (value, plain-English meaning). Mirrored into marts.config_thresholds.
THRESHOLDS: dict[str, tuple[float, str]] = {
    "volatile_income_cv": (
        0.45,
        "Income is 'volatile' when its coefficient of variation (std / mean of monthly money in) is above this. "
        "0.45 is roughly the top-quartile cut across all accounts.",
    ),
    "pensioner_income_share": (
        0.30,
        "An account is a 'pensioner' when more than this share of all money in came from pensions.",
    ),
    "lean_month_income_ratio": (
        0.55,
        "A 'lean month' is a month whose money in is below this fraction of the account's own typical income "
        "(same size as the EI job-loss shock).",
    ),
    "balance_slide_ratio": (
        0.50,
        "Balance is 'sliding' when last month's average balance is below this fraction of the highest monthly "
        "average balance in the 12 months before it.",
    ),
    "short_history_months": (
        18,
        "History is 'short' when the account has fewer than this many months of data.",
    ),
    "target_buffer_months_steady": (
        3,
        "Emergency-fund goal, in months of typical spending, for customers with steady income.",
    ),
    "target_buffer_months_volatile": (
        6,
        "Emergency-fund goal, in months of typical spending, for customers with volatile income.",
    ),
    "backup_plan_discretionary_cut": (
        0.30,
        "Default share of discretionary spending the backup plan cuts when a shock hits.",
    ),
    "backup_plan_runway_goal_months": (
        6,
        "The backup plan reports the discretionary cut needed to reach this many months of runway.",
    ),
    "savings_share_of_surplus": (
        0.50,
        "Goal plan: save this share of the monthly surplus (money in minus spending)...",
    ),
    "savings_share_of_discretionary": (
        0.10,
        "...plus this share of discretionary spending, capped at the full surplus.",
    ),
    "goal_plan_deadline_months": (
        12,
        "Goal plan when there is no surplus: the discretionary cut needed to reach the target within this many months.",
    ),
}


def threshold(name: str) -> float:
    """Return a threshold value by name."""
    return float(THRESHOLDS[name][0])
