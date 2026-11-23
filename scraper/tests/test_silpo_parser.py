import unittest
from scraper.parsers.silpo_parser import SilpoParser

class TestSilpoParser(unittest.TestCase):
    
    @classmethod
    def setUpClass(cls):
        cls.parser = SilpoParser()

    def test_info_product_1(self):
        url = 'https://silpo.ua/product/ridkyi-zasib-frosch-dlia-prannia-kolorovykh-rechei-134375'

        product_info = self.parser.info_about_product(url, fast_parse=False)

        self.assertEqual(product_info.url, url)
        self.assertTrue((500 < product_info.price < 600) and (product_info.price > product_info.price_on_sale))
        self.assertTrue(product_info.is_on_sale)
        self.assertTrue(300 < product_info.price_on_sale < 400)
        self.assertFalse(product_info.is_available)
        self.assertIsNotNone(product_info.title)
    
    def test_info_product_2(self):
        url = 'https://silpo.ua/product/korm-dlia-kotiv-sheba-black-gold-z-indychkoiu-v-zhele-712556'

        product_info = self.parser.info_about_product(url, fast_parse=False)

        self.assertEqual(product_info.url, url)
        self.assertTrue(20 < product_info.price < 30)
        self.assertFalse(product_info.is_on_sale)
        self.assertIsNone(product_info.price_on_sale)
        self.assertTrue(product_info.is_available)
        self.assertIsNotNone(product_info.title)

    def is_not_empty(self, product):
        result = (product.title is not None) and (product.price is not None)
        return result

    def test_basic_search(self):
        result = self.parser.find_n_products('сік садочок', 2)
        self.assertTrue(len(result) != 0)
        for product in result:
            self.assertTrue(self.is_not_empty(product))

    @classmethod
    def tearDownClass(cls):
        cls.parser._close()

def run_tests():
    unittest.main(exit=False)

if __name__ == '__main__':
    run_tests()
