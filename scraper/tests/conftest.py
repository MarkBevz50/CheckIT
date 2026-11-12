"""pytest hooks for the scraper tests (they are plain unittest classes and stay unchanged).

* every test here talks to the real store websites, so it gets the `live` marker and is
  deselected with `-m "not live"` (CI does that; the nightly run in E2.6 runs them);
* the 9 tests that call `info_about_product` target a method that no longer exists
  (parsers were rewritten to use store APIs) and are skipped until E2.2;
* Rozetka answers a query that matches a category ("iphone 15") with `meta.navigateTo`
  and no goods; that test is an expected failure until E2.2 follows the redirect.
  `strict=True` makes the suite fail once it starts passing, as a reminder to remove the xfail.
"""

from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent

STALE_REASON = "переписується в E2.2 (метод info_about_product більше не існує)"
CATEGORY_REASON = "Rozetka повертає meta.navigateTo; виправляється в E2.2"


def pytest_configure(config):
    config.addinivalue_line("markers", "live: calls the real store websites (network); excluded from CI")


def pytest_collection_modifyitems(config, items):
    for item in items:
        if HERE not in Path(str(item.path)).resolve().parents:
            continue
        item.add_marker(pytest.mark.live)
        if item.name.startswith("test_info_product"):
            item.add_marker(pytest.mark.skip(reason=STALE_REASON))
        elif item.cls is not None and item.cls.__name__ == "TestRozetkaParser" and item.name == "test_category_search":
            item.add_marker(pytest.mark.xfail(reason=CATEGORY_REASON, strict=True))
