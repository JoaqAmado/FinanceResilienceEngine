"""Gemini layer: never breaks the demo, never lets a made-up number through."""
import json

import pytest

from resilience import llm
from resilience.narrative import numbers_ok

FACTS = {"account_id": 98952, "judge_runway": "4.2 months", "income_after": "$2,153", "goal_target": "$12,722",
         "target_months": "6", "reality": {"pension kept": "23.4 months"}}
GOOD = {"headline": "Your runway is 4.2 months, short of the 6-month test.", "what_changed": "Income drops to $2,153.",
        "reality_check": "Keeping the pension gives 23.4 months.", "plan_steps": ["Save toward $12,722."],
        "caveat": "Judges' formula."}


def test_guard_accepts_only_numbers_from_facts():
    assert numbers_ok(GOOD, FACTS)
    bad = dict(GOOD, what_changed="Income drops to $2,000.")
    assert not numbers_ok(bad, FACTS)


def test_no_key_uses_template(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(llm, "_dotenv_value", lambda name: None)
    monkeypatch.setattr(llm, "api_key", lambda: None)
    story, status = llm.gemini_story(FACTS)
    assert story is None and "template" in status


class _Resp:
    def __init__(self, text):
        self.text = text


def _fake_client(payload):
    class Models:
        calls = 0

        def generate_content(self, model, contents, config):
            Models.calls += 1
            return _Resp(json.dumps(payload))

    class Client:
        def __init__(self, *a, **k):
            self.models = Models()
    return Client, Models


@pytest.fixture
def keyed(monkeypatch, tmp_path):
    monkeypatch.setattr(llm, "api_key", lambda: "test-key")
    monkeypatch.setattr(llm, "CACHE", tmp_path / "cache.json")


def test_good_story_is_used_and_cached(keyed, monkeypatch):
    from google import genai
    Client, Models = _fake_client(GOOD)
    monkeypatch.setattr(genai, "Client", Client)
    story, status = llm.gemini_story(FACTS)
    assert story == GOOD and status.startswith("Gemini")
    story2, status2 = llm.gemini_story(FACTS)
    assert story2 == GOOD and "cached" in status2 and Models.calls == 1


def test_invented_number_falls_back(keyed, monkeypatch):
    from google import genai
    Client, _ = _fake_client(dict(GOOD, plan_steps=["Cut $999 a month."]))
    monkeypatch.setattr(genai, "Client", Client)
    story, status = llm.gemini_story(FACTS)
    assert story is None and "failed the checks" in status


def test_headline_without_runway_falls_back(keyed, monkeypatch):
    from google import genai
    Client, _ = _fake_client(dict(GOOD, headline="Reviewing your financial runway"))
    monkeypatch.setattr(genai, "Client", Client)
    story, status = llm.gemini_story(FACTS)
    assert story is None and "failed the checks" in status


def test_api_error_falls_back(keyed, monkeypatch):
    from google import genai

    class Boom:
        def __init__(self, *a, **k):
            raise RuntimeError("network down")
    monkeypatch.setattr(genai, "Client", Boom)
    story, status = llm.gemini_story(FACTS)
    assert story is None and "unavailable" in status


def test_template_story_passes_its_own_guard_on_real_accounts():
    from resilience.core import DATA_DIR
    if not (DATA_DIR / "monthly_summary.csv").exists():
        pytest.skip("track data not present")
    from resilience import LAID_OFF_EI, FURNACE, apply_shock, backup_ladder, build_metrics, calendar_path, goal_plan
    from resilience.narrative import facts, template_story
    m = build_metrics()
    for acct in (20331, 20143, 88269, 98952, 77743, 32078, 20578):
        r = m.loc[acct]
        for shock in (LAID_OFF_EI, FURNACE):
            judge = apply_shock(r, shock)
            g = goal_plan(r, 6, target_kind="ei_proof")
            f = facts(acct, r, shock, judge, {"starting in January": calendar_path(r, shock)},
                      backup_ladder(r, shock, 6), g.target_buffer, g.shortfall, g.months_to_target, 6)
            assert numbers_ok(template_story(f), f), (acct, shock.name)


def test_retry_recovers_from_one_bad_output(keyed, monkeypatch):
    from google import genai
    outputs = [dict(GOOD, headline="Reviewing your financial runway"), GOOD]

    class Models:
        calls = 0

        def generate_content(self, model, contents, config):
            Models.calls += 1
            return _Resp(json.dumps(outputs[min(Models.calls - 1, 1)]))

    class Client:
        def __init__(self, *a, **k):
            self.models = Models()
    monkeypatch.setattr(genai, "Client", Client)
    story, status = llm.gemini_story(FACTS)
    assert story == GOOD and Models.calls == 2


def test_timeout_is_not_retried(keyed, monkeypatch):
    """A network that hangs: one timeout, not three in a row (the demo would freeze for 3x the timeout)."""
    from google import genai

    class ReadTimeout(Exception):
        pass
    attempts = []

    class Hangs:
        def __init__(self, *a, **k):
            attempts.append(1)
            raise ReadTimeout("timed out")
    monkeypatch.setattr(genai, "Client", Hangs)
    story, status = llm.gemini_story(FACTS)
    assert story is None and status == "Gemini unavailable (ReadTimeout): template used" and len(attempts) == 1
