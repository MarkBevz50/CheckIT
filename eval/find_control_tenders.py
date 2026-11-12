"""Find candidate control tenders via the public Prozorro API (metadata only).

Usage:
    python eval/find_control_tenders.py [--seed N] [--out candidates.json]

Scheme (15 candidates): 5 food (CPV 15*), 3 office (30*/22*), 3 chemicals/building
(398*/44*), 2 mixed (goods + services), 2 with large documentation (several PDF/DOCX).
Every candidate has items with quantity and unit, an expected cost and was announced
within the last 6 months. Documents are never downloaded, only their metadata is read.

The feed has no CPV filter, so the script samples feed pages at random dates inside
the window and inspects tenders from them until all buckets are filled.

How the control sample was made (for the experiment-methodology chapter):
  1. The window is the last 183 days (about 6 months).
  2. 30 random dates are drawn uniformly from the window. For each date one feed page
     (up to 1000 tenders, ascending from that date) is read from the public API
     (`GET /tenders?offset=<date>&limit=1000`). Only tenders of types belowThreshold,
     aboveThresholdUA, aboveThreshold and priceQuotation, not cancelled, are kept.
  3. The kept tenders are shuffled (seeded RNG) and their details are requested.
     A tender qualifies if it has items with CPV, quantity > 0 and unit, an expected
     cost, and a tender period that started inside the window.
  4. Qualifying tenders are put first-fit into buckets (rarest first), with a minimum
     number of items per bucket (3 for goods, 2 for mixed) and at most one tender
     per customer. Document metadata (count, PDF/DOCX count) is read but no document
     is downloaded; whether a document is a scan cannot be seen from the metadata.
  5. The run with `--seed 2` checked 3994 tenders and filled every bucket except
     "mixed": no tender in the sample combined goods with services or works.
"""

import argparse
import json
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import httpx

BASE = "https://public.api.openprocurement.org/api/2.5"
WINDOW_DAYS = 183
FEED_DATES = 30  # how many random dates to sample feed pages from
FEED_PAGE = 1000
DETAIL_WORKERS = 8
MAX_DETAILS = 6000  # safety cap on per-tender requests

METHODS = {"belowThreshold", "aboveThresholdUA", "aboveThreshold", "priceQuotation"}
BAD_STATUSES = {"cancelled", "unsuccessful", "draft", "draft.pending", "draft.stage2"}

# bucket name -> quota
QUOTAS = {"mixed": 2, "large_docs": 2, "food": 5, "office": 3, "chem_build": 3}
# minimum number of items: single-item tenders make a poor control set
MIN_ITEMS = {"mixed": 2, "large_docs": 1, "food": 3, "office": 3, "chem_build": 3}


def cpv_kind(cpv: str) -> str:
    """goods / works / services by CPV division."""
    division = int(cpv[:2]) if cpv[:2].isdigit() else -1
    if 3 <= division <= 44:
        return "goods"
    if division == 45:
        return "works"
    return "services" if division >= 50 else "other"


def get_json(client: httpx.Client, url: str, params=None, tries=4):
    for attempt in range(tries):
        try:
            r = client.get(url, params=params, timeout=30)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (404, 410):
                return None
        except httpx.HTTPError:
            pass
        time.sleep(1.5 * (attempt + 1))
    return None


def sample_feed(client: httpx.Client, rng: random.Random, since: datetime):
    """Return feed entries sampled from pages starting at random dates in the window."""
    now = datetime.now(timezone.utc)
    span = (now - since).total_seconds()
    seen, entries = set(), []
    for _ in range(FEED_DATES):
        start = since + timedelta(seconds=rng.uniform(0, span - 86400))
        data = get_json(client, f"{BASE}/tenders", {
            "offset": start.isoformat(),
            "limit": FEED_PAGE,
            "opt_fields": "tenderID,status,procurementMethodType,dateCreated",
        })
        for e in (data or {}).get("data", []):
            if e["id"] in seen:
                continue
            seen.add(e["id"])
            if e.get("procurementMethodType") in METHODS and e.get("status") not in BAD_STATUSES:
                entries.append(e)
    rng.shuffle(entries)
    return entries


def doc_stats(tender: dict) -> dict:
    docs = [d for d in tender.get("documents", []) if d.get("documentOf", "tender") == "tender"]
    heavy = 0
    for d in docs:
        fmt = (d.get("format") or "").lower()
        title = (d.get("title") or "").lower()
        if "pdf" in fmt or "word" in fmt or title.endswith((".pdf", ".docx", ".doc")):
            heavy += 1
    return {"documents": len(docs), "pdf_docx": heavy}


def summarize(tender: dict, since: datetime):
    """Return a candidate dict, or None if the tender does not meet the base criteria."""
    items = tender.get("items") or []
    value = (tender.get("value") or {}).get("amount")
    started = (tender.get("tenderPeriod") or {}).get("startDate") or tender.get("date")
    if not items or not value or not started:
        return None
    if datetime.fromisoformat(started) < since:
        return None
    parsed = []
    for it in items:
        cpv = (it.get("classification") or {}).get("id")
        unit = (it.get("unit") or {}).get("name")
        qty = it.get("quantity")
        if not cpv or not unit or not qty or qty <= 0:
            return None
        parsed.append({"description": it.get("description"), "cpv": cpv, "unit": unit, "quantity": qty})
    kinds = {cpv_kind(i["cpv"]) for i in parsed}
    entity = tender.get("procuringEntity") or {}
    return {
        "ua_id": tender["tenderID"],
        "hex_id": tender["id"],
        "title": tender.get("title"),
        "customer": entity.get("name"),
        "customer_edrpou": (entity.get("identifier") or {}).get("id"),
        "method": tender.get("procurementMethodType"),
        "status": tender.get("status"),
        "started": started,
        "expected_cost": value,
        "currency": (tender.get("value") or {}).get("currency"),
        "cpv_main": parsed[0]["cpv"],
        "items_count": len(parsed),
        "items": parsed,
        "kinds": sorted(kinds),
        **doc_stats(tender),
    }


def buckets_for(c: dict) -> list:
    """Buckets a candidate qualifies for, rarest first."""
    out = []
    cpvs = [i["cpv"] for i in c["items"]]
    if "goods" in c["kinds"] and ({"services", "works"} & set(c["kinds"])):
        out.append("mixed")
    # priced goods only: a control tender should have something to compare with stores
    if c["documents"] >= 4 and c["pdf_docx"] >= 2 and "goods" in c["kinds"]:
        out.append("large_docs")
    if c["kinds"] == ["goods"]:
        def share(prefixes):
            return sum(cpv.startswith(prefixes) for cpv in cpvs) / len(cpvs)

        if share(("15",)) >= 0.8:
            out.append("food")
        if share(("30", "22")) >= 0.8:
            out.append("office")
        if share(("398", "44")) >= 0.8:
            out.append("chem_build")
    return [b for b in out if c["items_count"] >= MIN_ITEMS[b]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--out", help="write full candidate data (JSON) to this file")
    args = ap.parse_args()

    sys.stdout.reconfigure(encoding="utf-8")
    rng = random.Random(args.seed)
    since = datetime.now(timezone.utc) - timedelta(days=WINDOW_DAYS)
    picked = {b: [] for b in QUOTAS}
    used_customers = set()

    with httpx.Client(headers={"User-Agent": "checkit-eval/1.0"}) as client:
        entries = sample_feed(client, rng, since)
        print(f"feed sample: {len(entries)} tenders of suitable type/status", file=sys.stderr)

        def fetch(entry):
            data = get_json(client, f"{BASE}/tenders/{entry['id']}")
            return (data or {}).get("data")

        checked = 0
        with ThreadPoolExecutor(DETAIL_WORKERS) as pool:
            for i in range(0, min(len(entries), MAX_DETAILS), 60):
                if all(len(picked[b]) >= q for b, q in QUOTAS.items()):
                    break
                for tender in pool.map(fetch, entries[i:i + 60]):
                    checked += 1
                    if not tender:
                        continue
                    cand = summarize(tender, since)
                    if not cand or cand["customer_edrpou"] in used_customers:
                        continue
                    for b in buckets_for(cand):
                        if len(picked[b]) < QUOTAS[b]:
                            picked[b].append({**cand, "bucket": b})
                            used_customers.add(cand["customer_edrpou"])
                            break
                print(f"checked {checked}: " + ", ".join(f"{b} {len(v)}/{QUOTAS[b]}" for b, v in picked.items()),
                      file=sys.stderr)

    rows = [c for b in QUOTAS for c in picked[b]]
    print(f"\n{'#':>2} {'bucket':<11} {'UA-ID':<24} {'customer':<42} {'CPV':<12} {'items':>5} {'cost, UAH':>14} {'docs':>4} {'pdf/docx':>8}")
    for n, c in enumerate(rows, 1):
        print(f"{n:>2} {c['bucket']:<11} {c['ua_id']:<24} {(c['customer'] or '')[:40]:<42} {c['cpv_main']:<12} "
              f"{c['items_count']:>5} {c['expected_cost']:>14,.0f} {c['documents']:>4} {c['pdf_docx']:>8}")
    missing = {b: q - len(picked[b]) for b, q in QUOTAS.items() if len(picked[b]) < q}
    if missing:
        print(f"\nnot filled: {missing} (rerun with another --seed)")
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False, indent=2)
        print(f"\nfull data: {args.out}")


if __name__ == "__main__":
    main()
