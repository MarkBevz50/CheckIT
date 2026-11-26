"""Runs the control tenders through the application (in-process, real handlers, real PostgreSQL) and collects what the
metrics need. Import -> price analysis -> risk analysis for every tender, as a user would click through it.

The run uses its own database `check_it_eval` on the compose PostgreSQL (created on first use, emptied before every run),
never the development database. Redis is switched off, so the run does not depend on what an earlier one cached.
"""

import asyncio
import json
import os
import re
import secrets
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "back-end"
DATA = ROOT / "eval" / "data"
STORES = "rozetka,silpo,epicentr"


def read_env(path: Path = ROOT / ".env") -> Dict[str, str]:
    values = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                name, value = line.split("=", 1)
                values[name.strip()] = value.strip().strip("\"'")
    return values


def eval_database_url() -> str:
    explicit = os.environ.get("EVAL_DATABASE_URL")
    if explicit:
        return explicit
    env = read_env()
    return (f"postgresql+asyncpg://{env['POSTGRES_USER']}:{env['POSTGRES_PASSWORD']}@127.0.0.1:5433/check_it_eval")


def prepare_environment() -> str:
    """Point the application at the evaluation database BEFORE it is imported (Settings reads the environment once)."""
    url = eval_database_url()
    os.environ["DATABASE_URL"] = url
    os.environ["REDIS_URL"] = ""
    for path in (str(ROOT), str(BACKEND)):
        if path not in sys.path:
            sys.path.insert(0, path)
    # keep the log readable: the application logs every store request at INFO
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    return url


async def _ensure_database(url: str) -> None:
    import asyncpg

    match = re.match(r"postgresql\+asyncpg://([^:]+):([^@]+)@([^:/]+):(\d+)/(\w+)", url)
    user, password, host, port, name = match.groups()
    connection = await asyncpg.connect(user=user, password=password, host=host, port=int(port), database="postgres")
    try:
        exists = await connection.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", name)
        if not exists:
            await connection.execute(f'CREATE DATABASE "{name}"')
    finally:
        await connection.close()


def reset_database(url: str) -> None:
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    asyncio.run(_ensure_database(url))
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    cfg.attributes["database_url"] = url
    command.upgrade(cfg, "head")

    async def truncate():
        engine = create_async_engine(url)
        try:
            async with engine.begin() as conn:
                await conn.execute(text("TRUNCATE users, tenders, tender_items, price_history RESTART IDENTITY CASCADE"))
        finally:
            await engine.dispose()

    asyncio.run(truncate())


def load_control_tenders(selected: Optional[List[str]] = None) -> List[dict]:
    tenders = json.loads((ROOT / "eval" / "control_tenders.json").read_text(encoding="utf-8"))["tenders"]
    return [t for t in tenders if not selected or t["id"] in selected]


def _normalize(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip().lower())


def item_ids(control_items: List[dict], tender_id: str, imported: List[dict]) -> List[str]:
    """Control ids (C05-01, ...) of the imported items: by name, falling back to position."""
    by_name = {_normalize(it["description"]): f"{tender_id}-{n:02d}" for n, it in enumerate(control_items, start=1)}
    ids = []
    for position, item in enumerate(imported, start=1):
        ids.append(by_name.get(_normalize(item["name"]), f"{tender_id}-{position:02d}"))
    return ids


def run_control(capture, tender_ids: Optional[List[str]] = None, stores: str = STORES, log=print) -> List[dict]:
    """Run the selected control tenders; `capture` is an installed Capture. Returns one dict per tender."""
    from fastapi.testclient import TestClient

    from app.main import app

    import logging

    logging.getLogger().setLevel(logging.WARNING)  # the run prints its own progress lines
    runs = []
    password = secrets.token_urlsafe(16)
    with TestClient(app) as client:
        response = client.post("/auth/register", json={"name": "Eval", "email": "eval@example.com", "password": password})
        response.raise_for_status()
        headers = {"Authorization": f"Bearer {response.json()['access_token']}"}

        for control in load_control_tenders(tender_ids):
            tender_id = control["id"]
            capture.tender = tender_id
            run = {"id": tender_id, "ua_id": control["ua_id"], "items": [], "risk": None, "errors": [], "seconds": {}}
            log(f"[{tender_id}] {control['ua_id']} ({len(control['items'])} items)")
            gemini_before = capture.gemini_calls

            def call(label, method, url, **kwargs):
                started = time.perf_counter()
                try:
                    reply = getattr(client, method)(url, headers=headers, **kwargs)
                except Exception as exc:  # noqa: BLE001  (BudgetExceeded and ReplayMiss are meant to stop the run)
                    if type(exc).__name__ in ("BudgetExceeded", "ReplayMiss"):
                        raise
                    run["errors"].append(f"{label}: {type(exc).__name__}: {str(exc)[:200]}")
                    return None
                run["seconds"][label] = round(time.perf_counter() - started, 1)
                if reply.status_code >= 400:
                    run["errors"].append(f"{label}: HTTP {reply.status_code} {reply.text[:200]}")
                    return None
                return reply.json()

            imported = call("import", "post", f"/tenders/import/{control['ua_id']}")
            if imported:
                ids = item_ids(control["items"], tender_id, imported["items"])
                call("analyze", "post", f"/tenders/{imported['id']}/analyze", params={"stores": stores})
                answer = call("risks", "post", "/assistant/analyze-risks", params={"tender_id": imported["id"], "stores": stores})
                if answer:
                    run["risk"] = {k: answer["risk_details"].get(k) for k in
                                   ("risk_score", "risk_level", "price_risk_score", "discriminatory_risk_score", "breakdown")}
                seen = {}
                for record in capture.validations:
                    if record["tender"] == tender_id:
                        seen.setdefault(_normalize(record["name"]), record)
                for item_id, item in zip(ids, imported["items"]):
                    record = seen.get(_normalize(item["name"]), {})
                    run["items"].append({
                        "item_id": item_id, "name": item["name"], "unit_price": item.get("unit_price"),
                        "price_source": item.get("price_source"), "quantity": item.get("quantity"),
                        "candidates": record.get("candidates", []), "relevant_urls": record.get("relevant_urls", []),
                    })
            run["seconds"]["total"] = round(sum(run["seconds"].values()), 1)
            run["usage"] = [u for u in capture.usage if u["tender"] == tender_id]
            run["parse_failures"] = capture.parse_failures.get(tender_id, 0)
            run["gemini_calls"] = capture.gemini_calls - gemini_before
            runs.append(run)
            log(f"    {run['seconds']}, LLM calls {len(run['usage'])}, spent so far ${capture.spent_real:.4f}, "
                f"errors {len(run['errors'])}")
    return runs
