"""Shared helpers for tests: fixture loading and offline replay of `requests.get`."""

import json
from pathlib import Path

import requests

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def load_json(relative_path: str):
    return json.loads((FIXTURES / relative_path).read_text(encoding="utf-8"))


class FakeResponse:
    """Minimal stand-in for requests.Response."""

    def __init__(self, status_code=200, body=None, kind="json"):
        self.status_code = status_code
        self._body = body
        self._kind = kind

    @property
    def text(self):
        return self._body if self._kind == "text" else json.dumps(self._body, ensure_ascii=False)

    def json(self):
        if self._kind == "text":
            raise ValueError("not JSON")
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error", response=self)


def replay_requests(monkeypatch, *recordings):
    """Serve `requests.get` from recorded store responses (tests/fixtures/stores/*.json).

    A request matches a recording by URL and params; an unknown request fails loudly.
    """
    entries = [entry for rec in recordings for entry in rec["requests"]]

    def fake_get(url, *args, **kwargs):
        params = kwargs.get("params")
        for entry in entries:
            if entry["url"] == url and entry["params"] == params:
                return FakeResponse(entry["status"], entry["body"], entry["kind"])
        raise AssertionError(f"No recorded response for GET {url} params={params}")

    monkeypatch.setattr(requests, "get", fake_get)
    return fake_get
