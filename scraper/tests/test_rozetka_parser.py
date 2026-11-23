import unittest
from scraper.parsers.rozetka_parser import RozetkaParser

class TestRozetkaParser(unittest.TestCase):
    
    @classmethod
    def setUpClass(self):
        self.parser = RozetkaParser()

    def test_info_product_on_sale_fast_parse_false(self):
        url = 'https://rozetka.com.ua/ua/apple-mynk3sx-a/p448428581/'

        product_info = self.parser.info_about_product(url, fast_parse=False)

        self.assertEqual(product_info.url, url)
        self.assertTrue(50000 < product_info.price < 70000)
        self.assertTrue(product_info.is_on_sale)
        self.assertTrue(50000 < product_info.price_on_sale < 70000 and product_info.price_on_sale < product_info.price)
        self.assertTrue(product_info.is_available)
        self.assertIsNotNone(product_info.title)

    def test_info_product_on_sale_fast_parse_true(self):
        url = 'https://rozetka.com.ua/ua/apple-mynk3sx-a/p448428581/'

        product_info = self.parser.info_about_product(url, fast_parse=True)

        self.assertEqual(product_info.url, url)
        self.assertTrue(50000 < product_info.price < 70000)
        self.assertIsNone(product_info.is_on_sale)
        self.assertIsNone(product_info.price_on_sale)
        self.assertIsNone(product_info.is_available)
        self.assertIsNotNone(product_info.title)

    def test_info_product_is_not_available_fast_parse_false(self):
        url = 'https://rozetka.com.ua/ua/apple-mxwn3sx-a/p448428545/'

        product_info = self.parser.info_about_product(url, fast_parse=False)

        self.assertEqual(product_info.url, url)
        self.assertTrue(50000 < product_info.price < 70000)
        self.assertTrue(product_info.is_on_sale)
        self.assertTrue(50000 < product_info.price_on_sale < 70000 and product_info.price_on_sale < product_info.price)
        self.assertFalse(product_info.is_available)
        self.assertIsNotNone(product_info.title)

    def test_info_product_is_not_available_fast_parse_true(self):
        url = 'https://rozetka.com.ua/ua/apple-mxwn3sx-a/p448428545/'

        product_info = self.parser.info_about_product(url, fast_parse=True)

        self.assertEqual(product_info.url, url)
        self.assertTrue(50000 < product_info.price < 70000)
        self.assertIsNone(product_info.is_on_sale)
        self.assertIsNone(product_info.price_on_sale)
        self.assertIsNone(product_info.is_available)
        self.assertIsNotNone(product_info.title)

    def is_not_empty(self, product):
        result = (product.title is not None) and (product.price is not None)
        return result

    def test_category_search(self):
        result = self.parser.find_n_products('iphone 15', 2)
        self.assertTrue(len(result) != 0)
        for product in result:
            self.assertTrue(self.is_not_empty(product))

    def test_basic_search(self):
        result = self.parser.find_n_products('сік садочок', 2)
        self.assertTrue(len(result) != 0)
        for product in result:
            self.assertTrue(self.is_not_empty(product))

    @classmethod
    def tearDownClass(self):
        self.parser._close()

def run_tests():
    unittest.main(exit=False)

if __name__ == '__main__':
    run_tests()
