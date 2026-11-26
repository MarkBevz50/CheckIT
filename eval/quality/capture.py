"""Record / replay layer around the application for the control run (E0.7).

Installed in-process, so the run goes through the real handlers (import, analysis, risk analysis) and the real
services. What is intercepted:

  Prozorro        requests.get to prozorro / openprocurement hosts   (kind "http")
  UA-ID -> hex    prozorro_router.convert_ua_to_hex_id               (kind "ua")
  store search    parser_service.search_products_async               (kind "search")
  Claude          claude_validator._client (messages.create)         (kind "llm", key = hash of all parameters)

mode "live":   the first request of a kind+key in this run goes to the network and is written to the snapshot; the
               same request again within the run is answered from the snapshot (one real fetch per distinct request).
mode "replay": everything is answered from the snapshot; a missing entry is a ReplayMiss (the snapshot is incomplete),
               except Claude, see below.
llm "replay":  Claude answers come from the snapshot when the hash of the request is there, otherwise the real API is
               called and the answer is stored. llm "live": always the real API (and the answer is stored).
Real Claude calls are counted against the budget (stop-cock): BudgetExceeded when the spent amount passes it.
"""

import json
import logging
import time
from types import SimpleNamespace
from typing import Any, Dict, List

from .snapshot import Snapshot, decode_body, digest, encode_body

PRICES = {"claude-haiku-5-5": (0.10e-6, 0.50e-6), "claude-sonnet-5-5": (2.00e-6, 10.00e-6)}  # list price per token


# the tender API lives at public.api.openprocurement.org, the documents at public-docs.prozorro.gov.ua
PROZORRO_HOSTS = ("prozorro", "openprocurement")


class ReplayMiss(RuntimeError):
    pass


class BudgetExceeded(RuntimeError):
    pass


def message_cost(model: str, input_tokens: int, output_tokens: int, cache_read: int = 0, cache_create: int = 0) -> float:
    pin, pout = PRICES.get(model, (0.0, 0.0))
    return (input_tokens + cache_read * 0.1 + cache_create * 1.25) * pin + output_tokens * pout


def serialize_message(message) -> dict:
    blocks = []
    for block in message.content:
        entry = {"type": block.type}
        for attr in ("text", "thinking"):
            if getattr(block, attr, None) is not None:
                entry[attr] = getattr(block, attr)
        blocks.append(entry)
    u = message.usage
    return {
        "model": message.model, "stop_reason": message.stop_reason, "content": blocks,
        "usage": {"input_tokens": u.input_tokens, "output_tokens": u.output_tokens,
                  "cache_read_input_tokens": getattr(u, "cache_read_input_tokens", 0) or 0,
                  "cache_creation_input_tokens": getattr(u, "cache_creation_input_tokens", 0) or 0},
    }


def deserialize_message(data: dict):
    return SimpleNamespace(
        model=data["model"], stop_reason=data["stop_reason"],
        content=[SimpleNamespace(**block) for block in data["content"]],
        usage=SimpleNamespace(**data["usage"]),
    )


class SnapshotResponse:
    """The part of requests.Response the application uses."""

    def __init__(self, status_code: int, content: bytes, content_type: str = ""):
        import requests

        self.status_code = status_code
        self.content = content
        self.headers = {"content-type": content_type}
        self._requests = requests
        self.url = ""

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")

    def json(self):
        return json.loads(self.content.decode("utf-8"))

    def raise_for_status(self):
        if self.status_code >= 400:
            raise self._requests.HTTPError(f"{self.status_code} Client/Server Error", response=self)


class Capture:
    def __init__(self, snapshot: Snapshot, mode: str, llm_mode: str, budget_usd: float = 1.0):
        assert mode in ("live", "replay") and llm_mode in ("replay", "live")
        self.snapshot, self.mode, self.llm_mode, self.budget = snapshot, mode, llm_mode, budget_usd
        self.spent_real = 0.0
        self.tender = None  # id of the control tender being processed (for the records)
        self.usage: List[Dict[str, Any]] = []
        self.validations: List[Dict[str, Any]] = []
        self.parse_failures: Dict[str, int] = {}
        self.gemini_calls = 0
        self._fresh = set()
        self._undo: List[Any] = []
        self._log_handler = None

    # ---- generic record/replay of one kind ------------------------------------------------------
    def _cached(self, kind: str, key: str, fetch):
        """Synchronous variant (used by requests.get)."""
        hit = self.snapshot.get(kind, key)
        if self.mode == "replay" or (hit is not None and (kind, key) in self._fresh):
            if hit is None:
                raise ReplayMiss(f"{kind} {key} is not in the snapshot {self.snapshot.date}")
            return hit
        value = fetch()
        self.snapshot.put(kind, key, value)
        self._fresh.add((kind, key))
        return value

    async def _cached_async(self, kind: str, key: str, fetch):
        hit = self.snapshot.get(kind, key)
        if self.mode == "replay" or (hit is not None and (kind, key) in self._fresh):
            if hit is None:
                raise ReplayMiss(f"{kind} {key} is not in the snapshot {self.snapshot.date}")
            return hit
        value = await fetch()
        self.snapshot.put(kind, key, value)
        self._fresh.add((kind, key))
        return value

    # ---- installation ----------------------------------------------------------------------------
    def install(self) -> "Capture":
        import requests

        from app.routers import prozorro_router
        from app.services import claude_validator, gemini_validator, parser_service

        capture = self
        real_get = requests.get

        def get(url, *args, **kwargs):
            if not any(host in str(url) for host in PROZORRO_HOSTS):
                if capture.mode == "replay":
                    raise ReplayMiss(f"network request in replay mode: {url}")
                return real_get(url, *args, **kwargs)
            key = digest({"url": str(url), "params": kwargs.get("params")})

            def fetch():
                response = real_get(url, *args, **kwargs)
                return {"status": response.status_code, "content": encode_body(response.content),
                        "content_type": response.headers.get("content-type", "")}

            data = capture._cached("http", key, fetch)
            return SnapshotResponse(data["status"], decode_body(data["content"]), data.get("content_type", ""))

        requests.get = get
        self._undo.append(lambda: setattr(requests, "get", real_get))

        real_convert = prozorro_router.convert_ua_to_hex_id

        async def convert(ua_id):
            async def fetch():
                return {"hex": await real_convert(ua_id)}

            return (await capture._cached_async("ua", digest(ua_id), fetch))["hex"]

        prozorro_router.convert_ua_to_hex_id = convert
        self._undo.append(lambda: setattr(prozorro_router, "convert_ua_to_hex_id", real_convert))

        real_search = parser_service.search_products_async

        async def search(product_name, stores, n=1, fast_parse=False, ignore_price_format=True, **extra):  # defaults as in the real function
            key = digest({"name": product_name, "stores": sorted(stores), "n": n, "fast": fast_parse,
                          "ignore": ignore_price_format, "extra": extra})

            async def fetch():
                return await real_search(product_name=product_name, stores=stores, n=n, fast_parse=fast_parse,
                                         ignore_price_format=ignore_price_format, **extra)

            return await capture._cached_async("search", key, fetch)

        parser_service.search_products_async = search
        self._undo.append(lambda: setattr(parser_service, "search_products_async", real_search))

        real_validate = parser_service.validate_matches

        async def validate(**kwargs):
            result = await real_validate(**kwargs)
            capture.validations.append({
                "tender": capture.tender, "name": kwargs["tender_name"],
                "candidates": [{k: m.get(k) for k in ("store", "store_name", "url", "title", "price", "price_on_sale")}
                               for m in kwargs["store_items"]],
                "relevant_urls": [m.get("url") for m in result if m.get("is_relevant", True)],
            })
            return result

        parser_service.validate_matches = validate
        self._undo.append(lambda: setattr(parser_service, "validate_matches", real_validate))

        real_gemini = gemini_validator.validate_matches

        async def gemini(*args, **kwargs):
            capture.gemini_calls += 1
            return await real_gemini(*args, **kwargs)

        gemini_validator.validate_matches = gemini
        self._undo.append(lambda: setattr(gemini_validator, "validate_matches", real_gemini))

        real_client = claude_validator._get_client()
        claude_validator._client = CachingClient(real_client, self)
        self._undo.append(lambda: setattr(claude_validator, "_client", real_client))

        class Counter(logging.Handler):
            def emit(handler, record):
                if "Failed to parse" in record.getMessage():
                    capture.parse_failures[capture.tender] = capture.parse_failures.get(capture.tender, 0) + 1

        self._log_handler = Counter(level=logging.WARNING)
        logging.getLogger("app.services.claude_validator").addHandler(self._log_handler)
        return self

    def uninstall(self) -> None:
        for undo in reversed(self._undo):
            undo()
        self._undo.clear()
        if self._log_handler:
            logging.getLogger("app.services.claude_validator").removeHandler(self._log_handler)

    def __enter__(self):
        return self.install()

    def __exit__(self, *exc):
        self.uninstall()


class CachingClient:
    """Stands in for AsyncAnthropic: answers from the snapshot or calls the real client, records every call."""

    def __init__(self, real, capture: Capture):
        self._real, self._capture = real, capture
        self.messages = SimpleNamespace(create=self._create)

    async def _create(self, **kwargs):
        from app.services import claude_validator as cv

        capture = self._capture
        key = digest(kwargs)
        cached = capture.snapshot.get("llm", key) if capture.llm_mode == "replay" else None
        started = time.perf_counter()
        if cached is not None:
            data, from_cache = cached, True
        else:
            if self._real is None:
                raise ReplayMiss("no Anthropic key and the answer is not in the snapshot")
            if capture.spent_real > capture.budget:
                raise BudgetExceeded(f"spent ${capture.spent_real:.4f} of the ${capture.budget:.2f} budget")
            message = await self._real.messages.create(**kwargs)
            data, from_cache = serialize_message(message), False
            capture.snapshot.put("llm", key, data)
        u = data["usage"]
        cost = message_cost(data["model"], u["input_tokens"], u["output_tokens"], u["cache_read_input_tokens"],
                            u["cache_creation_input_tokens"])
        if not from_cache:
            capture.spent_real += cost
        kinds = {cv.MAX_TOKENS_VALIDATE: "validate", cv.MAX_TOKENS_EXTRACT: "extract", cv.MAX_TOKENS_DISCRIM: "discrim"}
        capture.usage.append({
            "tender": capture.tender, "kind": kinds.get(kwargs.get("max_tokens"), "classify"), "model": data["model"],
            "stop_reason": data["stop_reason"], "blocks": [b["type"] for b in data["content"]],
            "input": u["input_tokens"], "output": u["output_tokens"], "cache_read": u["cache_read_input_tokens"],
            "cache_create": u["cache_creation_input_tokens"], "cost": cost, "cached": from_cache,
            "seconds": None if from_cache else round(time.perf_counter() - started, 2),
        })
        return deserialize_message(data)
