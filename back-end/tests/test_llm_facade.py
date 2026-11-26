"""llm_validator facade: Claude first, Gemini as the fallback (the providers are stubbed)."""

import pytest

from app.services import llm_validator

CLAUDE, GEMINI = "from-claude", "from-gemini"


@pytest.fixture
def providers(monkeypatch):
    """Replace both providers with stubs that record calls and return configurable values."""
    state = {"claude_enabled": True, "claude": CLAUDE, "gemini": GEMINI, "calls": []}

    def make(provider, key):
        async def stub(*args, **kwargs):
            state["calls"].append(provider)
            value = state[key if provider == "claude" else "gemini"]
            if isinstance(value, Exception):
                raise value
            return value

        return stub

    for fn in ("extract_items_from_text", "validate_matches", "analyze_document_text"):
        monkeypatch.setattr(llm_validator.claude_validator, fn, make("claude", "claude"))
        monkeypatch.setattr(llm_validator.gemini_validator, fn, make("gemini", "gemini"))
    monkeypatch.setattr(llm_validator, "_claude_enabled", lambda: state["claude_enabled"])
    return state


CALLS = {
    "extract_items_from_text": ("text",),
    "analyze_document_text": ("text",),
    "validate_matches": ("Сир", 100.0, 1.0, "кг", []),
}


@pytest.mark.parametrize("function", CALLS)
async def test_claude_answer_is_used_when_available(providers, function):
    result = await getattr(llm_validator, function)(*CALLS[function])
    assert result == CLAUDE
    assert providers["calls"] == ["claude"]


@pytest.mark.parametrize("function", ["extract_items_from_text", "analyze_document_text"])
async def test_gemini_answers_when_claude_returns_nothing(providers, function):
    providers["claude"] = None
    assert await getattr(llm_validator, function)(*CALLS[function]) == GEMINI
    assert providers["calls"] == ["claude", "gemini"]


@pytest.mark.parametrize("function", CALLS)
async def test_gemini_answers_when_claude_is_not_configured(providers, function):
    providers["claude_enabled"] = False
    assert await getattr(llm_validator, function)(*CALLS[function]) == GEMINI
    assert providers["calls"] == ["gemini"]


async def test_validate_matches_falls_back_to_gemini_when_claude_raises(providers):
    providers["claude"] = RuntimeError("boom")
    assert await llm_validator.validate_matches(*CALLS["validate_matches"]) == GEMINI
    assert providers["calls"] == ["claude", "gemini"]


def test_claude_is_enabled_only_with_an_api_key(monkeypatch):
    monkeypatch.setattr(llm_validator.settings, "anthropic_api_key", "")
    assert llm_validator._claude_enabled() is False
    monkeypatch.setattr(llm_validator.settings, "anthropic_api_key", "sk-test")
    assert llm_validator._claude_enabled() is True
