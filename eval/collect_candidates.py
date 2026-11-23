"""Collect store candidates for the items of the control tenders (no LLM, live network).

    python eval/collect_candidates.py                    (from the repo root)
    python eval/collect_candidates.py --only C05 C10     (some tenders only)

For every item of eval/control_tenders.json the three existing store parsers are queried
(Rozetka, Silpo, Epicentr). Raw HTTP responses are recorded by wrapping `requests.get`
(same technique as back-end/tests/fixtures/record_fixtures.py) into
eval/data/raw_store/<item_id>__<store>.json so that the pilot can be repeated offline.
Parsed candidates go to eval/data/candidates.jsonl, one line per (item, store, product).
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scraper.parsers.epicentr_parser import EpicentrParser  # noqa: E402
from scraper.parsers.rozetka_parser import RozetkaParser  # noqa: E402
from scraper.parsers.silpo_parser import SilpoParser  # noqa: E402

DATA = ROOT / "eval" / "data"
RAW = DATA / "raw_store"
PARSERS = {"rozetka": RozetkaParser, "silpo": SilpoParser, "epicentr": EpicentrParser}
PER_STORE = 5


def item_ids(tenders):
    """Yield (item_id, tender, item): C06-03 is the 3rd item of tender C06."""
    for tender in tenders:
        for number, item in enumerate(tender["items"], start=1):
            yield f'{tender["id"]}-{number:02d}', tender, item


def build_queries(description: str) -> list[str]:
    """From specific to general: cleaned name (first words), then the first two words."""
    text = re.sub(r"\s+", " ", description).strip()
    text = re.sub(r"\([^)]*\)", " ", text)                      # (0+0), (тип 1)
    text = re.sub(r"\b(ДСТУ|ГСТУ|ТУ)\s*[\d.:-]+", " ", text)   # standards
    text = re.sub(r"[\"«»]", " ", text)
    text = re.sub(r"\b\d+[.,]?\d*\s*(кг|г|л|мл|мм|м|см|шт)\b", " ", text, flags=re.I)
    words = [w for w in re.split(r"[\s,;]+", text) if w]
    queries = []
    for limit in (5, 3, 2):
        query = " ".join(words[:limit])
        if query and query not in queries:
            queries.append(query)
    return queries


def search_store(parser_cls, queries):
    """Run queries until one yields products; return (query, products, raw responses)."""
    recorded = []
    real_get = requests.get

    def recording_get(url, *args, **kwargs):
        response = real_get(url, *args, **kwargs)
        try:
            body, kind = response.json(), "json"
        except ValueError:
            body, kind = response.text, "text"
        recorded.append({"url": url, "params": kwargs.get("params"), "status": response.status_code,
                         "kind": kind, "body": body})
        return response

    requests.get = recording_get
    used, products = None, []
    try:
        parser = parser_cls()
        for query in queries:
            used = query
            products = parser.find_n_products(product=query, n=PER_STORE, fast_parse=False,
                                              ignore_price_format=True, raise_exception=False)
            if products:
                break
            time.sleep(1)
        try:
            parser._close()
        except Exception:
            pass
    except Exception as exc:  # network trouble must not stop the whole collection
        print("   error:", exc)
    finally:
        requests.get = real_get
    return used, products, recorded


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", help="tender ids, e.g. C05 C10")
    args = ap.parse_args()

    tenders = json.loads((ROOT / "eval" / "control_tenders.json").read_text(encoding="utf-8"))["tenders"]
    if args.only:
        tenders = [t for t in tenders if t["id"] in args.only]
    RAW.mkdir(parents=True, exist_ok=True)
    candidates_path = DATA / "candidates.jsonl"
    lines = []
    for item_id, tender, item in item_ids(tenders):
        queries = build_queries(item["description"])
        print(f"{item_id} {queries[0]!r}")
        for store, parser_cls in PARSERS.items():
            query, products, recorded = search_store(parser_cls, queries)
            (RAW / f"{item_id}__{store}.json").write_text(
                json.dumps({"item_id": item_id, "store": store, "queries": queries, "query_used": query,
                            "responses": recorded}, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"   {store:9} query={query!r} products={len(products)}")
            for rank, product in enumerate(products, start=1):
                lines.append({"item_id": item_id, "tender": tender["id"], "item": item["description"],
                              "unit": item["unit"], "store": store, "query": query, "rank": rank,
                              **product.to_dict()})
            time.sleep(1)
    if args.only and candidates_path.exists():  # keep other tenders' candidates
        kept = [json.loads(x) for x in candidates_path.read_text(encoding="utf-8").splitlines() if x]
        lines = [c for c in kept if c["tender"] not in args.only] + lines
    candidates_path.write_text("".join(json.dumps(c, ensure_ascii=False) + "\n" for c in lines), encoding="utf-8")
    print("candidates:", len(lines), "->", candidates_path.relative_to(ROOT))


if __name__ == "__main__":
    main()
