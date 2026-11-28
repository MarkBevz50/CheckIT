"""E0.7: judge B (OpenRouter) with a mocked API: budget stop-cock, partial result, resume, key never written to disk."""

import asyncio
import json
import sys
from pathlib import Path

import httpx
import pytest
import respx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "eval"))

import judge_b  # noqa: E402
import judge_prompts as jp  # noqa: E402

KEY = "sk-or-v1-THIS-MUST-NEVER-BE-WRITTEN"
CATALOG = {"data": [{"id": "google/gemini-3.7-flash", "pricing": {"prompt": "0.00000075", "completion": "0.00000375"},
                     "reasoning": {"supported_efforts": ["low", "medium", "high"], "mandatory": True},
                     "supported_parameters": ["temperature"]}]}


def pair(n):
    return {"pair_id": f"Q{n:03d}", "item": f"Item {n}", "unit": "шт", "title": f"Product {n}", "store_name": "Rozetka", "price": 10,
            "bucket_hint": "SECRET-HINT"}


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(judge_b, "LEDGER", tmp_path / "spend.json")
    monkeypatch.setattr(judge_b, "OUT", tmp_path / "labels.json")
    monkeypatch.setattr(judge_b, "RAW", tmp_path / "raw" / "raw.jsonl")
    monkeypatch.setattr(jp, "DATA", tmp_path)
    (tmp_path / "pairs_pilot.jsonl").write_text("\n".join(json.dumps(pair(n)) for n in (901, 902)), encoding="utf-8")
    monkeypatch.setattr(jp, "load_pairs", lambda include_pilot=False: [pair(1), pair(2), pair(3)])
    return tmp_path


def answer(content, cost=0.0003):
    return httpx.Response(200, json={"choices": [{"message": {"content": content}, "finish_reason": "stop"}],
                                     "usage": {"prompt_tokens": 300, "completion_tokens": 50, "cost": cost,
                                               "completion_tokens_details": {"reasoning_tokens": 20}}})


def run(part, budget):
    return asyncio.run(judge_b.run_part(part, KEY, budget))


def mock_api(router, content='{"label": "same", "reason": "тот самий товар"}', cost=0.0003):
    router.get("https://openrouter.ai/api/v1/models").mock(return_value=httpx.Response(200, json=CATALOG))
    return router.post("https://openrouter.ai/api/v1/chat/completions").mock(return_value=answer(content, cost))


def test_pairs_are_labeled_saved_and_paid_from_the_ledger(world):
    with respx.mock() as router:
        route = mock_api(router)
        budget = judge_b.Budget()
        result = run("pairs", budget)
    assert result == {"part": "pairs", "answered": 3, "not_sent": 0, "invalid": 0}
    saved = json.loads((world / "labels.json").read_text(encoding="utf-8"))
    assert {k: v["label"] for k, v in saved["pairs"].items()} == {"Q001": "same", "Q002": "same", "Q003": "same"}
    assert budget.spent == pytest.approx(0.0009)
    assert route.calls.last.request.headers["authorization"] == f"Bearer {KEY}"
    body = json.loads(route.calls.last.request.content)
    assert body["reasoning"] == {"effort": "low"} and body["temperature"] == 0
    assert "SECRET-HINT" not in route.calls.last.request.content.decode("utf-8")      # bucket_hint never reaches the judge


def test_the_key_is_never_written_to_disk(world):
    with respx.mock() as router:
        mock_api(router, content=f"leaked {KEY} in the answer")
        run("pairs", judge_b.Budget())
    for path in world.rglob("*"):
        if path.is_file():
            assert KEY not in path.read_text(encoding="utf-8"), path


def test_the_stop_cock_sends_nothing_that_could_exceed_the_limit_and_keeps_the_partial_result(world):
    """A request is sent only if spent + its WORST case (about $0.0085 for a pair) fits the limit; the real cost is $0.0003."""
    with respx.mock() as router:
        route = mock_api(router)
        budget = judge_b.Budget(limit=0.0090)  # room for the worst case of two requests one after another, not of a third
        result = run("pairs", budget)
    assert route.call_count == 2
    assert (result["answered"], result["not_sent"]) == (2, 1) and budget.stopped
    assert len(json.loads((world / "labels.json").read_text(encoding="utf-8"))["pairs"]) == 2
    assert budget.spent + budget.reserved <= 0.0090


def test_a_second_run_continues_where_the_first_stopped_and_the_limit_covers_all_runs(world):
    with respx.mock() as router:
        route = mock_api(router)
        run("pairs", judge_b.Budget(limit=0.0090))
        assert route.call_count == 2
        again = judge_b.Budget(limit=0.0090)               # a new process: the ledger remembers what was spent
        assert again.spent == pytest.approx(0.0006)
        run("pairs", again)
        assert route.call_count == 2                       # the limit is for all runs together: nothing more may be sent
        run("pairs", judge_b.Budget(limit=1.0))            # with room it finishes the rest
        assert route.call_count == 3
        run("pairs", judge_b.Budget(limit=1.0))
        assert route.call_count == 3                       # nothing left to ask


def test_calibration_uses_the_pilot_pairs_and_keeps_them_apart_from_the_queue(world):
    with respx.mock() as router:
        mock_api(router, content='{"label": "no", "reason": "аксесуар"}')
        run("calibration", judge_b.Budget())
    saved = json.loads((world / "labels.json").read_text(encoding="utf-8"))
    assert set(saved["calibration"]) == {"Q901", "Q902"} and saved["pairs"] == {}


def test_an_answer_that_is_not_a_label_is_recorded_as_invalid_and_not_hidden(world):
    with respx.mock() as router:
        mock_api(router, content="I cannot decide")
        result = run("pairs", judge_b.Budget())
    assert result["invalid"] == 3
    assert json.loads((world / "labels.json").read_text(encoding="utf-8"))["pairs"]["Q001"]["label"] == "invalid"


def test_parsing_of_pairs_and_findings():
    assert judge_b.extract_json('text ```json\n{"a": 1}\n``` tail') == {"a": 1}
    assert judge_b.extract_json("no json") is None
    assert judge_b.parse_pair('{"label": " Analog ", "reason": "r"}')["label"] == "analog"
    parsed = judge_b.parse_findings(
        '[{"id": "F001", "label": "true", "of": null, "reason": "a"}, {"id": "F002", "label": "duplicate", "of": "f001", "reason": "b"}]',
        ["F001", "F002", "F003"])
    assert parsed["F001"]["label"] == "true" and parsed["F002"] == {"label": "duplicate", "reason": "b", "of": "F001"}
    assert parsed["F003"]["label"] == "invalid"                                         # missing in the answer


def test_the_dry_run_needs_no_key_and_no_chat_request(monkeypatch, capsys):
    with respx.mock(assert_all_called=False) as router:
        router.get("https://openrouter.ai/api/v1/models").mock(return_value=httpx.Response(200, json=CATALOG))
        chat = router.post("https://openrouter.ai/api/v1/chat/completions")
        judge_b.dry_run(["google/gemini-3.7-flash"], with_pilot=False)
    assert chat.call_count == 0
    assert "google/gemini-3.7-flash" in capsys.readouterr().out
