"""Labels of pairs (item, store product): the pilot set plus the queue that every run adds to.

eval/data/pairs_pilot.jsonl   60 pairs of the pilot (P001...), in git
eval/data/pairs_queue.jsonl   matches the validator accepted that nobody has labeled yet (Q001...), in git
eval/data/labels.json         {"pairs": {pair_id: same|analog|no}, "item_types": {...}}, in git
Label the queue with: python eval/label_pairs.py --queue
"""

import json
from pathlib import Path
from typing import Dict, List, Tuple

DATA = Path(__file__).resolve().parents[2] / "eval" / "data"
PILOT = DATA / "pairs_pilot.jsonl"
QUEUE = DATA / "pairs_queue.jsonl"
LABELS = DATA / "labels.json"


def read_jsonl(path: Path) -> List[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_labels() -> dict:
    return json.loads(LABELS.read_text(encoding="utf-8")) if LABELS.exists() else {"pairs": {}, "item_types": {}}


def all_pair_rows() -> List[dict]:
    return read_jsonl(PILOT) + read_jsonl(QUEUE)


def append_to_queue(unlabeled: List[Tuple[str, str]], runs: List[dict]) -> int:
    """Add the accepted but unlabeled (item_id, url) pairs of these runs to the queue; returns how many were new."""
    known = {(row["item_id"], row["url"]) for row in all_pair_rows()}
    queue = read_jsonl(QUEUE)
    number = max([int(row["pair_id"][1:]) for row in queue] + [0])
    details = {}
    for run in runs:
        for item in run["items"]:
            for candidate in item.get("candidates", []):
                details[(item["item_id"], candidate.get("url"))] = (run["id"], item, candidate)
    added = []
    for pair in unlabeled:
        if pair in known or pair not in details:
            continue
        number += 1
        tender_id, item, candidate = details[pair]
        added.append({
            "pair_id": f"Q{number:03d}", "tender": tender_id, "item_id": pair[0], "item": item["name"],
            "unit": item.get("unit_name") or "",
            "store": candidate.get("store"), "store_name": candidate.get("store_name"), "title": candidate.get("title"),
            "price": candidate.get("price_on_sale") or candidate.get("price"), "url": pair[1], "bucket_hint": "queue",
        })
    if added:
        with QUEUE.open("a", encoding="utf-8") as handle:
            for row in added:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return len(added)


def labeled_pairs(labels: dict, rows: List[dict]) -> Dict[Tuple[str, str], str]:
    from .metrics import label_index

    return label_index(labels, rows)
