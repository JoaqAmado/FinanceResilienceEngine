"""The engine must answer every account under every twist, match the judge formula, and be fast."""
import json
import math
import random
import time

import pandas as pd
import pytest

from tangerine import engine, judge_reference
from tangerine.engine import PRESETS, Shock, UnknownAccount

JUDGE_FORMULA_PRESETS = ["no_shock", "job_loss_ei55", "bills_up_15", "furnace_1_month", "job_loss_plus_bills"]


def random_shocks(n=3, seed=2026):
    rng = random.Random(seed)
    return [
        Shock(
            income_factor=rng.choice([0.0, 0.3, 0.55, 0.8]),
            duration_months=rng.choice([None, 3, 6, 12]),
            income_after_months=rng.choice([0.0, 0.5]),
            bills_increase_pct=rng.choice([0.0, 0.1, 0.25, 0.5]),
            one_off_cost=rng.choice([0.0, 1_500.0, 10_000.0]),
            one_off_months_of_spending=rng.choice([0.0, 0.5, 2.0]),
        )
        for _ in range(n)
    ]


def _has_bad_number(obj) -> bool:
    if isinstance(obj, dict):
        return any(_has_bad_number(v) for v in obj.values())
    if isinstance(obj, list):
        return any(_has_bad_number(v) for v in obj)
    return isinstance(obj, float) and not math.isfinite(obj)


@pytest.fixture(scope="module")
def ids():
    return engine.account_ids()


def test_engine_knows_all_accounts(ids):
    assert len(ids) == 4500


@pytest.mark.parametrize("shock", list(PRESETS) + random_shocks(), ids=lambda s: s if isinstance(s, str) else s.describe())
def test_run_every_account_without_error(ids, shock):
    for account_id in ids:
        result = engine.run(account_id, shock, horizon=12)
        assert not _has_bad_number(result), f"NaN/inf in output for account {account_id}"
    json.dumps(result, allow_nan=False)  # JSON-serialisable


@pytest.mark.parametrize("preset", JUDGE_FORMULA_PRESETS)
def test_engine_runway_matches_oracle(ids, preset):
    ref = judge_reference.twist_runways()[preset]
    mismatches = []
    for account_id in ids:
        got = engine.judge_runway(engine.get_profile(account_id), preset).months
        want = ref.at[account_id]
        want = None if pd.isna(want) else float(want)
        if (got is None) != (want is None) or (got is not None and abs(got - want) > 0.1 + 1e-9):
            mismatches.append((account_id, got, want))
    assert not mismatches, f"{len(mismatches)} mismatches, e.g. {mismatches[:5]}"


def test_population_anchors(ids):
    """Sanity numbers from CLAUDE.md, with the judge runway rounded to 1 decimal."""
    profiles = [engine.get_profile(a) for a in ids]
    base = [engine.judge_runway(p, "no_shock").months for p in profiles]
    ei = [engine.judge_runway(p, "job_loss_ei55").months for p in profiles]
    assert sum(r is None for r in base) == 3315          # no shortfall with no shock
    assert sum(p["buffer"] < 0 for p in profiles) == 23   # negative buffer -> runway 0 under any shock
    assert sum(r is not None and r < 3 for r in ei) == 435
    assert sum(r is not None and r < 6 for r in ei) == 1578
    assert sum(r is None for r in ei) == 234


def test_negative_buffer_gives_zero_runway(ids):
    account = next(a for a in ids if engine.get_profile(a)["buffer"] <= 0)
    result = engine.run(account, "no_shock")
    assert result["judge_runway"]["months"] == 0.0
    assert "buffer already gone" in result["judge_runway"]["label"]
    assert any("overdraft" in n for n in result["notes"])


def test_zero_income_account(ids):
    account = next(a for a in ids if engine.get_profile(a)["typical_income"] == 0)
    result = engine.run(account, "job_loss_ei55")
    assert result["profile"]["has_zero_income"] is True
    assert not _has_bad_number(result)


def test_pensioner_gets_note(ids):
    account = next(a for a in ids if engine.get_profile(a)["is_pensioner"])
    notes = engine.run(account, "job_loss_ei55")["notes"]
    assert any("Pensioner" in n and "may not apply" in n for n in notes)


def test_unknown_account_raises():
    with pytest.raises(UnknownAccount):
        engine.get_profile(1)
    with pytest.raises(UnknownAccount):
        engine.get_profile("not-a-number")


def test_unknown_preset_raises():
    with pytest.raises(ValueError):
        engine.run(engine.account_ids()[0], "alien_invasion")


def test_no_shortfall_label():
    profile = {"typical_income": 10_000, "typical_spending": 5_000, "typical_household_bills": 1_000,
               "buffer": 20_000, "lean_month_income_p25": 8_000}
    assert engine.judge_runway(profile).label == "no shortfall (120+)"
    assert engine.judge_runway(profile).months is None


def test_runway_formula_toy_cases():
    f = engine.runway_formula
    assert f(10_000, 3_000, 5_000) == 5.0            # 10k / 2k gap
    assert f(10_000, 6_000, 5_000) is None           # income covers spending
    assert f(1_000, 0, 5_000, one_off=2_000) == 0.0  # the repair wipes out the buffer
    assert f(1_000_000, 0, 10) == 120.0              # capped


def test_simulation_matches_judge_runway_for_permanent_shock(ids):
    """With a permanent shock, the balance first goes negative in month ceil(runway)."""
    for account_id in ids[:300]:
        p = engine.get_profile(account_id)
        r = engine.judge_runway(p, "job_loss_ei55")
        if r.months is None or r.months == 0 or r.months >= 24 or r.buffer_left <= 0:
            continue
        exact = r.buffer_left / r.gap
        if abs(exact - round(exact)) < 1e-6:
            continue  # lands exactly on zero; < vs <= ambiguity
        path = engine.simulate(p, "job_loss_ei55", horizon=24)
        assert engine.months_until_zero(path) == math.ceil(exact)


def test_ei_for_six_months_lasts_longer_than_ei_forever(ids):
    p = next(engine.get_profile(a) for a in ids if engine.get_profile(a)["typical_income"] > 0)
    forever = engine.simulate(p, Shock(income_factor=0.55), horizon=24)
    six = engine.simulate(p, Shock(income_factor=0.55, duration_months=6, income_after_months=1.0), horizon=24)
    assert six["balance"].iloc[-1] >= forever["balance"].iloc[-1]


def test_run_is_fast_when_warm(ids):
    engine.run(ids[0])  # warm the cache
    started = time.perf_counter()
    for account_id in ids[:100]:
        engine.run(account_id, "job_loss_plus_bills")
    per_call_ms = (time.perf_counter() - started) * 1000 / 100
    assert per_call_ms < 50, f"run() took {per_call_ms:.1f} ms per call"
