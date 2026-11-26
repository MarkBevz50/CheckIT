"""E0.7: metrics of the documentation-analysis modes from the owner's blind labels of the findings.

    back-end\\.venv\\Scripts\\python.exe eval/doc_findings_report.py

Reads eval/data/doc_findings_pool.json (the findings), eval/data/doc_findings_provenance.json (which mode and run produced
each one, the cost of every call) and the "findings" section of eval/data/labels.json (true / false / duplicate).
Per mode: findings, true, false, duplicates, precision (true / labeled findings), distinct true requirements, the share of
all true requirements found by any mode, cost. Writes eval/metrics/doc_findings_report.md.
"""

import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "eval" / "data"
OUT = ROOT / "eval" / "metrics" / "doc_findings_report.md"


def pct(value):
    return "н/д" if value is None else f"{value * 100:.0f} %"


def compute(provenance: dict, labels: dict) -> dict:
    marks = labels.get("findings", {})
    modes = provenance["modes"]
    stats = {m: {"findings": 0, "true": 0, "false": 0, "duplicate": 0, "unlabeled": 0, "true_ids": set(),
                 "per_run": defaultdict(int)} for m in modes}
    for entry in provenance["pool"]:
        mark = marks.get(entry["id"], {}).get("label")
        for source in entry["sources"]:
            s = stats[source["mode"]]
            s["findings"] += 1
            s["per_run"][(entry["tender"], source["run"])] += 1
            if mark is None:
                s["unlabeled"] += 1
            else:
                s[mark] += 1
                if mark == "true":
                    s["true_ids"].add(entry["id"])
    union_true = set().union(*(s["true_ids"] for s in stats.values())) if stats else set()
    costs = defaultdict(list)
    for call in provenance["calls"]:
        costs[call["mode"]].append(call["cost_usd"])
    result = {}
    for mode, s in stats.items():
        labeled = s["true"] + s["false"] + s["duplicate"]
        runs = costs[mode]
        counts = list(s["per_run"].values())
        result[mode] = {
            "label": modes[mode]["label"], "calls": len(runs), "findings": s["findings"], "true": s["true"],
            "false": s["false"], "duplicate": s["duplicate"], "unlabeled": s["unlabeled"],
            "precision": round(s["true"] / labeled, 4) if labeled else None,
            "distinct_true": len(s["true_ids"]),
            "share_of_union_true": round(len(s["true_ids"]) / len(union_true), 4) if union_true else None,
            "cost_total": round(sum(runs), 5), "cost_per_call": round(sum(runs) / len(runs), 5) if runs else None,
            "findings_per_run": f"{min(counts)}–{max(counts)}" if counts else "н/д",
        }
    return {"modes": result, "union_true": len(union_true)}


def main():
    if sys.stdout.encoding != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")
    provenance = json.loads((DATA / "doc_findings_provenance.json").read_text(encoding="utf-8"))
    labels = json.loads((DATA / "labels.json").read_text(encoding="utf-8"))
    report = compute(provenance, labels)
    lines = ["# Режими аналізу документації за розміткою знахідок", "",
             f"Знімок {provenance['snapshot']}, текст обрізано до {provenance['text_limit']} символів (як у застосунку). "
             f"Різних справжніх вимог у всіх режимах разом: {report['union_true']}.", "",
             "| Режим | Викликів | Знахідок | Справжніх | Хибних | Дублів | Без розмітки | Точність | Різних справжніх | "
             "Частка від усіх справжніх | Знахідок за прогін | Вартість усього | Вартість виклику |",
             "|" + " --- |" * 13]
    for mode, m in report["modes"].items():
        lines.append(f"| {mode}: {m['label']} | {m['calls']} | {m['findings']} | {m['true']} | {m['false']} | {m['duplicate']} | "
                     f"{m['unlabeled']} | {pct(m['precision'])} | {m['distinct_true']} | {pct(m['share_of_union_true'])} | "
                     f"{m['findings_per_run']} | ${m['cost_total']:.4f} | ${m['cost_per_call']:.4f} |")
    text = "\n".join(lines) + "\n"
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
