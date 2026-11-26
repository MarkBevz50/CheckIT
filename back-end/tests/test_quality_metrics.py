"""E0.7: metric functions of eval/quality (synthetic data), the snapshot LLM cache and the history/report."""

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "eval"))

from quality import metrics, report, stability  # noqa: E402
from quality.capture import BudgetExceeded, Capture, CachingClient, message_cost  # noqa: E402
from quality.snapshot import Snapshot, digest  # noqa: E402


def item(item_id, name, relevant=(), candidates=()):
    return {"item_id": item_id, "name": name, "relevant_urls": list(relevant),
            "candidates": [{"url": u, "price": p} for u, p in candidates]}


LABELED = {("A-01", "u1"): "same", ("A-01", "u2"): "analog", ("A-01", "u3"): "no", ("A-02", "u9"): "same"}


# ---- coverage ------------------------------------------------------------------------------

def test_coverage_counts_relevant_observations_with_a_price():
    items = [
        item("A-01", "x", ["u1", "u2", "u3"], [("u1", 10), ("u2", 12), ("u3", 11)]),   # 3 observations
        item("A-02", "y", ["u9"], [("u9", 5)]),                                       # 1
        item("A-03", "z", ["u7"], [("u7", None)]),                                    # relevant but no price: not an observation
        item("A-04", "w", [], [("u8", 5)]),                                           # nothing relevant
    ]
    assert metrics.coverage(items, 1) == 0.5
    assert metrics.coverage(items, 3) == 0.25
    assert metrics.coverage([], 1) is None


# ---- precision and recall --------------------------------------------------------------------

def test_precision_uses_only_labeled_matches_and_reports_the_rest():
    items = [item("A-01", "x", ["u1", "u2", "u3", "u4"], [("u1", 1), ("u2", 1), ("u3", 1), ("u4", 1)])]
    quality = metrics.match_quality(items, LABELED)
    assert (quality["accepted"], quality["labeled"], quality["correct"], quality["same"]) == (4, 3, 2, 1)
    assert quality["precision_all"] == round(2 / 3, 4)
    assert quality["precision_same"] == round(1 / 3, 4)
    assert quality["labeled_share"] == 0.75
    assert quality["unlabeled"] == [("A-01", "u4")]


def test_recall_is_measured_only_on_labeled_positive_pairs_that_were_seen():
    items = [
        item("A-01", "x", ["u1"], [("u1", 1), ("u2", 1), ("u3", 1)]),  # u1 same accepted, u2 analog missed, u3 "no"
        item("A-02", "y", [], []),                                      # u9 labeled but never a candidate: not counted
    ]
    quality = metrics.match_quality(items, LABELED)
    assert quality["recall_n"] == 2
    assert quality["recall_labeled"] == 0.5


def test_label_index_joins_labels_with_pair_rows():
    rows = [{"pair_id": "P1", "item_id": "A-01", "url": "u1"}, {"pair_id": "P2", "item_id": "A-01", "url": "u2"}]
    assert metrics.label_index({"pairs": {"P1": "same"}}, rows) == {("A-01", "u1"): "same"}


# ---- false alarms ----------------------------------------------------------------------------

def risk(level, price=0, doc=0, aggregate=None, deviations=()):
    return {"risk_level": level, "price_risk_score": price, "discriminatory_risk_score": doc,
            "breakdown": {"aggregate_risk": aggregate, "price_deviations": list(deviations), "discriminatory_analysis": None}}


def test_an_aggregate_alarm_with_low_coverage_is_unsupported():
    result = metrics.assess_alarm(risk("medium", price=40, aggregate={"risk_level": "high", "coverage_pct": 33.3}), [])
    assert result["class"] == "unsupported"


def test_an_aggregate_alarm_with_enough_coverage_is_supported():
    result = metrics.assess_alarm(risk("medium", price=40, aggregate={"risk_level": "high", "coverage_pct": 80}), [])
    assert result["class"] == "supported"


def test_a_per_item_deviation_needs_three_observations():
    items = [item("A-01", "x", ["u1", "u2"], [("u1", 1), ("u2", 1)])]  # 2 observations
    deviation = [{"item_name": "x", "risk_level": "high"}]
    assert metrics.assess_alarm(risk("high", price=50, deviations=deviation), items)["class"] == "unsupported"
    items = [item("A-01", "x", ["u1", "u2", "u3"], [("u1", 1), ("u2", 1), ("u3", 1)])]
    assert metrics.assess_alarm(risk("high", price=50, deviations=deviation), items)["class"] == "supported"


def test_a_score_from_documentation_only_is_unverified_not_a_false_alarm():
    assert metrics.assess_alarm(risk("medium", doc=40), [])["class"] == "unverified_doc"


def test_low_risk_is_not_an_alarm():
    assert metrics.assess_alarm(risk("low", price=5), [])["alarm"] is False
    assert metrics.assess_alarm(None, [])["class"] == "no_risk_result"


# ---- tender metrics and summary ---------------------------------------------------------------

def usage(cost, cached=False, stop="end_turn"):
    return {"cost": cost, "cached": cached, "stop_reason": stop}


def test_tender_metrics_and_the_c10_expectation():
    run = {"id": "C10", "items": [item("A-01", "x", ["u1"], [("u1", 5)])], "risk": risk("low"),
           "usage": [usage(0.001), usage(0.002, cached=True), usage(0.001, stop="max_tokens")], "parse_failures": 1,
           "seconds": {"total": 12.0}}
    result = metrics.tender_metrics(run, LABELED, expected={"relevant_matches": 0})
    assert result["expected_behavior_met"] is False and result["accepted_matches"] == 1
    assert result["cost_usd"] == 0.004 and result["cost_real_usd"] == 0.002
    assert result["llm"] == {"calls": 3, "parse_failures": 1, "max_tokens": 1, "error_share": round(2 / 3, 4)}
    clean = dict(run, items=[item("A-01", "x", [], [("u1", 5)])])
    assert metrics.tender_metrics(clean, LABELED, expected={"relevant_matches": 0})["expected_behavior_met"] is True


def test_summary_pools_items_and_counts_alarms():
    a = {"id": "T1", "items": [item("A-01", "x", ["u1"], [("u1", 5)])], "risk": risk("medium", price=40, aggregate={"risk_level": "high", "coverage_pct": 30}),
         "usage": [usage(0.01)], "seconds": {"total": 10.0}}
    b = {"id": "T2", "items": [item("B-01", "y", [], [])], "risk": risk("low"), "usage": [usage(0.01)], "seconds": {"total": 20.0}}
    per = {r["id"]: metrics.tender_metrics(r, LABELED) for r in (a, b)}
    summary = metrics.summarize([a, b], per, LABELED)
    assert (summary["tenders"], summary["items"], summary["coverage_ge1"]) == (2, 2, 0.5)
    assert (summary["alarms"], summary["unsupported_alarms"], summary["false_alarm_rate"]) == (1, 1, 1.0)
    assert summary["cost_per_tender_usd"] == 0.01 and summary["seconds_per_tender"] == 15.0


# ---- snapshot and the LLM cache ---------------------------------------------------------------

def test_the_hash_depends_on_every_request_parameter_and_not_on_dict_order():
    base = {"model": "m", "system": [{"text": "s"}], "messages": [{"role": "user", "content": "q"}], "max_tokens": 10}
    assert digest(base) == digest(dict(reversed(list(base.items()))))
    for change in ({"model": "m2"}, {"system": [{"text": "s2"}]}, {"messages": [{"role": "user", "content": "q2"}]},
                   {"max_tokens": 11}, {"thinking": {"type": "disabled"}}, {"temperature": 0.5}):
        assert digest({**base, **change}) != digest(base), change


class RealClient:
    """Stands in for AsyncAnthropic and counts the calls that reach the API."""

    def __init__(self):
        self.calls = 0
        self.messages = SimpleNamespace(create=self._create)

    async def _create(self, **kwargs):
        self.calls += 1
        usage = SimpleNamespace(input_tokens=1000, output_tokens=100, cache_read_input_tokens=0, cache_creation_input_tokens=0)
        return SimpleNamespace(model="claude-haiku-5-5", stop_reason="end_turn", usage=usage,
                               content=[SimpleNamespace(type="text", text="[]")])


def ask(client, **kwargs):
    return asyncio.run(client.messages.create(max_tokens=2600, system=[{"text": "s"}], messages=[], model="claude-haiku-5-5", **kwargs))


def test_llm_answers_come_from_the_snapshot_until_a_parameter_changes(tmp_path):
    real = RealClient()
    capture = Capture(Snapshot("t", root=tmp_path), "replay", "replay", budget_usd=1.0)
    client = CachingClient(real, capture)

    ask(client)
    ask(client)
    assert real.calls == 1                                         # the second identical request is a snapshot hit
    ask(client, thinking={"type": "disabled"})
    assert real.calls == 2                                         # a changed parameter is a new key
    assert [u["cached"] for u in capture.usage] == [False, True, False]
    assert capture.usage[1]["cost"] == capture.usage[0]["cost"] == message_cost("claude-haiku-5-5", 1000, 100)
    assert capture.spent_real == pytest.approx(2 * message_cost("claude-haiku-5-5", 1000, 100))


def test_llm_live_bypasses_the_cache_and_the_budget_stops_the_run(tmp_path):
    real = RealClient()
    capture = Capture(Snapshot("t", root=tmp_path), "replay", "live", budget_usd=0.0001)
    client = CachingClient(real, capture)
    ask(client)
    with pytest.raises(BudgetExceeded):
        ask(client)
    assert real.calls == 1


# ---- stability, history and report -------------------------------------------------------------

def test_pairs_for_the_stability_check_are_balanced_and_repeatable():
    rows = [{"pair_id": f"P{n:03d}", "item_id": "A-01", "url": f"u{n}"} for n in range(1, 41)]
    labels = {"pairs": {r["pair_id"]: ("same", "analog", "no", "no")[n % 4] for n, r in enumerate(rows)}}
    first = stability.pick_pairs(rows, labels)
    assert len(first) == 20
    assert {label: sum(1 for p in first if p["label"] == label) for label in ("same", "analog", "no")} == {"same": 7, "analog": 7, "no": 6}
    assert first == stability.pick_pairs(list(reversed(rows)), labels)


def make_row(stage, mode="replay", coverage=0.5):
    summary = {"coverage_ge1": coverage, "coverage_ge3": 0.2, "precision_all": 0.8, "precision_same": 0.5, "labeled_share": 0.9,
               "recall_labeled": 0.7, "alarms": 4, "unsupported_alarms": 2, "false_alarm_rate": 0.5, "doc_findings": 3,
               "cost_per_tender_usd": 0.0021, "seconds_per_tender": None, "llm": {"error_share": 0.0}}
    tender = {"items": 3, "coverage_ge1": 0.3, "coverage_ge3": 0.0, "accepted": 4, "labeled": 3, "correct": 2,
              "alarm": {"level": "medium", "class": "unsupported"}, "cost_usd": 0.002, "seconds": None, "errors": [],
              "expected_behavior_met": False, "accepted_matches": 2}
    return {"date": "2026-11-28", "sha": "abc1234", "stage": stage, "mode": mode, "llm": "replay", "summary": summary,
            "tenders": {"C10": tender}, "stability": {"pairs": 20, "runs": 3, "changed": 4, "changed_share": 0.2, "cost_usd": 0.01}}


def test_history_rows_round_trip_and_the_report_has_the_tables(tmp_path, monkeypatch):
    monkeypatch.setattr(report, "METRICS", tmp_path)
    monkeypatch.setattr(report, "HISTORY", tmp_path / "history.jsonl")
    monkeypatch.setattr(report, "REPORT", tmp_path / "quality_report.md")
    monkeypatch.setattr(report, "CHART", tmp_path / "chart.png")
    report.append_history(make_row("E0.7 база"))
    report.append_history(make_row("після E1.10", coverage=0.7))
    history = report.read_history()
    assert [r["stage"] for r in history] == ["E0.7 база", "після E1.10"]

    text = report.build_report(history)
    assert "| E0.7 база | replay/replay |" in text and "50 %" in text and "70 %" in text
    assert "C10, очікувана поведінка" in text and "не виконано" in text
    assert "Стабільність валідації: 20 розмічених пар" in text

    drawn = report.write_report(history)
    assert (tmp_path / "quality_report.md").exists()
    if drawn:
        assert (tmp_path / "chart.png").stat().st_size > 1000


def test_a_history_file_line_is_valid_json_with_the_expected_keys():
    row = make_row("E0.7 база")
    assert set(json.loads(json.dumps(row))) >= {"date", "sha", "stage", "mode", "summary", "tenders", "stability"}


# ---- documentation findings per mode -----------------------------------------------------------

def test_doc_findings_metrics_count_true_false_and_duplicates_per_mode():
    sys.path.insert(0, str(ROOT / "eval"))
    import doc_findings_report as dfr

    provenance = {
        "modes": {"A": {"label": "a"}, "B": {"label": "b"}},
        "calls": [{"mode": "A", "cost_usd": 0.002}, {"mode": "A", "cost_usd": 0.004}, {"mode": "B", "cost_usd": 0.03}],
        "pool": [
            {"id": "F001", "tender": "C05", "sources": [{"mode": "A", "run": 1, "index": 1}, {"mode": "B", "run": 1, "index": 1}]},
            {"id": "F002", "tender": "C05", "sources": [{"mode": "A", "run": 1, "index": 2}, {"mode": "A", "run": 2, "index": 1}]},
            {"id": "F003", "tender": "C05", "sources": [{"mode": "B", "run": 1, "index": 2}]},
            {"id": "F004", "tender": "C05", "sources": [{"mode": "B", "run": 1, "index": 3}]},
        ],
    }
    labels = {"findings": {"F001": {"label": "true"}, "F002": {"label": "false"}, "F003": {"label": "duplicate", "of": "F001"}}}
    result = dfr.compute(provenance, labels)
    a, b = result["modes"]["A"], result["modes"]["B"]
    assert (a["findings"], a["true"], a["false"], a["precision"]) == (3, 1, 2, round(1 / 3, 4))
    assert (b["findings"], b["true"], b["duplicate"], b["unlabeled"]) == (3, 1, 1, 1)
    assert b["precision"] == round(1 / 2, 4)                       # the unlabeled one is not counted
    assert result["union_true"] == 1 and a["share_of_union_true"] == 1.0
    assert a["cost_total"] == 0.006 and a["cost_per_call"] == 0.003
