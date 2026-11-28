"""Quality metrics of the 10 control tenders (E0.7): run, append a row to eval/metrics/history.jsonl, rebuild the report.

    python eval/quality_report.py --stage "E0.7 база" --mode live                 # real network, records a snapshot
    python eval/quality_report.py --stage "E0.7 база" --mode replay               # Prozorro and stores from the snapshot
    python eval/quality_report.py --stage "після E1.10-E1.11" --mode replay --snapshot 2026-11-28
    python eval/quality_report.py --stage "E0.7 база" --mode replay --stability   # + 3x validation of 20 labeled pairs

Run it with back-end\\.venv\\Scripts\\python.exe from the repository root. Needs the compose PostgreSQL (port 5433) and the keys
in the root .env. Costs real money only for Claude requests that are not in the snapshot (stop-cock --budget, default $1);
--stability always calls the API (3 x validation of the pairs), so it is a flag.

mode live    network for Prozorro and the stores (each distinct request once), the snapshot is written to
             eval/snapshots/control/<date>/ (not in git)
mode replay  Prozorro and the stores come from the snapshot; compare stages ONLY in replay, so that the difference is
             the change of the code and not of the market
--llm replay (default) Claude answers come from the snapshot by the hash of ALL request parameters; a miss calls the API
--llm live   every Claude request goes to the API (the answers are stored again)
"""

import argparse
import datetime
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))

from quality.runner import prepare_environment  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--stage", required=False, help='label of the stage, e.g. "E0.7 база"')
    parser.add_argument("--mode", choices=("live", "replay"))
    parser.add_argument("--llm", choices=("replay", "live"), default="replay")
    parser.add_argument("--snapshot", help="snapshot date (replay: default the latest; live: default today)")
    parser.add_argument("--tenders", help="comma-separated control ids, default all ten")
    parser.add_argument("--budget", type=float, default=1.0, help="stop-cock for real Claude requests, USD (default 1)")
    parser.add_argument("--stability", action="store_true", help="validate 20 labeled pairs 3 times with the real API")
    parser.add_argument("--no-history", action="store_true", help="do not append to history.jsonl (trial run)")
    parser.add_argument("--report-only", action="store_true", help="only rebuild quality_report.md and the chart from the history")
    args = parser.parse_args(argv)

    if not args.report_only and not (args.stage and args.mode):
        parser.error("--stage and --mode are required (except with --report-only)")
    if args.report_only:
        from quality import report

        chart = report.write_report(report.read_history())
        print(f"report rebuilt{'' if chart else ' (no chart: matplotlib is missing)'}")
        return 0

    url = prepare_environment()
    from quality import labels as label_store, metrics, report, runner, stability
    from quality.capture import BudgetExceeded, Capture, ReplayMiss
    from quality.snapshot import Snapshot

    date = args.snapshot or (datetime.date.today().isoformat() if args.mode == "live" else Snapshot.latest())
    if not date:
        print("No snapshot yet: run --mode live first.", file=sys.stderr)
        return 2
    snapshot = Snapshot(date)
    if args.mode == "replay" and not snapshot.path.exists():
        print(f"Snapshot {date} does not exist.", file=sys.stderr)
        return 2
    selected = [t.strip() for t in args.tenders.split(",")] if args.tenders else None

    print(f"stage={args.stage!r} mode={args.mode} llm={args.llm} snapshot={date} database={url.rsplit('/', 1)[1]}")
    runner.reset_database(url)
    capture = Capture(snapshot, args.mode, args.llm, args.budget)
    try:
        with capture:
            runs = runner.run_control(capture, selected)
    except (BudgetExceeded, ReplayMiss) as exc:
        print(f"STOPPED: {exc}", file=sys.stderr)
        return 3

    if args.mode == "replay":
        for run in runs:
            run["seconds"] = None  # a replay answers from files: its timings say nothing about the application

    rows = label_store.all_pair_rows()
    all_labels = label_store.load_labels()
    sets = label_store.label_sets(all_labels, rows)
    labeled = sets["all"]
    expected = {t["id"]: t.get("expected_behavior") for t in runner.load_control_tenders(selected)}
    per_tender = {run["id"]: metrics.tender_metrics(run, labeled, expected.get(run["id"]) if run["id"] == "C10" else None)
                  for run in runs}
    summary = metrics.summarize(runs, per_tender, labeled)
    quality_sets = metrics.quality_by_set([i for r in runs for i in r["items"]], sets)
    unlabeled = metrics.match_quality([i for r in runs for i in r["items"]], labeled)["unlabeled"]
    queued = label_store.append_to_queue(unlabeled, runs) if not args.no_history else 0

    stability_result = None
    if args.stability:
        print("stability: 3 runs of validation on 20 labeled pairs (real API)...")
        stability_result = stability.run_stability_sync(3)

    row = {"date": datetime.date.today().isoformat(), "sha": report.git_sha(), "stage": args.stage, "mode": args.mode,
           "llm": args.llm, "snapshot": date, "budget_usd": args.budget, "spent_real_usd": round(capture.spent_real, 5),
           "summary": summary, "quality_sets": quality_sets, "tenders": per_tender, "stability": stability_result}
    if not args.no_history:
        report.append_history(row)
        chart = report.write_report(report.read_history())
        print(f"history: {report.HISTORY.relative_to(ROOT)}, report: {report.REPORT.relative_to(ROOT)}"
              f"{'' if chart else ' (no chart: matplotlib is missing)'}")

    s = summary
    print(f"\ncoverage >=1: {report.pct(s['coverage_ge1'])}, >=3: {report.pct(s['coverage_ge3'])} | "
          f"precision {report.pct(s['precision_all'])} (same only {report.pct(s['precision_same'])}) on {s['labeled']} labeled of "
          f"{s['accepted']} accepted | false alarms {s['unsupported_alarms']}/{s['alarms']} | doc findings {s['doc_findings']}")
    print(f"cost ${s['cost_usd']:.4f} (${s['cost_real_usd']:.4f} real) | LLM calls {s['llm']['calls']}, parse failures "
          f"{s['llm']['parse_failures']}, max_tokens {s['llm']['max_tokens']} | unlabeled accepted {s['unlabeled_accepted']}, "
          f"new in the queue {queued} | snapshot {snapshot.counts()}")
    for name, q in quality_sets.items():
        print(f"labels {name:12}: precision {report.pct(q['precision_all'])} (same only {report.pct(q['precision_same'])}) on "
              f"{q['labeled']} of {q['accepted']} accepted, recall {report.pct(q['recall_labeled'])} (n {q['recall_n']})")
    if "C10" in per_tender and "expected_behavior_met" in per_tender["C10"]:
        print(f"C10 expected behavior met: {per_tender['C10']['expected_behavior_met']}")
    errors = [(r["id"], e) for r in runs for e in r["errors"]]
    for tender_id, error in errors:
        print(f"  ERROR {tender_id}: {error}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
