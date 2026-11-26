"""Build eval/data/pairs_pilot.jsonl from eval/data/candidates.jsonl (offline).

    python eval/build_pairs.py

The candidates come from the store parsers (collect_candidates.py, no LLM). The selection
below was made by hand after reading the candidate lists; `bucket_hint` records what the
selector expected and is never shown to the labeler (label_pairs.py) or to the models.
Pairs are shuffled with a fixed seed so labeling is not clustered by bucket.

Selection key: "<item_id>:<store prefix><rank in the store's results>", store prefixes:
roz = Rozetka, sil = Silpo, epi = Epicentr.
"""

import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "eval" / "data"
STORES = {"roz": "rozetka", "sil": "silpo", "epi": "epicentr"}

SELECTION = {
    # same product (brand/spec/pack agree)
    "match": [
        "C03-02:roz1", "C03-02:roz2", "C03-05:roz1", "C03-06:roz3", "C03-10:roz4",
        "C04-02:roz1", "C04-04:roz3", "C05-03:roz4", "C06-02:roz1", "C06-06:roz4",
        "C06-08:roz4", "C06-10:roz3", "C06-11:roz5", "C06-13:roz4", "C07-01:roz3",
        "C07-07:roz3", "C07-08:roz1", "C07-09:roz1", "C09-08:epi2",
    ],
    # analog: other brand, pack size or a looser spec
    "analog": [
        "C01-01:roz5", "C01-02:roz3", "C03-01:roz1", "C03-04:roz3", "C03-09:roz2",
        "C04-01:roz1", "C04-03:roz3", "C05-01:roz4", "C06-03:roz5", "C06-04:roz1",
        "C06-07:roz1", "C07-06:roz2", "C07-10:sil3", "C08-05:roz1", "C09-05:roz2",
    ],
    # similar words but a different product (or wrong model/size)
    "hard_false": [
        "C01-03:roz1", "C02-02:roz4", "C03-03:sil1", "C03-08:roz3", "C04-04:roz2",
        "C05-01:roz1", "C05-02:roz1", "C06-09:roz1", "C06-10:roz4", "C06-11:roz3",
        "C06-12:sil1", "C06-13:roz1", "C07-04:roz1", "C07-11:roz1", "C08-02:roz3",
        "C08-04:roz2",
    ],
    # control tender C10: there are no analogs on the market
    "no_analog": [
        "C10-01:sil1", "C10-01:sil3", "C10-02:roz1", "C10-02:roz2", "C10-02:sil3",
        "C10-03:roz1", "C10-03:roz2", "C10-03:roz3", "C10-03:roz4", "C10-03:roz5",
    ],
}


def main():
    candidates = [json.loads(x) for x in (DATA / "candidates.jsonl").read_text(encoding="utf-8").splitlines() if x]
    index = {(c["item_id"], c["store"], c["rank"]): c for c in candidates}
    pairs = []
    for bucket, keys in SELECTION.items():
        for key in keys:
            item_id, spot = key.split(":")
            store, rank = STORES[spot[:3]], int(spot[3:])
            c = index[(item_id, store, rank)]
            pairs.append({
                "tender": c["tender"], "item_id": item_id,
                "item": " ".join(c["item"].split()), "unit": c["unit"],
                "store": store, "store_name": {"rozetka": "Rozetka", "silpo": "Сільпо", "epicentr": "Епіцентр"}[store],
                "title": c["title"], "price": c.get("price"), "url": c.get("url"),
                "bucket_hint": bucket,
            })
    random.Random(7).shuffle(pairs)
    for number, pair in enumerate(pairs, start=1):
        pair["pair_id"] = f"P{number:03d}"
    pairs = [{"pair_id": p["pair_id"], **{k: v for k, v in p.items() if k != "pair_id"}} for p in pairs]
    out = DATA / "pairs_pilot.jsonl"
    out.write_text("".join(json.dumps(p, ensure_ascii=False) + "\n" for p in pairs), encoding="utf-8")
    counts = {b: len(k) for b, k in SELECTION.items()}
    print(len(pairs), "pairs ->", out.relative_to(ROOT), counts)


if __name__ == "__main__":
    main()
