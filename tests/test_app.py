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


@needs_data
def test_portfolio_shows_the_2025_backtest_evidence():
    from resilience import evidence as E
    app = _fresh()
    assert not app.exception
    want = E.lines(E.build_evidence())
    captions = " ".join(c.value for c in app.caption)
    for key in ("passed", "lift", "irregular", "irregular_caveat", "s6"):
        assert want[key] in captions, key
    heads = [m.value for m in app.markdown if m.value.startswith("#### ")]
    assert heads[:2] == ["#### 1 · The judges' test misses people: who went overdrawn in 2025",
                         "#### 2 · A second finding: irregular money in"]


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


# --------------------------------------------- early-warning light

@needs_data
def test_early_warning_light_renders_beside_the_runway():
    app = _fresh()
    app.number_input(key="acct").set_value(77743).run()
    assert not app.exception
    line = [w.value for w in app.warning if w.value.startswith("Early-warning light")]
    assert line == ["Early-warning light 3/4: lowest balance under half a month of spending; almost all spending is "
                    "cash; irregular money in. In the 2025 backtest, 15 of 146 accounts with 3 points went "
                    "overdrawn (10.3%)."]
    box = [e for e in app.expander if e.label.startswith("Early-warning light")][0]
    rules, tiers = box.dataframe[0].value, box.dataframe[1].value
    assert list(rules["fired"]) == ["⚠️ fired", "⚠️ fired", "⚠️ fired", "not fired"]
    assert list(tiers["share"]) == ["0.08%", "2.2%", "7.1%", "10.3%", "46.7%"]
    caption = box.caption[-1].value
    assert "3,847 accounts" in caption and "75 of them went overdrawn" in caption
    # the backtest needed 6 rows after the opening month (7+ months counting it), not 6 months of history
    assert "accounts with 6+ months after the opening month that had never gone below zero" in caption
    assert "months of history" not in caption


@needs_data
def test_early_warning_light_says_already_overdrawn_without_a_rate():
    app = _fresh()                                                     # 20331 by default
    line = [x.value for x in [*app.warning, *app.info] if x.value.startswith("Early-warning light")]
    assert len(line) == 1 and "2/4" in line[0] and "Already overdrawn before" in line[0]
    assert "In the 2025 backtest" not in line[0]                      # no tier rate for an account outside it
    assert _runway(app) == "5.1 mo"                                    # the judges' number is untouched


@needs_data
def test_early_warning_light_gives_a_stale_account_no_backtest_rate():
    app = _fresh()
    app.number_input(key="acct").set_value(99477).run()                # activity stops 2024-03
    assert not app.exception
    warnings = [w.value for w in app.warning]
    assert "Account activity stops in 2024-03: the buffer may be out of date." in warnings
    line = [w for w in warnings if w.startswith("Early-warning light")]
    assert len(line) == 1 and line[0].startswith("Early-warning light 3/4: ")
    assert "Activity stops in 2024-03: the points are from the account's last 6 months up to then" in line[0]
    assert "In the 2025 backtest" not in line[0]


@needs_data
def test_early_warning_light_names_its_own_month_of_spending():
    app = _fresh()
    app.number_input(key="acct").set_value(55819).run()
    assert not app.exception
    assert [m for m in app.metric if m.label == "Buffer (B)"][0].delta == "0.3 months of spending"
    box = [e for e in app.expander if e.label.startswith("Early-warning light")][0]
    assert list(box.dataframe[0].value["this account"])[0] == "116.96 months of spending"
    assert box.caption[0].value == ("In the lowest-balance and balance-trend rules, a month of spending is this "
                                    "account's median money out over the same 6 months: $9.19. That is not the "
                                    "card's S (the median over all history), so these months can differ from "
                                    "the Buffer's.")


@needs_data
def test_early_warning_light_not_enough_history_names_the_light(monkeypatch):
    # no shipped account is short today, so the app is given one: opening month + 5 rows
    from resilience import warning as W
    monkeypatch.setattr(W, "account_light", lambda monthly, a, bt, snapshot=None: W.Light(
        int(a), W.NOT_ENOUGH_HISTORY, 5, None, (), None, "2025-12", 100.0))
    app = _fresh()
    assert not app.exception
    line = [x.value for x in app.info if "Not enough history" in x.value]
    assert line == ["Early-warning light: Not enough history: the light needs 6 months after the opening month "
                    "and this account has 5, so no points or backtest rate."]
