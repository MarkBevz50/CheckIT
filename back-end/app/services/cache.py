"""
Async Redis cache for product search results.

Provides a two-level cache:
  L1 — raw search results per store (skips Selenium)
  L2 — validated results with LLM data (skips Selenium + Gemini)

Falls back gracefully if Redis is unavailable.
"""

import json
import logging
from app.core.config import settings
from typing import Any, Optional

logger = logging.getLogger(__name__)

_redis_client = None
_redis_unavailable = False

DEFAULT_TTL = settings.cache_ttl_seconds  # 2 hours


async def _get_redis():
    """Lazy-init async Redis client. Returns None if unavailable."""
    global _redis_client, _redis_unavailable

    if _redis_unavailable:
        return None

    if _redis_client is not None:
        return _redis_client

    redis_url = settings.redis_url
    if not redis_url:
        logger.info("REDIS_URL not set — caching disabled")
        _redis_unavailable = True
        return None

    try:
        import redis.asyncio as aioredis
        _redis_client = aioredis.from_url(
            redis_url,
            decode_responses=True,
            socket_connect_timeout=3,
            socket_timeout=3,
        )
        # Verify connection
        await _redis_client.ping()
        logger.info(f"Redis connected: {redis_url}")
        return _redis_client
    except Exception as e:
        logger.warning(f"Redis connection failed: {e} — caching disabled")
        _redis_unavailable = True
        _redis_client = None
        return None


async def get_cached(key: str) -> Optional[Any]:
    """Get value from cache. Returns None on miss or error."""
    r = await _get_redis()
    if r is None:
        return None

    try:
        raw = await r.get(key)
        if raw is None:
            return None
        return json.loads(raw)
    except Exception as e:
        logger.warning(f"Cache read error for '{key[:80]}': {e}")
        return None


async def set_cached(key: str, value: Any, ttl: int = DEFAULT_TTL) -> None:
    """Store value in cache with TTL. Silently ignores errors."""
    r = await _get_redis()
    if r is None:
        return

    try:
        await r.set(key, json.dumps(value, ensure_ascii=False, default=str), ex=ttl)
    except Exception as e:
        logger.warning(f"Cache write error for '{key[:80]}': {e}")


def make_search_key(store: str, product_name: str, n: int) -> str:
    """Build L1 cache key for a single-store product search."""
    normalized = product_name.strip().lower()
    return f"search:{store}:{normalized}:{n}"


def make_validated_key(item_name: str, stores: list, n: int) -> str:
    """Build L2 cache key for validated (post-LLM) search results."""
    normalized = item_name.strip().lower()
    stores_key = ",".join(sorted(stores))
    return f"validated:{normalized}:{stores_key}:{n}"
