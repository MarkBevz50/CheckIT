"""cache: behaves as a no-op without Redis, and round-trips JSON when Redis is there."""

import json

import pytest

from app.services import cache


@pytest.fixture(autouse=True)
def fresh_cache_state(monkeypatch):
    monkeypatch.setattr(cache, "_redis_client", None)
    monkeypatch.setattr(cache, "_redis_unavailable", False)
    monkeypatch.setattr(cache.settings, "redis_url", "")


async def test_without_redis_url_the_cache_is_disabled():
    assert await cache._get_redis() is None
    assert cache._redis_unavailable is True


async def test_get_returns_none_without_redis():
    assert await cache.get_cached("search:rozetka:сир:3") is None


async def test_set_does_nothing_and_does_not_fail_without_redis():
    await cache.set_cached("k", {"a": 1})
    assert await cache.get_cached("k") is None


class FakeRedis:
    def __init__(self):
        self.data = {}
        self.ttl = {}

    async def get(self, key):
        return self.data.get(key)

    async def set(self, key, value, ex=None):
        self.data[key] = value
        self.ttl[key] = ex


async def test_values_round_trip_through_json_with_ttl(monkeypatch):
    fake = FakeRedis()

    async def fake_get_redis():
        return fake

    monkeypatch.setattr(cache, "_get_redis", fake_get_redis)
    value = {"items": [{"name": "Сир", "price": 99.5}]}
    await cache.set_cached("k", value, ttl=900)
    assert fake.ttl["k"] == 900
    assert json.loads(fake.data["k"]) == value
    assert await cache.get_cached("k") == value
    assert await cache.get_cached("missing") is None


async def test_redis_errors_are_swallowed(monkeypatch):
    class Broken:
        async def get(self, key):
            raise ConnectionError("down")

        async def set(self, *args, **kwargs):
            raise ConnectionError("down")

    async def fake_get_redis():
        return Broken()

    monkeypatch.setattr(cache, "_get_redis", fake_get_redis)
    assert await cache.get_cached("k") is None
    await cache.set_cached("k", 1)


def test_search_key_is_normalized():
    assert cache.make_search_key("rozetka", "  Сир Кисломолочний ", 3) == "search:rozetka:сир кисломолочний:3"


def test_validated_key_ignores_store_order():
    a = cache.make_validated_key("Сир", ["silpo", "rozetka"], 3)
    b = cache.make_validated_key("сир ", ["rozetka", "silpo"], 3)
    assert a == b == "validated:сир:rozetka,silpo:3"
