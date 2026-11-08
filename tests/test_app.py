"""The 90-day plan app: every account under every twist card, numbers traced to the engine, API errors."""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # make `app` importable

from app.main import SHOWCASE, app  # noqa: E402
from app.plan90 import build_90_day_plan  # noqa: E402
from tangerine import engine  # noqa: E402
from tangerine.engine import PRESETS  # noqa: E402

client = TestClient(app)


@pytest.mark.parametrize("preset", list(PRESETS))
def test_every_account_gets_a_plan(preset):
    """All 4,500 accounts x every twist card: a plan with steps, no errors."""
    for account_id in engine.account_ids():
        plan = build_90_day_plan(engine.run(account_id, preset))
        assert plan["prevent"]["steps"], account_id
        assert plan["survive"]["steps"], account_id
        assert len(plan["survive"]["checkpoints"]) == 3, account_id


def test_numbers_trace_to_the_engine():
    """Prevent checkpoints use the engine's monthly saving; survive uses the engine's simulated balance."""
    checked = 0
    for account_id in engine.account_ids()[:500]:
        result = engine.run(account_id, "job_loss_ei55")
        plan = build_90_day_plan(result)
        saving = result["plan"]["monthly_saving"]
        if saving:
            b = result["profile"]["buffer"]
            assert [c["balance"] for c in plan["prevent"]["checkpoints"]] == pytest.approx(
                [b + saving, b + 2 * saving, b + 3 * saving], abs=0.01)
            checked += 1
        shocked = {r["month"]: r["balance"] for r in result["simulation"]["rows"] if r["scenario"] == "shocked"}
        assert [c["balance"] for c in plan["survive"]["checkpoints"]] == [shocked[1], shocked[2], shocked[3]]
        assert plan["survive"]["runway_without_cuts"] == result["judge_runway"]["label"]
    assert checked > 0


def test_api_preset_matches_engine():
    for account_id in SHOWCASE.values():
        r = client.get(f"/api/plan/{account_id}", params={"preset": "job_loss_plus_bills"})
        assert r.status_code == 200
        body = r.json()
        direct = engine.run(account_id, "job_loss_plus_bills")
        assert body["judge_runway"] == direct["judge_runway"]  # judge number untouched
        assert body["stress_runway"] == direct["stress_runway"]
        assert "ninety_day_plan" in body


def test_api_custom_shock():
    r = client.get(f"/api/plan/{SHOWCASE['Volatile cash earner']}",
                   params={"income_factor": 0.55, "duration_months": 6, "bills_increase_pct": 0.2,
                           "one_off_months_of_spending": 1})
    assert r.status_code == 200
    s = r.json()["shock"]
    assert (s["income_factor"], s["duration_months"], s["bills_increase_pct"]) == (0.55, 6, 0.2)


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


def test_page_and_meta():
    assert "90-day resilience plan" in client.get("/").text
    meta = client.get("/api/meta").json()
    assert meta["account_count"] == 4500
    assert set(meta["presets"]) == set(PRESETS)
