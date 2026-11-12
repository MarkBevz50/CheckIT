"""Parsing of LLM replies (text -> data) for the Claude and Gemini validators.

These functions take plain text, so they survive the provider refactoring in E2-E5 and
will be used to check Haiku 5.5 output in E0.7. NOTE: the samples below are hand-written
in the shapes models really produce (bare JSON, ```json fences, chatter around the JSON);
replace or extend them with recorded Haiku 5.5 replies when the control run happens.
"""

import json
from types import SimpleNamespace

import pytest

from app.services import claude_validator as claude
from app.services import gemini_validator as gemini

VALIDATION = [
    {"index": 1, "is_relevant": True, "store_weight_g": 950, "tender_weight_g": 1000},
    {"index": 2, "is_relevant": False, "store_weight_g": None, "tender_weight_g": None},
]
VALIDATION_JSON = json.dumps(VALIDATION, ensure_ascii=False)

DISCRIMINATION = {
    "overall_risk": "medium",
    "discriminatory_requirements": [
        {"requirement": "Лише продукція бренду X", "severity": "high", "explanation": "Обмежує конкуренцію"}
    ],
    "summary": "Є вимога до конкретного бренду",
}


# ---- Claude: _parse_json_response -------------------------------------

@pytest.mark.parametrize(
    "reply",
    [
        VALIDATION_JSON,
        f"```json\n{VALIDATION_JSON}\n```",
        f"```\n{VALIDATION_JSON}\n```",
        f"  \n{VALIDATION_JSON}\n  ",
        f"Ось результат аналізу:\n{VALIDATION_JSON}\nСподіваюсь, це допоможе.",
    ],
    ids=["bare", "json-fence", "plain-fence", "whitespace", "chatter-around"],
)
def test_claude_parses_a_list_in_every_common_shape(reply):
    assert claude._parse_json_response(reply, expect_list=True) == VALIDATION


@pytest.mark.parametrize(
    "reply",
    [json.dumps(DISCRIMINATION, ensure_ascii=False), "Аналіз:\n" + json.dumps(DISCRIMINATION, ensure_ascii=False)],
    ids=["bare", "chatter-around"],
)
def test_claude_parses_an_object(reply):
    assert claude._parse_json_response(reply, expect_list=False) == DISCRIMINATION


@pytest.mark.parametrize("reply", ["", "Не можу відповісти", "[1, 2", '{"a": ', "```json\n```"])
def test_claude_returns_none_for_unparseable_replies(reply):
    assert claude._parse_json_response(reply) is None
    assert claude._parse_json_response(reply, expect_list=False) is None


def test_claude_empty_list_is_valid_data_not_a_failure():
    assert claude._parse_json_response("[]") == []


def test_claude_extract_text_joins_text_blocks_only():
    message = SimpleNamespace(
        content=[
            SimpleNamespace(type="text", text="[1,"),
            SimpleNamespace(type="thinking", thinking="..."),
            SimpleNamespace(type="text", text=" 2]"),
        ]
    )
    assert claude._extract_text(message) == "[1, 2]"


# ---- Gemini: _parse_response ------------------------------------------

@pytest.mark.parametrize(
    "reply",
    [VALIDATION_JSON, f"Результат:\n{VALIDATION_JSON}\nГотово."],
    ids=["bare", "chatter-around"],
)
def test_gemini_parses_a_list(reply):
    assert gemini._parse_response(reply, 2) == VALIDATION


@pytest.mark.parametrize("reply", ["", "нічого", "[1, 2", '{"index": 1}'])
def test_gemini_returns_none_for_unparseable_or_non_list_replies(reply):
    assert gemini._parse_response(reply, 2) is None


# ---- defaults used when validation is skipped -------------------------

@pytest.mark.parametrize("module", [claude, gemini], ids=["claude", "gemini"])
def test_default_fields_accept_everything_and_leave_weights_empty(module):
    items = [{"title": "Сік"}, {"title": "Сир"}]
    result = module._set_default_fields(items)
    assert all(i["is_relevant"] is True for i in result)
    assert all(i[k] is None for i in result for k in ("store_weight_g", "tender_weight_g", "price_per_unit"))
