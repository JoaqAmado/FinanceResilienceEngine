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


# ------------------------------------------------ regressions from mock judging

def _fresh():
    app = st_testing.AppTest.from_file(str(Path(__file__).resolve().parent.parent / "app.py"), default_timeout=120)
    app.run()
    return app


def _runway(app):
    return [m.value for m in app.metric if m.label == "Runway"][0]


def _story_headline(app):
    return [m.value for m in app.markdown if m.value.startswith("**Account ")][0]


@needs_data
def test_custom_starts_from_no_shock():
    app = _fresh()
    app.session_state["acct"] = 72845
    app.radio(key="preset").set_value("Custom").run()
    app.radio(key="oneoff_mode").set_value("$ amount").run()
    app.number_input(key="oneoff_amt").set_value(6000.0).run()
    assert not app.exception
    assert _runway(app) == "No shortfall (120+)"  # a $6,000 repair alone; income is NOT still at EI 55%


@needs_data
def test_furnace_one_off_survives_toggling_the_mode():
    app = _fresh()
    app.session_state["acct"] = 36427
    app.radio(key="preset").set_value("Furnace dies: 1× spending").run()
    before = _runway(app)
    app.radio(key="oneoff_mode").set_value("$ amount").run()
    app.radio(key="oneoff_mode").set_value("× typical spending").run()
    assert before == "3.6 mo" and _runway(app) == "3.6 mo"


@needs_data
def test_label_follows_the_levers_not_the_card():
    app = _fresh()
    app.session_state["acct"] = 91609
    app.slider(key="income_pct").set_value(100).run()
    app.number_input(key="extra").set_value(400.0).run()
    head = _story_headline(app)
    assert "Laid off" not in head and "+$400/mo" in head


@needs_data
def test_new_account_resets_levers_to_the_card():
    app = _fresh()
    app.session_state["acct"] = 82232
    app.number_input(key="extra").set_value(250.0).run()
    app.number_input(key="acct").set_value(40462).run()
    assert app.session_state["extra"] == 0.0


@needs_data
def test_overdrawn_and_loan_in_default_messages():
    app = _fresh()
    app.number_input(key="acct").set_value(75489).run()
    errors = " ".join(e.value for e in app.error)
    assert "ALREADY OVERDRAWN" in errors and "one-off ($0)" not in errors
    text = " ".join(m.value for m in app.markdown)
    assert "Line of Credit" not in text and "no new credit" in text


@needs_data
def test_pay_cut_is_not_an_ei_job_loss():
    app = _fresh()
    app.session_state["acct"] = 79750
    app.radio(key="preset").set_value("Custom").run()
    app.slider(key="income_pct").set_value(70).run()
    assert not app.session_state["job_loss"]
    assert [t for t in app.toggle if t.key == "t_cap"][0].disabled


@needs_data
def test_portfolio_labels_are_integers():
    app = _fresh()
    labels = " ".join(m.label for m in app.metric)
    assert "1,578 of 4,500" in labels and ".0" not in labels.replace("4,500", "")


# --------------------------------------------- regressions from the re-verification pass

@needs_data
def test_pay_cut_goal_is_sized_on_the_deeper_cut():
    app = _fresh()
    app.session_state["acct"] = 20401
    app.radio(key="preset").set_value("Custom").run()
    app.slider(key="income_pct").set_value(30).run()
    fund = [m for m in app.metric if m.label.startswith("Job-loss-proof fund")][0]
    assert _runway(app) == "3.8 mo" and "already in place" not in str(fund.delta)


@needs_data
def test_card_identical_shock_keeps_the_card_name():
    app = _fresh()
    app.session_state["acct"] = 20331
    app.radio(key="oneoff_mode").set_value("$ amount").run()   # $0 one-off: still exactly the EI card
    assert "Laid off: EI 55%" in _story_headline(app)


@needs_data
def test_no_ei_claim_advice_on_a_non_job_loss_card_for_loan_in_default():
    app = _fresh()
    app.number_input(key="acct").set_value(91609).run()
    app.radio(key="preset").set_value("Furnace dies: 1× spending").run()
    text = " ".join(m.value for m in app.markdown)
    assert "no new credit" in text and "EI claim" not in text
