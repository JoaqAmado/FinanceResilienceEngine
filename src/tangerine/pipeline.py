"""Build the DuckDB warehouse from the raw CSVs.

    python -m tangerine.pipeline          # full rebuild
    python -m tangerine.pipeline --check  # only run the data-quality checks

Steps
1. Convert transactions.csv -> warehouse/transactions.parquet (once; skipped if it already exists).
2. Write the thresholds from config.py into marts.config_thresholds.
3. Run every .sql file in sql/00_raw, sql/10_staging, sql/20_marts, in filename order.
4. Run every check in sql/90_quality. Each must return 0 rows, otherwise the build fails.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import duckdb

from tangerine import config


def connect(read_only: bool = False) -> duckdb.DuckDBPyConnection:
    """Open the warehouse file."""
    if read_only and not config.WAREHOUSE_PATH.exists():
        raise FileNotFoundError(
            f"{config.WAREHOUSE_PATH} does not exist yet. Build it first: python -m tangerine.pipeline"
        )
    config.WAREHOUSE_DIR.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(config.WAREHOUSE_PATH), read_only=read_only)


def render_sql(text: str) -> str:
    """Fill the path placeholders used by the raw-layer SQL files."""
    return (
        text.replace("{{DATA_DIR}}", config.DATA_DIR.as_posix())
        .replace("{{TRANSACTIONS_PARQUET}}", config.TRANSACTIONS_PARQUET.as_posix())
        .replace("{{REFERENCE_DATE}}", config.REFERENCE_DATE.isoformat())
        .replace("{{LAST_DATA_MONTH}}", config.LAST_DATA_MONTH)
    )


def sql_files(folder: str) -> list[Path]:
    return sorted((config.SQL_DIR / folder).glob("*.sql"))


def convert_transactions_to_parquet(con: duckdb.DuckDBPyConnection) -> None:
    """transactions.csv is ~100 MB; Parquet is ~5x smaller and much faster to query."""
    target = config.TRANSACTIONS_PARQUET
    if target.exists():
        print(f"  transactions parquet already exists: {target.name}")
        return
    source = config.DATA_DIR / "transactions.csv"
    if not source.exists():
        raise FileNotFoundError(
            f"{source} is missing. Copy the datathon pack's transactions.csv into {config.DATA_DIR}."
        )
    con.execute(
        f"""
        copy (
            select * from read_csv('{source.as_posix()}', header = true,
                types = {{'date': 'DATE', 'partner_bank': 'VARCHAR', 'partner_account': 'VARCHAR',
                          'purpose': 'VARCHAR'}})
        ) to '{target.as_posix()}' (format parquet, compression zstd)
        """
    )
    print(f"  wrote {target.name} ({target.stat().st_size / 1e6:.1f} MB)")


def write_thresholds(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("create schema if not exists marts")
    con.execute(
        "create or replace table marts.config_thresholds "
        "(threshold_name varchar primary key, threshold_value double, meaning varchar)"
    )
    con.executemany(
        "insert into marts.config_thresholds values (?, ?, ?)",
        [(name, float(value), meaning) for name, (value, meaning) in config.THRESHOLDS.items()],
    )
    con.execute("comment on table marts.config_thresholds is "
                "'Every threshold our flags and plans use, copied from src/tangerine/config.py so SQL and Python agree.'")
    con.execute("comment on column marts.config_thresholds.threshold_name is 'Name used in config.THRESHOLDS.'")
    con.execute("comment on column marts.config_thresholds.threshold_value is 'The value.'")
    con.execute("comment on column marts.config_thresholds.meaning is 'What the threshold controls, in plain English.'")


def run_sql_folders(con: duckdb.DuckDBPyConnection) -> None:
    for folder in config.SQL_BUILD_FOLDERS:
        print(f"[{folder}]")
        for path in sql_files(folder):
            started = time.perf_counter()
            con.execute(render_sql(path.read_text(encoding="utf-8")))
            print(f"  {path.name:<45} {time.perf_counter() - started:5.2f}s")


def run_quality_checks(con: duckdb.DuckDBPyConnection) -> dict[str, int]:
    """Return {check file name: number of violating rows}. Pass = every value is 0."""
    results = {}
    for path in sql_files(config.SQL_QUALITY_FOLDER):
        rows = con.execute(render_sql(path.read_text(encoding="utf-8"))).fetchall()
        results[path.name] = len(rows)
    return results


def print_quality(results: dict[str, int]) -> bool:
    print(f"[{config.SQL_QUALITY_FOLDER}]")
    for name, n_bad in results.items():
        print(f"  {'PASS' if n_bad == 0 else 'FAIL'}  {name}" + ("" if n_bad == 0 else f"  ({n_bad} bad rows)"))
    return all(n == 0 for n in results.values())


def build() -> bool:
    started = time.perf_counter()
    print(f"Raw data : {config.DATA_DIR}")
    print(f"Warehouse: {config.WAREHOUSE_PATH}")
    con = connect()
    try:
        convert_transactions_to_parquet(con)
        write_thresholds(con)
        run_sql_folders(con)
        ok = print_quality(run_quality_checks(con))
    finally:
        con.close()
    print(f"Done in {time.perf_counter() - started:.1f}s - quality checks {'PASSED' if ok else 'FAILED'}")
    return ok


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="only run the data-quality checks")
    args = parser.parse_args(argv)
    if args.check:
        con = connect(read_only=True)
        ok = print_quality(run_quality_checks(con))
        con.close()
    else:
        ok = build()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
