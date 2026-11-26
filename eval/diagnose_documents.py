"""E0.7 diagnosis: why does `extract_items_from_text` return 0 items, and does the discriminatory-requirements
analysis work on the document text itself? Runs inside the backend container (same code, same keys):

    docker compose exec -T -e PYTHONPATH=/app:/app/back-end backend python - C05 C09 C10 < eval/diagnose_documents.py

For every tender it downloads the public documents the way `parse_documents` does, then sends the combined text
(1) to item extraction and (2) straight to the discriminatory-requirements analysis, each in three modes:
  A  Haiku, thinking "default" (what the application did before E0.7)
  B  Haiku, thinking "disabled"
  C  Sonnet, thinking "between_tools"
Raw answers are printed (shortened) and the full texts and answers are written to /tmp/diagnose_documents/.
Nothing is written to the database. Stops when the spent amount passes the budget (default $0.60).
"""
import asyncio
import json
import logging
import os
import sys
from types import SimpleNamespace

import app.main  # noqa: F401  (sets up the application and its logging)

from app.core.config import settings  # noqa: E402
from app.prozorro_functionality import prozorro as pz  # noqa: E402
from app.routers.prozorro_router import convert_ua_to_hex_id  # noqa: E402
from app.services import claude_validator as cv  # noqa: E402

logging.getLogger().setLevel(logging.WARNING)
OUT = "/tmp/diagnose_documents"
os.makedirs(OUT, exist_ok=True)
BUDGET = float(os.environ.get("BUDGET_USD", "0.60"))
CONTROL = {"C02": "UA-2026-05-25-008612-a", "C05": "UA-2026-08-28-003259-a", "C09": "UA-2026-07-29-003387-a",
           "C10": "UA-2026-07-03-003732-a"}
PRICES = {"claude-haiku-5-5": (0.10e-6, 0.50e-6), "claude-sonnet-5-5": (2.00e-6, 10.00e-6)}
MODES = {
    "A haiku/default": ("fast", "default"),
    "B haiku/disabled": ("fast", "disabled"),
    "C sonnet/between_tools": ("smart", "between_tools"),
}
spent = 0.0
last = {}


class Recorder:
    """Wraps the real client: remembers the last message (raw answer, blocks, usage)."""

    def __init__(self, real):
        self.messages = SimpleNamespace(create=self._create)
        self._real = real

    async def _create(self, **kwargs):
        message = await self._real.messages.create(**kwargs)
        last["message"] = message
        last["kwargs"] = kwargs
        return message


def cost_of(message):
    u = message.usage
    pin, pout = PRICES.get(message.model, (0, 0))
    return (u.input_tokens + (u.cache_creation_input_tokens or 0) * 1.25 + (u.cache_read_input_tokens or 0) * 0.1) * pin + u.output_tokens * pout


async def collect_text(ua_id):
    hex_id = await convert_ua_to_hex_id(ua_id)
    contract = pz.get_contract(hex_id)
    refs = pz.get_document_urls(contract.get("documents", []))
    import requests

    parts, stats = [], []
    for url, doc_type in refs:
        try:
            response = requests.get(url, timeout=60)
            response.raise_for_status()
            if doc_type == "pdf":
                text = await pz._extract_text_all_pages(response.content)
            elif doc_type == "docx":
                text = pz.extract_text_from_docx(response.content)
            else:
                pdf = await asyncio.to_thread(pz.convert_doc_to_pdf, response.content)
                text = await pz._extract_text_all_pages(pdf)
        except Exception as exc:  # noqa: BLE001
            stats.append((doc_type, 0, f"FAILED {type(exc).__name__}: {str(exc)[:80]}"))
            continue
        stats.append((doc_type, len(text.strip()), url[-40:]))
        if text.strip():
            parts.append(text)
    return "\n\n".join(parts), stats


async def run_mode(task, mode, text):
    global spent
    tier, thinking = MODES[mode]
    settings.llm_document_tier = tier
    settings.llm_thinking_extract = thinking
    settings.llm_thinking_documents = thinking
    last.clear()
    if task == "extract":
        result = await cv.extract_items_from_text(text)
        shown = f"{len(result)} items" if result is not None else "None (parse failed or call failed)"
    else:
        result = await cv.analyze_discriminatory_requirements(text)
        if result is None:
            shown = "None"
        else:
            findings = result.get("discriminatory_requirements", [])
            shown = f"overall={result.get('overall_risk')} findings={len(findings)} " + ", ".join(
                f"{f.get('severity')}:{str(f.get('type'))[:24]}" for f in findings[:6])
    message = last.get("message")
    if message is None:
        return f"{task:8} {mode:24} NO CALL MADE ({shown})", result
    spent += cost_of(message)
    u = message.usage
    raw = "".join(getattr(b, "text", "") for b in message.content)
    line = (f"{task:8} {mode:24} {message.model} stop={message.stop_reason} blocks={[b.type for b in message.content]} "
            f"in={u.input_tokens} out={u.output_tokens} ${cost_of(message):.4f} -> {shown}\n"
            f"          raw[:200]={raw[:200]!r}")
    return line, {"result": result, "raw": raw}


async def main(ids):
    cv._client = Recorder(cv._get_client())
    for cid in ids:
        text, stats = await collect_text(CONTROL[cid])
        open(f"{OUT}/{cid}_text.txt", "w", encoding="utf-8").write(text)
        print(f"\n===== {cid} {CONTROL[cid]}: {len(stats)} documents, {len(text)} characters of text =====")
        for doc_type, chars, note in stats:
            print(f"   {doc_type:5} {chars:7} chars  {note}")
        for task in ("extract", "discrim"):
            for mode in MODES:
                if spent > BUDGET:
                    print(f"BUDGET ${BUDGET} reached (spent ${spent:.4f}), stopping")
                    return
                line, data = await run_mode(task, mode, text)
                print(line)
                open(f"{OUT}/{cid}_{task}_{mode.split()[0]}.json", "w", encoding="utf-8").write(json.dumps(data, ensure_ascii=False, default=str, indent=1))
    print(f"\nTOTAL SPENT ${spent:.4f}")


asyncio.run(main(sys.argv[1:] or ["C05", "C10"]))
