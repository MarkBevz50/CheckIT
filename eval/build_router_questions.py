"""Build eval/data/router_questions.json: 18 questions "is this item sold in network X?" (offline).

    python eval/build_router_questions.py

Ground truth (`sold`) and its basis are written here by hand; the owner reviews the table.
  * yes: a pair of the item with a product of that network is labeled same/analog in labels.json,
    or the network's own candidate list (candidates.jsonl) shows the product;
  * no: the category is clearly foreign for the network, or the item is a service/work
    (those are never sold at retail).
`obvious` is False for the cases where the network sells something one would not expect
(forms on Rozetka, household chemicals in Silpo); the summary reports them separately.
"""

import json
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data"
NETWORKS = {"rozetka": "Rozetka", "silpo": "Сільпо", "epicentr": "Епіцентр"}

# (source item id, network, sold, obvious, basis)
QUESTIONS = [
    ("C09-08", "epicentr", True, True, "пара analog: перфоратор Bosch GBH 240 (Епіцентр)"),
    ("C03-05", "silpo", True, True, "кандидат Сільпо: «Крупа «Сквирянка» гречана ядриця»"),
    ("C06-13", "rozetka", True, True, "пара same: голка банківська Buromax 15 см"),
    ("C07-07", "rozetka", True, True, "пара same: Italtek Bitum Remover 1 л"),
    ("C06-10", "rozetka", True, True, "пара same: Біндер Buromax 32 мм чорний 12 шт"),
    ("C04-04", "silpo", True, True, "кандидат Сільпо: «Оцет столовий для консервації 9%»"),
    ("C10-03", "rozetka", True, False, "пара analog: посвідчення про перевірку знань з охорони праці (бланк на Rozetka)"),
    ("C07-10", "silpo", True, False, "пара analog: «Очисник салону Sapfire» (автохімія в Сільпо)"),
    ("C07-03", "silpo", True, False, "кандидат Сільпо: «Засіб для миття скла Mr.Muscle» (побутова хімія)"),
    ("C02-01", "epicentr", False, True, "м'ясо: чужа категорія для Епіцентру"),
    ("C05-03", "silpo", False, True, "чорнило для принтера: кандидати Сільпо — ковбаса і пергамент"),
    ("C05-01", "silpo", False, True, "чорнило Canon: кандидати Сільпо — маркер і наповнювач"),
    ("C09-05", "silpo", False, True, "дриль-шурупокрут: кандидати Сільпо — стейк і джин"),
    ("C08-02", "silpo", False, True, "клей для плитки: кандидати Сільпо — устриці"),
    ("C08-03", "silpo", False, True, "покрівельні мембрани: кандидати Сільпо — харчова плівка"),
    ("K04", "rozetka", False, True, "послуга (CPV 66*): у роздріб не продається"),
    ("K07", "epicentr", False, True, "послуга (CPV 77*): у роздріб не продається"),
    ("K13", "rozetka", False, True, "роботи (CPV 45*): у роздріб не продаються"),
]


def main():
    items = {}
    for tender in json.loads((DATA.parent / "control_tenders.json").read_text(encoding="utf-8"))["tenders"]:
        for number, item in enumerate(tender["items"], start=1):
            items[f'{tender["id"]}-{number:02d}'] = item
    for item in json.loads((DATA / "classification_items.json").read_text(encoding="utf-8"))["items"]:
        items[item["id"]] = item
    out = []
    for number, (item_id, network, sold, obvious, basis) in enumerate(QUESTIONS, start=1):
        item = items[item_id]
        out.append({
            "id": f"R{number:02d}", "item_id": item_id,
            "name": " ".join(item["description"].split()), "cpv": item.get("cpv"), "unit": item.get("unit"),
            "network": network, "network_name": NETWORKS[network],
            "sold": sold, "obvious": obvious, "basis": basis,
        })
    (DATA / "router_questions.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    yes = sum(q["sold"] for q in out)
    print(len(out), "questions:", yes, "yes /", len(out) - yes, "no;", sum(not q["obvious"] for q in out), "non-obvious")


if __name__ == "__main__":
    main()
