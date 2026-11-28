"""Draws the blind control sample of the labeling scheme (E0.7): 20 random pairs of the labeling queue and 10 random findings.

    back-end\\.venv\\Scripts\\python.exe eval/make_blind_sample.py            # writes eval/data/blind_sample.json (once)
    back-end\\.venv\\Scripts\\python.exe eval/make_blind_sample.py --show     # prints the ids, changes nothing

The owner labels these items first, with no answer of any judge in sight (label_pairs.py --blind, label_source = human_blind).
The judges label them too, but only to measure how well they agree with the owner; the final label of a blind item is the
owner's. The draw is random with a fixed seed and is made BEFORE any judge has run, so the sample cannot depend on the
judges' answers. The file is never overwritten silently: --force is needed, and then the labels already given must be
reviewed by hand.
"""

import argparse
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "eval" / "data"
SAMPLE = DATA / "blind_sample.json"
SEED = 20261128
PAIRS_N, FINDINGS_N = 20, 10


def draw(pair_ids, finding_ids, seed=SEED, pairs_n=PAIRS_N, findings_n=FINDINGS_N) -> dict:
    """Random, repeatable: the same ids and seed always give the same sample. Ids are sorted first, so the order of the files is irrelevant."""
    rng = random.Random(seed)
    return {
        "seed": seed,
        "pairs": sorted(rng.sample(sorted(pair_ids), min(pairs_n, len(pair_ids)))),
        "findings": sorted(rng.sample(sorted(finding_ids), min(findings_n, len(finding_ids)))),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--show", action="store_true", help="print the current sample, change nothing")
    parser.add_argument("--force", action="store_true", help="draw again and overwrite the file")
    args = parser.parse_args()

    if args.show:
        print(SAMPLE.read_text(encoding="utf-8") if SAMPLE.exists() else "no sample yet")
        return
    if SAMPLE.exists() and not args.force:
        sys.exit(f"{SAMPLE.relative_to(ROOT)} exists; it is not overwritten without --force.")
    queue = [json.loads(line) for line in (DATA / "pairs_queue.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    pool = json.loads((DATA / "doc_findings_pool.json").read_text(encoding="utf-8"))
    sample = draw([row["pair_id"] for row in queue], [row["id"] for row in pool])
    SAMPLE.write_text(json.dumps(sample, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"pairs {len(sample['pairs'])} of {len(queue)}, findings {len(sample['findings'])} of {len(pool)}")


if __name__ == "__main__":
    main()
