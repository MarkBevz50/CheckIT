"""Pick 20 items for the classification task: 10 works (CPV 45*) and 10 services (CPV 50*-98*).

    python eval/find_classification_items.py [--seed N]

The 66 items of the control tenders are all goods, so the classifier task would check nothing.
Items come from the public Prozorro API with the same sampling as find_control_tenders.py
(random feed pages inside the last 183 days). Rules:
  * one item per tender, at most one tender per customer, at most 3 items per CPV group (first 3 digits, e.g. 452, 713);
  * the item has a description of at least 15 characters, a CPV code and a unit;
  * the tender itself is not required to have quantities, since only the text is classified.

Labeling rule (documented for the diploma): the label comes from the CPV division of the item,
as in the CPV regulation: 03-44 goods -> product, 45 construction works -> work,
50-98 services -> service. The label is never read from the item text.
Output: eval/data/classification_items.json (ground truth is the `label` field).
"""

import argparse
import json
import random
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from find_control_tenders import (BASE, DETAIL_WORKERS, WINDOW_DAYS, cpv_kind, get_json,
                                  sample_feed)

OUT = Path(__file__).resolve().parent / "data" / "classification_items.json"
QUOTA = {"work": 10, "service": 10}
MAX_PER_GROUP = 3
MAX_DETAILS = 4000
LABELS = {"works": "work", "services": "service"}


def pick_item(tender: dict, since: datetime):
    """Return the first item of the tender that is a work or a service, else None."""
    started = (tender.get("tenderPeriod") or {}).get("startDate") or tender.get("date")
    if not started or datetime.fromisoformat(started) < since:
        return None
    for item in tender.get("items") or []:
        cpv = (item.get("classification") or {}).get("id") or ""
        unit = (item.get("unit") or {}).get("name")
        description = " ".join((item.get("description") or "").split())
        label = LABELS.get(cpv_kind(cpv)) if cpv else None
        if label and unit and len(description) >= 15:
            return {"description": description, "cpv": cpv, "unit": unit, "label": label}
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=2)
    args = ap.parse_args()
    rng = random.Random(args.seed)
    since = datetime.now(timezone.utc) - timedelta(days=WINDOW_DAYS)
    chosen, customers, groups, checked = [], set(), Counter(), 0
    with httpx.Client() as client:
        entries = sample_feed(client, rng, since)
        print("feed:", len(entries), "tenders")

        def fetch(entry):
            data = get_json(client, f"{BASE}/tenders/{entry['id']}")
            return (data or {}).get("data")

        for start in range(0, min(len(entries), MAX_DETAILS), DETAIL_WORKERS * 8):
            batch = entries[start:start + DETAIL_WORKERS * 8]
            with ThreadPoolExecutor(DETAIL_WORKERS) as pool:
                tenders = list(pool.map(fetch, batch))
            for tender in filter(None, tenders):
                checked += 1
                item = pick_item(tender, since)
                if not item:
                    continue
                entity = tender.get("procuringEntity") or {}
                customer = (entity.get("identifier") or {}).get("id") or entity.get("name")
                group = item["cpv"][:3]
                have = sum(1 for c in chosen if c["label"] == item["label"])
                if (have >= QUOTA[item["label"]] or customer in customers
                        or groups[group] >= MAX_PER_GROUP):
                    continue
                customers.add(customer)
                groups[group] += 1
                chosen.append({
                    "ua_id": tender["tenderID"], "hex_id": tender["id"], "title": tender.get("title"),
                    "customer": entity.get("name"), "customer_edrpou": customer,
                    "method": tender.get("procurementMethodType"), **item,
                })
            counts = Counter(c["label"] for c in chosen)
            if all(counts[k] >= v for k, v in QUOTA.items()):
                break
    print("checked", checked, "tenders;", dict(Counter(c["label"] for c in chosen)))
    for number, item in enumerate(sorted(chosen, key=lambda c: (c["label"], c["cpv"])), start=1):
        item["id"] = f"K{number:02d}"
    chosen.sort(key=lambda c: c["id"])
    OUT.write_text(json.dumps({
        "rule": "label by CPV division: 45 -> work, 50-98 -> service (03-44 -> product, not used here)",
        "items": chosen}, ensure_ascii=False, indent=1), encoding="utf-8")
    print("saved", OUT)


if __name__ == "__main__":
    main()
