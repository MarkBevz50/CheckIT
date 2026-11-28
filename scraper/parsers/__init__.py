import logging

# Logging is configured once, by the application (back-end/app/core/logging_config.py). A library package must
# not call logging.basicConfig: it used to set the root logger to ERROR for the whole process.
logger = logging.getLogger(__name__)


class ProductInfo:
    def __init__(self, url, price, is_on_sale, price_on_sale, is_available, title):
        self.url = url
        self.price = price
        self.is_on_sale = is_on_sale
        self.price_on_sale = price_on_sale
        self.is_available = is_available
        self.title = title

    def to_dict(self):
        return {
            "url": self.url,
            "price": self.price,
            "is_on_sale": self.is_on_sale,
            "price_on_sale": self.price_on_sale,
            "is_available": self.is_available,
            "title": self.title
        }

    def __str__(self):
        return str(self.to_dict())
