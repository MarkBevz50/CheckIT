"""Record real API responses into tests/fixtures/ (run manually, needs network).

    python back-end/tests/fixtures/record_fixtures.py          (from the repo root)

Prozorro tenders are saved as returned by the public API, with contact data redacted.
Store responses are recorded by wrapping `requests.get` while the real scraper parsers
run, and are replayed offline by tests via tests/helpers.py.
"""

import json
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from scraper.parsers.epicentr_parser import EpicentrParser  # noqa: E402
from scraper.parsers.rozetka_parser import RozetkaParser  # noqa: E402
from scraper.parsers.silpo_parser import SilpoParser  # noqa: E402

HERE = Path(__file__).resolve().parent
PROZORRO_API = "https://public.api.openprocurement.org/api/2.5/tenders/"

# fixture name -> hex tender id
TENDERS = {
    "tender_with_unit_price": "19faf82ea14446bdbc549c7bcc5db9b5",  # reporting, 1 item, unit price given
    "tender_single_item_no_unit_price": "740b08adc0544ea2ad61372fd9585a1d",  # aboveThreshold, 1 item, no unit price, 9 documents
    "tender_many_items_no_unit_price": "918e22e124484ae186116cfd8ce67f06",  # priceQuotation, 11 items
}
REDACT_KEYS = {"contactPoint", "signerInfo", "email", "telephone", "faxNumber"}


def redact(node):
    if isinstance(node, dict):
        return {k: ("REDACTED" if k in REDACT_KEYS else redact(v)) for k, v in node.items()}
    if isinstance(node, list):
        return [redact(v) for v in node]
    return node


def record_tenders():
    out = HERE / "prozorro"
    out.mkdir(exist_ok=True)
    for name, ident in TENDERS.items():
        data = requests.get(PROZORRO_API + ident, timeout=60).json()
        path = out / f"{name}.json"
        path.write_text(json.dumps(redact(data), ensure_ascii=False, indent=1), encoding="utf-8")
        print("saved", path.relative_to(ROOT))


def record_store(name, parser, query, n, slug):
    recorded = []
    real_get = requests.get

    def recording_get(url, *args, **kwargs):
        response = real_get(url, *args, **kwargs)
        try:
            body = response.json()
            kind = "json"
        except ValueError:
            body = response.text
            kind = "text"
        recorded.append({
            "url": url,
            "params": kwargs.get("params"),
            "status": response.status_code,
            "kind": kind,
            "body": body,
        })
        return response

    requests.get = recording_get
    try:
        results = parser.find_n_products(query, n)
    finally:
        requests.get = real_get
    out = HERE / "stores"
    out.mkdir(exist_ok=True)
    path = out / f"{name}_{slug}.json"
    path.write_text(
        json.dumps({"query": query, "n": n, "products_found": len(results), "requests": recorded},
                   ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    print("saved", path.relative_to(ROOT), f"({len(results)} products, {len(recorded)} requests)")


if __name__ == "__main__":
    record_tenders()
    record_store("rozetka", RozetkaParser(), "сік садочок", 2, "juice")
    record_store("silpo", SilpoParser(), "сік садочок", 2, "juice")
    record_store("epicentr", EpicentrParser(), "сік садочок", 2, "juice")
    # Rozetka answers 200 without `goods` and with meta.navigateTo (category redirect); needed for E2.2
    record_store("rozetka", RozetkaParser(), "iphone 15", 2, "iphone15_navigate_to")
