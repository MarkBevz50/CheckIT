"""Research (E4 preparation, 28 November 2026): are there AVERAGE consumer prices by region in the open data of Derzhstat?

    back-end\\.venv\\Scripts\\python.exe eval/research_derzhstat_prices.py

Downloads the SDMX-JSON resource "Зміни цін (тарифів) на споживчі товари (послуги)" of the dataset
https://data.gov.ua/dataset/c1cd8f39-c2ee-4f20-8c8a-6cdde6e6f343 (licence: Creative Commons Attribution; 9 MB), reads the series of the
indicator AVG_CONS_PRCS (average prices) and prints, per good: the national price of the latest month, its unit code, the number of
regions and of months. Writes eval/results/research/derzhstat_avg_prices.csv.

Names of goods and regions are not in this file: they come from the big index file of the same dataset ("136.csv", ~520 MB) and are kept in
eval/results/research/derzhstat_names.json (extracted once). Unit codes are printed as codes; the ones known from the CSV are named below.
"""

import csv
import json
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "eval" / "results" / "research"
URL = ("https://data.gov.ua/dataset/12f4fe34-0759-4271-b1f6-780995f0ec4a/resource/9d4280b1-20ce-4aae-a005-24e4b9b7e32c/download/"
       "df_price_change_consumer_goods_service_latest.json")
NATIONAL = "UA00000000000000000"
KNOWN_UNITS = {"1010": "відсоток", "1180": "кілограм", "2500": "500 г", "2680": "1000 г", "2510": "десяток", "2520": "200 г"}


def load() -> dict:
    return httpx.get(URL, timeout=180, follow_redirects=True, headers={"User-Agent": "CheckIT research (read-only)"}).json()["data"]


def average_prices(data: dict, names: dict) -> list:
    structure = data["structures"][0]
    series_dims = structure["dimensions"]["series"]
    values = {d["id"]: [v["id"] for v in d["values"]] for d in series_dims}
    times = [v["value"] for v in structure["dimensions"]["observation"][0]["values"]]
    attribute_ids = [a["id"] for a in structure["attributes"]["series"]]
    units = [v.get("id") for v in next(a for a in structure["attributes"]["series"] if a["id"] == "UNITS_OF_MEASURE")["values"]]
    rows = {}
    for key, series in data["dataSets"][0]["series"].items():
        parts = [int(x) for x in key.split(":")]
        if values["INDICATOR"][parts[0]] != "AVG_CONS_PRCS":
            continue
        good, region = values["GOODS_SERVICES_TYPE"][parts[3]], values["REGION"][parts[2]]
        observed = {t: o[0] for t, o in series["observations"].items() if o and o[0] is not None}
        if not observed:
            continue
        last = max(observed, key=int)
        attrs = series.get("attributes") or []
        unit_index = attrs[attribute_ids.index("UNITS_OF_MEASURE")] if len(attrs) > attribute_ids.index("UNITS_OF_MEASURE") else None
        entry = rows.setdefault(good, {"regions": 0, "national": None})
        entry["regions"] += 1
        if region == NATIONAL:
            entry["national"] = {"period": times[int(last)], "price": float(observed[last]), "months": len(observed),
                                 "unit_code": units[unit_index] if unit_index is not None else None}
    return [{"code": code, "name": names["goods"].get(code, "?"), "regions": e["regions"], **(e["national"] or {})} for code, e in sorted(rows.items())]


def main():
    if sys.stdout.encoding != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")
    names = json.loads((RESULTS / "derzhstat_names.json").read_text(encoding="utf-8"))
    table = average_prices(load(), names)
    path = RESULTS / "derzhstat_avg_prices.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["code", "name", "unit_code", "unit_name", "latest_period", "national_price", "regions", "months"])
        for r in table:
            writer.writerow([r["code"], r["name"], r.get("unit_code"), KNOWN_UNITS.get(str(r.get("unit_code")), ""), r.get("period"),
                             r.get("price"), r["regions"], r.get("months")])
    print(f"{len(table)} goods with average prices; regions per good: {sorted({r['regions'] for r in table})}; "
          f"latest period: {max(r['period'] for r in table if r.get('period'))}")
    for r in table[:12]:
        print(f"  {r['code']:14} {r['name'][:44]:44} unit {r.get('unit_code')} {r.get('period')} {r.get('price')}")
    print(f"written {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
