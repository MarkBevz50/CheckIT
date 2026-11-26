"""Parsing of REAL Claude Haiku 5.5 replies recorded by the OpenRouter pilot (eval/openrouter_pilot.py).

tests/fixtures/llm/haiku_5_5_pilot_responses.json holds 169 replies to the application's own prompts:
47 validations (`_VALIDATE_SYSTEM`), 86 tender-type classifications (`CLASSIFY_SYSTEM_PROMPT`) and
2 x 18 router questions. Unlike the hand-written samples in test_llm_response_parsing.py these are exactly
what the model returned (thinking switched off, temperature 0), so a change in the parser or in the
prompts' output contract that breaks real replies is caught here. Offline: the file is read from disk.
"""

import json
import re
from pathlib import Path

import pytest

from app.schemas.tender import TenderType
from app.services import claude_validator as claude

FIXTURE = Path(__file__).parent / "fixtures" / "llm" / "haiku_5_5_pilot_responses.json"
RECORDED = json.loads(FIXTURE.read_text(encoding="utf-8"))["responses"]
EXPECTED_COUNTS = {"validate": 47, "classify": 86, "router_desc": 18, "router_plain": 18}


def replies(task):
    return [r for r in RECORDED if r["task"] == task]


def test_fixture_has_the_recorded_sets_and_every_reply_ended_normally():
    counts = {task: len(replies(task)) for task in EXPECTED_COUNTS}
    assert counts == EXPECTED_COUNTS
    assert {r["finish_reason"] for r in RECORDED} == {"stop"}  # no truncation in the recorded run


@pytest.mark.parametrize("reply", replies("validate"), ids=lambda r: r["key"])
def test_validation_reply_parses_into_one_entry_per_store_item(reply):
    parsed = claude._parse_json_response(reply["response_text"], expect_list=True)
    assert isinstance(parsed, list)
    # the user message numbers the candidates "1. [Store] ...": the reply must answer each of them
    expected_indexes = [int(n) for n in re.findall(r"^(\d+)\. \[", reply["user_message"], flags=re.MULTILINE)]
    assert expected_indexes
    assert [entry["index"] for entry in parsed] == expected_indexes
    for entry in parsed:
        assert isinstance(entry["is_relevant"], bool)
        for weight in ("store_weight_g", "tender_weight_g"):
            assert entry.get(weight) is None or isinstance(entry[weight], (int, float))


@pytest.mark.parametrize("reply", replies("classify"), ids=lambda r: r["key"])
def test_classification_reply_is_one_known_tender_type(reply):
    # the same normalisation as tender_classifier._classify_by_llm applies before the lookup
    word = reply["response_text"].strip().lower().strip("\"'.,! ")
    assert word in {"product", "service", "work", "mixed"}
    assert TenderType(word)


@pytest.mark.parametrize("task", ["router_desc", "router_plain"])
def test_router_replies_parse_as_an_object_with_a_boolean(task):
    for reply in replies(task):
        parsed = claude._parse_json_response(reply["response_text"], expect_list=False)
        assert isinstance(parsed, dict), reply["key"]
        assert isinstance(parsed["sold"], bool), reply["key"]


def test_the_parser_also_survives_the_shapes_the_recorded_replies_could_take():
    """The recorded replies are bare JSON; wrap the first one the ways models are known to."""
    raw = replies("validate")[0]["response_text"]
    expected = json.loads(raw)
    for wrapped in (f"```json\n{raw}\n```", f"Ось результат:\n{raw}\nГотово.", f"\n  {raw}  \n"):
        assert claude._parse_json_response(wrapped, expect_list=True) == expected
