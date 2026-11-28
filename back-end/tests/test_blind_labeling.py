"""E0.7: the blind control sample and the label sources (no network, no database)."""

import builtins
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "eval"))

import label_pairs  # noqa: E402
import make_blind_sample  # noqa: E402


def test_the_draw_is_random_but_repeatable_and_independent_of_the_input_order():
    pairs = [f"Q{n:03d}" for n in range(1, 114)]
    findings = [f"F{n:03d}" for n in range(1, 75)]
    first = make_blind_sample.draw(pairs, findings)
    assert len(first["pairs"]) == 20 and len(first["findings"]) == 10
    assert set(first["pairs"]) <= set(pairs) and set(first["findings"]) <= set(findings)
    assert first == make_blind_sample.draw(list(reversed(pairs)), list(reversed(findings)))
    assert first["pairs"] != pairs[:20]  # not simply the first ones
    assert make_blind_sample.draw(pairs, findings, seed=1)["pairs"] != first["pairs"]


def test_a_sample_larger_than_the_input_takes_everything():
    sample = make_blind_sample.draw(["Q1", "Q2"], ["F1"])
    assert sample["pairs"] == ["Q1", "Q2"] and sample["findings"] == ["F1"]


@pytest.fixture
def blind_world(tmp_path, monkeypatch):
    """A tiny labeling world: 3 queue pairs, 2 findings, a sample of 2 pairs and 1 finding, answers typed by a fake owner."""
    data = tmp_path
    queue = [{"pair_id": f"Q{n}", "item": f"Item {n}", "unit": "шт", "title": f"Product {n}", "store_name": "Rozetka",
              "price": 10, "url": f"u{n}", "bucket_hint": "SECRET-HINT"} for n in (1, 2, 3)]
    (data / "pairs_queue.jsonl").write_text("\n".join(json.dumps(r) for r in queue), encoding="utf-8")
    pool = [{"id": "F001", "tender": "C05", "quote": "Quote one", "type": "brand", "severity": "high", "explanation": "MODEL-SAYS-SO"},
            {"id": "F002", "tender": "C05", "quote": "Quote two", "type": "x", "severity": "low", "explanation": "other"}]
    (data / "doc_findings_pool.json").write_text(json.dumps(pool), encoding="utf-8")
    (data / "blind_sample.json").write_text(json.dumps({"seed": 1, "pairs": ["Q1", "Q3"], "findings": ["F002"]}), encoding="utf-8")
    (data / "labels.json").write_text(json.dumps({"pairs": {"P001": "same"}, "item_types": {}}), encoding="utf-8")
    for name, value in (("BLIND", data / "blind_sample.json"), ("QUEUE", data / "pairs_queue.jsonl"),
                        ("FINDINGS", data / "doc_findings_pool.json"), ("LABELS", data / "labels.json")):
        monkeypatch.setattr(label_pairs, name, value)
    monkeypatch.setattr(label_pairs, "_labels_ref", {})
    monkeypatch.setattr(label_pairs, "_source", {"value": "human"})
    return data


def type_answers(monkeypatch, answers):
    iterator = iter(answers)
    shown = []
    monkeypatch.setattr(builtins, "input", lambda prompt="": shown.append(prompt) or next(iterator))
    return shown


def test_blind_mode_labels_only_the_sample_marks_the_source_and_shows_no_model_answers(blind_world, monkeypatch, capsys):
    type_answers(monkeypatch, ["1", "3", "2"])  # Q1 same, Q3 no, F002 false
    label_pairs.run_blind(_prepared(label_pairs))
    shown = capsys.readouterr().out
    assert "SECRET-HINT" not in shown and "MODEL-SAYS-SO" not in shown and "Quote one" not in shown  # not in the sample
    assert "Quote two" in shown and "Item 1" in shown and "Item 2" not in shown                       # only the sample
    assert "brand" not in shown and "high" not in shown                                                # no type, no severity

    labels = json.loads((blind_world / "labels.json").read_text(encoding="utf-8"))
    assert labels["pairs"] == {"P001": "same", "Q1": "same", "Q3": "no"}                                # the old label is untouched
    assert labels["findings"] == {"F002": {"label": "false"}}
    assert labels["label_sources"]["pairs"] == {"Q1": "human_blind", "Q3": "human_blind"}
    assert labels["label_sources"]["findings"] == {"F002": "human_blind"}


def _prepared(module):
    labels = module.load_labels()
    module._labels_ref["labels"] = labels
    return labels


def test_a_label_without_a_recorded_source_counts_as_human_in_the_statistics(blind_world, capsys):
    label_pairs.stats()
    assert "sources pairs: {'human': 1}" in capsys.readouterr().out
