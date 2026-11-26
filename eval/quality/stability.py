"""Stability of the validation (E0.7): the same labeled pairs are validated 3 times with the real API (no snapshot cache)
and we count the pairs whose decision changed between the runs. Costs real money, so it is a separate flag.

For every item that has chosen pairs the validator gets what it gets in the application: the item and all the candidates
the pilot collected for it (eval/data/candidates.jsonl), not just the chosen pair.
"""

import asyncio
import json
from pathlib import Path
from typing import Dict, List

from .capture import message_cost
from .labels import all_pair_rows, load_labels, read_jsonl

ROOT = Path(__file__).resolve().parents[2]
PAIRS_WANTED = {"same": 7, "analog": 7, "no": 6}  # 20 pairs, balanced by label


def pick_pairs(rows: List[dict], labels: dict, wanted: Dict[str, int] = PAIRS_WANTED) -> List[dict]:
    """The first pairs (by pair id) of each label, so the choice is the same on every run."""
    picked, left = [], dict(wanted)
    for row in sorted(rows, key=lambda r: r["pair_id"]):
        label = labels.get("pairs", {}).get(row["pair_id"])
        if label in left and left[label] > 0:
            picked.append({**row, "label": label})
            left[label] -= 1
    return picked


def _candidate(row: dict) -> dict:
    return {"store": row.get("store"), "store_name": row.get("store_name") or row.get("store"), "url": row.get("url"),
            "title": row.get("title"), "price": row.get("price"),
            "price_on_sale": row.get("price_on_sale") if str(row.get("is_on_sale")).lower() == "true" else None}


async def run_stability(runs: int = 3, log=print) -> dict:
    from app.services import claude_validator as cv

    labels = load_labels()
    pairs = pick_pairs(all_pair_rows(), labels)
    candidates = read_jsonl(ROOT / "eval" / "data" / "candidates.jsonl")
    controls = {}
    for tender in json.loads((ROOT / "eval" / "control_tenders.json").read_text(encoding="utf-8"))["tenders"]:
        for number, item in enumerate(tender["items"], start=1):
            controls[f"{tender['id']}-{number:02d}"] = item

    by_item: Dict[str, List[dict]] = {}
    for pair in pairs:
        by_item.setdefault(pair["item_id"], []).append(pair)

    cost = {"usd": 0.0}
    original = cv._log_usage

    def record(label, message, max_tokens):
        u = message.usage
        cost["usd"] += message_cost(message.model, u.input_tokens, u.output_tokens, u.cache_read_input_tokens or 0,
                                    u.cache_creation_input_tokens or 0)
        return original(label, message, max_tokens)

    cv._log_usage = record
    decisions: Dict[str, List[bool]] = {pair["pair_id"]: [] for pair in pairs}
    try:
        for item_id, item_pairs in by_item.items():
            control = controls[item_id]
            pool = {}
            for row in candidates:
                if row["item_id"] == item_id:
                    pool[row["url"]] = _candidate(row)
            for pair in item_pairs:
                pool.setdefault(pair["url"], _candidate(pair))
            store_items = list(pool.values())
            for _ in range(runs):
                result = await cv.validate_matches(control["description"], 0.0, float(control.get("quantity") or 0) or None,
                                                   control.get("unit"), [dict(c) for c in store_items])
                relevant = {m["url"] for m in result if m.get("is_relevant", False)}
                for pair in item_pairs:
                    decisions[pair["pair_id"]].append(pair["url"] in relevant)
            log(f"    stability {item_id}: {len(item_pairs)} pairs x {runs} runs, spent ${cost['usd']:.4f}")
    finally:
        cv._log_usage = original
    changed = [pid for pid, values in decisions.items() if len(set(values)) > 1]
    return {"pairs": len(pairs), "runs": runs, "items": len(by_item), "changed": len(changed),
            "changed_share": round(len(changed) / len(pairs), 4) if pairs else None, "changed_pairs": sorted(changed),
            "cost_usd": round(cost["usd"], 5)}


def run_stability_sync(runs: int = 3, log=print) -> dict:
    return asyncio.run(run_stability(runs, log))
