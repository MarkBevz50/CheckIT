"""E0.7: consensus of the two judges, the owner's review queue and the --review screen (no network, no database)."""

import builtins
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "eval"))

import judge_merge  # noqa: E402
import label_pairs  # noqa: E402


def judge(pairs, findings, contaminated=()):
    return {"pairs": {k: {"label": v, "reason": f"reason {k}"} for k, v in pairs.items()},
            "findings": {k: {"label": v, "reason": f"reason {k}"} for k, v in findings.items()},
            "contaminated_findings": list(contaminated)}


def test_pairs_agreeing_judges_are_accepted_and_disagreement_goes_to_the_owner():
    a = judge({"Q1": "same", "Q2": "same", "Q3": "no", "Q4": "analog"}, {})
    b = judge({"Q1": "same", "Q2": "analog", "Q3": "invalid", "Q4": "analog"}, {})
    merged = judge_merge.plan({"pairs": {}}, a, b, ["Q1", "Q2", "Q3", "Q4"], [])
    assert merged["auto_pairs"] == {"Q1": "same", "Q4": "analog"}
    assert merged["review_pairs"] == ["Q2", "Q3"]                    # a disagreement and an invalid answer


def test_an_existing_label_is_never_touched_whoever_gave_it():
    a = judge({"Q1": "same", "Q2": "same", "Q3": "same"}, {"F1": "false"})
    b = judge({"Q1": "same", "Q2": "no", "Q3": "same"}, {"F1": "false"})
    labels = {"pairs": {"Q1": "no", "Q2": "analog"}, "findings": {"F1": {"label": "true"}}}  # blind / older human / earlier merge
    merged = judge_merge.plan(labels, a, b, ["Q1", "Q2", "Q3"], ["F1"])
    assert merged["auto_pairs"] == {"Q3": "same"} and merged["review_pairs"] == []
    assert merged["auto_findings"] == [] and merged["review_findings"] == {}


def test_only_a_unanimous_false_finding_is_accepted_automatically():
    findings_a = {"F1": "false", "F2": "false", "F3": "duplicate", "F4": "duplicate", "F5": "true", "F6": "false", "F7": "duplicate"}
    findings_b = {"F1": "false", "F2": "true", "F3": "false", "F4": "duplicate", "F5": "true", "F6": "false", "F7": "false"}
    merged = judge_merge.plan({}, judge({}, findings_a, contaminated=["F6"]), judge({}, findings_b),
                              [], ["F1", "F2", "F3", "F4", "F5", "F6", "F7"])
    assert merged["auto_findings"] == ["F1"]
    assert merged["review_findings"] == {
        "F2": "true by at least one judge", "F3": "other mix", "F4": "unanimous duplicate", "F5": "true by at least one judge",
        "F6": "judge A not independent", "F7": "other mix"}


def test_apply_writes_only_accepted_labels_with_their_source():
    labels = {"pairs": {"Q9": "no"}, "findings": {}, "label_sources": {"pairs": {"Q9": "human_blind"}}}
    judge_merge.apply(labels, {"auto_pairs": {"Q1": "same"}, "review_pairs": ["Q2"], "auto_findings": ["F1"], "review_findings": {"F2": "x"}})
    assert labels["pairs"] == {"Q9": "no", "Q1": "same"} and labels["findings"] == {"F1": {"label": "false"}}
    assert labels["label_sources"]["pairs"] == {"Q9": "human_blind", "Q1": "llm_consensus"}
    assert labels["label_sources"]["findings"] == {"F1": "llm_consensus"}


@pytest.fixture
def review_world(tmp_path, monkeypatch):
    queue = [{"pair_id": f"Q{n}", "item": f"Item {n}", "unit": "шт", "title": f"Product {n}", "store_name": "Rozetka", "price": 1,
              "url": f"u{n}"} for n in (1, 2)]
    (tmp_path / "pairs_queue.jsonl").write_text("\n".join(json.dumps(r) for r in queue), encoding="utf-8")
    pool = [{"id": "F1", "tender": "C05", "quote": "Quote one"}, {"id": "F2", "tender": "C05", "quote": "Quote two"}]
    (tmp_path / "doc_findings_pool.json").write_text(json.dumps(pool), encoding="utf-8")
    a = judge({"Q1": "same", "Q2": "no"}, {"F1": "false", "F2": "true"})
    b = judge({"Q1": "analog", "Q2": "no"}, {"F1": "false", "F2": "false"})
    (tmp_path / "judge_a_labels.json").write_text(json.dumps(a), encoding="utf-8")
    (tmp_path / "judge_b_labels.json").write_text(json.dumps(b), encoding="utf-8")
    (tmp_path / "labels.json").write_text(json.dumps({"pairs": {}, "item_types": {}}), encoding="utf-8")
    for module, names in ((label_pairs, {"QUEUE": "pairs_queue.jsonl", "FINDINGS": "doc_findings_pool.json", "LABELS": "labels.json",
                                         "DATA": None}),
                          (judge_merge, {"JUDGE_A": "judge_a_labels.json", "JUDGE_B": "judge_b_labels.json", "LABELS": "labels.json"})):
        for name, filename in names.items():
            monkeypatch.setattr(module, name, tmp_path if filename is None else tmp_path / filename)
    monkeypatch.setattr(label_pairs, "_labels_ref", {})
    monkeypatch.setattr(label_pairs, "_source", {"value": "human"})
    return tmp_path


def test_the_review_shows_both_judges_and_records_human_labels(review_world, monkeypatch, capsys):
    answers = iter(["2", "1"])                       # Q1 -> analog; F2 (the only finding for the owner) -> true
    monkeypatch.setattr(builtins, "input", lambda prompt="": next(answers))
    labels = label_pairs.load_labels()
    label_pairs._labels_ref["labels"] = labels
    label_pairs.run_review(labels)
    shown = capsys.readouterr().out
    assert "Item 1" in shown and "Item 2" not in shown                       # Q2: both judges said "no", nothing to review
    assert "Суддя A: same: reason Q1" in shown and "Суддя B: analog: reason Q1" in shown
    assert "Quote two" in shown and "Quote one" not in shown                 # F1: unanimous false, accepted automatically
    assert "true by at least one judge" in shown
    saved = json.loads((review_world / "labels.json").read_text(encoding="utf-8"))
    assert saved["pairs"] == {"Q1": "analog"} and saved["findings"] == {"F2": {"label": "true"}}
    assert saved["label_sources"] == {"pairs": {"Q1": "human"}, "findings": {"F2": "human"}}
