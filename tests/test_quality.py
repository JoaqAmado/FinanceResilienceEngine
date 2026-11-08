"""Every data-quality check in sql/90_quality must return 0 rows."""
import pytest

from tangerine import config, pipeline

CHECKS = pipeline.sql_files(config.SQL_QUALITY_FOLDER)


@pytest.mark.parametrize("check", CHECKS, ids=[p.name for p in CHECKS])
def test_quality_check_returns_no_rows(con, check):
    bad_rows = con.execute(pipeline.render_sql(check.read_text(encoding="utf-8"))).fetchall()
    assert bad_rows == [], f"{check.name} found {len(bad_rows)} bad rows, e.g. {bad_rows[:3]}"


def test_there_are_quality_checks():
    assert len(CHECKS) >= 10
