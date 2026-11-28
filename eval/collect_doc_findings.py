"""E0.7: collect discriminatory-requirement findings of three Claude modes on the same text, for blind labeling.

    back-end\\.venv\\Scripts\\python.exe eval/collect_doc_findings.py [--snapshot DATE] [--runs 2] [--tenders C05,C09,C10]

Modes (same prompt, same text, the text is cut to the first 30 000 characters exactly as the application does; the full
text is the subject of E5.6):
  A  Haiku 5.5, thinking "default" (what the application sent before E0.7)
  B  Haiku 5.5, thinking "disabled"
  C  Sonnet 5.5, thinking "between_tools"
Every mode runs --runs times (default 2) per tender, so the spread between runs of one mode is visible.

The document texts come from the snapshot of the control run (replay of Prozorro), the Claude calls are real (stop-cock
--budget, default $0.6). Output:
  eval/data/doc_findings_pool.json        findings of all modes in ONE list, identical quotes merged, shuffled, NO model
                                          mark: this is what label_pairs.py --findings shows (in git)
  eval/data/doc_findings_provenance.json  which mode and run produced which finding, and the cost of every call (in git, but
                                          not shown by the labeling tool)
Then: python eval/label_pairs.py --findings, and python eval/doc_findings_report.py for the metrics per mode.
"""

import argparse
import asyncio
import json
import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))

from quality.runner import prepare_environment  # noqa: E402

DATA = ROOT / "eval" / "data"
MODES = {
    "A": {"tier": "fast", "thinking": "default", "label": "Haiku 5.5, міркування за замовчуванням"},
    "B": {"tier": "fast", "thinking": "disabled", "label": "Haiku 5.5, без міркування"},
    "C": {"tier": "smart", "thinking": "between_tools", "label": "Sonnet 5.5, between_tools"},
}
TEXT_LIMIT = 30000


def normalize(quote: str) -> str:
    return re.sub(r"\s+", " ", (quote or "").strip().lower())


async def collect(tenders, runs, snapshot, budget):
    from quality.snapshot import Snapshot
    from app.core.config import settings
    from app.prozorro_functionality import prozorro as pz
    from app.routers import prozorro_router
    from app.services import claude_validator as cv
    from quality.capture import Capture

    control = {t["id"]: t for t in json.loads((ROOT / "eval" / "control_tenders.json").read_text(encoding="utf-8"))["tenders"]}
    calls, findings = [], []
    class ReadOnlyLlm(Snapshot):
        """The control run replays the Claude answers of its snapshot by the hash of the request, and mode B of this collection sends
        the very same request as the application does: writing the new answers would silently change the baseline."""

        def put(self, kind, key, value):
            if kind != "llm":
                super().put(kind, key, value)

    snapshot = ReadOnlyLlm(snapshot.date)
    with Capture(snapshot, "replay", "live", budget) as capture:
        for tender_id in tenders:
            capture.tender = tender_id
            hex_id = await prozorro_router.convert_ua_to_hex_id(control[tender_id]["ua_id"].upper())  # the application sends it upper-cased
            refs = pz.get_document_urls(pz.get_contract(hex_id).get("documents", []))
            text = (await pz.extract_documents_text(refs))[:TEXT_LIMIT]
            print(f"[{tender_id}] {len(refs)} documents, {len(text)} characters analysed")
            for mode, spec in MODES.items():
                settings.llm_document_tier, settings.llm_thinking_documents = spec["tier"], spec["thinking"]
                for run in range(1, runs + 1):
                    before = len(capture.usage)
                    result = await cv.analyze_discriminatory_requirements(text)
                    usage = capture.usage[before:]
                    calls.append({"tender": tender_id, "mode": mode, "run": run, "cost_usd": round(sum(u["cost"] for u in usage), 5),
                                  "model": usage[-1]["model"] if usage else None, "output_tokens": sum(u["output"] for u in usage),
                                  "overall_risk": (result or {}).get("overall_risk"), "failed": result is None})
                    for index, finding in enumerate((result or {}).get("discriminatory_requirements", []), start=1):
                        findings.append({"tender": tender_id, "mode": mode, "run": run, "index": index, **finding})
                    print(f"    {mode} run {run}: {len((result or {}).get('discriminatory_requirements', []))} findings, "
                          f"${calls[-1]['cost_usd']:.4f}, spent ${capture.spent_real:.4f}")
    return calls, findings


def build_pool(findings):
    """One entry per (tender, normalized quote); the explanation and type of the first occurrence are shown."""
    pool, provenance = {}, []
    for f in findings:
        key = (f["tender"], normalize(f.get("text")))
        entry = pool.setdefault(key, {"tender": f["tender"], "quote": (f.get("text") or "").strip(),
                                      "type": f.get("type"), "severity": f.get("severity"),
                                      "explanation": f.get("explanation"), "_sources": []})
        entry["_sources"].append({"mode": f["mode"], "run": f["run"], "index": f["index"], "severity": f.get("severity")})
    entries = list(pool.values())
    random.Random(20261127).shuffle(entries)  # blind order: not grouped by tender or by model
    public = []
    for number, entry in enumerate(entries, start=1):
        finding_id = f"F{number:03d}"
        public.append({"id": finding_id, **{k: v for k, v in entry.items() if k != "_sources"}})
        provenance.append({"id": finding_id, "tender": entry["tender"], "sources": entry["_sources"]})
    return public, provenance


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--snapshot")
    parser.add_argument("--runs", type=int, default=2)
    parser.add_argument("--tenders", default="C05,C09,C10")
    parser.add_argument("--budget", type=float, default=0.6)
    args = parser.parse_args()

    prepare_environment()
    from quality.snapshot import Snapshot

    date = args.snapshot or Snapshot.latest()
    snapshot = Snapshot(date)
    print(f"snapshot {date}, tenders {args.tenders}, {args.runs} runs per mode, budget ${args.budget}")
    calls, findings = asyncio.run(collect(args.tenders.split(","), args.runs, snapshot, args.budget))
    public, provenance = build_pool(findings)
    (DATA / "doc_findings_pool.json").write_text(json.dumps(public, ensure_ascii=False, indent=1), encoding="utf-8")
    (DATA / "doc_findings_provenance.json").write_text(
        json.dumps({"modes": MODES, "text_limit": TEXT_LIMIT, "snapshot": date, "calls": calls, "pool": provenance},
                   ensure_ascii=False, indent=1), encoding="utf-8")
    total = sum(c["cost_usd"] for c in calls)
    print(f"\n{len(findings)} findings -> {len(public)} items to label (identical quotes merged), cost ${total:.4f}")
    print("next: python eval/label_pairs.py --findings")


if __name__ == "__main__":
    main()
