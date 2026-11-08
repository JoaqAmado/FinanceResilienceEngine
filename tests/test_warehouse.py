"""sql/ reproduces the judges' numbers: run in DuckDB here, and in Snowflake when credentials exist."""
import re
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from resilience import warehouse
from resilience.core import DATA_DIR, LAID_OFF_EI, build_metrics, portfolio_runway

needs_data = pytest.mark.skipif(not (DATA_DIR / "monthly_summary.csv").exists(), reason="track data not present")
try:
    import duckdb  # noqa: F401
    needs_duckdb = pytest.mark.skipif(False, reason="duckdb installed")
except ImportError:
    needs_duckdb = pytest.mark.skip(reason="duckdb not installed")

SETTINGS = (*warehouse.REQUIRED, *warehouse.DEFAULTS)


@pytest.fixture(scope="module")
def engine():
    return build_metrics()


@pytest.fixture(scope="module")
def duck():
    con = warehouse.duckdb_connect()
    warehouse.run_sql_files(con)
    yield con
    con.close()


@pytest.fixture
def no_credentials(monkeypatch):
    for name in SETTINGS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(warehouse, "_dotenv_value", lambda name: None)


# ------------------------------------------------- the SQL equals the engine

@needs_data
@needs_duckdb
def test_duckdb_judge_metrics_equal_engine_on_every_account(engine):
    sql = warehouse.duckdb_metrics()
    assert len(sql) == 4500 and sql.index.equals(engine.index)
    for col in warehouse.METRIC_COLUMNS:
        assert (sql[col] - engine[col]).abs().max() < 1e-6, col
    assert warehouse.parity(sql, engine) == 0


@needs_data
@needs_duckdb
def test_duckdb_ei55_runway_equals_engine(duck, engine):
    sql = warehouse.fetch_runway(duck)
    eng = portfolio_runway(engine, LAID_OFF_EI)
    assert warehouse.parity(sql, eng) == 0
    assert int(np.isinf(sql).sum()) == int(np.isinf(eng).sum())  # no shortfall (120+)


@needs_data
@needs_duckdb
def test_portfolio_summary_counts(duck, engine):
    s = warehouse.fetch_summary(duck)
    eng = portfolio_runway(engine, LAID_OFF_EI)
    assert s["accounts"] == 4500
    assert s["under_6_months"] == int((eng < 6).sum()) == 1578
    assert s["under_6_months_pct"] == 35.1
    assert s["buffer_gone"] == int((engine["B"] <= 0).sum())
    assert s["no_shortfall_accounts"] == int(np.isinf(eng).sum())


@needs_data
@needs_duckdb
def test_local_parity_report_is_all_matches(engine):
    r = warehouse.local_parity(engine)
    assert r["metrics_matched"] == r["runway_matched"] == r["accounts"] == r["sql_rows"] == 4500
    assert r["metric_mismatches"] == r["runway_mismatches"] == 0
    assert r["under_6_months_sql"] == r["under_6_months_engine"] == 1578
    assert warehouse.all_match(r)


@needs_data
def test_no_runway_sits_near_a_rounding_tie(engine):
    # SQL ROUND sends a .x5 tie away from zero, numpy to even. No account is within 1e-9 of a tie under
    # EI 55%, so the 1-decimal runway is the same under any rounding rule (sql/20_ei55_runway.sql).
    gap = engine["S"] - 0.55 * engine["I"]
    ok = (engine["B"] > 0) & (gap > 0)
    y = np.minimum(engine["B"][ok] / gap[ok], 120) * 10
    assert int((np.abs(y - np.floor(y) - 0.5) < 1e-9).sum()) == 0


# ---------------------------------------------------------------- parity()

def test_parity_counts_each_disagreeing_account():
    a = pd.DataFrame({"I": [1.0, 2.0, 3.0], "B": [0.0, 1.0, np.inf]}, index=[1, 2, 3])
    assert warehouse.parity(a, a) == 0
    assert warehouse.parity(a, a + 1e-9) == 0                     # inside the tolerance
    b = a.copy()
    b.loc[2, "I"] += 1e-3                                          # a value off
    assert warehouse.parity(a, b) == 1
    assert warehouse.parity(a, b.drop(index=3)) == 2               # and an account missing
    assert warehouse.parity(a, b.assign(B=[0.0, 1.0, 5.0]), columns=["B"]) == 1  # inf vs a number


def test_parity_on_series_treats_two_infs_as_equal():
    s = pd.Series([np.inf, 2.2, 0.0])
    assert warehouse.parity(s, s.copy()) == 0
    assert warehouse.parity(s, pd.Series([np.inf, 2.3, 0.0])) == 1
    assert warehouse.parity(s, pd.Series([np.nan, 2.2, 0.0])) == 1


# ------------------------------------------------------------- portability

def test_sql_files_are_portable():
    files = warehouse.sql_files()
    assert [p.name for p in files] == ["10_judge_metrics.sql", "20_ei55_runway.sql"]
    one_dialect = r"\b(IFF|DIV0|NVL|NVL2|ZEROIFNULL|QUANTILE\w*|LIST_\w+|STRUCT_PACK|STRFTIME|TO_CHAR|DATEADD)\s*\("
    for path in files:
        text = path.read_text()
        code = "\n".join(line.split("--")[0] for line in text.splitlines())
        comments = "\n".join(line.split("--", 1)[1] for line in text.splitlines() if "--" in line)
        assert '"' not in code, f"{path.name}: quoted identifier"          # Snowflake would make it case-sensitive
        assert "::" not in code, f"{path.name}: shorthand cast"
        assert not re.search(one_dialect, code, re.IGNORECASE), path.name
        assert "'" not in comments and ";" not in comments, f"{path.name}: a quote or ; in a comment"


def test_sql_splits_into_the_expected_statements_for_snowflake():
    split = pytest.importorskip("snowflake.connector._internal.text_utils").split_statements
    from io import StringIO
    heads = []
    for path in warehouse.sql_files():
        heads += [s.split(" AS")[0] for s, _ in split(StringIO(path.read_text()), remove_comments=True) if s]
    assert heads == ["CREATE OR REPLACE VIEW JUDGE_METRICS", "CREATE OR REPLACE VIEW EI55_RUNWAY",
                     "CREATE OR REPLACE VIEW PORTFOLIO_SUMMARY"]


# -------------------------------------------------------- settings, secrets

def test_settings_defaults_and_available(no_credentials, monkeypatch):
    assert not warehouse.available()
    s = warehouse.settings()
    assert (s["SNOWFLAKE_WAREHOUSE"], s["SNOWFLAKE_DATABASE"], s["SNOWFLAKE_SCHEMA"]) == ("COMPUTE_WH", "TANGERINE", "PUBLIC")
    assert s["SNOWFLAKE_ROLE"] is None
    before = warehouse.fingerprint()
    for name in (*warehouse.REQUIRED, "SNOWFLAKE_PASSWORD"):
        monkeypatch.setenv(name, f"fake-{name.lower()}")
    assert warehouse.available() and warehouse.fingerprint() != before


def test_lower_case_names_are_upper_cased_and_odd_ones_refused(no_credentials, monkeypatch):
    monkeypatch.setenv("SNOWFLAKE_DATABASE", "tangerine_dev")
    assert warehouse._names()["SNOWFLAKE_DATABASE"] == "TANGERINE_DEV"
    monkeypatch.setenv("SNOWFLAKE_SCHEMA", "public; drop table x")
    with pytest.raises(ValueError):
        warehouse._names()


def test_cli_without_credentials_sends_nothing_and_prints_no_values(no_credentials, monkeypatch, capsys):
    monkeypatch.setenv("SNOWFLAKE_ACCOUNT", "acct-sentinel-123")  # user and password still missing
    monkeypatch.setattr(warehouse, "connect", lambda *a, **k: pytest.fail("connect() must not be called"))
    for cmd in ("verify", "load"):
        assert warehouse.main([cmd]) == 2
    out = capsys.readouterr()
    assert "acct-sentinel-123" not in out.out + out.err and "SNOWFLAKE_PASSWORD" in out.err


def test_scrub_masks_every_credential(no_credentials, monkeypatch):
    monkeypatch.setenv("SNOWFLAKE_ACCOUNT", "xy12345")
    monkeypatch.setenv("SNOWFLAKE_USER", "marco_test")
    monkeypatch.setenv("SNOWFLAKE_PASSWORD", "pw-sentinel!")
    msg = "250001: Could not connect to XY12345.snowflakecomputing.com as MARCO_TEST (pw-sentinel!)"
    clean = warehouse.scrub(msg)
    assert not re.search("xy12345|marco_test|pw-sentinel", clean, re.IGNORECASE) and "250001" in clean
    monkeypatch.setenv("SNOWFLAKE_ACCOUNT", "myorg_acct1")
    assert "myorg" not in warehouse.scrub("host myorg-acct1.snowflakecomputing.com and MYORG_ACCT1").lower()


def test_cli_failure_message_is_scrubbed(no_credentials, monkeypatch, capsys):
    monkeypatch.setenv("SNOWFLAKE_ACCOUNT", "xy12345")
    monkeypatch.setenv("SNOWFLAKE_USER", "marco_test")
    monkeypatch.setenv("SNOWFLAKE_PASSWORD", "pw-sentinel!")

    def boom(*a, **k):
        raise RuntimeError("login failed for MARCO_TEST at xy12345 with pw-sentinel!")
    monkeypatch.setattr(warehouse, "connect", boom)
    assert warehouse.main(["verify"]) == 1
    out = capsys.readouterr()
    assert "login failed" in out.err and not re.search("xy12345|marco_test|pw-sentinel", out.out + out.err, re.I)


# ----------------------------------------------------------------- the app

APP = str(Path(__file__).resolve().parent.parent / "app.py")


def _run_app():
    st_testing = pytest.importorskip("streamlit.testing.v1")
    app = st_testing.AppTest.from_file(APP, default_timeout=120)
    app.run()
    return app


def _method_panel(app):
    assert not app.exception, app.exception
    assert any(e.label == "Computed in Snowflake" for e in app.expander)
    return " ".join(c.value for c in app.caption), " ".join(s.value for s in app.success)


@needs_data
def test_app_never_touches_snowflake_without_credentials(no_credentials, monkeypatch):
    monkeypatch.setattr(warehouse, "connect", lambda *a, **k: pytest.fail("connect() must not be called"))
    monkeypatch.setattr(warehouse, "verify", lambda *a, **k: pytest.fail("verify() must not be called"))
    captions, _ = _method_panel(_run_app())
    assert "DuckDB" in captions and "local-parity" in captions


@needs_data
def test_app_shows_the_snowflake_match_count(no_credentials, monkeypatch):
    for name in (*warehouse.REQUIRED, "SNOWFLAKE_PASSWORD"):
        monkeypatch.setenv(name, f"app-test-{name.lower()}")  # fresh fingerprint: no cached result reused
    report = {"accounts": 4500, "sql_rows": 4500, "metrics_matched": 4500, "metric_mismatches": 0,
              "runway_matched": 4500, "runway_mismatches": 0, "under_6_months_sql": 1578,
              "under_6_months_engine": 1578, "under_6_months_pct_sql": 35.1}
    monkeypatch.setattr(warehouse, "verify", lambda engine=None: report)
    _, success = _method_panel(_run_app())
    assert "Snowflake judges' numbers match the engine on 4,500/4,500 accounts" in success


# ------------------------------------------------------- live, opt-in only

@needs_data
@pytest.mark.live
@pytest.mark.skipif(not warehouse.available(), reason="no Snowflake credentials (SNOWFLAKE_ACCOUNT/USER + key file or password)")
def test_snowflake_matches_engine_on_every_account(engine):
    r = warehouse.verify(engine)  # needs `python -m resilience.warehouse load` once
    assert r["sql_rows"] == r["metrics_matched"] == 4500 and r["metric_mismatches"] == 0
    assert r["runway_mismatches"] == 0, "see the rounding note in sql/20_ei55_runway.sql"
    assert r["under_6_months_sql"] == 1578
