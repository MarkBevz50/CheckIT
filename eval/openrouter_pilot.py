"""OpenRouter pilot: compare LLMs on the three LLM tasks of the application.

    python eval/openrouter_pilot.py --dry-run                 estimate calls and cost, no chat requests
    python eval/openrouter_pilot.py --models anthropic/claude-haiku-5.5 --limit 3 --budget 0.1
    python eval/openrouter_pilot.py --budget 2                full run (only with the owner's permission)
    python eval/openrouter_pilot.py --summarize               rebuild eval/results/pilot_summary.md from the raw answers
    python eval/openrouter_pilot.py --export-haiku-fixtures   save Haiku 5.5 answers as test fixtures

Tasks (each with the application's own prompt, imported, not copied):
  validate   _VALIDATE_SYSTEM + _build_validate_user_message (claude_validator): one call per tender item
             with all its store candidates, like the application; the answer is is_relevant per candidate.
  classify   CLASSIFY_SYSTEM_PROMPT + build_items_text (tender_classifier): item name, CPV code and unit.
  router     new prompt "is this item sold in network X?", with and without the network descriptions.

The OpenRouter key is read from the OPENROUTER_API_KEY environment variable or from .env and is
used only in the Authorization header: it is never printed, stored in results, or added to Settings.
Raw answers go to eval/results/pilot/<model>/<task>.jsonl (gitignored, resumable: finished calls are
skipped on the next run). The budget guard stops before a call whose worst-case cost would exceed --budget.
"""

import argparse
import asyncio
import hashlib
import json
import math
import os
import re
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
# the application modules read Settings on import; these placeholders are never used to connect anywhere
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://pilot:pilot@localhost:5432/pilot")
os.environ.setdefault("SECRET_KEY", "pilot-not-a-secret")
sys.path[:0] = [str(ROOT), str(ROOT / "back-end")]

from app.services.claude_validator import (  # noqa: E402
    _VALIDATE_SYSTEM, _build_validate_user_message, _parse_json_response)
from app.services.tender_classifier import CLASSIFY_SYSTEM_PROMPT, build_items_text  # noqa: E402

DATA = ROOT / "eval" / "data"
RESULTS = ROOT / "eval" / "results"
RAW = RESULTS / "pilot"
SUMMARY = RESULTS / "pilot_summary.md"
HAIKU = "anthropic/claude-haiku-5.5"
HAIKU_FIXTURES = ROOT / "back-end" / "tests" / "fixtures" / "llm" / "haiku_5_5_pilot_responses.json"
API = "https://openrouter.ai/api/v1"

# cheap models first: if the budget guard stops the run, the expensive ones are the ones left out
MODELS = [
    "anthropic/claude-haiku-5.5", "openai/gpt-6-luna", "deepseek/deepseek-v4.1-flash", "z-ai/glm-5.3-flash",
    "qwen/qwen3.8-flash", "mistralai/mistral-small-2603", "google/gemini-3.1-flash-lite",
    "openai/gpt-6.1-terra", "google/gemini-3.7-flash", "anthropic/claude-sonnet-5.5",
]

# visible-answer limits: the application uses 2000 for validation and 10-16 for classification
MAX_TOKENS = {"validate": 2000, "classify": 16, "router": 32}
REASONING_HEADROOM = 2000  # extra tokens for models whose reasoning cannot be switched off
TYPICAL_REASONING = 500  # assumed reasoning tokens per call for models that cannot switch it off (dry-run only)
EFFORT_ORDER = ["minimal", "low", "medium", "high", "xhigh", "max"]
CONCURRENCY = 6
TASKS = ("validate", "classify", "router_desc", "router_plain")

_ROUTER_NETWORKS = """
Мережі:
- Rozetka (rozetka.com.ua) — маркетплейс з дуже широким асортиментом: електроніка, інструменти, канцтовари й офісні бланки, будівельні та автотовари, побутова хімія, фасовані продукти.
- Сільпо (silpo.ua) — продуктові супермаркети: продукти харчування, напої, побутова хімія, товари догляду.
- Епіцентр (epicentrk.ua) — будівельні й господарські товари, інструменти, сад і дім.
"""
_ROUTER_TEMPLATE = """Ти — помічник, що вирішує, в яких торгових мережах шукати ціну для позиції тендерної закупівлі в Україні.

ЗАДАЧА: для позиції тендера і однієї торгової мережі визнач, чи продається в цій мережі такий товар (або його прямий аналог) у роздріб чи онлайн, тобто чи має сенс шукати його там.
{networks}
ПРАВИЛА:
- true — якщо звичайний покупець міг би знайти цей товар або його пряму заміну в цій мережі.
- false — якщо це послуга чи роботи (вони в роздріб не продаються) або явно чужа для мережі категорія.
- При сумніві став true: зайвий пошук дешевий (валідація відсіє сміття), а пропущена мережа — це втрачена ціна.

Відповідай ТІЛЬКИ JSON-об'єктом без коментарів і без markdown-обгортки:
{{"sold": true}} або {{"sold": false}}"""
ROUTER_SYSTEM = {
    "router_desc": _ROUTER_TEMPLATE.format(networks=_ROUTER_NETWORKS),
    "router_plain": _ROUTER_TEMPLATE.format(networks=""),
}
SYSTEMS = {"validate": _VALIDATE_SYSTEM, "classify": CLASSIFY_SYSTEM_PROMPT, **ROUTER_SYSTEM}


# ─── data ─────────────────────────────────────────────────────────────

def read_jsonl(path):
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x]


def load_data():
    labels = json.loads((DATA / "labels.json").read_text(encoding="utf-8"))
    pairs = read_jsonl(DATA / "pairs_pilot.jsonl")
    control = {}
    for tender in json.loads((ROOT / "eval" / "control_tenders.json").read_text(encoding="utf-8"))["tenders"]:
        for number, item in enumerate(tender["items"], start=1):
            control[f'{tender["id"]}-{number:02d}'] = item
    extra = json.loads((DATA / "classification_items.json").read_text(encoding="utf-8"))["items"]
    questions = json.loads((DATA / "router_questions.json").read_text(encoding="utf-8"))
    return labels, pairs, control, extra, questions


def build_requests(data, limit=None):
    """Return {task: [request dict]}; a request has key, user message and ground truth."""
    labels, pairs, control, extra, questions = data
    out = {task: [] for task in TASKS}

    groups = defaultdict(list)
    for pair in pairs:
        groups[pair["item_id"]].append(pair)
    for item_id, group in groups.items():
        item = control[item_id]
        store_items = [{"store_name": p["store_name"], "title": p["title"], "price": p["price"]} for p in group]
        user = _build_validate_user_message(" ".join(item["description"].split()), 0, item.get("quantity"),
                                            item.get("unit"), store_items)  # price 0 as the app does without one
        out["validate"].append({"key": f"validate:{item_id}", "user": user,
                                "truth": [labels["pairs"][p["pair_id"]] for p in group],
                                "pair_ids": [p["pair_id"] for p in group]})

    classify_items = [(i, {"name": " ".join(c["description"].split()), "cpv": c["cpv"], "unit_name": c["unit"]},
                       labels["item_types"][i], "control") for i, c in control.items()]
    classify_items += [(c["id"], {"name": c["description"], "cpv": c["cpv"], "unit_name": c["unit"]},
                        c["label"], "extra") for c in extra]
    for item_id, item, truth, origin in classify_items:
        out["classify"].append({"key": f"classify:{item_id}", "truth": truth, "origin": origin,
                                "user": f"Перелік позицій тендера:\n{build_items_text([item])}"})

    for task in ("router_desc", "router_plain"):
        for q in questions:
            out[task].append({"key": f'{task}:{q["id"]}', "truth": q["sold"], "obvious": q["obvious"],
                              "user": f'Позиція тендера: "{q["name"]}" (CPV: {q["cpv"]}) [{q["unit"]}]\n'
                                      f'Мережа: {q["network_name"]}'})
    if limit:
        out = {task: reqs[:limit] for task, reqs in out.items()}
    return out


# ─── OpenRouter ───────────────────────────────────────────────────────

def load_key():
    key = os.environ.get("OPENROUTER_API_KEY")
    if key:
        return key.strip()
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("OPENROUTER_API_KEY="):
                return line.split("=", 1)[1].strip().strip("\"'")
    return None


def fetch_catalog(models):
    """Public model list: prices and reasoning support (no key needed)."""
    data = httpx.get(f"{API}/models", timeout=60).json()["data"]
    by_id = {m["id"]: m for m in data}
    missing = [m for m in models if m not in by_id]
    if missing:
        sys.exit(f"Not in the OpenRouter catalog: {missing}")
    catalog = {}
    for model in models:
        m = by_id[model]
        catalog[model] = {"price_in": float(m["pricing"]["prompt"]), "price_out": float(m["pricing"]["completion"]),
                          "reasoning": m.get("reasoning"), "params": m.get("supported_parameters", [])}
    return catalog


def reasoning_setting(meta):
    """(reasoning request field or None, extra output-token headroom).

    Reasoning is limited wherever the model supports it: switched off if the model allows it (like the
    application, which never enables thinking), otherwise the lowest effort (or the smallest budget)."""
    info = meta.get("reasoning")
    if not info:
        return None, 0
    efforts = info.get("supported_efforts") or []
    if not info.get("mandatory"):
        if "none" in efforts:
            return {"effort": "none"}, 0
        if info.get("supports_max_tokens") or not efforts:
            return {"enabled": False}, 0
    lowest = [e for e in EFFORT_ORDER if e in efforts]
    if lowest:
        return {"effort": lowest[0]}, REASONING_HEADROOM
    if info.get("supports_max_tokens"):
        return {"max_tokens": 1024}, REASONING_HEADROOM
    return None, 0


def est_tokens(text):
    return math.ceil(len(text) / 2.2)  # rough for Ukrainian text; only used for estimates


def worst_case_cost(meta, system, user, task, headroom):
    return (est_tokens(system + user) * meta["price_in"]
            + (MAX_TOKENS[task.split("_")[0]] + headroom) * meta["price_out"])


SAFETY = 1.3  # margin on the estimate of a whole (model x task) set before it is started
TYPICAL_OUT = {"validate": 140, "classify": 3, "router": 12}  # visible output tokens per call, before any measurement


class Budget:
    """Budget guard. The real check is per (model x task) set: a set is started only if its whole estimated
    cost fits, so the stop never cuts a model in the middle of a task. The per-call check is an emergency brake."""

    def __init__(self, limit):
        self.limit, self.spent, self.skipped, self.stopped = limit, 0.0, [], False

    def fits(self, cost):
        return self.spent + cost <= self.limit

    def allow(self):
        if self.spent >= self.limit:
            self.stopped = True
        return not self.stopped


def observed_out_tokens(model, base_task):
    """Average completion tokens (visible + reasoning) per call measured so far for the model and task, else None."""
    used = [(rec["response"].get("usage") or {}).get("completion_tokens")
            for task in TASKS if task.split("_")[0] == base_task
            for rec in load_records(model, task) if "response" in rec]
    used = [u for u in used if u is not None]
    return sum(used) / len(used) if used else None


def estimate_pending(model, meta, tasks, requests):
    """Typical cost of the calls still to do, per task: {task: (cost, n_calls, source)}.
    Uses measured output tokens when the model has answers already, else the assumptions above."""
    _, headroom = reasoning_setting(meta)
    out = {}
    for task in tasks:
        base = task.split("_")[0]
        pending = [r for r in requests[task] if r["key"] not in done_keys(model, task)]
        measured = observed_out_tokens(model, base)
        n_out = measured if measured is not None else TYPICAL_OUT[base] + (TYPICAL_REASONING if headroom else 0)
        cost = sum(est_tokens(SYSTEMS[task] + r["user"]) * meta["price_in"] + n_out * meta["price_out"] for r in pending)
        out[task] = (cost, len(pending), "measured" if measured is not None else "assumed")
    return out


def result_path(model, task):
    return RAW / model.replace("/", "__") / f"{task}.jsonl"


def done_keys(model, task):
    path = result_path(model, task)
    if not path.exists():
        return set()
    records = (json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x)
    return {r["key"] for r in records if "response" in r}  # failed calls are retried on the next run


async def call_model(client, key, model, meta, task, req, budget, lock, sem):
    reasoning, headroom = reasoning_setting(meta)
    base_task = task.split("_")[0]
    system = SYSTEMS[task]
    async with sem:
        async with lock:
            if not budget.allow():
                return None
        body = {"model": model, "max_tokens": MAX_TOKENS[base_task] + headroom,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": req["user"]}]}
        if "temperature" in meta["params"]:
            body["temperature"] = 0
        if reasoning is not None:
            body["reasoning"] = reasoning
        record = {"key": req["key"], "task": task, "model": model,
                  "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                  "request": {"max_tokens": body["max_tokens"], "reasoning": reasoning,
                              "temperature": body.get("temperature"), "user": req["user"],
                              "system_sha": hashlib.sha256(system.encode()).hexdigest()[:12]}}
        started = time.perf_counter()
        for attempt in range(4):
            try:
                resp = await client.post(f"{API}/chat/completions", json=body, timeout=120,
                                         headers={"Authorization": f"Bearer {key}"})
            except httpx.HTTPError as exc:
                record["error"] = type(exc).__name__
                await asyncio.sleep(2 * (attempt + 1))
                continue
            if resp.status_code == 200:
                record.pop("error", None)
                payload = resp.json()
                break
            record["error"] = f"HTTP {resp.status_code}: {resp.text[:300]}"
            if resp.status_code not in (408, 429, 500, 502, 503, 504):
                payload = None
                break
            await asyncio.sleep(3 * (attempt + 1))
        else:
            payload = None
        record["latency_s"] = round(time.perf_counter() - started, 3)
        if payload and payload.get("choices"):
            choice = payload["choices"][0]
            message = choice.get("message") or {}
            usage = payload.get("usage") or {}
            record["response"] = {"content": message.get("content"), "finish_reason": choice.get("finish_reason"),
                                  "reasoning_chars": len(message.get("reasoning") or ""), "usage": usage}
            record.pop("error", None)
        elif payload is not None:
            record["error"] = f"no choices: {str(payload)[:200]}"
        usage = (record.get("response") or {}).get("usage") or {}
        cost = usage.get("cost")
        if cost is None:
            cost = (usage.get("prompt_tokens", 0) * meta["price_in"] + usage.get("completion_tokens", 0) * meta["price_out"])
        async with lock:
            budget.spent += cost
        path = result_path(model, task)
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record, ensure_ascii=False).replace(key, "<redacted>")  # the key never reaches the disk
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        return record


def tasks_for(model, tasks, model_tasks):
    return model_tasks.get(model, tasks)


async def run(models, tasks, model_tasks, requests, catalog, budget, key):
    lock, sem = asyncio.Lock(), asyncio.Semaphore(CONCURRENCY)
    async with httpx.AsyncClient() as client:
        for model in models:
            meta = catalog[model]
            for task, (cost, n_calls, source) in estimate_pending(model, meta, tasks_for(model, tasks, model_tasks), requests).items():
                if not n_calls:
                    continue
                need = cost * SAFETY
                if not budget.fits(need):
                    budget.skipped.append((model, task))
                    print(f"{model:36} {task:13} SKIPPED: estimated ${need:.4f} ({source} tokens) does not fit "
                          f"into the remaining ${budget.limit - budget.spent:.4f}")
                    continue
                finished = done_keys(model, task)
                jobs = [call_model(client, key, model, meta, task, r, budget, lock, sem)
                        for r in requests[task] if r["key"] not in finished]
                before = budget.spent
                made = [r for r in await asyncio.gather(*jobs) if r]
                errors = sum(1 for r in made if "response" not in r)
                print(f"{model:36} {task:13} calls={len(made):3} errors={errors} estimate=${need:.4f} "
                      f"actual=${budget.spent - before:.4f}  total=${budget.spent:.4f}/{budget.limit}")
    if budget.skipped:
        print("NOT RUN (did not fit the budget):", ", ".join(f"{m}:{t}" for m, t in budget.skipped))
    if budget.stopped:
        print("EMERGENCY STOP: the budget was exhausted inside a set; see the summary for incomplete sets.")


# ─── dry run ──────────────────────────────────────────────────────────

def dry_run(models, tasks, model_tasks, requests, catalog, budget_limit):
    print("OPENROUTER_API_KEY:", "found (hidden)" if load_key() else "NOT FOUND")
    total = 0.0
    for model in models:
        meta = catalog[model]
        reasoning, _ = reasoning_setting(meta)
        est = estimate_pending(model, meta, tasks_for(model, tasks, model_tasks), requests)
        cost = sum(c for c, _, _ in est.values())
        total += cost
        detail = ", ".join(f"{t}={n}({src[0]})" for t, (_, n, src) in est.items())
        print(f"{model:36} in ${meta['price_in'] * 1e6:6.3f}/M out ${meta['price_out'] * 1e6:6.3f}/M "
              f"reasoning={reasoning}  remaining calls: {detail}  estimate ${cost:.3f}")
    print(f"TOTAL estimate ${total:.3f} (x{SAFETY} safety = ${total * SAFETY:.3f}), budget ${budget_limit}")
    print(f"(a = assumed, m = measured output tokens from answers already received; assumption for models with "
          f"mandatory reasoning: {TYPICAL_REASONING} reasoning tokens per call; input tokens are characters / 2.2)")


def check_secrets():
    """Look for the key or an Authorization header in the raw results without printing the key."""
    key = load_key()
    hits = {"key": 0, "authorization": 0, "bearer": 0, "sk-or-": 0}
    files = list(RAW.rglob("*")) if RAW.exists() else []
    scanned = 0
    for path in (f for f in files if f.is_file()):
        scanned += 1
        text = path.read_text(encoding="utf-8", errors="replace")
        low = text.lower()
        hits["key"] += bool(key and key in text)
        hits["authorization"] += "authorization" in low
        hits["bearer"] += "bearer" in low
        hits["sk-or-"] += bool(re.search(r"sk-or-[A-Za-z0-9_-]{20,}", text))  # a key-like string, not the error text
    print(f"scanned {scanned} files in eval/results/pilot/; files with: {hits}")
    return not any(hits.values())


# ─── scoring and summary ─────────────────────────────────────────────

def load_records(model, task):
    path = result_path(model, task)
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x] if path.exists() else []


def parse_validate(content):
    data = _parse_json_response(content or "", expect_list=True)
    if not isinstance(data, list):
        return None
    out = {}
    for entry in data:
        if isinstance(entry, dict) and isinstance(entry.get("index"), int) and isinstance(entry.get("is_relevant"), bool):
            out[entry["index"]] = entry["is_relevant"]
    return out


def parse_classify(content):
    text = (content or "").strip().lower().strip("\"'.,! ")
    return text if text in ("product", "service", "work", "mixed") else None


def parse_router(content):
    data = _parse_json_response(content or "", expect_list=False)
    return data.get("sold") if isinstance(data, dict) and isinstance(data.get("sold"), bool) else None


def prf(tp, fp, fn):
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return precision, recall, f1


def score_binary(pairs_true_pred):
    """pairs of (truth bool, prediction bool or None). None counts as wrong and as 'negative'."""
    tp = sum(1 for t, p in pairs_true_pred if t and p)
    fp = sum(1 for t, p in pairs_true_pred if not t and p)
    fn = sum(1 for t, p in pairs_true_pred if t and not p)
    correct = sum(1 for t, p in pairs_true_pred if p is not None and t == p)
    precision, recall, f1 = prf(tp, fp, fn)
    return {"n": len(pairs_true_pred), "acc": correct / len(pairs_true_pred) if pairs_true_pred else 0.0,
            "precision": precision, "recall": recall, "f1": f1}


def pct(x):
    return f"{100 * x:.0f}%"


def percentile(values, q):
    if not values:
        return float("nan")
    values = sorted(values)
    return values[min(len(values) - 1, math.ceil(q * len(values)) - 1)]


def score_model(model, requests):
    res = {"model": model}
    # validation: per pair, binary relevant = same or analog
    rows, by_label, fmt = [], defaultdict(list), 0
    by_key = {r["key"]: r for r in load_records(model, "validate")}
    if len(by_key) < len(requests["validate"]):
        by_key = {}  # incomplete set: no metrics, it is listed under "incomplete sets" instead
    for req in requests["validate"]:
        rec = by_key.get(req["key"])
        parsed = parse_validate(((rec or {}).get("response") or {}).get("content")) if rec else None
        if rec and parsed is None:
            fmt += 1
        for index, (truth, pair_id) in enumerate(zip(req["truth"], req["pair_ids"]), start=1):
            if not rec:
                continue
            pred = (parsed or {}).get(index)
            rows.append((truth in ("same", "analog"), pred))
            by_label[truth].append(pred)
    res["validate"] = score_binary(rows) if rows else None
    res["validate_by_label"] = {k: (sum(1 for p in v if p) if k != "no" else sum(1 for p in v if p is False), len(v))
                                for k, v in by_label.items()}
    res["validate_fmt"] = fmt
    # classification
    by_key = {r["key"]: r for r in load_records(model, "classify")}
    if len(by_key) < len(requests["classify"]):
        by_key = {}
    binary_control, binary_extra, three = [], [], []
    fmt = 0
    for req in requests["classify"]:
        rec = by_key.get(req["key"])
        if not rec:
            continue
        pred = parse_classify(((rec.get("response") or {}).get("content")))
        if pred is None:
            fmt += 1
        (binary_control if req["origin"] == "control" else binary_extra).append(
            (req["truth"] == "product", None if pred is None else pred == "product"))
        three.append(pred == req["truth"])
    res["classify"] = {"control": score_binary(binary_control) if binary_control else None,
                       "extra": score_binary(binary_extra) if binary_extra else None,
                       "all": score_binary(binary_control + binary_extra) if three else None,
                       "three_acc": sum(three) / len(three) if three else None, "fmt": fmt}
    # router
    for task in ("router_desc", "router_plain"):
        by_key = {r["key"]: r for r in load_records(model, task)}
        if len(by_key) < len(requests[task]):
            by_key = {}
        rows, hard, fmt = [], [], 0
        for req in requests[task]:
            rec = by_key.get(req["key"])
            if not rec:
                continue
            pred = parse_router((rec.get("response") or {}).get("content"))
            if pred is None:
                fmt += 1
            rows.append((req["truth"], pred))
            if not req["obvious"]:
                hard.append((req["truth"], pred))
        res[task] = {"all": score_binary(rows) if rows else None, "hard": score_binary(hard) if hard else None, "fmt": fmt}
    # operations
    latencies, cost, tin, tout, reasoning_tokens, calls, errors, truncated = [], 0.0, 0, 0, 0, 0, 0, 0
    for task in TASKS:
        for rec in load_records(model, task):
            calls += 1
            if "response" not in rec:
                errors += 1
                continue
            usage = rec["response"].get("usage") or {}
            latencies.append(rec["latency_s"])
            cost += usage.get("cost") or 0.0
            tin += usage.get("prompt_tokens", 0)
            tout += usage.get("completion_tokens", 0)
            reasoning_tokens += (usage.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0
            truncated += rec["response"].get("finish_reason") == "length"
    res["ops"] = {"calls": calls, "errors": errors, "truncated": truncated, "p50": percentile(latencies, 0.5),
                  "p95": percentile(latencies, 0.95), "cost": cost, "tin": tin, "tout": tout,
                  "reasoning": reasoning_tokens, "per1000": 1000 * cost / calls if calls else 0.0}
    return res


def write_summary(models, requests, catalog):
    scored = [score_model(m, requests) for m in models]
    scored = [s for s in scored if s["ops"]["calls"]]
    if not scored:
        sys.exit("No raw results in eval/results/pilot/: nothing to summarize.")
    n_val = sum(len(r["truth"]) for r in requests["validate"])
    lines = [
        "# Пілот OpenRouter: порівняння моделей на трьох задачах застосунку",
        "",
        f"Зведення створено {datetime.now().strftime('%Y-%m-%d %H:%M')} скриптом `eval/openrouter_pilot.py --summarize`. "
        "Сирі відповіді моделей лежать у `eval/results/pilot/` (не в git).",
        "",
        "**Важливо про вибірку.** Це пілот: 60 пар валідації, 86 позицій класифікації (66 product + 20 work/service) і "
        "18 питань роутера. Різниця в 1–2 відповіді між моделями це шум, а не перевага. Розмітку зробив один розмітник.",
        "",
        "**Промпти й дані.** Валідація й класифікація використовують промпти застосунку (імпортовані з `claude_validator` і "
        "`tender_classifier`, а не скопійовані). Класифікація отримує назву, код CPV і одиницю виміру кожної позиції, "
        "по одній позиції в запиті. Промпт роутера новий, у двох варіантах: з описом мереж (`desc`) і без нього (`plain`).",
        "",
        "**Міркування.** Де модель дозволяє, їх вимкнено (`effort: none` або `enabled: false`, як у застосунку, що не вмикає thinking); "
        "де вимкнути не можна (`mandatory`), стоїть найнижчий `effort`, а вихідний ліміт збільшено на "
        f"{REASONING_HEADROOM} токенів. Фактичні параметри кожного запиту збережено в сирих відповідях.",
        "",
        "## 1. Валідація пар (головна метрика: «релевантний (same або analog) / ні»)",
        "",
        f"{n_val} пар. Відповідь без розбору або без запису для пари рахується як помилка й як «ні». "
        "Тристороння точність не обчислюється: промпт застосунку повертає лише `is_relevant`, тому окремо показано, "
        "яку частку `same`, `analog` і `no` модель класифікувала правильно.",
        "",
        "| Модель | Accuracy | Precision | Recall | F1 | same знайдено | analog знайдено | no відхилено | помилки формату |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for s in sorted([x for x in scored if x["validate"]], key=lambda x: -x["validate"]["f1"]):
        v, b = s["validate"], s["validate_by_label"]
        lines.append(f"| `{s['model']}` | {pct(v['acc'])} | {pct(v['precision'])} | {pct(v['recall'])} | {pct(v['f1'])} | "
                     f"{b.get('same', (0, 0))[0]}/{b.get('same', (0, 0))[1]} | {b.get('analog', (0, 0))[0]}/{b.get('analog', (0, 0))[1]} | "
                     f"{b.get('no', (0, 0))[0]}/{b.get('no', (0, 0))[1]} | {s['validate_fmt']} |")
    lines += [
        "",
        "## 2. Класифікація позицій (головна метрика: «product / не product»)",
        "",
        "Це рішення застосунок використовує, щоб запускати пошук цін. Модель відповідає `product`, `service`, `work` або `mixed`; "
        "для бінарної метрики `product` це «так», усе інше «ні». Точність окремо для 66 позицій-товарів і для 20 інших "
        "(10 робіт, 10 послуг). Тристороння точність (product/service/work) другорядна: мітки service і work визначено за "
        "конвенцією CPV (45 — роботи, 50–98 — послуги), тому позиції на кшталт «Послуга з поточного ремонту…» з CPV 45* "
        "мають мітку `work`, і модель, що читає текст, може «помилитись» через формулювання замовника, а не через слабкість.",
        "",
        "| Модель | Бінарна accuracy (всі 86) | product-позиції (66) | інші (20) | Тристороння accuracy | помилки формату |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for s in sorted([x for x in scored if x["classify"]["all"]], key=lambda x: -x["classify"]["all"]["acc"]):
        c = s["classify"]
        lines.append(f"| `{s['model']}` | {pct(c['all']['acc'])} | {pct(c['control']['acc'])} ({c['control']['n']}) | "
                     f"{pct(c['extra']['acc'])} ({c['extra']['n']}) | {pct(c['three_acc'])} | {c['fmt']} |")
    lines += [
        "",
        "## 3. Роутер: «чи продається це в мережі X» (18 питань: 9 так, 9 ні, з них 3 неочевидні «так»)",
        "",
        "Бінарна accuracy; «неочевидні» це товари, які мережа продає, хоча цього не очікуєш (бланки на Rozetka, побутова хімія в Сільпо).",
        "",
        "**Обмеження еталона.** 6 з 9 відповідей «ні» стосуються Сільпо. Перекіс відображає реальність: Rozetka як маркетплейс продає майже все, "
        "включно з продуктами, тому чесних «ні» для неї серед товарів майже немає (її «ні» це лише послуги й роботи). "
        "Крім того, «ні» для товарів спирається на топ-5 кандидатів, які повернув парсер мережі, а не на повний каталог, "
        "а «так» на ваші мітки пар або на назви кандидатів. 18 питань це орієнтир, не вимірювання.",
        "",
        "| Модель | desc: accuracy | desc: recall «так» | desc: неочевидні (3) | plain: accuracy | plain: recall «так» | plain: неочевидні (3) | помилки формату |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for s in scored:
        d, p = s["router_desc"], s["router_plain"]
        if not d["all"] or not p["all"]:
            continue
        lines.append(f"| `{s['model']}` | {pct(d['all']['acc'])} | {pct(d['all']['recall'])} | {pct(d['hard']['acc'])} | "
                     f"{pct(p['all']['acc'])} | {pct(p['all']['recall'])} | {pct(p['hard']['acc'])} | {d['fmt'] + p['fmt']} |")
    lines += [
        "",
        "## 4. Вартість, затримка й міркування (усі задачі разом)",
        "",
        "Вартість береться з `usage.cost` відповіді OpenRouter. «Токени міркувань» це частина вихідних токенів, "
        "витрачена на міркування (`completion_tokens_details.reasoning_tokens`).",
        "",
        "| Модель | Викликів | Вартість, $ | $ за 1000 викликів | p50, с | p95, с | Вхідні токени | Вихідні токени | з них міркування | Обрізано (length) | Помилки API |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for s in scored:
        o = s["ops"]
        lines.append(f"| `{s['model']}` | {o['calls']} | {o['cost']:.4f} | {o['per1000']:.3f} | {o['p50']:.1f} | {o['p95']:.1f} | "
                     f"{o['tin']} | {o['tout']} | {o['reasoning']} | {o['truncated']} | {o['errors']} |")
    expected = {t: len(requests[t]) for t in TASKS}
    gaps = []
    for model in models:
        for task in TASKS:
            got = len({r["key"] for r in load_records(model, task) if "response" in r})
            if got != expected[task]:
                gaps.append(f"`{model}`: {task} {got}/{expected[task]}" + (" (не запускалось)" if got == 0 else " (неповний набір)"))
    lines += [
        "",
        f"Загальна вартість пілоту: ${sum(s['ops']['cost'] for s in scored):.4f}.",
        "",
    ]
    if gaps:
        lines += ["**Неповні або не запущені набори** (такі результати не можна порівнювати з повними; "
                  "рядки таблиць вище для цих моделей і задач дивіться з цим застереженням):", ""]
        lines += [f"- {g}" for g in gaps] + [""]
    SUMMARY.write_text("\n".join(lines), encoding="utf-8")
    print("saved", SUMMARY.relative_to(ROOT))


def export_haiku_fixtures(requests):
    """Real answers of anthropic/claude-haiku-5.5 for the JSON-parsing tests (backlog item from E0.7)."""
    out = []
    for task in TASKS:
        by_key = {r["key"]: r for r in load_records(HAIKU, task)}
        for req in requests[task]:
            rec = by_key.get(req["key"])
            if rec and "response" in rec:
                out.append({"task": task, "key": req["key"], "user_message": req["user"],
                            "response_text": rec["response"]["content"], "finish_reason": rec["response"]["finish_reason"],
                            "output_tokens": (rec["response"]["usage"] or {}).get("completion_tokens")})
    if not out:
        sys.exit("No Haiku answers yet.")
    HAIKU_FIXTURES.parent.mkdir(parents=True, exist_ok=True)
    HAIKU_FIXTURES.write_text(json.dumps({"model": HAIKU, "note": "recorded by eval/openrouter_pilot.py; system prompts are in "
                                          "claude_validator / tender_classifier / eval/openrouter_pilot.py",
                                          "responses": out}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(len(out), "Haiku responses ->", HAIKU_FIXTURES.relative_to(ROOT))


def main():
    if sys.stdout.encoding != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--budget", type=float, default=2.0, help="stop before spending more than this many USD")
    ap.add_argument("--models", nargs="*", default=MODELS)
    ap.add_argument("--tasks", nargs="*", default=list(TASKS), choices=TASKS)
    ap.add_argument("--limit", type=int, help="at most N requests per task and model (smoke test)")
    ap.add_argument("--model-tasks", nargs="*", default=[], metavar="MODEL=TASK,TASK",
                    help="run only these tasks for a model, e.g. anthropic/claude-sonnet-5.5=validate")
    ap.add_argument("--check-secrets", action="store_true", help="scan the raw results for the key or an Authorization header")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--summarize", action="store_true")
    ap.add_argument("--export-haiku-fixtures", action="store_true")
    args = ap.parse_args()

    model_tasks = {}
    for item in args.model_tasks:
        model, _, names = item.partition("=")
        model_tasks[model] = [t for t in names.split(",") if t in TASKS]
    if args.check_secrets:
        sys.exit(0 if check_secrets() else 1)
    requests = build_requests(load_data(), None if args.summarize else args.limit)
    if args.export_haiku_fixtures:
        return export_haiku_fixtures(build_requests(load_data()))
    catalog = fetch_catalog(args.models)
    if args.summarize:
        return write_summary(args.models, requests, catalog)
    if args.dry_run:
        return dry_run(args.models, args.tasks, model_tasks, requests, catalog, args.budget)
    key = load_key()
    if not key:
        sys.exit("OPENROUTER_API_KEY is not set (environment or .env).")
    (RAW).mkdir(parents=True, exist_ok=True)
    (RAW / "models_snapshot.json").write_text(json.dumps(catalog, ensure_ascii=False, indent=1), encoding="utf-8")
    asyncio.run(run(args.models, args.tasks, model_tasks, requests, catalog, Budget(args.budget), key))


if __name__ == "__main__":
    main()
