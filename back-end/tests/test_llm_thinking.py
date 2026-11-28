"""E0.7: the reasoning parameter is taken from the configuration of each task, not guessed from the model name."""

import asyncio
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.core.config import Settings, settings
from app.services import claude_validator as cv
from app.services import tender_classifier


class RecordingClient:
    """AsyncAnthropic stand-in: records the arguments of every messages.create call."""

    def __init__(self, answer):
        self.calls = []
        self.messages = SimpleNamespace(create=self._create)
        self._answer = answer

    async def _create(self, **kwargs):
        self.calls.append(kwargs)
        usage = SimpleNamespace(input_tokens=1, output_tokens=1, cache_read_input_tokens=0, cache_creation_input_tokens=0)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=self._answer)], usage=usage, stop_reason="end_turn")


@pytest.fixture
def client(monkeypatch):
    def install(answer):
        recording = RecordingClient(answer)
        monkeypatch.setattr(cv, "_get_client", lambda: recording)
        monkeypatch.setattr(settings, "anthropic_api_key", "sk-ant-test")
        return recording

    return install


def run(coroutine):
    return asyncio.run(coroutine)


def test_defaults_switch_reasoning_off_for_every_task():
    for name in ("classify", "validate", "extract", "documents"):
        assert getattr(Settings.model_fields[f"llm_thinking_{name}"], "default") == "disabled"


def test_helper_builds_the_request_argument():
    assert cv.thinking_kwargs("disabled") == {"thinking": {"type": "disabled"}}
    assert cv.thinking_kwargs("between_tools") == {"thinking": {"type": "between_tools"}}
    assert cv.thinking_kwargs("default") == {}


def test_an_unknown_value_is_rejected_at_startup(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@h:5432/d")
    monkeypatch.setenv("SECRET_KEY", "x" * 40)
    monkeypatch.setenv("LLM_THINKING_VALIDATE", "enabled")
    with pytest.raises((ValidationError, RuntimeError)):
        from app.core.config import load_settings

        load_settings()


def test_classification_uses_its_own_setting(client, monkeypatch):
    recording = client("product")
    monkeypatch.setattr(settings, "llm_thinking_classify", "between_tools")
    monkeypatch.setattr(settings, "llm_thinking_validate", "default")  # another task: must not leak in
    run(tender_classifier._classify_by_llm([{"name": "Борошно"}]))
    assert recording.calls[0]["thinking"] == {"type": "between_tools"}


def test_validation_uses_its_own_setting(client, monkeypatch):
    recording = client('[{"index": 1, "is_relevant": true}]')
    monkeypatch.setattr(settings, "llm_thinking_validate", "disabled")
    monkeypatch.setattr(settings, "llm_thinking_classify", "default")
    run(cv.validate_matches("Борошно", 10.0, 1.0, "кг", [{"title": "Борошно 1 кг", "price": 20.0}]))
    assert recording.calls[0]["thinking"] == {"type": "disabled"}


def test_extraction_and_documents_have_separate_settings(client, monkeypatch):
    recording = client("[]")
    monkeypatch.setattr(settings, "llm_thinking_extract", "between_tools")
    monkeypatch.setattr(settings, "llm_thinking_documents", "default")
    run(cv.extract_items_from_text("текст"))
    assert recording.calls[0]["thinking"] == {"type": "between_tools"}

    recording = client('{"overall_risk": "low", "discriminatory_requirements": []}')
    run(cv.analyze_discriminatory_requirements("текст"))
    assert "thinking" not in recording.calls[0]  # "default": the parameter is not sent at all
