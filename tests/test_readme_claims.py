"""Invariant 8: the portfolio tiles and charts = resilience.portfolio from the engine = data/derived/*.csv = the
numbers the README and docs/findings.md quote (1,578, 2,304, 783 and the rest). No runtime badge: tests only."""
from pathlib import Path

import pandas as pd
import pytest

from resilience.consistency import PORTFOLIO_TABLES, check_portfolio
from resilience.core import DATA_DIR, build_metrics
from resilience.portfolio import build_all

ROOT = Path(__file__).resolve().parent.parent
needs_data = pytest.mark.skipif(not (DATA_DIR / "monthly_summary.csv").exists(), reason="track data not present")


@pytest.fixture(scope="module")
def P():
    return build_all(build_metrics())


@needs_data
def test_engine_derived_csvs_readme_and_findings_agree(P):
    issues = check_portfolio(P, ROOT / "data" / "derived", readme=(ROOT / "README.md").read_text(),
                             findings=(ROOT / "docs" / "findings.md").read_text())
    assert not issues, [str(i) for i in issues]


@needs_data
def test_the_readme_numbers_are_the_engine_numbers(P):
    h = P["headlines"].iloc[0]
    acc = P["accounts"]
    safe = acc["runway_ei55"] >= 6
    assert (int(h.fail_6mo_ei55), int(h.fail_6mo_ei55_cap2026)) == (1578, 2304)
    assert (int((safe & (acc["runway_ei55_S6"] < 6)).sum()), int(safe.sum())) == (783, 2922)


@needs_data
def test_the_app_tiles_show_the_engine_numbers(P):
    st_testing = pytest.importorskip("streamlit.testing.v1")
    app = st_testing.AppTest.from_file(str(ROOT / "app.py"), default_timeout=120)
    app.run()
    assert not app.exception
    labels = [x.label for x in app.metric]
    assert check_portfolio(P, ROOT / "data" / "derived", tiles=labels) == []


@needs_data
def test_a_derived_csv_that_drifted_is_caught(P, tmp_path):
    for name in PORTFOLIO_TABLES:
        src = ROOT / "data" / "derived" / f"{name}.csv"
        (tmp_path / src.name).write_bytes(src.read_bytes())
    bands = pd.read_csv(tmp_path / "income_bands.csv")
    bands.loc[0, "fail_6mo_ei55_pct"] += 0.1
    bands.to_csv(tmp_path / "income_bands.csv", index=False)
    issues = check_portfolio(P, tmp_path, readme="no numbers here")
    assert {str(i).split(":")[1].strip().split()[0] for i in issues} >= {"income_bands.csv"}
    assert any("README doesn't quote" in str(i) for i in issues)
