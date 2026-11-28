"""Judge A (Claude Opus in the session) reads the items through this export, which contains exactly what judge B sees:

    back-end\\.venv\\Scripts\\python.exe eval/judge_a_export.py [--pairs|--findings] [--from N --to M]

Pairs: the tender item, its unit, the store product title, the store and the price. Findings: the tender title and the quotes of
that tender (numbered). Nothing else is printed: no decision of the application's model, no type, severity or explanation of a
finding, no bucket_hint, and this script never opens eval/data/labels.json, the blind sample or the labels of judge B.
Judge A writes its labels into eval/data/judge_a_labels.json (see eval/judge_a_write.py).
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))

import judge_prompts as jp  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pairs", action="store_true")
    parser.add_argument("--findings", action="store_true")
    parser.add_argument("--from", dest="start", type=int, default=1)
    parser.add_argument("--to", dest="end", type=int, default=10_000)
    args = parser.parse_args()
    if sys.stdout.encoding != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")

    if args.pairs or not args.findings:
        rows = jp.load_pairs()
        for number, row in enumerate(rows, start=1):
            if args.start <= number <= args.end:
                print(f"--- {row['pair_id']}\n{jp.pair_user(row)}")
    if args.findings or not args.pairs:
        titles = jp.tender_titles()
        for tender, rows in jp.load_findings().items():
            print(f"\n=== {tender} ({len(rows)} quotes)\n{jp.findings_user(titles[tender], rows)}")


if __name__ == "__main__":
    main()
