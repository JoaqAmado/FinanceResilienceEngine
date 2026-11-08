"""The LLM backend of the chat, with the provider mocked: no network, no key needed.

It may only translate words into the intent schema; the same input must always give the same Shock; every
failure falls back to the offline rules without raising and without caching; no account data goes out and no
secret comes back in a log, cache file or exception.
"""
import json
import socket

import pytest

from resilience import shock_llm as L
from resilience import shock_parser as sp
from resilience.core import DATA_DIR, LAID_OFF_EI, Shock, build_metrics

needs_data = pytest.mark.skipif(not (DATA_DIR / "monthly_summary.csv").exists(), reason="track data not present")
SECRET = "sk-test-SECRET-do-not-leak-123"
MSG = "baby on the way, about $900 a month more"           # not golden; the rules read it too


@pytest.fixture(scope="module")
def m():
    return build_metrics()


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Every test gets empty caches and logs in tmp_path, and no cooldown left over."""
    monkeypatch.setattr(sp, "LOCAL_CACHE", tmp_path / "shock_intents.json")
    monkeypatch.setattr(sp, "FROZEN_CACHE", tmp_path / "frozen.json")
    monkeypatch.setattr(sp, "DISAGREEMENTS", tmp_path / "disagreements.jsonl")
    monkeypatch.delenv("SHOCK_LLM", raising=False)
    monkeypatch.delenv("SHOCK_GEMINI_MODEL", raising=False)
    L.reset_cooldown()
    yield tmp_path
    L.reset_cooldown()


def answer(**parts) -> dict:
    """A full, schema-shaped model answer."""
    return L._example(**parts)


class Fake:
    """A provider adapter that returns canned answers (or raises) and records each request."""
    name = "Gemini"

    def __init__(self, *responses):
        self.model = L.model_id()
        self.responses = list(responses)
        self.calls = []

    def complete_json(self, system, user, schema):
        self.calls.append({"system": system, "user": user, "schema": schema})
        r = self.responses[min(len(self.calls), len(self.responses)) - 1]
        if isinstance(r, Exception):
            raise r
        if isinstance(r, str):
            return json.loads(r)
        return r


def backends(adapter):
    return [sp.GoldenParser(), sp.CacheLookup(), sp.LLMParser(adapter), sp.RuleParser()]


def parse(m, msg, adapter, acct=20331, current=Shock(), target=6):
    return sp.parse_shock(msg, m.loc[acct], current, target, metrics=m, backends=backends(adapter))


def all_text(tmp_path) -> str:
    return " ".join(p.read_text() for p in tmp_path.iterdir() if p.is_file())


# ------------------------------------------------------------------ the happy path and determinism

@needs_data
def test_a_valid_response_becomes_the_expected_shock(m):
    fake = Fake(answer(monthly_cost={"kind": "set", "amount": 900}))
    res = parse(m, MSG, fake)
    assert res.source == "llm" and res.clarify is None
    assert sp.same_shock(res.shock, Shock(extra_monthly_cost=900.0)) and res.target == 6
    assert res.understood_as == "+$900/mo new monthly costs · must last 6 months"   # built by code, not the model


@needs_data
def test_same_input_same_result_with_one_provider_call(m):
    fake = Fake(answer(income={"kind": "pay_cut_pct", "pct": 0.5}))
    msg = "their hours get cut down a lot, roughly half, from next month"
    results = [parse(m, msg, fake, current=LAID_OFF_EI) for _ in range(10)]
    assert len(fake.calls) == 1
    assert [r.source for r in results] == ["llm"] + ["cache"] * 9
    assert all(r.shock == results[0].shock and r.understood_as == results[0].understood_as for r in results)
    assert results[0].shock.income_multiplier == 0.5 and not results[0].shock.job_loss


@needs_data
def test_frozen_entry_is_used_when_the_provider_is_unreachable_or_there_is_no_key(m, monkeypatch, isolated):
    msg = "a rough patch where the money coming in halves"
    norm = sp.normalize(msg)
    key = sp.cache_key(norm, Shock(), L.model_id(), L.PROMPT_VERSION)
    intent = sp.canonicalize_intent(answer(income={"kind": "keep_pct", "pct": 0.5}))
    sp._write_entries(sp.FROZEN_CACHE, {key: {"message": norm, "intent": intent}}, "test")

    down = Fake(socket.timeout("timed out"))
    res = parse(m, msg, down)
    assert res.source == "cache" and res.shock.income_multiplier == 0.5 and not down.calls

    from resilience import llm
    monkeypatch.setattr(llm, "api_key", lambda: None)
    assert L.provider_name() == "off"
    res2 = sp.parse_shock(msg, m.loc[20331], Shock(), 6, metrics=m)    # the default backends, no key
    assert res2.source == "cache" and res2.shock == res.shock


def test_cache_key_changes_with_prompt_model_schema_and_current_not_whitespace_or_case(monkeypatch):
    norm = sp.normalize("Rent  up $300 a month")
    base = sp.cache_key(norm, Shock(), "gemini-x-001", "shock-v1")
    assert sp.cache_key(sp.normalize("rent up 300 A MONTH"), Shock(), "gemini-x-001", "shock-v1") == base
    assert sp.cache_key(sp.normalize("  RENT up $300   a month "), Shock(), "gemini-x-001", "shock-v1") == base
    assert sp.cache_key(norm, Shock(), "gemini-x-001", "shock-v2") != base
    assert sp.cache_key(norm, Shock(), "gemini-x-002", "shock-v1") != base
    assert sp.cache_key(norm, LAID_OFF_EI, "gemini-x-001", "shock-v1") != base
    assert sp.cache_key(norm, Shock(name="another label"), "gemini-x-001", "shock-v1") == base  # names don't count
    monkeypatch.setattr(sp, "INTENT_SCHEMA_VERSION", "intent-v2")
    assert sp.cache_key(norm, Shock(), "gemini-x-001", "shock-v1") != base


@needs_data
def test_canonicalization_makes_small_output_differences_irrelevant(m):
    a = answer(bills={"kind": "increase_pct", "pct": 0.15}, income={"kind": "job_loss_ei", "pct": 0.55})
    b = json.loads(json.dumps(a, sort_keys=True))
    b = dict(reversed(list(b.items())))                                     # key order
    b["bills"] = {"pct": 0.1500001, "kind": "INCREASE_PCT"}                  # float noise, enum case
    b["income"] = {"amount": 0, "pct": 55, "kind": " Job_Loss_EI "}          # percent units, whitespace
    shocks = []
    for i, ans in enumerate((a, b)):
        fake = Fake(ans)
        shocks.append(parse(m, f"some new wording number {i}", fake).shock)
    assert shocks[0] == shocks[1]
    assert sp.canonicalize_intent(a) == sp.canonicalize_intent(b)


# ------------------------------------------------------------------ failures fall back to the rules

class HTTPish(Exception):
    def __init__(self, code):
        super().__init__(f"request failed with key={SECRET}")
        self.code = code


FAILURES = {
    "invalid JSON": "{not json",
    "extra keys": {**answer(monthly_cost={"kind": "set", "amount": 900}), "advice": "save more"},
    "out of range": answer(monthly_cost={"kind": "set", "amount": -900}),
    "unknown kind": answer(monthly_cost={"kind": "lots", "amount": 900}),
    "missing section": {k: v for k, v in answer().items() if k != "bills"},
    "timeout": socket.timeout(f"timed out talking with {SECRET}"),
    "401": HTTPish(401),
    "5xx": HTTPish(503),
}


@needs_data
@pytest.mark.parametrize("what", list(FAILURES))
def test_every_failure_falls_back_to_the_rules_and_caches_nothing(m, isolated, what):
    fake = Fake(FAILURES[what])
    res = parse(m, MSG, fake)
    assert res.source == "rules" and sp.same_shock(res.shock, Shock(extra_monthly_cost=900.0))
    assert not sp.LOCAL_CACHE.exists()
    retried = what in ("invalid JSON", "extra keys", "out of range", "unknown kind", "missing section")
    assert len(fake.calls) == (2 if retried else 1)                        # one retry, only for bad answers
    assert SECRET not in repr(res) and SECRET not in all_text(isolated)


@needs_data
def test_a_network_failure_skips_the_llm_for_five_minutes(m):
    fake = Fake(socket.timeout("down"))
    parse(m, MSG, fake)
    parse(m, "baby on the way, maybe $950 a month more", fake)
    assert len(fake.calls) == 1 and L.COOLDOWN_S == 300


@needs_data
def test_a_retry_that_succeeds_is_used_and_cached(m):
    fake = Fake("{oops", answer(monthly_cost={"kind": "set", "amount": 900}))
    res = parse(m, MSG, fake)
    assert res.source == "llm" and len(fake.calls) == 2 and sp.LOCAL_CACHE.exists()


@needs_data
def test_an_llm_clarify_is_passed_on_and_changes_nothing(m):
    fake = Fake(answer(clarify="What happens to the money coming in?"))
    res = parse(m, "things could go sideways", fake, current=LAID_OFF_EI, target=8)
    assert res.clarify == "What happens to the money coming in?" and res.shock == LAID_OFF_EI and res.target == 8


# ------------------------------------------------------------------ agreement check

@needs_data
def test_a_disagreement_with_the_rules_warns_and_is_logged(m, isolated):
    fake = Fake(answer(monthly_cost={"kind": "set", "amount": 1900}))     # the rules read $900
    res = parse(m, MSG, fake)
    assert res.shock.extra_monthly_cost == 1900.0 and res.source == "llm"
    assert any(w.startswith("rules read this differently: +$900/mo") for w in res.warnings)
    lines = sp.DISAGREEMENTS.read_text().splitlines()
    assert len(lines) == 1 and json.loads(lines[0])["rules"]["extra_monthly_cost"] == 900.0
    again = parse(m, MSG, fake)                                          # cache hit: same warning, no new log line
    assert again.source == "cache" and again.warnings == res.warnings
    assert len(sp.DISAGREEMENTS.read_text().splitlines()) == 1


@needs_data
def test_agreement_adds_no_warning(m):
    res = parse(m, MSG, Fake(answer(monthly_cost={"kind": "set", "amount": 900})))
    assert res.warnings == [] and not sp.DISAGREEMENTS.exists()


# ------------------------------------------------------------------ what goes out, what never comes back

@needs_data
def test_no_account_data_goes_to_the_provider(m):
    fake = Fake(answer(monthly_cost={"kind": "set", "amount": 900}))
    parse(m, MSG, fake, acct=98952, current=LAID_OFF_EI)
    sent = fake.calls[0]
    payload = json.loads(sent["user"])
    assert set(payload) == {"message", "current"} and payload["message"] == sp.normalize(MSG)
    assert payload["current"] == sp.shock_key(LAID_OFF_EI)
    row = m.loc[98952]
    blob = sent["system"] + sent["user"]
    for v in ("98952", f"{row.I:.2f}", f"{row.B:.2f}", f"{row.S:.2f}", f"{row.I:,.0f}", f"{row.B:,.0f}"):
        assert v not in blob, v


def test_the_schema_is_strict_with_no_ranges():
    def walk(node):
        if node.get("type") == "object":
            assert node["additionalProperties"] is False and set(node["required"]) == set(node["properties"])
            for child in node["properties"].values():
                walk(child)
        assert "minimum" not in node and "maximum" not in node
    walk(sp.INTENT_SCHEMA)
    assert sp.INTENT_SCHEMA["properties"]["income"]["properties"]["kind"]["enum"] == list(sp.INCOME_KINDS)


def test_the_prompt_is_fixed_and_has_the_glossary_and_eight_examples():
    assert L.PROMPT_VERSION and len(L.FEW_SHOT) == 8
    for phrase in ("55%", "NOT a job loss", "a month of spending", "for N months", "unchanged"):
        assert phrase in L.SYSTEM, phrase
    for _, ans in L.FEW_SHOT:   # every few-shot answer is itself a valid, strict intent
        L._validated(ans)
    kinds = {json.dumps(a, sort_keys=True) for _, a in L.FEW_SHOT}
    assert any('"clarify": "What' in k for k in kinds) and any("set_last_percent" in k for k in kinds)
    assert any("to_amount" in k for k in kinds)


def test_the_model_is_pinned(monkeypatch):
    assert "latest" not in L.GEMINI_MODEL and "latest" not in L.CORTEX_MODEL
    monkeypatch.setenv("SHOCK_GEMINI_MODEL", "gemini-flash-latest")
    with pytest.raises(ValueError):
        L.model_id()


def test_gemini_adapter_sends_deterministic_settings_and_hides_the_key(monkeypatch):
    from google import genai
    seen = {}

    class Models:
        def generate_content(self, model, contents, config):
            seen.update(model=model, contents=contents, config=config)

            class R:
                text = json.dumps(answer())
            return R()

    class Client:
        def __init__(self, api_key, http_options):
            seen["timeout"] = http_options.timeout
            self.models = Models()
    monkeypatch.setattr(genai, "Client", Client)
    ad = L.GeminiAdapter(SECRET)
    assert SECRET not in repr(ad)
    ad.complete_json("sys", "{}", sp.INTENT_SCHEMA)
    c = seen["config"]
    assert (c.temperature, c.top_p, c.top_k, c.seed, c.candidate_count) == (0.0, 1.0, L.TOP_K, L.SEED, 1)
    assert c.response_json_schema == sp.INTENT_SCHEMA and c.response_mime_type == "application/json"
    assert seen["model"] == L.GEMINI_MODEL and seen["timeout"] == 10_000


@pytest.mark.parametrize("exc, kind", [(HTTPish(401), "auth"), (HTTPish(403), "auth"), (HTTPish(500), "server"),
                                       (socket.timeout(SECRET), "network"), (ConnectionError(SECRET), "network"),
                                       (RuntimeError(SECRET), "other")])
def test_gemini_errors_never_carry_their_text(monkeypatch, exc, kind):
    from google import genai

    class Client:
        def __init__(self, *a, **k):
            raise exc
    monkeypatch.setattr(genai, "Client", Client)
    with pytest.raises(L.ProviderError) as info:
        L.GeminiAdapter(SECRET).complete_json("sys", "{}", sp.INTENT_SCHEMA)
    assert info.value.kind == kind and SECRET not in str(info.value) and info.value.__cause__ is None


def test_cortex_adapter_only_with_a_pat(monkeypatch):
    monkeypatch.setenv("SHOCK_LLM", "cortex")
    monkeypatch.delenv("SNOWFLAKE_PAT", raising=False)
    from resilience import llm
    monkeypatch.setattr(llm, "_dotenv_value", lambda name: None)
    assert L.provider_name() == "off"
    monkeypatch.setenv("SNOWFLAKE_PAT", SECRET)
    monkeypatch.setenv("SNOWFLAKE_ACCOUNT", "ab12345")
    assert L.provider_name() == "cortex" and SECRET not in repr(L.default_adapter())


def test_shock_llm_off_means_no_call(monkeypatch):
    monkeypatch.setenv("SHOCK_LLM", "off")
    assert L.provider_name() == "off" and L.default_adapter() is None
    assert L.llm_intent("laid off", Shock()) == (None, "LLM off")


def test_warm_and_freeze_with_a_fake_provider(isolated):
    fake = Fake(answer(income={"kind": "job_loss_ei", "pct": 0.55}))
    counts = sp.warm(["Laid off, EI pays 55%", "they got let go"], adapter=fake, out=open("/dev/null", "w"))
    assert counts == {"cached": 0, "new": 2, "failed": 0}
    again = sp.warm(["Laid off, EI pays 55%", "they got let go"], adapter=fake, out=open("/dev/null", "w"))
    assert again == {"cached": 2, "new": 0, "failed": 0} and len(fake.calls) == 2
    n = sp.freeze(["they got let go"], out=open("/dev/null", "w"))
    frozen = json.loads(sp.FROZEN_CACHE.read_text())["entries"]
    assert n == 1 and [e["message"] for e in frozen.values()] == ["they got let go"]


# ------------------------------------------------------------------ live (opt-in, needs a key)

@pytest.mark.live
@needs_data
def test_live_warm_twice_then_cold_rerun_matches(m, isolated):
    if L.provider_name() == "off":
        pytest.skip("no LLM key configured")
    phrases = list(sp.HINT_CHIPS) + list(sp.PRACTICE_PHRASINGS)
    first = sp.warm(phrases)
    second = sp.warm(phrases)
    assert second["new"] == 0 and second["cached"] == first["cached"] + first["new"]
    warm_shocks = {p: parse(m, p, None).shock for p in phrases}
    sp.LOCAL_CACHE.unlink()
    L.reset_cooldown()
    differed = [p for p in phrases if parse(m, p, None).shock != warm_shocks[p]]
    assert not differed, f"add these to the golden table: {differed}"
