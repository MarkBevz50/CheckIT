"""Criteria and prompts of the two judges (E0.7). The SAME text is used for judge A (Claude Opus in the session, which reads the
items through eval/judge_a_export.py) and for judge B (a model of another family through OpenRouter, eval/judge_b.py).

What a judge sees:   pairs     the tender item, its unit, the store product title, the store and the price
                     findings  the tender title and the quote of every finding of that tender (numbered)
What a judge never sees: the decision of the application's model (is_relevant, type, severity, explanation of a
finding), bucket_hint of the pilot pairs, the labels of the other judge, the owner's labels.
"""

import json
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "eval" / "data"
PAIR_LABELS = ("same", "analog", "no")
FINDING_LABELS = ("true", "false", "duplicate")

PAIR_SYSTEM = """Ти досвідчений фахівець із публічних закупівель в Україні. Тобі дають позицію тендера і один товар з інтернет-магазину. Визнач, чи можна порівнювати ціну цього товару з ціною позиції.

Критерії міток:
- same: товар закриває позицію тендера (фасовка може відрізнятися);
- analog: той самий тип товару, ціну можна порівнювати, одна неключова вимога інша;
- no: інший товар, аксесуар, набір, непорівнянна ціна.

Відповідай лише JSON-об'єктом без пояснень поза ним: {"label": "same" | "analog" | "no", "reason": "до 15 слів"}"""

FINDINGS_SYSTEM = """Ти досвідчений фахівець із публічних закупівель в Україні й антимонопольного контролю. Тобі дають назву тендера і пронумерований список цитат із його документації, які автоматична система вважає дискримінаційними вимогами. Для кожної цитати визнач мітку.

Критерії міток:
- true: вимога, що без потреби обмежує конкуренцію (бренд без «або еквівалент», надмірний досвід, вимоги до місцезнаходження чи складу, нереальні строки, нерелевантні документи);
- false: вимоги закону, технічні характеристики товару, типові умови договору, загальні фрази;
- duplicate: та сама вимога вже є в цьому списку під меншим номером (вкажи номер у полі "of").

Відповідай лише JSON-масивом, по одному об'єкту на кожну цитату, у тому самому порядку: [{"id": "F001", "label": "true" | "false" | "duplicate", "of": "F000" або null, "reason": "до 15 слів"}, ...]"""


def read_jsonl(path: Path) -> List[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.exists() else []


def pair_user(row: dict) -> str:
    """The pair as a judge sees it. bucket_hint, the model's decision and any label are left out on purpose."""
    return (f"Позиція тендера: {row['item']}" + (f" (одиниця: {row['unit']})" if row.get("unit") else "") + "\n"
            f"Товар у магазині: {row['title']}\n"
            f"Магазин: {row.get('store_name') or row.get('store')}; ціна: {row.get('price')} грн")


def findings_user(tender_title: str, rows: List[dict]) -> str:
    lines = [f"Тендер: {tender_title}", "", "Цитати:"]
    lines += [f"{row['id']}: {' '.join(str(row.get('quote') or '').split())}" for row in rows]
    return "\n".join(lines)


def load_pairs(include_pilot: bool = False) -> List[dict]:
    """Pairs of the labeling queue (accepted matches nobody has labeled), optionally with the 60 labeled pilot pairs."""
    rows = read_jsonl(DATA / "pairs_queue.jsonl")
    return (read_jsonl(DATA / "pairs_pilot.jsonl") + rows) if include_pilot else rows


def load_findings() -> Dict[str, List[dict]]:
    """Findings of the pool grouped by tender: {"C05": [{id, tender, quote, ...}, ...]} (type, severity, explanation are not used)."""
    pool = json.loads((DATA / "doc_findings_pool.json").read_text(encoding="utf-8"))
    grouped: Dict[str, List[dict]] = {}
    for row in sorted(pool, key=lambda r: r["id"]):
        grouped.setdefault(row["tender"], []).append(row)
    return grouped


def tender_titles() -> Dict[str, str]:
    tenders = json.loads((ROOT / "eval" / "control_tenders.json").read_text(encoding="utf-8"))["tenders"]
    return {t["id"]: t["title"] for t in tenders}
