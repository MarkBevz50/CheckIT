"""Judge B of the labeling scheme (E0.7): a model of another family (not Claude) labels pairs and findings by the same
criteria as judge A (eval/judge_prompts.py).

    back-end\\.venv\\Scripts\\python.exe eval/judge_b.py --dry-run [--models a,b] [--with-pilot]   estimate only, no request, no key
    back-end\\.venv\\Scripts\\python.exe eval/judge_b.py --all                                       calibration, pairs, findings (in this order)
    back-end\\.venv\\Scripts\\python.exe eval/judge_b.py --calibrate | --pairs | --findings           one part
    back-end\\.venv\\Scripts\\python.exe eval/judge_b.py --status                                     what has been spent

Money: ONE hard limit of $0.50 for all runs together. The amount spent is kept in eval/data/judge_b_spend.json between
runs. Before EVERY request the script reserves the worst case of that request (input plus the whole output cap, reasoning
included) and sends it only if spent + reserved + worst case stays within the limit; otherwise it stops, keeps the partial
result and says so. The real cost of a request is `usage.cost` of the answer (else tokens x list price).

The OpenRouter key is read from OPENROUTER_API_KEY (environment or the root .env), is never printed and is stripped from
everything written to disk. Results: eval/data/judge_b_labels.json (committed), raw answers: eval/results/judge_b/ (local).
The script never reads the owner's labels.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))

import judge_prompts as jp  # noqa: E402
from openrouter_pilot import REASONING_HEADROOM, TYPICAL_REASONING, est_tokens, fetch_catalog, load_key, reasoning_setting  # noqa: E402

API = "https://openrouter.ai/api/v1"
MODEL = "google/gemini-3.7-flash"
CANDIDATES = [MODEL, "openai/gpt-6-luna", "google/gemini-3.1-flash-lite", "openai/gpt-6.1-terra"]
HARD_LIMIT = 0.50
ESTIMATE_LIMIT = 0.40
PAIR_OUT = 45          # visible answer tokens of one pair ({"label": ..., "reason": "up to 15 words"})
FINDING_OUT = 40       # visible answer tokens per finding of a list
PAIR_MAX_TOKENS = 200  # the cap of the visible answer sent with a pair request
FINDINGS_MAX_TOKENS = 4000
SAFETY = 1.3
CONCURRENCY = 4
LEDGER = ROOT / "eval" / "data" / "judge_b_spend.json"
OUT = ROOT / "eval" / "data" / "judge_b_labels.json"
RAW = ROOT / "eval" / "results" / "judge_b" / "raw.jsonl"


# ---- dry-run -------------------------------------------------------------------------------------------

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


def dry_run(models, with_pilot):
    calls = plan_calls(with_pilot)
    pairs = sum(1 for c in calls if c[0] == "pair")
    tokens_in = sum(est_tokens(c[1] + c[2]) for c in calls)
    print(f"calls: {pairs} pairs + {len(calls) - pairs} findings lists = {len(calls)}; input ≈ {tokens_in} tokens "
          f"(system prompt of the pairs ≈ {est_tokens(jp.PAIR_SYSTEM)}, of the findings ≈ {est_tokens(jp.FINDINGS_SYSTEM)})")
    catalog = fetch_catalog(models)
    print(f"\n{'model':32} {'$/M in':>7} {'$/M out':>8}  {'reasoning':32} {'estimate':>9} {'x1.3':>7} {'pilot-based':>11} {'worst case':>10}")
    for model in models:
        meta = catalog[model]
        e = estimate(meta, calls)
        pilot = measured_reasoning(model)
        measured = "n/a" if pilot is None else f"${estimate(meta, calls, pilot)['expected']:.4f}"
        mode = "off" if e["reasoning"] in ({"effort": "none"}, {"enabled": False}) else (str(e["reasoning"]) + " (cannot be off)" if e["reasoning"] else "n/a")
        print(f"{model:32} {meta['price_in'] * 1e6:7.2f} {meta['price_out'] * 1e6:8.2f}  {mode:32} ${e['expected']:8.4f} ${e['expected'] * SAFETY:6.4f} {measured:>11} ${e['worst']:9.4f}")
    print(f"\nrules: estimate x{SAFETY} must be below ${ESTIMATE_LIMIT:.2f}; hard limit ${HARD_LIMIT:.2f} for everything together; "
          f"reasoning headroom for models that cannot switch it off: {REASONING_HEADROOM} tokens per call")


# ---- the real run ---------------------------------------------------------------------------------------

class Budget:
    """One limit for all runs together; the spent amount lives in the ledger file. A request is reserved before it is sent."""

    def __init__(self, limit=HARD_LIMIT, ledger=None):
        self.limit, self.path = limit, ledger or LEDGER
        self.data = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {"spent_usd": 0.0, "calls": 0}
        self.reserved, self.stopped = 0.0, False

    @property
    def spent(self) -> float:
        return self.data["spent_usd"]

    def reserve(self, worst: float) -> bool:
        if self.spent + self.reserved + worst > self.limit:
            self.stopped = True
            return False
        self.reserved += worst
        return True

    def settle(self, worst: float, cost: float) -> None:
        self.reserved -= worst
        self.data["spent_usd"] = round(self.spent + cost, 6)
        self.data["calls"] += 1
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=1), encoding="utf-8")


def extract_json(text):
    """The first JSON value (object or array) in the text, tolerant of code fences and chatter; None if there is none."""
    decoder = json.JSONDecoder()
    for position, char in enumerate(text or ""):
        if char in "[{":
            try:
                return decoder.raw_decode(text[position:])[0]
            except ValueError:
                continue
    return None


def parse_pair(content):
    data = extract_json(content)
    label = str((data or {}).get("label", "")).strip().lower() if isinstance(data, dict) else ""
    return {"label": label if label in jp.PAIR_LABELS else "invalid", "reason": str((data or {}).get("reason", ""))[:200] if isinstance(data, dict) else ""}


def parse_findings(content, ids):
    data = extract_json(content)
    by_id = {str(item.get("id")): item for item in data if isinstance(item, dict)} if isinstance(data, list) else {}
    result = {}
    for finding_id in ids:
        item = by_id.get(finding_id)
        label = str((item or {}).get("label", "")).strip().lower()
        record = {"label": label if label in jp.FINDING_LABELS else "invalid", "reason": str((item or {}).get("reason", ""))[:200]}
        if label == "duplicate" and (item or {}).get("of"):
            record["of"] = str(item["of"]).upper()
        result[finding_id] = record
    return result


async def ask(client, key, meta, budget, lock, system, user, visible_max, kind, item_key):
    """One request. Returns (content, finish_reason, usage) or None when the budget does not allow it or the request failed."""
    reasoning, headroom = reasoning_setting(meta)
    max_tokens = visible_max + headroom
    worst = est_tokens(system + user) * meta["price_in"] + max_tokens * meta["price_out"]
    async with lock:
        if not budget.reserve(worst):
            return None
    body = {"model": MODEL, "max_tokens": max_tokens,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    if "temperature" in meta["params"]:
        body["temperature"] = 0
    if reasoning is not None:
        body["reasoning"] = reasoning
    payload, error = None, None
    for attempt in range(4):
        try:
            response = await client.post(f"{API}/chat/completions", json=body, timeout=180, headers={"Authorization": f"Bearer {key}"})
        except httpx.HTTPError as exc:
            error = type(exc).__name__
            await asyncio.sleep(2 * (attempt + 1))
            continue
        if response.status_code == 200:
            payload, error = response.json(), None
            break
        error = f"HTTP {response.status_code}"
        if response.status_code not in (408, 429, 500, 502, 503, 504):
            break
        await asyncio.sleep(3 * (attempt + 1))
    usage = (payload or {}).get("usage") or {}
    cost = usage.get("cost")
    if cost is None:
        cost = usage.get("prompt_tokens", 0) * meta["price_in"] + usage.get("completion_tokens", 0) * meta["price_out"]
    async with lock:
        budget.settle(worst, cost if payload else 0.0)
    choice = ((payload or {}).get("choices") or [{}])[0]
    content = (choice.get("message") or {}).get("content")
    RAW.parent.mkdir(parents=True, exist_ok=True)
    record = {"kind": kind, "key": item_key, "error": error, "finish": choice.get("finish_reason"), "usage": usage, "content": content}
    with RAW.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False).replace(key, "<redacted>") + "\n")
    if payload is None or content is None:
        return None
    return content, choice.get("finish_reason"), usage


def load_out():
    if OUT.exists():
        return json.loads(OUT.read_text(encoding="utf-8"))
    return {"model": MODEL, "reasoning": {"effort": "low"}, "calibration": {}, "pairs": {}, "findings": {}, "calls": []}


def save_out(data):
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(OUT)


async def run_part(part, key, budget, out=None):
    """part: calibration | pairs | findings. Skips what is already in the result file, saves after every answer."""
    out = out if out is not None else load_out()
    meta = fetch_catalog([MODEL])[MODEL]
    lock = asyncio.Lock()
    semaphore = asyncio.Semaphore(CONCURRENCY)
    done = skipped = invalid = 0

    async with httpx.AsyncClient() as client:
        async def one_pair(section, row):
            nonlocal done, skipped, invalid
            if row["pair_id"] in out[section]:
                return
            async with semaphore:
                answer = await ask(client, key, meta, budget, lock, jp.PAIR_SYSTEM, jp.pair_user(row), PAIR_MAX_TOKENS, section, row["pair_id"])
            if answer is None:
                skipped += 1
                return
            content, finish, usage = answer
            record = parse_pair(content)
            record["finish"] = finish
            out[section][row["pair_id"]] = record
            out["calls"].append({"kind": section, "key": row["pair_id"], "cost": usage.get("cost"), "tokens": usage.get("completion_tokens"),
                                 "reasoning": (usage.get("completion_tokens_details") or {}).get("reasoning_tokens")})
            done += 1
            invalid += record["label"] == "invalid"
            save_out(out)

        async def one_findings(tender, rows, title):
            nonlocal done, skipped, invalid
            if all(r["id"] in out["findings"] for r in rows):
                return
            async with semaphore:
                answer = await ask(client, key, meta, budget, lock, jp.FINDINGS_SYSTEM, jp.findings_user(title, rows),
                                   FINDINGS_MAX_TOKENS, "findings", tender)
            if answer is None:
                skipped += len(rows)
                return
            content, finish, usage = answer
            parsed = parse_findings(content, [r["id"] for r in rows])
            for finding_id, record in parsed.items():
                record["finish"] = finish
                out["findings"][finding_id] = record
                invalid += record["label"] == "invalid"
            out["calls"].append({"kind": "findings", "key": tender, "cost": usage.get("cost"), "tokens": usage.get("completion_tokens"),
                                 "reasoning": (usage.get("completion_tokens_details") or {}).get("reasoning_tokens")})
            done += len(rows)
            save_out(out)

        if part == "calibration":
            await asyncio.gather(*(one_pair("calibration", row) for row in jp.read_jsonl(jp.DATA / "pairs_pilot.jsonl")))
        elif part == "pairs":
            await asyncio.gather(*(one_pair("pairs", row) for row in jp.load_pairs()))
        else:
            titles = jp.tender_titles()
            await asyncio.gather(*(one_findings(t, rows, titles[t]) for t, rows in jp.load_findings().items()))
    return {"part": part, "answered": done, "not_sent": skipped, "invalid": invalid}


def run_all(parts):
    key = load_key()
    if not key:
        sys.exit("OPENROUTER_API_KEY is not set (environment or the root .env).")
    budget = Budget()
    out = load_out()
    print(f"model {MODEL}, effort low; spent so far ${budget.spent:.4f} of ${budget.limit:.2f}")
    for part in parts:
        result = asyncio.run(run_part(part, key, budget, out))
        print(f"{part}: answered {result['answered']}, not sent {result['not_sent']}, invalid answers {result['invalid']}; "
              f"spent ${budget.spent:.4f}")
        if budget.stopped:
            print(f"STOPPED by the budget stop-cock: the next request would exceed ${budget.limit:.2f}. The partial result is saved; "
                  f"nothing further was sent.")
            break
    costs = [c["cost"] for c in out["calls"] if c.get("cost") is not None]
    print(f"calls {len(out['calls'])}, real cost by usage ${sum(costs):.4f}, ledger ${budget.spent:.4f}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="estimate only: no request, no key")
    parser.add_argument("--models", help="comma-separated OpenRouter ids for --dry-run")
    parser.add_argument("--with-pilot", action="store_true", help="--dry-run: also count the 60 pilot pairs")
    parser.add_argument("--all", action="store_true", help="calibration (60 pilot pairs), then the queue pairs, then the findings")
    parser.add_argument("--calibrate", action="store_true")
    parser.add_argument("--pairs", action="store_true")
    parser.add_argument("--findings", action="store_true")
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args()
    if sys.stdout.encoding != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")

    if args.status:
        budget = Budget()
        return print(f"spent ${budget.spent:.4f} of ${budget.limit:.2f} in {budget.data['calls']} calls")
    if args.dry_run:
        return dry_run(args.models.split(",") if args.models else CANDIDATES, args.with_pilot)
    parts = ["calibration", "pairs", "findings"] if args.all else [p for p, flag in
                                                                    (("calibration", args.calibrate), ("pairs", args.pairs), ("findings", args.findings)) if flag]
    if not parts:
        parser.error("choose --dry-run, --status, --all or some of --calibrate --pairs --findings")
    run_all(parts)


if __name__ == "__main__":
    main()
