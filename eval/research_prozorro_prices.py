"""Research (E4 preparation, 28 November 2026): where do actual PRICES PER UNIT live in the Prozorro public API?

    back-end\\.venv\\Scripts\\python.exe eval/research_prozorro_prices.py [--target 200] [--out eval/results/research]

Reads only the public API (read-only GET, at most 6 requests in flight, a pause between pages). Samples completed tenders of the CPV
groups 15, 30, 39 and 44 from several months of 2026 and counts, per procedure type and per CPV group, in how many items a price per
unit exists: written explicitly in the tender item (unit.value), derivable (a single-item tender with one active award: award value /
quantity, with the VAT flag), or neither. Also looks at the contracts of the sampled tenders and at the number of tenders by procedure
type in the scanned feed (priceQuotation = electronic catalog). Writes a JSON with the raw counts; prints a summary.
"""

import argparse
import asyncio
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://public.api.openprocurement.org/api/2.5"
GROUPS = ("15", "30", "39", "44")
WINDOWS = ["2026-02-01T00:00:00", "2026-03-15T00:00:00", "2026-05-01T00:00:00", "2026-06-15T00:00:00"]  # feed offsets (dateModified)


async def get(client, url, params=None):
    for attempt in range(4):
        try:
            response = await client.get(url, params=params, timeout=60)
            if response.status_code == 200:
                return response.json()
            if response.status_code in (404, 410):
                return None
        except httpx.HTTPError:
            pass
        await asyncio.sleep(1.5 * (attempt + 1))
    return None


def cpv_group(item):
    code = ((item.get("classification") or {}).get("id") or "")[:2]
    return code


def item_price(tender, item, award):
    """(kind, unit price) where kind is explicit / derived / none."""
    unit_value = (item.get("unit") or {}).get("value") or {}
    if unit_value.get("amount") not in (None, 0):
        return "explicit", unit_value["amount"]
    items = tender.get("items") or []
    quantity = item.get("quantity")
    if award and len(items) == 1 and quantity:
        amount = (award.get("value") or {}).get("amount")
        if amount:
            return "derived", amount / quantity
    return "none", None


async def sample(target, skip_reporting=False, pages_per_window=6, contracts=False):
    counts = Counter()            # feed-level: procedure types seen among the scanned tenders
    rows = []                     # one per item of a sampled tender
    tenders_seen = tenders_used = 0
    limits = asyncio.Semaphore(6)
    async with httpx.AsyncClient(headers={"User-Agent": "CheckIT research (read-only, contact: project owner)"}) as client:
        async def fetch_tender(tender_id):
            async with limits:
                return await get(client, f"{BASE}/tenders/{tender_id}")

        for window in WINDOWS:
            offset, pages = window, 0
            while tenders_used < target * (WINDOWS.index(window) + 1) / len(WINDOWS) and pages < pages_per_window:
                feed = await get(client, f"{BASE}/tenders", {"offset": offset, "limit": 200, "opt_fields": "procurementMethodType,status"})
                if not feed or not feed.get("data"):
                    break
                pages += 1
                offset = feed["next_page"]["offset"]
                for entry in feed["data"]:
                    counts[entry.get("procurementMethodType", "?")] += 1
                complete = [e for e in feed["data"] if e.get("status") == "complete"
                            and not (skip_reporting and e.get("procurementMethodType") == "reporting")]
                results = await asyncio.gather(*(fetch_tender(e["id"]) for e in complete))
                for result in results:
                    tenders_seen += 1
                    tender = (result or {}).get("data")
                    if not tender:
                        continue
                    items = tender.get("items") or []
                    groups = {cpv_group(i) for i in items}
                    if not groups & set(GROUPS):
                        continue
                    tenders_used += 1
                    award = next((a for a in tender.get("awards", []) if a.get("status") == "active"), None)
                    contract = next((c for c in tender.get("contracts", []) if c.get("status") == "active"), None)
                    contract_items = (contract or {}).get("items") or []
                    detail = None
                    if contracts and contract:
                        async with limits:
                            detail = ((await get(client, f"{BASE}/contracts/{contract['id']}")) or {}).get("data")
                        contract_items = (detail or {}).get("items") or contract_items
                    for item in items:
                        if cpv_group(item) not in GROUPS:
                            continue
                        kind, price = item_price(tender, item, award)
                        rows.append({
                            "tender": tender["tenderID"], "type": tender.get("procurementMethodType"), "group": cpv_group(item),
                            "multi": len(items) > 1, "quantity": item.get("quantity") is not None, "kind": kind,
                            "has_active_award": award is not None, "vat": (award or {}).get("value", {}).get("valueAddedTaxIncluded"),
                            "contract_has_items": bool(contract_items),
                            "contract_item_unit_value": any(((ci.get("unit") or {}).get("value") or {}).get("amount") for ci in contract_items),
                            "award_has_items": bool((award or {}).get("items")),
                            "contract_fetched": detail is not None, "contract_changes": len((detail or {}).get("changes") or []),
                            "contract_keys": sorted((detail or {}).keys())[:0],
                        })
    return {"feed_procedure_types": counts, "tenders_scanned_complete": tenders_seen, "tenders_used": tenders_used, "rows": rows}


def summarize(data):
    rows = data["rows"]
    by_type, by_group = defaultdict(Counter), defaultdict(Counter)
    for row in rows:
        by_type[row["type"]][row["kind"]] += 1
        by_group[row["group"]][row["kind"]] += 1

    def pct(counter):
        total = sum(counter.values())
        return {k: f"{counter[k]} ({counter[k] / total * 100:.0f} %)" for k in ("explicit", "derived", "none")}, total

    print(f"complete tenders looked at: {data['tenders_scanned_complete']}, with CPV 15/30/39/44: {data['tenders_used']}, items: {len(rows)}")
    print("feed procedure types (all statuses, scanned pages):", dict(data["feed_procedure_types"].most_common(8)))
    print("\nprice per unit by procedure type:")
    for kind, counter in sorted(by_type.items(), key=lambda kv: -sum(kv[1].values())):
        shares, total = pct(counter)
        print(f"  {kind:24} items {total:4}  {shares}")
    print("\nprice per unit by CPV group:")
    for group in GROUPS:
        if by_group[group]:
            shares, total = pct(by_group[group])
            print(f"  {group}  items {total:4}  {shares}")
    overall = Counter(r["kind"] for r in rows)
    print("\noverall:", pct(overall))
    print("multi-item tenders: items", sum(1 for r in rows if r["multi"]), "| single-item:", sum(1 for r in rows if not r["multi"]))
    print("contracts with items:", sum(1 for r in rows if r["contract_has_items"]), "| contract items with unit.value:",
          sum(1 for r in rows if r["contract_item_unit_value"]), "| awards with items:", sum(1 for r in rows if r["award_has_items"]))
    print("contracts read from /contracts/{id}:", sum(1 for r in rows if r.get("contract_fetched")), "| with changes:",
          sum(1 for r in rows if r.get("contract_changes")))
    print("derived prices with unknown VAT flag:", sum(1 for r in rows if r["kind"] == "derived" and r["vat"] is None))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--target", type=int, default=200)
    parser.add_argument("--competitive", action="store_true", help="skip 'reporting' tenders, scan more feed pages, read /contracts/{id}")
    parser.add_argument("--out", default=str(ROOT / "eval" / "results" / "research"))
    args = parser.parse_args()
    if sys.stdout.encoding != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")
    data = asyncio.run(sample(args.target, skip_reporting=args.competitive, pages_per_window=40 if args.competitive else 6,
                              contracts=args.competitive))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / ("prozorro_prices_sample%s.json" % ("_competitive" if args.competitive else ""))).write_text(json.dumps({**data, "feed_procedure_types": dict(data["feed_procedure_types"])},
                                                                ensure_ascii=False), encoding="utf-8")
    summarize(data)


if __name__ == "__main__":
    main()
