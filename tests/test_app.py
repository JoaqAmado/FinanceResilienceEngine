"""Headless run of the Streamlit app over every rehearsal and edge account and every twist card."""
from pathlib import Path

import pytest

from resilience.core import DATA_DIR

st_testing = pytest.importorskip("streamlit.testing.v1")
needs_data = pytest.mark.skipif(not (DATA_DIR / "monthly_summary.csv").exists(), reason="track data not present")

ACCOUNTS = [20331, 20143, 88269, 98952, 77743,          # rehearsal
            32078, 20578, 26939, 20303, 20866, 21903]    # overdrawn, S=0, I=0, bills by SO, stale, minor
PRESETS = ["Laid off: EI 55%", "Furnace dies: 1× spending", "Job loss + bills +15%"]


@pytest.fixture(scope="module")
def at():
    app = st_testing.AppTest.from_file(str(Path(__file__).resolve().parent.parent / "app.py"), default_timeout=120)
    app.run()
    assert not app.exception, app.exception
    return app


@needs_data
@pytest.mark.parametrize("acct", ACCOUNTS)
def test_app_runs_every_twist_with_all_checks_on(at, acct):
    for preset in PRESETS:
        at.session_state["acct"] = acct
        at.session_state["preset"] = preset
        for k, v in {"income_pct": 55 if "EI" in preset or "Job" in preset else 100,
                     "bills_pct": 15 if "bills" in preset else 0,
                     "oneoff_x": 1.0 if "Furnace" in preset else 0.0}.items():
            at.session_state[k] = v
        for toggles in (False, True):
            for t in ("t_cap", "t_ww", "t_pens", "t_s6", "t_bfb"):
                at.session_state[t] = toggles
            at.run()
            assert not at.exception, (acct, preset, toggles, at.exception)


@needs_data
def test_app_shows_judges_number_for_20331(at):
    at.session_state["acct"] = 20331
    at.session_state["preset"] = "Laid off: EI 55%"
    at.session_state["income_pct"] = 55
    at.session_state["bills_pct"] = 0
    at.session_state["oneoff_x"] = 0.0
    for t in ("t_cap", "t_ww", "t_pens", "t_s6", "t_bfb"):
        at.session_state[t] = False
    at.run()
    values = [m.value for m in at.metric]
    assert "5.1 mo" in values


@needs_data
def test_cap_does_not_touch_a_non_job_loss_twist(at):
    at.session_state["acct"] = 20143
    at.session_state["preset"] = "Furnace dies: 1× spending"
    at.session_state["income_pct"] = 100
    at.session_state["bills_pct"] = 0
    at.session_state["oneoff_x"] = 1.0
    at.session_state["t_cap"] = True
    at.run()
    runways = [m.value for m in at.metric if m.label in ("Runway", "Runway with selected checks")]
    assert runways[0] == runways[1] == "1.3 mo"
