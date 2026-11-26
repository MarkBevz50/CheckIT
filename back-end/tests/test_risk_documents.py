"""E0.7: the discriminatory-requirements analysis works on the text of the documents (no database, no network)."""

import asyncio
from types import SimpleNamespace

import pytest

from app.models.model import User
from app.prozorro_functionality import prozorro
from app.routers import ai_assistant
from app.services import claude_validator, parser_service, risk_analyzer

DOCUMENT_TEXT = "Умови закупівлі. Постачальник має мати сертифікат ISO 9001 та склад у межах міста. " * 5


class FakeDb:
    def __init__(self, tender):
        self.tender = tender

    async def execute(self, *args, **kwargs):
        tender = self.tender

        class Result:
            def scalar_one_or_none(self):
                return tender

        return Result()


@pytest.fixture
def pipeline(monkeypatch):
    """analyze_risks with everything outside it replaced; `seen` records what the document analysis received."""
    seen = {"discrimination_input": None, "extract_items_calls": 0}

    async def search(items, stores, n):
        return []

    async def document_text(refs):
        return DOCUMENT_TEXT

    async def extract_items(text):
        seen["extract_items_calls"] += 1
        return []  # what the real extraction returns for tender conditions

    async def discrimination(text):
        seen["discrimination_input"] = text
        return {"overall_risk": "high", "discriminatory_requirements": [{"severity": "high", "type": "brand", "text": "x"}]}

    monkeypatch.setattr(parser_service, "search_and_validate_items", search)
    monkeypatch.setattr(prozorro, "get_contract", lambda hex_id: {"documents": [{}]})
    monkeypatch.setattr(prozorro, "get_document_urls", lambda documents: [("https://example.com/a.docx", "docx")])
    monkeypatch.setattr(prozorro, "extract_documents_text", document_text)
    monkeypatch.setattr(claude_validator, "extract_items_from_text", extract_items)
    monkeypatch.setattr(risk_analyzer, "analyze_discriminatory_requirements", discrimination)
    return seen


def analyze(tender):
    return asyncio.run(
        ai_assistant.analyze_risks(
            tender_id=1, stores="rozetka", db=FakeDb(tender), current_user=User(id=7, name="T", email="t@example.com")
        )
    )


def test_the_analysis_receives_the_document_text_even_when_item_extraction_would_return_nothing(pipeline):
    tender = SimpleNamespace(
        title="Тендер", prozorro_id="aaaa0000bbbb1111cccc2222dddd3333", total_amount=1000.0, expected_cost=1000.0,
        items=[SimpleNamespace(name="Борошно", quantity=1.0, unit_name="кг", unit_price=None, price_source="unknown")],
    )
    response = analyze(tender)

    assert pipeline["discrimination_input"] == DOCUMENT_TEXT
    assert pipeline["extract_items_calls"] == 0  # a whole LLM call (12k input tokens) less per analysis
    assert response.risk_details["discriminatory_risk_score"] == 50
    assert response.risk_details["breakdown"]["discriminatory_analysis"]["overall_risk"] == "high"


def test_parse_documents_still_extracts_items_from_the_text(monkeypatch):
    async def text(refs):
        return DOCUMENT_TEXT

    async def items(combined):
        assert combined == DOCUMENT_TEXT
        return [{"name": "Борошно"}]

    monkeypatch.setattr(prozorro, "extract_documents_text", text)
    monkeypatch.setattr(prozorro, "extract_items_from_text", items)
    assert asyncio.run(prozorro.parse_documents([("u", "pdf")])) == [{"name": "Борошно"}]
