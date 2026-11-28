"""E0.7 diagnosis: which value of the control tender C03 does not fit its column (import fails with
"value too long for type character varying(500)"). Replays Prozorro from the snapshot, no network, no LLM.

    docker run ... python - < eval/diagnose_c03.py      (see the run command in eval/quality_report.py)
"""
import asyncio
import os
import sys

sys.path[:0] = ["/app", "/app/back-end", "/app/eval"]
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@h:5432/d")
from quality.runner import prepare_environment  # noqa: E402

prepare_environment()
from quality.capture import Capture  # noqa: E402
from quality.snapshot import Snapshot  # noqa: E402

import app.main  # noqa: F401,E402
from app.prozorro_functionality import prozorro as pz  # noqa: E402
from app.routers import prozorro_router  # noqa: E402

LIMITS = {"name": 500, "title": 500, "unit_name": 50, "dk_code": 50, "brand": 200, "specifications": None}


async def main():
    with Capture(Snapshot(Snapshot.latest()), "replay", "replay", 0):
        hex_id = await prozorro_router.convert_ua_to_hex_id("UA-2026-08-21-008968-A")
        contract = pz.get_contract(hex_id)
        print("tender title", len(contract.get("title", "")), "| customer", len(contract.get("procuringEntity", {}).get("name", "")))
        items = await pz.get_contract_info(hex_id)
        print(len(items), "items; longest values per field:")
        longest = {}
        for item in items:
            for key, value in item.items():
                if isinstance(value, str):
                    longest[key] = max(longest.get(key, 0), len(value))
        for key, length in sorted(longest.items(), key=lambda kv: -kv[1])[:8]:
            print(f"   {key}: {length}")


asyncio.run(main())
