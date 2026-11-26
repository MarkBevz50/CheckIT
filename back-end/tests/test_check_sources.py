"""scripts/check_sources.py: the store availability check that is run first on a new server (E0.6)."""

import importlib.util
import json
from pathlib import Path

import pytest
import requests

from tests.helpers import FakeResponse, load_json, replay_requests

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_sources.py"
spec = importlib.util.spec_from_file_location("check_sources", SCRIPT)
cs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cs)

RECORDINGS = {"rozetka": "stores/rozetka_juice.json", "silpo": "stores/silpo_juice.json", "epicentr": "stores/epicentr_juice.json"}


def call(status=200, error=None, challenge=False):
    return {"host": "x", "status": status, "error": error, "bytes": 10, "seconds": 0.1, "challenge": challenge}


# ---- classify: the verdict of one search -------------------------------

def test_products_found_means_ok():
    assert cs.classify([call(200)], products=3) == cs.OK


@pytest.mark.parametrize("status", [401, 403, 429, 451, 503])
def test_a_blocking_status_is_a_block_even_if_something_was_found(status):
    assert cs.classify([call(200), call(status)], products=1) == cs.BLOCKED


def test_a_challenge_page_without_products_is_a_block():
    assert cs.classify([call(200, challenge=True)], products=0) == cs.BLOCKED


def test_a_challenge_marker_on_a_page_with_products_is_not_a_block():
    assert cs.classify([call(200, challenge=True)], products=2) == cs.OK  # e.g. a captcha script on a normal page


def test_a_connection_error_is_a_network_problem():
    assert cs.classify([call(None, error="ConnectTimeout")], products=0) == cs.NETWORK


def test_an_answer_without_products_and_without_a_block_means_a_broken_parser():
    assert cs.classify([call(200)], products=0) == cs.BROKEN


def test_no_requests_at_all_is_an_error():
    assert cs.classify([], products=0) == cs.ERROR


def test_one_blocked_search_makes_the_store_blocked_but_one_ok_search_beats_the_rest():
    assert cs.store_verdict([{"verdict": cs.OK}, {"verdict": cs.BLOCKED}]) == cs.BLOCKED
    assert cs.store_verdict([{"verdict": cs.OK}, {"verdict": cs.BROKEN}]) == cs.OK
    assert cs.store_verdict([{"verdict": cs.NETWORK}, {"verdict": cs.BROKEN}]) == cs.NETWORK


# ---- the real parsers on recorded answers ------------------------------

@pytest.mark.parametrize("store", sorted(RECORDINGS))
def test_every_store_is_ok_on_its_recorded_answers(monkeypatch, store):
    recording = load_json(RECORDINGS[store])
    replay_requests(monkeypatch, recording)
    result = cs.check_store(store, [recording["query"]], n=recording["n"], pause=0)
    assert result["verdict"] == cs.OK
    assert result["searches"][0]["products"] == recording["products_found"]
    assert result["searches"][0]["calls"]  # the HTTP calls of the real parser were recorded


@pytest.mark.parametrize("store", sorted(RECORDINGS))
def test_a_403_from_the_shop_is_reported_as_blocked(monkeypatch, store):
    monkeypatch.setattr(requests, "get", lambda url, *a, **k: FakeResponse(403, "Access denied", kind="text"))
    result = cs.check_store(store, ["anything"], n=2, pause=0)
    assert result["verdict"] == cs.BLOCKED


def test_a_connection_failure_is_reported_as_network(monkeypatch):
    def refuse(url, *args, **kwargs):
        raise requests.ConnectionError("no route")
    monkeypatch.setattr(requests, "get", refuse)
    assert cs.check_store("silpo", ["anything"], n=2, pause=0)["verdict"] == cs.NETWORK


def test_requests_get_is_restored_after_every_search(monkeypatch):
    sentinel = lambda url, *a, **k: FakeResponse(403, "x", kind="text")  # noqa: E731
    monkeypatch.setattr(requests, "get", sentinel)
    cs.check_store("epicentr", ["a", "b"], n=2, pause=0)
    assert requests.get is sentinel


# ---- the report ----------------------------------------------------------

def test_the_table_and_the_diploma_paragraph_name_the_blocked_store():
    results = [
        {"store": "rozetka", "name": "Rozetka", "verdict": cs.BLOCKED,
         "searches": [{"query": "q", "products": 0, "calls": [call(403)], "verdict": cs.BLOCKED}]},
        {"store": "silpo", "name": "Сільпо", "verdict": cs.OK,
         "searches": [{"query": "q", "products": 3, "calls": [call(200)], "verdict": cs.OK}]},
    ]
    table = cs.render(results)
    assert "Rozetka" in table and cs.BLOCKED in table and "403" in table
    text = cs.diploma_paragraph(results, "vps-1", "2026-12-01 10:00", ip="203.0.113.5")
    assert "vps-1" in text and "203.0.113.5" in text and "блокують запити" in text and "Rozetka" in text


def test_main_returns_nonzero_when_a_store_is_not_ok(monkeypatch, capsys):
    monkeypatch.setattr(requests, "get", lambda url, *a, **k: FakeResponse(403, "Access denied", kind="text"))
    assert cs.main(["--stores", "silpo", "--queries", "x", "--pause", "0"]) == 1
    assert "Абзац для PLAN/DIPLOMA_NOTES.md" in capsys.readouterr().out


def test_main_json_output_is_valid(monkeypatch, capsys):
    monkeypatch.setattr(requests, "get", lambda url, *a, **k: FakeResponse(403, "Access denied", kind="text"))
    cs.main(["--stores", "silpo", "--queries", "x", "--pause", "0", "--json"])
    data = json.loads(capsys.readouterr().out)
    assert data[0]["store"] == "silpo" and data[0]["verdict"] == cs.BLOCKED
