"""
Parser service — wraps parsers and provides a unified interface for multiple stores.
"""

import asyncio
import logging
import re
from typing import List, Dict, Any

from scraper.parsers.rozetka_parser import RozetkaParser
from scraper.parsers.silpo_parser import SilpoParser
from scraper.parsers.epicentr_parser import EpicentrParser
from app.services.llm_validator import validate_matches, is_service_item

logger = logging.getLogger(__name__)

# Registry of available parsers
AVAILABLE_PARSERS = {
    "rozetka": {
        "class": RozetkaParser,
        "name": "Rozetka",
        "url": "https://rozetka.com.ua",
    },
    "silpo": {
        "class": SilpoParser,
        "name": "Сільпо",
        "url": "https://silpo.ua",
    },
    "epicentr": {
        "class": EpicentrParser,
        "name": "Епіцентр",
        "url": "https://epicentrk.ua",
    },
}


def _normalize_unicode(text: str) -> str:
    """Normalize Unicode whitespace and invisible characters common in Prozorro data."""
    # Replace non-breaking spaces, zero-width spaces, and other Unicode whitespace
    text = re.sub(r'[\u00a0\u200b\u200c\u200d\u2060\ufeff]', ' ', text)
    # Collapse multiple spaces into one
    text = re.sub(r' {2,}', ' ', text)
    return text.strip()


_STRIP_CHARS = "«»\"',. \t"


def _simplify_product_name(name: str) -> List[str]:
    """
    Generate progressively simpler search queries from a Prozorro product name.
    Returns list of queries from most specific to most general.
    E.g. "Масло вершкове моноліт жирністю не менше 72%" ->
         ["Масло вершкове моноліт жирністю не менше 72%",
          "Масло вершкове моноліт 72%",
          "Масло вершкове"]
    """
    name = _normalize_unicode(name)
    queries = [name]

    # Remove filler words and keep nouns/adjectives + percentages
    stop_words = {
        "не", "менше", "більше", "ніж", "від", "до", "для", "або", "та",
        "із", "зі", "по", "на", "за", "без", "при", "що", "як", "що",
        "моноліт", "монолітне", "фасований", "фасоване", "фасована",
        "нефасований", "нефасоване", "штука", "штук", "упаковка",
        "пакування", "марки", "марка", "типу", "тип", "розмір",
    }
    words = name.split()
    filtered = [w for w in words if w.lower().strip(_STRIP_CHARS) not in stop_words]
    # Keep percentage patterns attached
    simplified = " ".join(filtered)
    if simplified != name:
        queries.append(simplified)

    # Take only the first 2-3 meaningful words (usually the product type)
    core_words = [w for w in filtered if not re.match(r'^[\d%,.]+$', w.strip(_STRIP_CHARS))]
    if len(core_words) >= 2:
        short = " ".join(core_words[:2])
        # Add percentage if present in original
        pct = re.search(r'\d+[.,]?\d*\s*%', name)
        if pct:
            short_with_pct = f"{short} {pct.group()}"
            if short_with_pct not in queries:
                queries.append(short_with_pct)
        if short not in queries:
            queries.append(short)

    # Deduplicate while preserving order
    seen = set()
    result = []
    for q in queries:
        q = q.strip()
        if q and q not in seen:
            seen.add(q)
            result.append(q)

    return result


def _sync_search_products(
    parser_key: str,
    product_name: str,
    n: int = 1,
    fast_parse: bool = False,
    ignore_price_format: bool = True,
) -> List[Dict[str, Any]]:
    """
    Synchronous function that creates a parser, searches for products, and returns results.
    This runs inside asyncio.to_thread() to avoid blocking the event loop.
    """
    parser_info = AVAILABLE_PARSERS.get(parser_key)
    if not parser_info:
        raise ValueError(f"Unknown parser: {parser_key}")

    parser = None
    try:
        logger.info(f"[{parser_key}] Creating parser for product: '{product_name}'")
        parser = parser_info["class"]()

        # Try progressively simpler queries if full Prozorro name yields no results
        queries = _simplify_product_name(product_name)
        results = []
        for query in queries:
            results = parser.find_n_products(
                product=query,
                n=n,
                fast_parse=fast_parse,
                ignore_price_format=ignore_price_format,
                raise_exception=False,
            )
            if results:
                logger.info(f"[{parser_key}] Found {len(results)} products for '{query}'")
                break
            logger.info(f"[{parser_key}] No results for '{query}', trying simpler query...")

        if not results:
            logger.info(f"[{parser_key}] No products found for any query variant of '{product_name}'")
            return []

        # Convert ProductInfo objects to dicts and add store info
        return [
            {
                **product.to_dict(),
                "store": parser_key,
                "store_name": parser_info["name"],
            }
            for product in results
        ]
    except Exception as e:
        logger.warning(f"[{parser_key}] Failed to search for '{product_name}': {e}")
        return []
    finally:
        if parser is not None:
            try:
                parser._close()
            except Exception:
                pass


async def search_products_async(
    product_name: str,
    stores: List[str],
    n: int = 1,
    fast_parse: bool = False,
    ignore_price_format: bool = True,
) -> List[Dict[str, Any]]:
    """
    Search for a product across multiple stores asynchronously.
    Each store parser runs in a separate thread via asyncio.to_thread().
    Results are cached per store in Redis (L1 cache).

    Args:
        product_name: Name of the product to search for
        stores: List of store keys (e.g., ["rozetka", "epicentr"])
        n: Number of products to find per store
        fast_parse: If True, only get price; if False, get full details
        ignore_price_format: If True, return raw price strings

    Returns:
        List of product dicts with store info attached
    """
    from app.services.cache import get_cached, set_cached, make_search_key

    # Validate stores
    valid_stores = [s for s in stores if s in AVAILABLE_PARSERS]
    if not valid_stores:
        logger.warning(f"No valid stores provided: {stores}")
        return []

    all_products = []
    stores_to_search = []

    # L1 cache: check each store individually
    for store in valid_stores:
        cache_key = make_search_key(store, product_name, n)
        cached = await get_cached(cache_key)
        if cached is not None:
            logger.info(f"[{store}] Cache hit for '{product_name[:60]}'")
            all_products.extend(cached)
        else:
            stores_to_search.append(store)

    if not stores_to_search:
        return all_products

    # Run uncached stores in parallel threads
    tasks = [
        asyncio.to_thread(
            _sync_search_products,
            store,
            product_name,
            n,
            fast_parse,
            ignore_price_format,
        )
        for store in stores_to_search
    ]

    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Process results and cache per store
    for store, result in zip(stores_to_search, results):
        if isinstance(result, Exception):
            logger.warning(f"[{store}] Exception during search: {result}")
            continue
        # Cache this store's results (even empty — avoids re-searching)
        cache_key = make_search_key(store, product_name, n)
        await set_cached(cache_key, result)
        logger.info(f"[{store}] Cache miss — stored {len(result)} results for '{product_name[:60]}'")
        all_products.extend(result)

    return all_products


async def search_products_for_items(
    items: List[Dict[str, Any]],
    stores: List[str],
    n: int = 1,
) -> List[Dict[str, Any]]:
    """
    Search for each item from a list across specified stores.

    Args:
        items: List of dicts with 'name' key (e.g., from Prozorro or Excel)
        stores: List of store keys
        n: Number of products per item per store

    Returns:
        Flat list of all found products
    """
    all_results = []
    for item in items:
        product_name = item.get("name") or item.get("product_name", "")
        if not product_name:
            continue

        results = await search_products_async(
            product_name=product_name,
            stores=stores,
            n=n,
            fast_parse=False,
            ignore_price_format=True,
        )
        all_results.extend(results)

    return all_results


async def search_and_validate_items(
    items: List[Dict[str, Any]],
    stores: List[str],
    n: int = 3,
) -> List[Dict[str, Any]]:
    """
    Search for each tender item across stores, then validate matches with Gemini LLM.
    Uses L2 cache to skip both search and validation for previously seen items.

    Returns a list of matched groups — one per tender item — with validated store products.
    """
    from app.services.cache import get_cached, set_cached, make_validated_key

    matched_items = []

    for item in items:
        product_name = item.get("name") or item.get("product_name", "")
        if not product_name:
            continue

        # Skip service items — they can't be found in retail stores
        if is_service_item(product_name):
            logger.info(f"Skipping service item: '{product_name[:80]}'")
            matched_items.append({
                "tender_item": item,
                "matches": [],
                "skipped_reason": "service",
            })
            continue

        # L2 cache: check for validated results
        l2_key = make_validated_key(product_name, stores, n)
        cached_group = await get_cached(l2_key)
        if cached_group is not None:
            logger.info(f"L2 cache hit for '{product_name[:60]}'")
            # Restore the original tender_item from this request
            cached_group["tender_item"] = item
            matched_items.append(cached_group)
            continue

        tender_price = None
        raw_price = item.get("unit_price")
        if raw_price is not None:
            try:
                tender_price = float(raw_price)
            except (ValueError, TypeError):
                pass

        tender_quantity = None
        raw_qty = item.get("quantity")
        if raw_qty is not None:
            try:
                tender_quantity = float(raw_qty)
            except (ValueError, TypeError):
                pass

        tender_unit = item.get("unit_name")

        # Search all stores in parallel (uses L1 cache internally)
        store_results = await search_products_async(
            product_name=product_name,
            stores=stores,
            n=n,
            fast_parse=False,
            ignore_price_format=True,
        )

        # Validate with LLM (filters false positives + extracts weights)
        validated = await validate_matches(
            tender_name=product_name,
            tender_price=tender_price or 0,
            tender_quantity=tender_quantity,
            tender_unit=tender_unit,
            store_items=store_results,
        )

        # Keep only relevant matches
        relevant = [m for m in validated if m.get("is_relevant", True)]

        group = {
            "tender_item": item,
            "matches": relevant,
        }
        matched_items.append(group)

        # Store in L2 cache
        await set_cached(l2_key, group)
        logger.info(f"L2 cache miss — stored {len(relevant)} validated matches for '{product_name[:60]}'")

    return matched_items


def get_available_stores() -> List[Dict[str, str]]:
    """Return list of available stores for the frontend."""
    return [
        {"key": key, "name": info["name"], "url": info["url"]}
        for key, info in AVAILABLE_PARSERS.items()
    ]


async def save_price_history(
    item_id: int,
    matches: List[Dict[str, Any]],
) -> None:
    """Save validated store prices to PriceHistory for tracking over time.

    Called after successful scraping + LLM validation for a tender item.
    Only saves prices for relevant matches.
    """
    from app.database import SessionLocal
    from app.models.tender import PriceHistory

    if not matches or not item_id:
        return

    try:
        async with SessionLocal() as session:
            for match in matches:
                effective_price = match.get("price_on_sale") or match.get("price")
                if effective_price is None:
                    continue
                try:
                    price_val = float(effective_price)
                except (ValueError, TypeError):
                    continue

                entry = PriceHistory(
                    item_id=item_id,
                    price=price_val,
                    source_store=match.get("store_name", match.get("store", "unknown")),
                    product_title=match.get("title", "")[:500],
                    product_url=match.get("url", "")[:1000] if match.get("url") else None,
                )
                session.add(entry)

            await session.commit()
            logger.info(f"Saved {len(matches)} price history entries for item #{item_id}")
    except Exception as e:
        logger.warning(f"Failed to save price history for item #{item_id}: {e}")
