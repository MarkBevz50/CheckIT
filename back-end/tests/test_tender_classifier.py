"""tender_classifier: regex level (no LLM key is configured in tests)."""

import pytest

from app.schemas.tender import TenderType
from app.services import tender_classifier
from app.services.tender_classifier import _classify_by_regex, classify_tender_type_async


def names(*values):
    return [{"name": v} for v in values]


@pytest.mark.parametrize(
    "items, expected",
    [
        ([], TenderType.PRODUCT),
        (names("Молоко"), TenderType.PRODUCT),
        (names("Молоко", "Хліб пшеничний"), TenderType.PRODUCT),
        (names("Послуги з прибирання приміщень"), TenderType.SERVICE),
        (names("Капітальний ремонт даху"), TenderType.WORK),
        (names("Будівництво дороги"), TenderType.WORK),
        (names("Послуги з харчування", "Молоко", "Хліб"), TenderType.MIXED),
        (names("Послуги з харчування", "Послуги з прибирання"), TenderType.SERVICE),
    ],
    ids=["empty", "one-product", "products", "service", "work-repair", "work-build", "mixed", "services"],
)
def test_regex_classification(items, expected):
    assert _classify_by_regex(items) == expected


def test_description_is_used_when_name_is_missing():
    assert _classify_by_regex([{"description": "Будівництво дороги"}]) == TenderType.WORK


def test_missing_name_counts_as_product():
    assert _classify_by_regex([{"name": None}, {}]) == TenderType.PRODUCT


async def test_async_classifier_falls_back_to_regex_without_llm_key(monkeypatch):
    monkeypatch.setattr(tender_classifier.settings, "anthropic_api_key", "")
    monkeypatch.setattr(tender_classifier.settings, "gemini_api_key", "")
    assert await classify_tender_type_async(names("Капітальний ремонт даху")) == TenderType.WORK
    assert await classify_tender_type_async(names("Молоко")) == TenderType.PRODUCT


async def test_async_classifier_returns_product_for_empty_items():
    assert await classify_tender_type_async([]) == TenderType.PRODUCT


# ---- sync entry point -------------------------------------------------

def test_sync_classifier_falls_back_to_regex_without_llm():
    assert tender_classifier.classify_tender_type(names("Капітальний ремонт даху")) == TenderType.WORK
    assert tender_classifier.classify_tender_type([]) == TenderType.PRODUCT


async def test_sync_classifier_inside_a_running_loop_uses_regex():
    assert tender_classifier.classify_tender_type(names("Послуги з прибирання")) == TenderType.SERVICE


# ---- reply mapping of the Claude path ---------------------------------

class FakeAnthropic:
    def __init__(self, reply=None, error=None):
        self.reply, self.error, self.calls = reply, error, []
        self.messages = self

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        from types import SimpleNamespace

        return SimpleNamespace(content=[SimpleNamespace(type="text", text=self.reply)])


@pytest.fixture
def claude(monkeypatch):
    from app.services import claude_validator

    def install(client):
        monkeypatch.setattr(tender_classifier.settings, "anthropic_api_key", "test-key")
        monkeypatch.setattr(claude_validator, "_get_client", lambda: client)
        return client

    return install


@pytest.mark.parametrize(
    "reply, expected",
    [("work", TenderType.WORK), ('"Service."', TenderType.SERVICE), (" mixed! ", TenderType.MIXED), ("PRODUCT", TenderType.PRODUCT)],
)
async def test_claude_reply_is_mapped_to_a_type(claude, reply, expected):
    claude(FakeAnthropic(reply=reply))
    assert await tender_classifier._classify_by_llm(names("Щось")) == expected


async def test_unmapped_claude_reply_falls_through_to_none_without_gemini(claude):
    claude(FakeAnthropic(reply="не знаю"))
    assert await tender_classifier._classify_by_llm(names("Щось")) is None


async def test_claude_failure_does_not_break_classification(claude):
    claude(FakeAnthropic(error=RuntimeError("rate limited")))
    assert await tender_classifier._classify_by_llm(names("Щось")) is None
    assert await classify_tender_type_async(names("Капітальний ремонт даху")) == TenderType.WORK


async def test_prompt_lists_names_cpv_and_units(claude):
    client = claude(FakeAnthropic(reply="product"))
    await tender_classifier._classify_by_llm([{"name": "Сир", "dk_code": "15540000-5", "unit_name": "кг"}])
    prompt = client.calls[0]["messages"][0]["content"]
    assert "1. Сир (CPV: 15540000-5) [кг]" in prompt
