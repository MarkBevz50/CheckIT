#!/usr/bin/env python3
"""Can THIS machine reach Rozetka, Silpo and Epicentr? Run it first on a new server (E0.6).

    sudo apt install -y git python3-requests       # a bare Ubuntu needs nothing else
    python3 scripts/check_sources.py [--queries ручка молоко] [--n 3] [--show-ip] [--json]

It runs the real parsers of the application (scraper/parsers) on two searches per store and records every HTTP
call they make. The verdict per store tells a block (the main risk of E0.6: shops often refuse data-center IPs)
apart from a broken parser and from a network problem:

    OK              products were found
    ЗАБЛОКОВАНО     HTTP 401/403/429/451/503 or a bot-challenge page (Cloudflare, captcha)
    МЕРЕЖА          the connection failed (DNS, timeout, reset)
    ПАРСЕР ЗЛАМАНИЙ the shop answered but no products were found and it is not a block
    ПОМИЛКА         the parser made no request at all

Exit code 0 only if every store is OK. The output ends with a paragraph for PLAN/DIPLOMA_NOTES.md.
"""

import argparse
import json
import socket
import sys
import time
from datetime import datetime
from importlib import import_module
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))  # `scraper` is imported from the checkout, nothing is installed

try:
    import requests
except ImportError:  # pragma: no cover - only on a machine without the package
    sys.exit("The 'requests' package is missing. On Ubuntu: sudo apt install -y python3-requests")

OK, BLOCKED, NETWORK, BROKEN, ERROR = "OK", "ЗАБЛОКОВАНО", "МЕРЕЖА", "ПАРСЕР ЗЛАМАНИЙ", "ПОМИЛКА"

# store key -> (name, module, class, default queries that always have results)
STORES = {
    "rozetka": ("Rozetka", "scraper.parsers.rozetka_parser", "RozetkaParser", ["ручка кулькова", "зошит"]),
    "silpo": ("Сільпо", "scraper.parsers.silpo_parser", "SilpoParser", ["молоко", "сир"]),
    "epicentr": ("Епіцентр", "scraper.parsers.epicentr_parser", "EpicentrParser", ["перфоратор", "цемент"]),
}
BLOCK_STATUSES = {401, 403, 429, 451, 503}
CHALLENGE_MARKERS = ("just a moment", "attention required", "captcha", "access denied", "verify you are human",
                     "cf-chl", "unusual traffic", "are you a robot")


def record_calls(calls: list):
    """Wrap requests.get so that every call of a parser is recorded (status, size, time, errors, challenge page)."""
    real_get = requests.get

    def wrapped(url, *args, **kwargs):
        started = time.perf_counter()
        host = urlparse(url).netloc
        try:
            response = real_get(url, *args, **kwargs)
        except Exception as exc:
            calls.append({"host": host, "status": None, "error": type(exc).__name__, "bytes": 0,
                          "seconds": round(time.perf_counter() - started, 2), "challenge": False})
            raise
        text = getattr(response, "text", "") or ""
        calls.append({"host": host, "status": response.status_code, "error": None, "bytes": len(text),
                      "seconds": round(time.perf_counter() - started, 2),
                      "challenge": any(marker in text[:5000].lower() for marker in CHALLENGE_MARKERS)})
        return response

    requests.get = wrapped
    return real_get


def classify(calls: list, products: int) -> str:
    """Verdict of one search from the HTTP calls it made and the number of products it returned."""
    if not calls:
        return ERROR
    if any(call["status"] in BLOCK_STATUSES for call in calls):
        return BLOCKED
    if products > 0:
        return OK
    if any(call["error"] for call in calls):
        return NETWORK
    if any(call["challenge"] for call in calls):
        return BLOCKED
    return BROKEN


def store_verdict(searches: list) -> str:
    verdicts = [s["verdict"] for s in searches]
    for verdict in (BLOCKED,):
        if verdict in verdicts:
            return verdict
    if OK in verdicts:
        return OK
    for verdict in (NETWORK, BROKEN, ERROR):
        if verdict in verdicts:
            return verdict
    return ERROR


def check_store(key: str, queries: list, n: int, pause: float = 1.0) -> dict:
    name, module_name, class_name, _ = STORES[key]
    parser = getattr(import_module(module_name), class_name)()
    searches = []
    for query in queries:
        calls = []
        real_get = record_calls(calls)
        try:
            products = parser.find_n_products(product=query, n=n, fast_parse=True, ignore_price_format=True,
                                              raise_exception=False)
        except Exception as exc:  # a parser must not stop the check of the other stores
            products = []
            calls.append({"host": "?", "status": None, "error": type(exc).__name__, "bytes": 0, "seconds": 0.0,
                          "challenge": False})
        finally:
            requests.get = real_get
        searches.append({"query": query, "products": len(products), "calls": calls, "verdict": classify(calls, len(products))})
        time.sleep(pause)
    return {"store": key, "name": name, "verdict": store_verdict(searches), "searches": searches}


def render(results: list) -> str:
    lines = [f"{'Магазин':<10} {'Вердикт':<16} {'HTTP':<22} {'Товарів':<10} {'Сер. час, с':<12}", "-" * 74]
    for r in results:
        calls = [c for s in r["searches"] for c in s["calls"]]
        statuses = ",".join(sorted({str(c["status"] or c["error"]) for c in calls})) or "-"
        found = "/".join(str(s["products"]) for s in r["searches"])
        average = sum(c["seconds"] for c in calls) / len(calls) if calls else 0.0
        lines.append(f"{r['name']:<10} {r['verdict']:<16} {statuses:<22} {found:<10} {average:<12.2f}")
    return "\n".join(lines)


def diploma_paragraph(results: list, host: str, when: str, ip: str | None = None) -> str:
    parts = [f"{r['name']}: {r['verdict']}" for r in results]
    where = f"{host}" + (f" (IP {ip})" if ip else "")
    blocked = [r["name"] for r in results if r["verdict"] == BLOCKED]
    tail = (" Магазини, що блокують запити з цієї адреси: " + ", ".join(blocked) + ".") if blocked else ""
    return (f"Перевірка доступності магазинів з сервера {where}, {when}: " + "; ".join(parts) +
            f". Для кожного магазину виконано пошук за двома запитами справжніми парсерами застосунку.{tail}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--queries", nargs="*", help="the same queries for every store (default: two per store)")
    ap.add_argument("--n", type=int, default=3, help="products requested per search (default 3)")
    ap.add_argument("--stores", nargs="*", choices=sorted(STORES), default=sorted(STORES))
    ap.add_argument("--show-ip", action="store_true", help="look up the public IP of this machine (api.ipify.org)")
    ap.add_argument("--pause", type=float, default=1.0, help="seconds between searches (default 1)")
    ap.add_argument("--json", action="store_true", help="print the raw results as JSON instead of the table")
    args = ap.parse_args(argv)

    results = [check_store(key, args.queries or STORES[key][3], args.n, args.pause) for key in args.stores]
    ip = None
    if args.show_ip:
        try:
            ip = requests.get("https://api.ipify.org", timeout=10).text.strip()
        except Exception:
            ip = "невідомий"
    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=1))
    else:
        print(render(results))
        print("\nАбзац для PLAN/DIPLOMA_NOTES.md:\n" + diploma_paragraph(
            results, socket.gethostname(), datetime.now().strftime("%Y-%m-%d %H:%M"), ip))
    return 0 if all(r["verdict"] == OK for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
