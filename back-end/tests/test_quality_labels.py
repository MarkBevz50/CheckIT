"""E0.7: metrics on different label sets, per-item expectations of C10 and the agreement figures of the judges."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "eval"))

import judge_agreement as ja  # noqa: E402
from quality import labels as label_store, metrics  # noqa: E402


def item(item_id, relevant=(), candidates=()):
    return {"item_id": item_id, "name": item_id, "relevant_urls": list(relevant), "candidates": [{"url": u, "price": 1} for u in candidates]}


# ---- label sets ------------------------------------------------------------------------------------------

def test_label_sets_separate_model_labels_from_human_ones_and_noted_items():
    rows = [{"pair_id": f"Q{n}", "item_id": "A-01", "url": f"u{n}"} for n in range(1, 6)] + [{"pair_id": "P1", "item_id": "A-01", "url": "u9"}]
    labels = {"pairs": {"Q1": "same", "Q2": "analog", "Q3": "no", "Q4": "same", "P1": "analog"},
              "label_sources": {"pairs": {"Q1": "llm_consensus", "Q2": "human", "Q3": "human_blind", "Q4": "human"}}}
    notes = {"pairs": {"Q4": ["claude_consulted"]}}
    sets = label_store.label_sets(labels, rows, notes)
    assert set(sets["all"]) == {("A-01", "u1"), ("A-01", "u2"), ("A-01", "u3"), ("A-01", "u4"), ("A-01", "u9")}
    assert set(sets["human"]) == {("A-01", "u2"), ("A-01", "u3"), ("A-01", "u4"), ("A-01", "u9")}   # no llm_consensus; P1 has no source = older human
    assert set(sets["human_clean"]) == {("A-01", "u2"), ("A-01", "u3"), ("A-01", "u9")}             # and without the noted Q4


def test_the_same_items_get_a_different_precision_on_each_set():
    items = [item("A-01", relevant=["u1", "u2", "u3"], candidates=["u1", "u2", "u3"])]
    sets = {"all": {("A-01", "u1"): "same", ("A-01", "u2"): "no", ("A-01", "u3"): "analog"},
            "human": {("A-01", "u2"): "no", ("A-01", "u3"): "analog"}}
    quality = metrics.quality_by_set(items, sets)
    assert quality["all"]["precision_all"] == round(2 / 3, 4) and quality["human"]["precision_all"] == 0.5
    assert "unlabeled" not in quality["all"] and quality["human"]["labeled"] == 2


# ---- C10 expectations per item ---------------------------------------------------------------------------

RULES = {"C10-01": {"max_accepted": 0}, "C10-02": {"max_accepted": 0}, "C10-03": {"allowed_labels": ["same", "analog"]}}


def test_a_blank_specific_to_the_enterprise_must_have_no_match_while_analogs_are_allowed_for_the_certificate():
    labeled = {("C10-03", "u1"): "analog", ("C10-03", "u2"): "analog"}
    good = [item("C10-01"), item("C10-02"), item("C10-03", relevant=["u1", "u2"])]
    assert metrics.expected_behavior(good, labeled, RULES) == {"met": True, "violated_items": [], "unverified": 0}
    bad = [item("C10-01", relevant=["x"]), item("C10-02"), item("C10-03", relevant=["u1"])]
    assert metrics.expected_behavior(bad, labeled, RULES)["violated_items"] == ["C10-01"]


def test_an_accepted_match_labeled_no_violates_and_an_unlabeled_one_cannot_be_verified():
    assert metrics.expected_behavior([item("C10-03", relevant=["u1"])], {("C10-03", "u1"): "no"}, RULES)["met"] is False
    verdict = metrics.expected_behavior([item("C10-03", relevant=["u1"])], {}, RULES)
    assert verdict["met"] is None and verdict["unverified"] == 1


def test_tender_metrics_uses_the_per_item_rules_when_the_expectation_has_them():
    run = {"id": "C10", "items": [item("C10-01"), item("C10-03", relevant=["u1"], candidates=["u1"])], "risk": None, "usage": []}
    result = metrics.tender_metrics(run, {("C10-03", "u1"): "analog"}, expected={"items": RULES})
    assert result["expected_behavior_met"] is True and result["expected_violated_items"] == []


# ---- agreement figures -----------------------------------------------------------------------------------

def test_kappa_and_agreement():
    assert ja.kappa([("a", "a"), ("b", "b")]) == 1.0
    assert ja.kappa([("a", "b"), ("b", "a")]) == -1.0
    assert ja.kappa([("a", "a"), ("a", "a")]) is None                 # chance agreement 1: undefined
    assert ja.kappa([]) is None
    assert ja.figures([("a", "a"), ("a", "b")]) == {"n": 2, "agree": 0.5, "kappa": 0.0}


def test_pair_views_give_three_classes_and_binary_with_and_without_notes():
    items = [("Q1", "same", "same"), ("Q2", "same", "analog"), ("Q3", "no", "analog"), ("Q4", "analog", "analog")]
    views = ja.pair_views(items, noted={"Q3"})
    assert views["all"]["3 classes"]["agree"] == 0.5 and views["all"]["binary"]["agree"] == 0.75
    assert views["without notes"]["3 classes"]["n"] == 3 and views["without notes"]["binary"]["agree"] == 1.0


def test_finding_views_compare_true_against_the_rest_and_can_leave_out_contaminated_items():
    items = [("F1", "true", "true"), ("F2", "false", "duplicate"), ("F3", "true", "false"), ("F4", "false", "false")]
    views = ja.finding_views(items, noted={"F4"}, excluded={"F3"})
    assert views["all"]["true vs rest"] == {"n": 3, "agree": 1.0, "kappa": 1.0}   # F3 left out: its judge label is not independent
    assert views["without notes"]["true vs rest"]["n"] == 2
    assert views["all"]["3 classes"]["agree"] == round(2 / 3, 3)                   # duplicate against false is a 3-class miss


def test_only_labels_with_the_blind_source_count_as_blind():
    labels = {"pairs": {"Q1": "same", "Q2": "no"}, "label_sources": {"pairs": {"Q1": "human_blind", "Q2": "human"}},
              "findings": {"F1": {"label": "true"}}, "label_sources_findings": {}}
    assert ja.human_blind(labels, "pairs", "Q1") == "same"
    assert ja.human_blind(labels, "pairs", "Q2") is None
    assert ja.human_blind(labels, "findings", "F1") is None
