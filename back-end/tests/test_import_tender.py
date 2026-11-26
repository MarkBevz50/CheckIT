"""POST /tenders/import/{prozorro_id} on recorded Prozorro tenders, no network, no database."""

from datetime import datetime

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.routers.authorization import get_current_user
from tests.helpers import FakeResponse, load_json

WITH_UNIT_PRICE = "tender_with_unit_price"
SINGLE_ITEM = "tender_single_item_no_unit_price"
MANY_ITEMS = "tender_many_items_no_unit_price"


def fixture(name):
    return load_json(f"prozorro/{name}.json")


def hex_id(name):
    return fixture(name)["data"]["id"]


class FakeResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class ImportSession:
    """AsyncSession stand-in: optional pre-existing tender, collects what is saved."""

    def __init__(self, existing=None):
        self.existing = existing
        self.added = []

    async def execute(self, *args, **kwargs):
        return FakeResult(self.existing)

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        pass

    async def refresh(self, obj):
        # what the database would fill in on INSERT
        obj.id = 1
        obj.created_at = obj.updated_at = datetime(2026, 11, 12)
        obj.warranty_required = bool(obj.warranty_required)
        obj.requires_license = bool(obj.requires_license)
        for number, item in enumerate(obj.items, start=1):
            item.id = number


@pytest.fixture
def client_for():
    def make(session=None):
        async def override_db():
            yield session or ImportSession()

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_current_user] = lambda: "user@example.com"
        return TestClient(app)

    yield make
    app.dependency_overrides.clear()


@pytest.fixture
def prozorro(monkeypatch):
    """Serve the Prozorro API (sync `requests` in prozorro.py) from recorded tenders."""
    import requests

    served = {}

    def fake_get(url, *args, **kwargs):
        for tender_id, body in served.items():
            if url.endswith(f"/tenders/{tender_id}"):
                return FakeResponse(200, body)
        return FakeResponse(404, {"errors": [{"description": "Not Found"}]})

    monkeypatch.setattr(requests, "get", fake_get)
    return served


@pytest.fixture
def market(monkeypatch):
    """Control the market-price search used when a tender has no unit price."""
    from app.services import parser_service

    state = {"products": [], "queries": []}

    async def fake_search(product_name, **kwargs):
        state["queries"].append(product_name)
        return state["products"]

    monkeypatch.setattr(parser_service, "search_products_async", fake_search)
    return state


def synthetic_tender(tender_id, item_name, unit_price=10.0):
    return {
        "data": {
            "id": tender_id,
            "title": item_name,
            "value": {"amount": unit_price * 2, "currency": "UAH"},
            "procuringEntity": {"name": "Тестовий замовник"},
            "items": [
                {"description": item_name, "quantity": 2.0, "unit": {"name": "шт", "value": {"amount": unit_price}}}
            ],
        }
    }


# ---- prices -----------------------------------------------------------

def test_unit_price_from_the_tender_is_kept(client_for, prozorro, market):
    prozorro[hex_id(WITH_UNIT_PRICE)] = fixture(WITH_UNIT_PRICE)
    response = client_for().post(f"/tenders/import/{hex_id(WITH_UNIT_PRICE)}")

    assert response.status_code == 201
    body = response.json()
    assert body["prozorro_id"] == hex_id(WITH_UNIT_PRICE)
    assert body["tender_type"] == "product"
    assert body["expected_cost"] == 35.0
    assert body["customer_name"].startswith("КОМУНАЛЬНЕ НЕКОМЕРЦІЙНЕ")
    [item] = body["items"]
    assert (item["unit_price"], item["price_source"], item["quantity"]) == (35.0, "tender", 1.0)
    assert market["queries"] == []  # no market search when the tender has a price


def test_single_item_price_is_derived_from_the_total(client_for, prozorro, market):
    prozorro[hex_id(SINGLE_ITEM)] = fixture(SINGLE_ITEM)
    response = client_for().post(f"/tenders/import/{hex_id(SINGLE_ITEM)}")

    assert response.status_code == 201
    [item] = response.json()["items"]
    assert item["price_source"] == "tender"
    assert item["quantity"] == 45.0
    assert item["unit_price"] == pytest.approx(150787.58 / 45)
    assert response.json()["total_amount"] == pytest.approx(150787.58)


@pytest.fixture
def many_items_from_documents(monkeypatch, prozorro):
    """The recorded multi-item tender has no usable item names/prices, so the importer reads
    the documents; replace that step with a fixed result (no downloads in tests)."""
    from app.prozorro_functionality import prozorro as prozorro_module

    prozorro[hex_id(MANY_ITEMS)] = fixture(MANY_ITEMS)

    async def fake_parse_documents(urls):
        return [
            {"name": "Борошно пшеничне", "quantity": 1000, "unit_name": "кг", "unit_price": 25.0},
            {"name": "Пластівці вівсяні", "quantity": 200, "unit_name": "кг", "unit_price": " "},
        ]

    monkeypatch.setattr(prozorro_module, "parse_documents", fake_parse_documents)


def test_missing_price_falls_back_to_the_market_median(client_for, many_items_from_documents, market):
    market["products"] = [{"price": 100.0}, {"price_on_sale": 80.0}, {"price": 120.0}]
    response = client_for().post(f"/tenders/import/{hex_id(MANY_ITEMS)}")

    assert response.status_code == 201
    first, second = response.json()["items"]
    assert (first["unit_price"], first["price_source"]) == (25.0, "tender")
    assert (second["unit_price"], second["price_source"]) == (100.0, "market_estimate")
    assert market["queries"] == ["Пластівці вівсяні"]


def test_price_is_unknown_when_the_market_has_nothing(client_for, many_items_from_documents, market):
    market["products"] = []
    response = client_for().post(f"/tenders/import/{hex_id(MANY_ITEMS)}")

    second = response.json()["items"][1]
    assert (second["unit_price"], second["price_source"]) == (None, "unknown")


# ---- classification ---------------------------------------------------

@pytest.mark.parametrize(
    "item_name, expected",
    [
        ("Послуги з прибирання приміщень", "service"),
        ("Капітальний ремонт даху", "work"),
        ("Молоко пастеризоване", "product"),
    ],
)
def test_tender_type_is_classified_from_item_names(client_for, prozorro, market, item_name, expected):
    prozorro["abc123"] = synthetic_tender("abc123", item_name)
    response = client_for().post("/tenders/import/abc123")
    assert response.status_code == 201
    assert response.json()["tender_type"] == expected


# ---- errors -----------------------------------------------------------

def test_duplicate_import_is_rejected_with_409(client_for, prozorro, market):
    prozorro[hex_id(WITH_UNIT_PRICE)] = fixture(WITH_UNIT_PRICE)
    response = client_for(ImportSession(existing=object())).post(f"/tenders/import/{hex_id(WITH_UNIT_PRICE)}")
    assert response.status_code == 409


def test_unknown_tender_returns_404(client_for, prozorro, market):
    response = client_for().post("/tenders/import/ffffffffffffffffffffffffffffffff")
    assert response.status_code == 404


# ---- UA-ID resolution through Clarity Project -------------------------

UA_ID = "UA-2026-09-10-000098-a"
CLARITY_URL = f"https://clarity-project.info/tender/{UA_ID.lower()}"


@respx.mock
def test_ua_id_is_resolved_to_the_hex_id(client_for, prozorro, market):
    prozorro[hex_id(WITH_UNIT_PRICE)] = fixture(WITH_UNIT_PRICE)
    page = f'<link rel="canonical" href="https://clarity-project.info/tender/{hex_id(WITH_UNIT_PRICE)}"/>'
    route = respx.get(CLARITY_URL).mock(return_value=httpx.Response(200, text=page))

    response = client_for().post(f"/tenders/import/{UA_ID}")

    assert route.called
    assert response.status_code == 201
    assert response.json()["prozorro_id"] == UA_ID


@respx.mock
def test_unknown_ua_id_returns_404(client_for, prozorro, market):
    respx.get(CLARITY_URL).mock(return_value=httpx.Response(404))
    assert client_for().post(f"/tenders/import/{UA_ID}").status_code == 404


@respx.mock
def test_clarity_outage_returns_502(client_for, prozorro, market):
    respx.get(CLARITY_URL).mock(return_value=httpx.Response(503))
    assert client_for().post(f"/tenders/import/{UA_ID}").status_code == 502


@respx.mock
def test_page_without_hex_id_returns_404(client_for, prozorro, market):
    respx.get(CLARITY_URL).mock(return_value=httpx.Response(200, text="<html>nothing</html>"))
    assert client_for().post(f"/tenders/import/{UA_ID}").status_code == 404
