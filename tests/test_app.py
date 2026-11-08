"""The resilience plan app: every account under every twist card, numbers traced to the engine and marts, API errors."""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # make `app` importable

from app.main import APP_PRESETS, HORIZON_MONTHS, SHOWCASE, app  # noqa: E402
from app.plan import build_look_back, build_next_12_months  # noqa: E402
from tangerine import engine, history  # noqa: E402
from tangerine.engine import Shock  # noqa: E402

client = TestClient(app)


def _plan(account_id, shock):
    result = engine.run(account_id, shock, horizon=HORIZON_MONTHS)
    look_back = build_look_back(result, history.recent_months(account_id))
    return result, look_back, build_next_12_months(result, look_back)


@pytest.mark.parametrize("shock", APP_PRESETS + [
    Shock(income_factor=0.55, duration_months=6, bills_increase_amount=250, one_off_cost=4000),
    Shock(bills_increase_amount=1000),
], ids=lambda s: s if isinstance(s, str) else s.describe())
def test_every_account_gets_a_plan(shock):
    """All 4,500 accounts x every app twist card (+ custom shocks): look back + 4 phases, no errors."""
    for account_id in engine.account_ids():
        _, look_back, nxt = _plan(account_id, shock)
        assert look_back["lessons"], account_id
        assert [ph["title"] for ph in nxt["phases"]] == ["React", "Hold the line", "Adjust", "Rebuild"]
        assert all(ph["steps"] for ph in nxt["phases"]), account_id


def test_look_back_matches_the_mart(con):
    """Look-back months are the account's last 6 rows of marts.fact_account_month, unchanged."""
    for account_id in SHOWCASE.values():
        expected = con.execute(
            "select month, money_in, money_out, net_cash_flow, days_below_zero from marts.fact_account_month "
            "where account_id = ? order by month desc limit 6", [account_id]).fetchall()[::-1]
        result, look_back, _ = _plan(account_id, "job_loss_ei55")
        got = [(m["month"], m["money_in"], m["money_out"], m["net"], m["days_below_zero"]) for m in look_back["months"]]
        assert got == [(m, round(i, 2), round(o, 2), round(n, 2), d) for m, i, o, n, d in expected]
        assert look_back["stats"]["total_net"] == pytest.approx(sum(r[3] for r in expected), abs=0.01)


def test_checkpoints_trace_to_the_simulation():
    """Phase checkpoints are the engine's simulated balances at months 3, 6, 12."""
    for account_id in engine.account_ids()[:300]:
        result, _, nxt = _plan(account_id, "job_loss_ei55")
        path = {(r["scenario"], r["month"]): r["balance"] for r in result["simulation"]["rows"]}
        for ph in nxt["phases"][1:]:
            c = ph["checkpoint"]
            assert c["without_cuts"] == path[("shocked", c["month"])]
            assert c["with_plan"] == path[("with_plan", c["month"])]
        assert nxt["runway_without_cuts"] == result["judge_runway"]["label"]
        assert max(r["month"] for r in result["simulation"]["rows"]) == 12


def test_plan_path_applies_the_backup_cut():
    p = engine.get_profile(SHOWCASE["Volatile cash earner"])
    path = engine.simulate(p, "job_loss_ei55", horizon=12, discretionary_cut=0.3)
    shocked = path[path.scenario == "shocked"].set_index("month").spending
    planned = path[path.scenario == "with_plan"].set_index("month").spending
    assert (shocked - planned).loc[1:].round(6).eq(round(0.3 * p["typical_discretionary_spending"], 6)).all()


def test_bills_amount_adds_dollars_to_spending():
    p = engine.get_profile(20111)
    base = engine.judge_runway(p, Shock())
    more = engine.judge_runway(p, Shock(bills_increase_amount=300))
    assert more.spending_after == pytest.approx(base.spending_after + 300)
    # The judge preset is unaffected by the new field
    assert engine.judge_runway(p, "bills_up_15").spending_after == pytest.approx(
        p["typical_spending"] + 0.15 * p["typical_household_bills"])


def test_api_preset_matches_engine():
    for account_id in SHOWCASE.values():
        r = client.get(f"/api/plan/{account_id}", params={"preset": "job_loss_ei55"})
        assert r.status_code == 200
        body = r.json()
        direct = engine.run(account_id, "job_loss_ei55", horizon=HORIZON_MONTHS)
        assert body["judge_runway"] == direct["judge_runway"]  # judge number untouched
        assert body["stress_runway"] == direct["stress_runway"]
        assert set(body["resilience_plan"]) == {"look_back", "next_12_months"}


def test_api_custom_shock():
    r = client.get(f"/api/plan/{SHOWCASE['Volatile cash earner']}",
                   params={"income_factor": 0.55, "duration_months": 6, "bills_increase_amount": 250,
                           "one_off_cost": 4000})
    assert r.status_code == 200
    body = r.json()
    s = body["shock"]
    assert (s["income_factor"], s["duration_months"], s["bills_increase_amount"], s["one_off_cost"]) == (0.55, 6, 250, 4000)
    assert body["judge_runway"]["one_off_cost"] == 4000


def test_unknown_account_suggests_real_ones():
    ids = set(engine.account_ids())
    for guess in (1, 12345, 50000, 99999, 999999999):
        assert guess not in ids
        r = client.get(f"/api/plan/{guess}")
        assert r.status_code == 404
        suggestions = r.json()["detail"]["suggestions"]
        assert suggestions and all(s in ids for s in suggestions)
        assert client.get(f"/api/plan/{suggestions[0]}").status_code == 200


def test_accounts_list():
    ids = client.get("/api/accounts").json()
    assert len(ids) == 4500 and ids == sorted(ids)


def test_api_errors():
    assert client.get("/api/plan/999999999").status_code == 404
    assert client.get("/api/plan/abc").status_code == 422
    assert client.get("/api/plan/20111", params={"preset": "meteor"}).status_code == 400
    assert client.get("/api/plan/20111", params={"income_factor": -1}).status_code == 422
    assert client.get("/api/plan/20111", params={"bills_increase_amount": -5}).status_code == 422


def test_other_uis_can_call_the_api():
    """CORS: a front end on another origin (e.g. the React app on :5173) is allowed to read the API."""
    r = client.get("/api/meta", headers={"Origin": "http://localhost:5173"})
    assert r.headers["access-control-allow-origin"] in ("*", "http://localhost:5173")
    assert client.get("/openapi.json").json()["paths"].keys() >= {"/api/meta", "/api/accounts", "/api/plan/{account_id}"}


def test_page_and_meta():
    assert "Resilience plan" in client.get("/").text
    meta = client.get("/api/meta").json()
    assert meta["account_count"] == 4500
    assert list(meta["presets"]) == APP_PRESETS


def test_typed_numbers_match_the_judges_cards():
    """Typing 15 (% of bills) or one month of spending ($) gives the same runway as the judges' preset cards."""
    for account_id in SHOWCASE.values():
        p = engine.get_profile(account_id)
        typed_bills = client.get(f"/api/plan/{account_id}", params={"bills_increase_pct": 0.15}).json()
        card_bills = engine.run(account_id, "bills_up_15", horizon=HORIZON_MONTHS)
        assert typed_bills["judge_runway"] == card_bills["judge_runway"]
        typed_repair = client.get(f"/api/plan/{account_id}",
                                  params={"one_off_cost": p["typical_spending"]}).json()
        card_repair = engine.run(account_id, "furnace_1_month", horizon=HORIZON_MONTHS)
        assert typed_repair["judge_runway"]["months"] == card_repair["judge_runway"]["months"]


def test_check_engine_zones_match_the_f10_test(con):
    """The light's zones are the F10 stress-runway quartiles (red = Q1, amber = Q2, green = Q3 + Q4)."""
    from tangerine import check_engine
    q = con.execute("select loans, defaults, min_value from marts.mart_default_drivers "
                    "where driver = 'stress_runway_with_loan' order by group_order").fetchall()
    red, amber, green = check_engine.zones()
    assert (red["loans"], red["defaults"]) == (q[0][0], q[0][1])
    assert (amber["loans"], amber["defaults"]) == (q[1][0], q[1][1])
    assert (green["loans"], green["defaults"]) == (q[2][0] + q[3][0], q[2][1] + q[3][1])
    assert red["to_months"] == amber["from_months"] == q[1][2] and amber["to_months"] == q[2][2]
    assert sum(z["loans"] for z in (red, amber, green)) == 682


def test_check_engine_light_in_the_api():
    from tangerine import check_engine
    red, amber, green = check_engine.zones()
    assert check_engine.light(0.0)["zone"] == "red"
    assert check_engine.light(red["to_months"])["zone"] == "amber"   # boundary goes to the higher zone
    assert check_engine.light(amber["to_months"])["zone"] == "green"
    assert check_engine.light(None)["zone"] == "green"                # no shortfall
    for account_id in SHOWCASE.values():
        ce = client.get(f"/api/plan/{account_id}", params={"preset": "job_loss_ei55"}).json()["check_engine"]
        expected = engine.stress_runway(engine.get_profile(account_id), "no_shock").months
        assert ce["stress_runway_months"] == expected                  # always the NO-shock stress runway
        assert ce["zone"] == check_engine.light(expected)["zone"]
