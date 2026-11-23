import logging
import requests

from scraper.parsers import ProductInfo

logger = logging.getLogger(__name__)

SILPO_API_URL = "https://sf-ecom-api.silpo.ua/v1/uk/branches/00000000-0000-0000-0000-000000000000/products"
SILPO_BASE_URL = "https://silpo.ua"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "application/json",
}


class SilpoParser:

    def _close(self):
        pass

    def _search_products(self, product: str, limit: int) -> list:
        """Search Silpo API and return product items."""
        resp = requests.get(
            SILPO_API_URL,
            params={"search": product, "limit": limit, "offset": 0},
            headers=HEADERS,
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json().get("items", [])

    def find_n_products(self, product, n, fast_parse=True, raise_exception=False, ignore_price_format=True):
        results = []
        try:
            items = self._search_products(product, n)
            logger.info(f"[silpo] Found {len(items)} products for '{product}'")

            for item in items[:n]:
                try:
                    price = item.get("price")
                    old_price = item.get("oldPrice")
                    is_on_sale = old_price is not None and old_price != price and old_price > 0
                    price_on_sale = price if is_on_sale else None
                    actual_price = old_price if is_on_sale else price

                    slug = item.get("slug", "")
                    url = f"{SILPO_BASE_URL}/product/{slug}" if slug else SILPO_BASE_URL

                    info = ProductInfo(
                        url=url,
                        price=actual_price,
                        is_on_sale=is_on_sale,
                        price_on_sale=price_on_sale,
                        is_available=True,  # API only returns available products
                        title=item.get("title", ""),
                    )
                    results.append(info)
                except Exception as e:
                    logger.warning(f"[silpo] Failed to parse product: {e}")
                    if raise_exception:
                        raise

        except Exception as e:
            logger.warning(f"[silpo] Search failed for '{product}': {e}")
            if raise_exception:
                raise

        logger.info(f"[silpo] Returning {len(results)} products for '{product}'")
        return results
