"""Snowflake mirror of the judges' numbers. Optional: the engine and the app never depend on it.

    python -m resilience.warehouse local-parity     # offline: sql/ in DuckDB vs the engine
    python -m resilience.warehouse load             # upload data/raw/*.csv (not transactions), create the views
    python -m resilience.warehouse verify           # Snowflake views vs resilience.build_metrics()

The SQL in sql/ runs unchanged in Snowflake and in DuckDB, so parity is checked
with no account and no network. Both get the same upper-cased tables from the same pandas
frames. Settings come from the environment or the local, gitignored .env:

    SNOWFLAKE_ACCOUNT, SNOWFLAKE_USER                       required
    SNOWFLAKE_PRIVATE_KEY_FILE (key-pair login, preferred) or SNOWFLAKE_PASSWORD
    SNOWFLAKE_WAREHOUSE (COMPUTE_WH), SNOWFLAKE_DATABASE (TANGERINE), SNOWFLAKE_SCHEMA (PUBLIC)
    SNOWFLAKE_ROLE                                          optional

No setting value is ever printed: the CLI prints counts only, and error text is scrubbed.
"""
from __future__ import annotations

import argparse
import hashlib
import logging
import os
import warnings
import re
import sys
from collections.abc import Sequence
from pathlib import Path

import numpy as np
import pandas as pd

from .core import DATA_DIR, LAID_OFF_EI, build_metrics, portfolio_runway
from .llm import _dotenv_value

ROOT = Path(__file__).resolve().parent.parent
SQL_DIR = ROOT / "sql"
METRIC_COLUMNS = ("I", "F", "S", "H", "B", "P")
TOLERANCE = 1e-6
TABLES = ("monthly_summary", "loans", "accounts", "clients", "dispositions", "cards", "districts", "standing_orders")
SQL_TABLES = ("monthly_summary", "loans")  # what sql/ reads
REQUIRED = ("SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER")
SECRETS = ("SNOWFLAKE_PASSWORD", "SNOWFLAKE_PRIVATE_KEY_FILE")  # one of these is needed
DEFAULTS = {"SNOWFLAKE_WAREHOUSE": "COMPUTE_WH", "SNOWFLAKE_DATABASE": "TANGERINE",
            "SNOWFLAKE_SCHEMA": "PUBLIC", "SNOWFLAKE_ROLE": None}
MISSING = ("Snowflake is not configured: set SNOWFLAKE_ACCOUNT, SNOWFLAKE_USER and either "
           "SNOWFLAKE_PRIVATE_KEY_FILE or SNOWFLAKE_PASSWORD in the environment or .env. Nothing was sent.")
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")


# ---------------------------------------------------------------- settings

def _setting(name: str) -> str | None:
    return os.environ.get(name) or _dotenv_value(name) or DEFAULTS.get(name)


def settings() -> dict[str, str | None]:
    """Every SNOWFLAKE_* setting. It holds the password: never print or log it."""
    return {name: _setting(name) for name in (*REQUIRED, *SECRETS, *DEFAULTS)}


def _key_file() -> Path | None:
    value = _setting("SNOWFLAKE_PRIVATE_KEY_FILE")
    path = Path(os.path.expanduser(value)) if value else None
    return path if path and path.is_file() else None


def available() -> bool:
    return all(_setting(name) for name in REQUIRED) and bool(_key_file() or _setting("SNOWFLAKE_PASSWORD"))


def fingerprint() -> str:
    """A hash of the settings, so a cache can tell when the credentials change."""
    return hashlib.sha256(repr(sorted(settings().items())).encode()).hexdigest()


def scrub(text: str) -> str:
    """Error text with every account, user, password and role value masked."""
    s = settings()
    values = [s[name] for name in (*REQUIRED, *SECRETS, "SNOWFLAKE_ROLE") if s[name]]
    if s["SNOWFLAKE_ACCOUNT"]:
        values.append(s["SNOWFLAKE_ACCOUNT"].replace("_", "-"))  # how an account name appears in its host
    for value in sorted(set(values), key=len, reverse=True):
        text = re.sub(re.escape(value), "***", text, flags=re.IGNORECASE)
    return text


def _names() -> dict[str, str | None]:
    """Warehouse, database, schema and role, upper-cased: write_pandas quotes what it is given, so a
    lower-case name would become a different, case-sensitive object from the unquoted SQL's."""
    out: dict[str, str | None] = {}
    for key in DEFAULTS:
        value = _setting(key)
        if value is not None and not _IDENTIFIER.match(value):
            raise ValueError(f"{key} must be a plain identifier (letters, digits, _ or $)")
        out[key] = value.upper() if value else None
    return out


# -------------------------------------------------------------- connections

def connect(create: bool = False):
    """Key-pair login (or password) with the settings, then USE the database and schema (created first if `create`)."""
    if not available():
        raise RuntimeError(MISSING)
    logging.getLogger("snowflake.connector").setLevel(logging.WARNING)  # its INFO logs name the account/user
    warnings.filterwarnings("ignore", message=".*enable_server_session_keep_alive_auto_detection.*")
    import snowflake.connector

    s, n = settings(), _names()
    kwargs = dict(account=s["SNOWFLAKE_ACCOUNT"], user=s["SNOWFLAKE_USER"],
                  warehouse=n["SNOWFLAKE_WAREHOUSE"], login_timeout=30, query_tag="twin_runway")
    key = _key_file()
    if key:  # private key stays in its file outside the repo; only its path is configured
        kwargs.update(authenticator="SNOWFLAKE_JWT", private_key_file=str(key))
    else:
        kwargs["password"] = s["SNOWFLAKE_PASSWORD"]
    if n["SNOWFLAKE_ROLE"]:
        kwargs["role"] = n["SNOWFLAKE_ROLE"]
    conn = snowflake.connector.connect(**kwargs)  # database and schema may not exist yet
    try:
        db, schema = n["SNOWFLAKE_DATABASE"], n["SNOWFLAKE_SCHEMA"]
        cur = conn.cursor()
        if create:
            cur.execute(f"CREATE DATABASE IF NOT EXISTS {db}")
            cur.execute(f"CREATE SCHEMA IF NOT EXISTS {db}.{schema}")
        cur.execute(f"USE SCHEMA {db}.{schema}")
        cur.close()
    except Exception:
        conn.close()
        raise
    return conn


def _frame(name: str, data_dir: Path | str = DATA_DIR) -> pd.DataFrame:
    """A track table with UPPER-case columns, as both warehouses store it."""
    dtype = {"partner_bank": str} if name == "transactions" else None  # the brief: read partner_bank as text
    df = pd.read_csv(Path(data_dir) / f"{name}.csv", dtype=dtype)
    df.columns = [c.upper() for c in df.columns]
    return df


def load_tables(conn, tables: Sequence[str] = TABLES, data_dir: Path | str = DATA_DIR) -> dict[str, int]:
    """Upload each CSV with write_pandas (Parquet, PUT, COPY INTO), replacing the table. Returns rows per table."""
    from snowflake.connector.pandas_tools import write_pandas

    n = _names()
    rows = {}
    for name in tables:
        res = write_pandas(conn, _frame(name, data_dir), name.upper(), database=n["SNOWFLAKE_DATABASE"],
                           schema=n["SNOWFLAKE_SCHEMA"], auto_create_table=True, overwrite=True)
        if not res.success:
            raise RuntimeError(f"{name}: COPY INTO reported a failure")
        rows[name] = int(res.nrows)
    return rows


def duckdb_connect(data_dir: Path | str = DATA_DIR, tables: Sequence[str] = SQL_TABLES):
    """In-memory DuckDB holding the same upper-cased tables load_tables() sends to Snowflake."""
    import duckdb

    con = duckdb.connect()
    for name in tables:
        con.register("track_frame", _frame(name, data_dir))
        con.execute(f"CREATE TABLE {name.upper()} AS SELECT * FROM track_frame")
        con.unregister("track_frame")
    return con


def _is_duckdb(conn) -> bool:
    try:
        import duckdb
    except ImportError:
        return False
    return isinstance(conn, duckdb.DuckDBPyConnection)


def _query(conn, sql: str) -> pd.DataFrame:
    if _is_duckdb(conn):
        return conn.execute(sql).df()
    cur = conn.cursor()
    try:
        return cur.execute(sql).fetch_pandas_all()
    finally:
        cur.close()


# ---------------------------------------------------------------- the SQL

def sql_files() -> list[Path]:
    return sorted(SQL_DIR.glob("*.sql"))


def run_sql_files(conn) -> list[str]:
    """Run every file in sql/ in order, on Snowflake or DuckDB alike."""
    for path in sql_files():
        text = path.read_text()
        if _is_duckdb(conn):
            conn.execute(text)
        else:
            conn.execute_string(text, remove_comments=True, return_cursors=False)
    return [p.name for p in sql_files()]


def _by_account(df: pd.DataFrame) -> pd.DataFrame:
    df = df.rename(columns=str.upper)  # Snowflake returns UPPER case; normalise both
    out = df.set_index("ACCOUNT_ID")
    out.index = out.index.astype("int64")
    out.index.name = "account_id"
    return out.sort_index()


def fetch_metrics(conn) -> pd.DataFrame:
    """JUDGE_METRICS as the engine names it: indexed by account_id, columns I, F, S, H, B, P."""
    return _by_account(_query(conn, "SELECT * FROM JUDGE_METRICS"))[list(METRIC_COLUMNS)].astype(float)


def fetch_runway(conn) -> pd.Series:
    """EI55_RUNWAY in the engine's encoding (portfolio_runway): no shortfall = +inf."""
    df = _by_account(_query(conn, "SELECT ACCOUNT_ID, NO_SHORTFALL, RUNWAY_MONTHS FROM EI55_RUNWAY"))
    months = df["RUNWAY_MONTHS"].astype(float)
    return months.where(~df["NO_SHORTFALL"].astype(bool), np.inf).rename(LAID_OFF_EI.name)


def fetch_summary(conn) -> dict[str, float]:
    row = _query(conn, "SELECT * FROM PORTFOLIO_SUMMARY").rename(columns=str.lower).iloc[0]
    return {k: (float(v) if k.endswith("_pct") else int(v)) for k, v in row.items()}


# ----------------------------------------------------------------- parity

def _agree(a, b, columns: Sequence[str] | None = None, tol: float = TOLERANCE) -> pd.Series:
    a = a.to_frame("value") if isinstance(a, pd.Series) else a
    b = b.to_frame("value") if isinstance(b, pd.Series) else b
    cols = list(columns) if columns is not None else [c for c in a.columns if c in b.columns]
    if not cols:
        raise ValueError("no common columns to compare")
    ids = a.index.union(b.index)
    x, y = a.reindex(ids)[cols].astype(float), b.reindex(ids)[cols].astype(float)
    with np.errstate(invalid="ignore"):
        differ = ((x - y).abs() > tol) | (x.isna() != y.isna())  # inf - inf is NaN: two infs agree
    return ~differ.any(axis=1)


def parity(a, b, columns: Sequence[str] | None = None, tol: float = TOLERANCE) -> int:
    """Accounts where a and b disagree: a value differs by more than tol, or one side is missing or NaN.

    Two frames compare their common columns (or `columns`); two Series compare values. +inf equals +inf.
    """
    return int((~_agree(a, b, columns, tol)).sum())


def compare(conn, engine: pd.DataFrame | None = None) -> dict[str, float]:
    """Run sql/ on conn and check it against the Python engine. Counts only."""
    eng = build_metrics() if engine is None else engine
    run_sql_files(conn)
    sql, runway_sql, summary = fetch_metrics(conn), fetch_runway(conn), fetch_summary(conn)
    runway_eng = portfolio_runway(eng, LAID_OFF_EI)
    metrics_ok = _agree(sql, eng, METRIC_COLUMNS)
    runway_ok = _agree(runway_sql, runway_eng)
    return {
        "accounts": len(eng),
        "sql_rows": len(sql),
        "metrics_matched": int(metrics_ok.reindex(eng.index, fill_value=False).sum()),
        "metric_mismatches": int((~metrics_ok).sum()),
        "runway_matched": int(runway_ok.reindex(eng.index, fill_value=False).sum()),
        "runway_mismatches": int((~runway_ok).sum()),
        "under_6_months_sql": summary["under_6_months"],
        "under_6_months_engine": int((runway_eng < 6).sum()),
        "under_6_months_pct_sql": summary["under_6_months_pct"],
    }


def all_match(report: dict) -> bool:
    return (report["metric_mismatches"] == 0 and report["runway_mismatches"] == 0
            and report["sql_rows"] == report["accounts"]
            and report["under_6_months_sql"] == report["under_6_months_engine"])


def local_parity(engine: pd.DataFrame | None = None, data_dir: Path | str = DATA_DIR) -> dict[str, float]:
    """compare() on an in-memory DuckDB over data/raw/*.csv: no account, no network."""
    con = duckdb_connect(data_dir)
    try:
        return compare(con, engine)
    finally:
        con.close()


def duckdb_metrics(data_dir: Path | str = DATA_DIR) -> pd.DataFrame:
    """JUDGE_METRICS computed by the SQL files in DuckDB over the CSVs."""
    con = duckdb_connect(data_dir)
    try:
        run_sql_files(con)
        return fetch_metrics(con)
    finally:
        con.close()


def verify(engine: pd.DataFrame | None = None) -> dict[str, float]:
    """compare() on Snowflake. Needs `load` to have run once."""
    conn = connect()
    try:
        return compare(conn, engine)
    finally:
        conn.close()


# -------------------------------------------------------------------- CLI

def _print_report(where: str, r: dict) -> None:
    n = r["accounts"]
    print(f"{where} · judges' numbers (I, F, S, H, B, P): {r['metrics_matched']:,}/{n:,} accounts match the engine "
          f"(tolerance {TOLERANCE:g}), {r['metric_mismatches']:,} mismatches, {r['sql_rows']:,} SQL rows")
    print(f"{where} · EI 55% runway: {r['runway_matched']:,}/{n:,} accounts match, {r['runway_mismatches']:,} mismatches")
    print(f"{where} · PORTFOLIO_SUMMARY: {r['under_6_months_sql']:,} of {n:,} under 6 months "
          f"({r['under_6_months_pct_sql']:.1f}%); engine {r['under_6_months_engine']:,}")


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m resilience.warehouse",
                                description="Judges' numbers in SQL: DuckDB offline, Snowflake when configured.")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("local-parity", help="run sql/ in DuckDB over data/raw/*.csv and compare (offline)")
    load = sub.add_parser("load", help="upload the track tables to Snowflake and create the views")
    load.add_argument("--with-transactions", action="store_true", help="also upload transactions.csv (about 100 MB)")
    sub.add_parser("verify", help="compare the Snowflake views with the engine on every account")
    a = p.parse_args(argv)

    if a.cmd == "local-parity":
        report = local_parity()
        _print_report("DuckDB", report)
        return 0 if all_match(report) else 1
    if not available():
        print(MISSING, file=sys.stderr)
        return 2
    try:
        if a.cmd == "verify":
            report = verify()
            _print_report("Snowflake", report)
            return 0 if all_match(report) else 1
        conn = connect(create=True)
        try:
            tables = TABLES + (("transactions",) if a.with_transactions else ())
            for name, rows in load_tables(conn, tables).items():
                print(f"loaded {name.upper()}: {rows:,} rows")
            print("created views from " + ", ".join(run_sql_files(conn)))
        finally:
            conn.close()
        return 0
    except Exception as e:  # connector errors can echo the account or user: scrub before printing
        print(f"Snowflake {a.cmd} failed: {type(e).__name__}: {scrub(str(e))}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
