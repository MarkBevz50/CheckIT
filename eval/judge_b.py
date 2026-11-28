"""Judge B of the labeling scheme (E0.7): a model of another family (not Claude) labels the same pairs and findings by the same
criteria as judge A. Only the --dry-run part exists so far: it estimates the cost, it sends NO chat request and needs no key.

    back-end\\.venv\\Scripts\\python.exe eval/judge_b.py --dry-run [--models a,b] [--with-pilot]

Budget rules of the whole run: a hard limit of $0.50; the estimate must stay below $0.40 (else a cheaper model is proposed);
before EVERY call the script checks that the amount spent plus the worst case of that call stays within the limit.
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))

import judge_prompts as jp  # noqa: E402
from openrouter_pilot import REASONING_HEADROOM, TYPICAL_REASONING, est_tokens, fetch_catalog, reasoning_setting  # noqa: E402

CANDIDATES = ["google/gemini-3.7-flash", "openai/gpt-6-luna", "google/gemini-3.1-flash-lite", "openai/gpt-6.1-terra"]
HARD_LIMIT = 0.50
ESTIMATE_LIMIT = 0.40
PAIR_OUT = 45          # visible answer tokens of one pair ({"label": ..., "reason": "up to 15 words"})
FINDING_OUT = 40       # visible answer tokens per finding of a list
PAIR_MAX_TOKENS = 200  # the cap sent with a pair request (worst case of a call)
FINDINGS_MAX_TOKENS = 4000
SAFETY = 1.3           # margin on the estimate, as in the pilot


def plan_calls(with_pilot: bool):
    """[(kind, system, user, expected_output_tokens, max_tokens)] for the whole run."""
    calls = []
    for row in jp.load_pairs(include_pilot=with_pilot):
        calls.append(("pair", jp.PAIR_SYSTEM, jp.pair_user(row), PAIR_OUT, PAIR_MAX_TOKENS))
    titles = jp.tender_titles()
    for tender, rows in jp.load_findings().items():
        calls.append(("findings", jp.FINDINGS_SYSTEM, jp.findings_user(titles[tender], rows), FINDING_OUT * len(rows), FINDINGS_MAX_TOKENS))
    return calls


def measured_reasoning(model):
    """Average reasoning tokens per call of this model in the pilot (eval/results/pilot, local, not in git), else None."""
    path = ROOT / "eval" / "results" / "pilot" / model.replace("/", "__") / "validate.jsonl"
    if not path.exists():
        return None
    values = []
    for line in path.read_text(encoding="utf-8").splitlines():
        usage = ((json.loads(line).get("response") or {}).get("usage") or {}) if line.strip() else {}
        tokens = (usage.get("completion_tokens_details") or {}).get("reasoning_tokens")
        if isinstance(tokens, (int, float)):
            values.append(tokens)
    return sum(values) / len(values) if values else None


def estimate(meta, calls, typical_override=None):
    reasoning, headroom = reasoning_setting(meta)
    typical = (TYPICAL_REASONING if typical_override is None else typical_override) if headroom else 0
    expected = worst = 0.0
    for _, system, user, out, max_tokens in calls:
        tokens_in = est_tokens(system + user)
        expected += tokens_in * meta["price_in"] + (out + typical) * meta["price_out"]
        worst += tokens_in * meta["price_in"] + (max_tokens + headroom) * meta["price_out"]
    return {"reasoning": reasoning, "headroom": headroom, "expected": expected, "worst": worst}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", required=True, help="estimate only (the only mode implemented so far)")
    parser.add_argument("--models", help="comma-separated OpenRouter ids, default: the candidates of this script")
    parser.add_argument("--with-pilot", action="store_true", help="also count the 60 labeled pilot pairs (calibration of the judges)")
    args = parser.parse_args()
    if sys.stdout.encoding != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")

    models = args.models.split(",") if args.models else CANDIDATES
    calls = plan_calls(args.with_pilot)
    pairs = sum(1 for c in calls if c[0] == "pair")
    tokens_in = sum(est_tokens(c[1] + c[2]) for c in calls)
    print(f"calls: {pairs} pairs + {len(calls) - pairs} findings lists = {len(calls)}; input ≈ {tokens_in} tokens "
          f"(system prompt of the pairs ≈ {est_tokens(jp.PAIR_SYSTEM)}, of the findings ≈ {est_tokens(jp.FINDINGS_SYSTEM)})")
    catalog = fetch_catalog(models)
    print(f"\n{'model':32} {'$/M in':>7} {'$/M out':>8}  {'reasoning':32} {'estimate':>9} {'x1.3':>7} {'pilot-based':>11} {'worst case':>10}")
    results = {}
    for model in models:
        meta = catalog[model]
        e = estimate(meta, calls)
        pilot = measured_reasoning(model)
        e["measured"] = estimate(meta, calls, pilot)["expected"] if pilot is not None else None
        results[model] = e
        mode = "off" if e["reasoning"] in ({"effort": "none"}, {"enabled": False}) else (str(e["reasoning"]) + " (cannot be off)" if e["reasoning"] else "n/a")
        measured = "n/a" if e["measured"] is None else f"${e['measured']:.4f}"
        print(f"{model:32} {meta['price_in'] * 1e6:7.2f} {meta['price_out'] * 1e6:8.2f}  {mode:32} ${e['expected']:8.4f} ${e['expected'] * SAFETY:6.4f} {measured:>11} ${e['worst']:9.4f}")
    print(f"\nrules: estimate x{SAFETY} must be below ${ESTIMATE_LIMIT:.2f}, the worst case of the whole run below the hard limit ${HARD_LIMIT:.2f}; "
          f"reasoning headroom for models that cannot switch it off: {REASONING_HEADROOM} tokens per call, typical {TYPICAL_REASONING}")


if __name__ == "__main__":
    main()
