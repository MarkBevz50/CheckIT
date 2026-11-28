"""Merges the labels of the two judges into labels.json (E0.7) and builds the owner's review queue.

    back-end\\.venv\\Scripts\\python.exe eval/judge_merge.py            # shows the counts, changes nothing
    back-end\\.venv\\Scripts\\python.exe eval/judge_merge.py --apply    # writes the accepted labels into eval/data/labels.json

Rules (the owner's):
  pairs     both judges gave the same label        -> accepted, label_source = "llm_consensus"
            the labels differ (or one is invalid)  -> the owner's review (label_pairs.py --review), label_source = "human"
  findings  only a unanimous "false"               -> accepted, label_source = "llm_consensus"
            everything else goes to the owner: a "true" of at least one judge, a unanimous "duplicate", any other mix
            (and every finding whose judge-A label is not independent: judge_a_labels.json["contaminated_findings"])
Never touched: a label that already exists in labels.json, whoever gave it (the owner's older labels, the blind sample, labels
accepted by an earlier merge). The script prints counts only, never labels.
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "eval" / "data"
JUDGE_A, JUDGE_B, LABELS = DATA / "judge_a_labels.json", DATA / "judge_b_labels.json", DATA / "labels.json"
PAIR_LABELS = ("same", "analog", "no")
FINDING_LABELS = ("true", "false", "duplicate")


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def plan(labels, judge_a, judge_b, pair_ids, finding_ids):
    """{"auto_pairs": {id: label}, "review_pairs": [id], "auto_findings": [id], "review_findings": {id: reason}}"""
    result = {"auto_pairs": {}, "review_pairs": [], "auto_findings": [], "review_findings": {}}
    for pair_id in pair_ids:
        if pair_id in labels.get("pairs", {}):
            continue
        a = (judge_a["pairs"].get(pair_id) or {}).get("label")
        b = (judge_b["pairs"].get(pair_id) or {}).get("label")
        if a == b and a in PAIR_LABELS:
            result["auto_pairs"][pair_id] = a
        else:
            result["review_pairs"].append(pair_id)
    contaminated = set(judge_a.get("contaminated_findings", []))
    for finding_id in finding_ids:
        if finding_id in labels.get("findings", {}):
            continue
        a = (judge_a["findings"].get(finding_id) or {}).get("label")
        b = (judge_b["findings"].get(finding_id) or {}).get("label")
        if finding_id in contaminated:
            result["review_findings"][finding_id] = "judge A not independent"
        elif a == "false" and b == "false":
            result["auto_findings"].append(finding_id)
        elif "true" in (a, b):
            result["review_findings"][finding_id] = "true by at least one judge"
        elif a == b == "duplicate":
            result["review_findings"][finding_id] = "unanimous duplicate"
        else:
            result["review_findings"][finding_id] = "other mix"
    return result


def apply(labels, merged):
    sources = labels.setdefault("label_sources", {})
    for pair_id, label in merged["auto_pairs"].items():
        labels.setdefault("pairs", {})[pair_id] = label
        sources.setdefault("pairs", {})[pair_id] = "llm_consensus"
    for finding_id in merged["auto_findings"]:
        labels.setdefault("findings", {})[finding_id] = {"label": "false"}
        sources.setdefault("findings", {})[finding_id] = "llm_consensus"
    return labels


def load_all():
    queue = [json.loads(line) for line in (DATA / "pairs_queue.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    pool = load_json(DATA / "doc_findings_pool.json")
    return load_json(LABELS), load_json(JUDGE_A), load_json(JUDGE_B), [r["pair_id"] for r in queue], [f["id"] for f in pool]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="write the accepted labels into labels.json")
    args = parser.parse_args()
    labels, a, b, pair_ids, finding_ids = load_all()
    merged = plan(labels, a, b, pair_ids, finding_ids)
    reasons = {}
    for reason in merged["review_findings"].values():
        reasons[reason] = reasons.get(reason, 0) + 1
    print(f"pairs:    accepted by consensus {len(merged['auto_pairs'])}, to the owner's review {len(merged['review_pairs'])} "
          f"(of {len(pair_ids)}; labels that already exist are left alone)")
    print(f"findings: accepted (unanimous false) {len(merged['auto_findings'])}, to the owner's review {len(merged['review_findings'])} "
          f"(of {len(finding_ids)}); reasons: {reasons}")
    if args.apply:
        tmp = LABELS.with_suffix(".tmp")
        tmp.write_text(json.dumps(apply(labels, merged), ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
        tmp.replace(LABELS)
        print("labels.json updated")
    else:
        print("nothing written (use --apply)")


if __name__ == "__main__":
    if sys.stdout.encoding != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")
    main()
