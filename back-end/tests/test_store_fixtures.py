"""Store scrapers replayed from recorded real responses (tests/fixtures/stores)."""

import pytest

from scraper.parsers.epicentr_parser import EpicentrParser
from scraper.parsers.rozetka_parser import RozetkaParser
from scraper.parsers.silpo_parser import SilpoParser
from tests.helpers import load_json, replay_requests


@pytest.mark.parametrize(
    "parser_class, fixture",
    [
        (RozetkaParser, "stores/rozetka_juice.json"),
        (SilpoParser, "stores/silpo_juice.json"),
        (EpicentrParser, "stores/epicentr_juice.json"),
    ],
    ids=["rozetka", "silpo", "epicentr"],
)
def test_search_returns_products_from_recorded_response(monkeypatch, parser_class, fixture):
    recording = load_json(fixture)
    replay_requests(monkeypatch, recording)

    products = parser_class().find_n_products(recording["query"], recording["n"])

    assert len(products) == recording["products_found"] == 2
    for product in products:
        assert product.title
        assert product.price and product.price > 0
        assert product.url.startswith("https://")


def test_rozetka_category_redirect_currently_yields_no_products(monkeypatch):
    """Rozetka answers 'iphone 15' with HTTP 200 and meta.navigateTo (a category redirect)
    but no `goods`, so the scraper finds nothing. E2.2 must follow the redirect; then this
    test changes to expect products."""
    recording = load_json("stores/rozetka_iphone15_navigate_to.json")
    body = recording["requests"][0]["body"]
    assert "goods" not in body["data"]
    assert body["data"]["meta"]["navigateTo"]["url"]

    replay_requests(monkeypatch, recording)
    assert RozetkaParser().find_n_products("iphone 15", 2) == []


def test_replay_fails_loudly_for_an_unrecorded_request(monkeypatch):
    replay_requests(monkeypatch, load_json("stores/silpo_juice.json"))
    with pytest.raises(AssertionError, match="No recorded response"):
        RozetkaParser().find_n_products("щось інше", 1, raise_exception=True)
