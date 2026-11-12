"""Model selection, max_tokens and usage warnings in claude_validator (no network)."""

import logging
from types import SimpleNamespace

from app.core.config import settings
from app.services import claude_validator as cv


def _message(stop_reason="end_turn", input_tokens=100, cache_read=0, cache_create=0, output=50):
    usage = SimpleNamespace(
        input_tokens=input_tokens,
        cache_read_input_tokens=cache_read,
        cache_creation_input_tokens=cache_create,
        output_tokens=output,
    )
    return SimpleNamespace(usage=usage, stop_reason=stop_reason)


def test_document_model_follows_tier(monkeypatch):
    monkeypatch.setattr(settings, "llm_fast_model", "fast-x")
    monkeypatch.setattr(settings, "llm_smart_model", "smart-x")
    monkeypatch.setattr(settings, "llm_document_tier", "fast")
    assert cv._document_model() == "fast-x"
    assert cv._model() == "fast-x"
    monkeypatch.setattr(settings, "llm_document_tier", "smart")
    assert cv._document_model() == "smart-x"
    assert cv._model() == "fast-x"


def test_max_tokens_raised_for_new_tokenizer():
    assert cv.MAX_TOKENS_EXTRACT >= 8000 * 1.3
    assert cv.MAX_TOKENS_VALIDATE >= 2000 * 1.3
    assert cv.MAX_TOKENS_DISCRIM >= 4000 * 1.3


def test_warns_when_output_truncated(caplog):
    with caplog.at_level(logging.WARNING, logger=cv.logger.name):
        cv._log_usage("t", _message(stop_reason="max_tokens"), 100)
    assert "truncated" in caplog.text


def test_warns_when_prompt_exceeds_80k_including_cache(caplog):
    with caplog.at_level(logging.WARNING, logger=cv.logger.name):
        cv._log_usage("t", _message(input_tokens=1000, cache_read=60000, cache_create=20000), 100)
    assert "81000 tokens" in caplog.text


def test_no_warning_for_normal_request(caplog):
    with caplog.at_level(logging.WARNING, logger=cv.logger.name):
        cv._log_usage("t", _message(input_tokens=5000), 100)
    assert caplog.text == ""
