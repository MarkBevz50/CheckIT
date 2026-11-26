"""Snapshot of everything a control run reads from outside the application, so that a later run can be replayed.

    eval/snapshots/control/<date>/
        http/<hash>.json     Prozorro responses (tender JSON, documents), key = URL and query parameters
        search/<hash>.json   store search results, key = product name, stores, n and the other search arguments
        ua/<hash>.json       UA-ID -> hex ID
        llm/<hash>.json      Claude answers, key = hash of ALL request parameters (model, system, messages, thinking,
                             max_tokens, ...): a changed prompt, model or parameter is a new key, an unchanged one is
                             answered from the snapshot

The directory is not in git (eval/snapshots/ is ignored); the history of metrics (eval/metrics/history.jsonl) is.
"""

import base64
import hashlib
import json
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[2]
SNAPSHOTS = ROOT / "eval" / "snapshots" / "control"
KINDS = ("http", "search", "ua", "llm")


def digest(obj: Any) -> str:
    """Stable hash of any JSON-like value (dict order does not matter)."""
    text = json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:40]


class Snapshot:
    def __init__(self, date: str, root: Optional[Path] = None):
        self.date = date
        self.path = (root or SNAPSHOTS) / date

    @staticmethod
    def latest(root: Optional[Path] = None) -> Optional[str]:
        base = root or SNAPSHOTS
        dates = sorted(p.name for p in base.iterdir() if p.is_dir()) if base.exists() else []
        return dates[-1] if dates else None

    def get(self, kind: str, key: str) -> Optional[Any]:
        file = self.path / kind / f"{key}.json"
        if not file.exists():
            return None
        return json.loads(file.read_text(encoding="utf-8"))

    def put(self, kind: str, key: str, value: Any) -> None:
        folder = self.path / kind
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{key}.json").write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")

    def counts(self) -> dict:
        return {kind: len(list((self.path / kind).glob("*.json"))) if (self.path / kind).exists() else 0 for kind in KINDS}


def encode_body(content: bytes) -> str:
    return base64.b64encode(content).decode("ascii")


def decode_body(text: str) -> bytes:
    return base64.b64decode(text.encode("ascii"))
