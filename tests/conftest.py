"""The suite runs offline even when a GEMINI_API_KEY is configured (.env, environment or Streamlit secrets).

The chat's LLM backend is turned off for every test; tests/test_shock_llm.py mocks the provider, and its opt-in
live test (-m live) clears this setting to reach the real model.
"""
import pytest


@pytest.fixture(autouse=True)
def _no_llm(monkeypatch, request):
    if request.node.get_closest_marker("live") is None:
        monkeypatch.setenv("SHOCK_LLM", "off")
