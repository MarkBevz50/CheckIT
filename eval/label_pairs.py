"""Console labeling tool for the OpenRouter pilot (pairs and item types).

    python eval/label_pairs.py             items first, then pairs
    python eval/label_pairs.py --pairs     pairs only
    python eval/label_pairs.py --items     item types only
    python eval/label_pairs.py --queue     pairs the validator accepted in a control run (eval/data/pairs_queue.jsonl)
    python eval/label_pairs.py --findings  documentation findings (eval/data/doc_findings_pool.json): blind, no model mark
    python eval/label_pairs.py --blind     the blind control sample (eval/data/blind_sample.json): 20 pairs and 10 findings,
                                           shown WITHOUT any answer of the judges, label_source = human_blind
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
FINDINGS = DATA / "doc_findings_pool.json"  # made by eval/collect_doc_findings.py
BLIND = DATA / "blind_sample.json"  # made by eval/make_blind_sample.py
QUEUE = DATA / "pairs_queue.jsonl"  # filled by eval/quality_report.py with accepted matches nobody has labeled
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


def load_pairs(path: Path = PAIRS) -> list[dict]:
    if not path.exists():
        sys.exit(f"No {path.relative_to(ROOT)} yet: generate the pairs first (the queue is filled by eval/quality_report.py).")
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x]


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


_source = {"value": "human"}  # label_source of the labels given in this session: human, or human_blind for --blind


def set_source(kind, item_id):
    _labels_ref["labels"].setdefault("label_sources", {}).setdefault(kind, {})[item_id] = _source["value"]


def drop_source(kind, item_id):
    _labels_ref["labels"].setdefault("label_sources", {}).setdefault(kind, {}).pop(item_id, None)


def run(entries, labels_section, show, keys, title, kind=None):
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
                if kind:
                    drop_source(kind, previous["id"])
                queue.insert(0, entry)
                queue.insert(0, previous)
                yield_save()
            else:
                queue.insert(0, entry)
        else:
            labels_section[entry["id"]] = keys[answer]
            if kind:
                set_source(kind, entry["id"])
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


FINDING_KEYS = {"1": "true", "2": "false", "3": "duplicate"}


def show_finding(finding):
    print(f'  Тендер     : {finding["tender"]}')
    print(f'  Тип/вага   : {finding.get("type")} / {finding.get("severity")}')
    print(f'  Цитата     : {finding.get("quote")}')
    print(f'  Пояснення  : {finding.get("explanation")}')


def show_finding_blind(finding):
    """Exactly what a judge sees: the tender and the quote. No type, severity or explanation of the application's model."""
    titles = {t["id"]: t["title"] for t in json.loads(TENDERS.read_text(encoding="utf-8"))["tenders"]}
    print(f'  Тендер     : {finding["tender"]}: {titles.get(finding["tender"], "")[:120]}')
    print(f'  Цитата     : {finding.get("quote")}')


def run_findings(labels, only_ids=None, blind=False):
    """1 = a real discriminatory requirement, 2 = not one, 3 = a duplicate of another finding (asks which)."""
    if not FINDINGS.exists():
        sys.exit(f"No {FINDINGS.relative_to(ROOT)} yet: run eval/collect_doc_findings.py first.")
    pool = json.loads(FINDINGS.read_text(encoding="utf-8"))
    if only_ids is not None:
        pool = [f for f in pool if f["id"] in only_ids]
    show = show_finding_blind if blind else show_finding
    section = labels.setdefault("findings", {})
    queue = [f for f in pool if f["id"] not in section]
    skipped, history = [], []
    print(f"\n=== Знахідки документації{' (сліпа вибірка)' if blind else ''}: {len(pool) - len(queue)} of {len(pool)} done, {len(queue)} left ===")
    print("1 = справжня дискримінаційна вимога, 2 = ні, 3 = дубль іншої знахідки")
    while queue or skipped:
        if not queue:
            print("-- skipped entries again --")
            queue, skipped = skipped, []
        finding = queue.pop(0)
        print(f"\n[{sum(1 for f in pool if f['id'] in section) + 1}/{len(pool)}] {finding['id']}")
        show(finding)
        answer = ask("label", FINDING_KEYS)
        if answer == "q":
            return False
        if answer == "s":
            skipped.append(finding)
        elif answer == "b":
            if history:
                previous = history.pop()
                section.pop(previous["id"], None)
                drop_source("findings", previous["id"])
                queue.insert(0, finding)
                queue.insert(0, previous)
                save_labels(labels)
            else:
                queue.insert(0, finding)
        else:
            record = {"label": FINDING_KEYS[answer]}
            if record["label"] == "duplicate":
                for other in pool:
                    if other["tender"] == finding["tender"] and section.get(other["id"], {}).get("label") == "true":
                        print(f'     {other["id"]}: {str(other["quote"])[:110]}')
                original = input("   дубль якої вимоги (id, наприклад F012; Enter = не вказувати) > ").strip().upper()
                if original:
                    record["of"] = original
            section[finding["id"]] = record
            set_source("findings", finding["id"])
            history.append(finding)
            save_labels(labels)
    return True


def show_item(item):
    print(f'  Тендер: {item["tender_title"]}')
    print(f'  Позиція: {item["description"]}  ({item["unit"]}, CPV {item["cpv"]})')


def stats():
    labels = load_labels()
    pairs = load_pairs() if PAIRS.exists() else []
    items = load_items()
    from collections import Counter
    queue = load_pairs(QUEUE) if QUEUE.exists() else []
    labeled_queue = sum(1 for p in queue if p["pair_id"] in labels["pairs"])
    print(f"pairs : {len(labels['pairs'])}/{len(pairs) + len(queue)}", dict(Counter(labels["pairs"].values())))
    print(f"queue : {labeled_queue}/{len(queue)} labeled")
    print(f"items : {len(labels['item_types'])}/{len(items)}", dict(Counter(labels["item_types"].values())))
    sources = labels.get("label_sources", {})
    for kind in ("pairs", "findings"):
        labeled = labels.get(kind, {})
        counts = Counter(sources.get(kind, {}).get(item_id, "human") for item_id in labeled)  # no record = human (older labels)
        print(f"sources {kind}: {dict(counts)}")


def run_blind(labels):
    """The blind control sample: pairs first, then findings. Nothing of the judges' work is shown or even read here."""
    if not BLIND.exists():
        sys.exit(f"No {BLIND.relative_to(ROOT)} yet: run eval/make_blind_sample.py first.")
    sample = json.loads(BLIND.read_text(encoding="utf-8"))
    _source["value"] = "human_blind"
    rows = {row["pair_id"]: row for row in load_pairs(QUEUE)}
    pairs = [{**rows[pid], "id": pid} for pid in sample["pairs"]]
    print("Сліпа вибірка: відповідей суддів тут немає. Критерії: same = закриває позицію (фасовка може відрізнятися); "
          "analog = той самий тип товару, ціну можна порівнювати, одна неключова вимога інша; no = інший товар, аксесуар, набір, непорівнянна ціна.")
    if not run(pairs, labels["pairs"], show_pair, PAIR_KEYS, "Сліпа вибірка: пари", kind="pairs"):
        return print("Збережено. До наступного разу.")
    if not run_findings(labels, only_ids=set(sample["findings"]), blind=True):
        return print("Збережено. До наступного разу.")
    print("\nСліпу вибірку розмічено.")


def main():
    if sys.stdout.encoding != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")
    args = set(sys.argv[1:])
    if "--stats" in args:
        return stats()
    labels = load_labels()
    _labels_ref["labels"] = labels
    if "--blind" in args:
        return run_blind(labels)
    if "--findings" in args:
        return print("Готово.") if run_findings(labels) else print("Збережено. До наступного разу.")
    from_queue = "--queue" in args
    do_items = "--pairs" not in args and not from_queue
    do_pairs = "--items" not in args
    if do_items and not run(load_items(), labels["item_types"], show_item, ITEM_KEYS, "Типи позицій"):
        return print("Збережено. До наступного разу.")
    if do_pairs:
        pairs = [{**p, "id": p["pair_id"]} for p in load_pairs(QUEUE if from_queue else PAIRS)]
        if not run(pairs, labels["pairs"], show_pair, PAIR_KEYS, "Черга пар" if from_queue else "Пари", kind="pairs"):
            return print("Збережено. До наступного разу.")
    print("\nГотово.")
    stats()


if __name__ == "__main__":
    main()
