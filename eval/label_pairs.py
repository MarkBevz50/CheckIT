"""Console labeling tool for the OpenRouter pilot (pairs and item types).

    python eval/label_pairs.py             items first, then pairs
    python eval/label_pairs.py --pairs     pairs only
    python eval/label_pairs.py --items     item types only
    python eval/label_pairs.py --stats     progress and label distribution

Pairs (eval/data/pairs_pilot.jsonl): 1 = same, 2 = analog, 3 = no, s = skip (shown again at
the end of this run and in the next one), b = back one, q = quit.
Item types (the control tenders' items): 1 = product, 2 = service, 3 = work. A tender's own type
(mixed) is not labeled: code derives it from the item types.

Progress is written to eval/data/labels.json after every answer, and the next run continues
where the previous one stopped. The expected bucket of a pair (bucket_hint) is NOT shown, so
labeling stays blind.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "eval" / "data"
PAIRS = DATA / "pairs_pilot.jsonl"
LABELS = DATA / "labels.json"
TENDERS = ROOT / "eval" / "control_tenders.json"

PAIR_KEYS = {"1": "same", "2": "analog", "3": "no"}
ITEM_KEYS = {"1": "product", "2": "service", "3": "work"}


def load_labels() -> dict:
    if LABELS.exists():
        return json.loads(LABELS.read_text(encoding="utf-8"))
    return {"pairs": {}, "item_types": {}}


def save_labels(labels: dict) -> None:
    tmp = LABELS.with_suffix(".tmp")
    tmp.write_text(json.dumps(labels, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    tmp.replace(LABELS)  # atomic: an interrupted write never corrupts the progress


def load_pairs() -> list[dict]:
    if not PAIRS.exists():
        sys.exit(f"No {PAIRS.relative_to(ROOT)} yet: generate the pairs first.")
    return [json.loads(x) for x in PAIRS.read_text(encoding="utf-8").splitlines() if x]


def load_items() -> list[dict]:
    tenders = json.loads(TENDERS.read_text(encoding="utf-8"))["tenders"]
    items = []
    for tender in tenders:
        for number, item in enumerate(tender["items"], start=1):
            items.append({"id": f'{tender["id"]}-{number:02d}', "tender_title": tender["title"][:90],
                          "description": item["description"], "unit": item["unit"], "cpv": item.get("cpv")})
    return items


def ask(prompt: str, keys: dict) -> str:
    options = "/".join(f"{k}={v}" for k, v in keys.items())
    while True:
        answer = input(f"{prompt} [{options}, s=skip, b=back, q=quit] > ").strip().lower()
        if answer in keys or answer in ("s", "b", "q"):
            return answer


def run(entries, labels_section, show, keys, title):
    pending = [e for e in entries if e["id"] not in labels_section]
    print(f"\n=== {title}: {len(entries) - len(pending)} of {len(entries)} done, {len(pending)} left ===")
    queue, skipped, history = list(pending), [], []
    while queue or skipped:
        if not queue:
            print("-- skipped entries again --")
            queue, skipped = skipped, []
        entry = queue.pop(0)
        done = sum(1 for e in entries if e["id"] in labels_section)
        print(f"\n[{done + 1}/{len(entries)}]")
        show(entry)
        answer = ask("label", keys)
        if answer == "q":
            return False
        if answer == "s":
            skipped.append(entry)
        elif answer == "b":
            if history:
                previous = history.pop()
                labels_section.pop(previous["id"], None)
                queue.insert(0, entry)
                queue.insert(0, previous)
                yield_save()
            else:
                queue.insert(0, entry)
        else:
            labels_section[entry["id"]] = keys[answer]
            history.append(entry)
            yield_save()
    return True


_labels_ref = {}


def yield_save():
    save_labels(_labels_ref["labels"])


def show_pair(pair):
    print(f'  Позиція тендера : {pair["item"]}  ({pair["unit"]})')
    print(f'  Товар у магазині: {pair["title"]}')
    print(f'  Магазин / ціна  : {pair["store_name"]} / {pair.get("price")}')
    print(f'  Посилання       : {pair.get("url")}')


def show_item(item):
    print(f'  Тендер: {item["tender_title"]}')
    print(f'  Позиція: {item["description"]}  ({item["unit"]}, CPV {item["cpv"]})')


def stats():
    labels = load_labels()
    pairs = load_pairs() if PAIRS.exists() else []
    items = load_items()
    from collections import Counter
    print(f"pairs : {len(labels['pairs'])}/{len(pairs)}", dict(Counter(labels["pairs"].values())))
    print(f"items : {len(labels['item_types'])}/{len(items)}", dict(Counter(labels["item_types"].values())))


def main():
    if sys.stdout.encoding != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")
    args = set(sys.argv[1:])
    if "--stats" in args:
        return stats()
    labels = load_labels()
    _labels_ref["labels"] = labels
    do_items = "--pairs" not in args
    do_pairs = "--items" not in args
    if do_items and not run(load_items(), labels["item_types"], show_item, ITEM_KEYS, "Типи позицій"):
        return print("Збережено. До наступного разу.")
    if do_pairs:
        pairs = [{**p, "id": p["pair_id"]} for p in load_pairs()]
        if not run(pairs, labels["pairs"], show_pair, PAIR_KEYS, "Пари"):
            return print("Збережено. До наступного разу.")
    print("\nГотово.")
    stats()


if __name__ == "__main__":
    main()
