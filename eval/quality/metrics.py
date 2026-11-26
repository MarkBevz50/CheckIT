"""Quality metrics of a control run: pure functions on plain dicts (unit-tested in back-end/tests).

Definitions (also in PLAN/DIPLOMA_NOTES.md, section "Метрики якості"):

  coverage_ge1 / coverage_ge3   share of the goods items that have at least 1 / at least 3 relevant observations
                                (a relevant match with a price); 3 is the reliability threshold of E4.6
  precision_all                 among the matches the validator accepted as relevant AND the owner has labeled,
                                the share labeled "same" or "analog"; precision_same counts only "same".
                                labeled_share says how much of the accepted matches is labeled; the rest goes to the
                                labeling queue, so the labeled set grows with every run
  recall_labeled                among the labeled pairs ("same"/"analog") that the run actually saw as candidates,
                                the share the validator accepted. Only on labeled pairs: the labeled set is not a
                                random sample, so this is a lower-confidence number
  false alarm                   a tender with overall risk >= medium whose price part is not backed by data
                                (aggregate risk with coverage below the threshold, or per-item deviation from fewer
                                than 3 observations). A score that comes only from documentation findings is
                                "unverified" until quotes are verified (E1.9); it is reported, not counted
  c10                           the expected behavior of C10: no relevant matches at all
"""

from typing import Dict, Iterable, List, Optional, Tuple

POSITIVE = ("same", "analog")
MIN_OBSERVATIONS = 3
AGGREGATE_MIN_COVERAGE = 0.6  # the threshold that E1.10 puts into Settings; until then the report uses this value


def _number(value) -> Optional[float]:
    try:
        number = float(str(value).replace(",", ".").replace(" ", ""))
        return number if number > 0 else None
    except (TypeError, ValueError):
        return None


def observations(item: dict) -> int:
    """Relevant matches of an item that carry a price."""
    relevant = set(item.get("relevant_urls") or [])
    return sum(1 for c in item.get("candidates", []) if c.get("url") in relevant and _number(c.get("price_on_sale") or c.get("price")))


def ratio(numerator: float, denominator: float) -> Optional[float]:
    return round(numerator / denominator, 4) if denominator else None


def coverage(items: List[dict], k: int) -> Optional[float]:
    return ratio(sum(1 for item in items if observations(item) >= k), len(items))


def label_index(labels: dict, pair_rows: Iterable[dict]) -> Dict[Tuple[str, str], str]:
    """(item_id, url) -> label, from labels.json ("pairs") and the rows that describe the pairs."""
    result = {}
    for row in pair_rows:
        label = labels.get("pairs", {}).get(row["pair_id"])
        if label:
            result[(row["item_id"], row["url"])] = label
    return result


def match_quality(items: List[dict], labeled: Dict[Tuple[str, str], str]) -> dict:
    accepted = [(item["item_id"], url) for item in items for url in set(item.get("relevant_urls") or [])]
    known = [labeled[pair] for pair in accepted if pair in labeled]
    unlabeled = [pair for pair in accepted if pair not in labeled]
    correct = sum(1 for label in known if label in POSITIVE)
    same = sum(1 for label in known if label == "same")

    seen_positive, recalled = 0, 0
    for item in items:
        urls = {c.get("url") for c in item.get("candidates", [])}
        accepted_urls = set(item.get("relevant_urls") or [])
        for url in urls:
            if labeled.get((item["item_id"], url)) in POSITIVE:
                seen_positive += 1
                recalled += url in accepted_urls
    return {
        "accepted": len(accepted), "labeled": len(known), "correct": correct, "same": same,
        "precision_all": ratio(correct, len(known)), "precision_same": ratio(same, len(known)),
        "labeled_share": ratio(len(known), len(accepted)),
        "recall_labeled": ratio(recalled, seen_positive), "recall_n": seen_positive,
        "unlabeled": unlabeled,
    }


def assess_alarm(risk: Optional[dict], items: List[dict], min_coverage: float = AGGREGATE_MIN_COVERAGE) -> dict:
    """Classify the overall risk of one tender: none | supported | unsupported | unverified_doc."""
    if not risk:
        return {"level": None, "alarm": False, "class": "no_risk_result"}
    level = risk.get("risk_level")
    alarm = level in ("medium", "high")
    price_score = risk.get("price_risk_score") or 0
    doc_score = risk.get("discriminatory_risk_score") or 0
    breakdown = risk.get("breakdown") or {}
    if not alarm:
        return {"level": level, "alarm": False, "class": "none"}

    price_supported = None
    if price_score > 0:
        by_name = {item["name"]: item for item in items}
        deviations = [d for d in breakdown.get("price_deviations", []) if d.get("risk_level") in ("high", "medium")]
        if deviations:
            price_supported = all(observations(by_name.get(d.get("item_name"), {})) >= MIN_OBSERVATIONS for d in deviations)
        else:
            aggregate = breakdown.get("aggregate_risk") or {}
            coverage_share = (aggregate.get("coverage_pct") or 0) / 100.0
            price_supported = aggregate.get("risk_level") in ("high", "medium") and coverage_share >= min_coverage
    if price_supported is False:
        klass = "unsupported"
    elif price_supported is True:
        klass = "supported"
    elif doc_score > 0:
        klass = "unverified_doc"
    else:
        klass = "unsupported"  # a level without any positive component: no evidence at all
    return {"level": level, "alarm": True, "class": klass, "price_score": price_score, "doc_score": doc_score}


def llm_errors(usage: List[dict], parse_failures: int) -> dict:
    calls = len(usage)
    truncated = sum(1 for u in usage if u.get("stop_reason") == "max_tokens")
    return {"calls": calls, "parse_failures": parse_failures, "max_tokens": truncated,
            "error_share": ratio(parse_failures + truncated, calls)}


def tender_metrics(run: dict, labeled: Dict[Tuple[str, str], str], expected: Optional[dict] = None) -> dict:
    items = run["items"]
    quality = match_quality(items, labeled)
    findings = ((run.get("risk") or {}).get("breakdown") or {}).get("discriminatory_analysis") or {}
    findings = findings.get("discriminatory_requirements", []) if isinstance(findings, dict) else []
    usage = run.get("usage", [])
    metrics = {
        "items": len(items), "coverage_ge1": coverage(items, 1), "coverage_ge3": coverage(items, 3),
        **{k: v for k, v in quality.items() if k != "unlabeled"},
        "unlabeled_accepted": len(quality["unlabeled"]),
        "alarm": assess_alarm(run.get("risk"), items),
        "doc_findings": len(findings),
        "cost_usd": round(sum(u["cost"] for u in usage), 5),
        "cost_real_usd": round(sum(u["cost"] for u in usage if not u["cached"]), 5),
        "seconds": run.get("seconds"),
        "llm": llm_errors(usage, run.get("parse_failures", 0)),
        "gemini_calls": run.get("gemini_calls", 0),
        "errors": run.get("errors", []),
    }
    if expected is not None:
        accepted_pairs = [(item["item_id"], url) for item in items for url in set(item.get("relevant_urls") or [])]
        metrics["expected_behavior_met"] = len(accepted_pairs) == expected.get("relevant_matches", 0)
        metrics["expected_relevant_matches"] = expected.get("relevant_matches", 0)
        metrics["accepted_matches"] = len(accepted_pairs)
        # what the accepted matches are by the labels: false ones ("no") are what false_matches_allowed is about
        metrics["accepted_false"] = sum(1 for pair in accepted_pairs if labeled.get(pair) == "no")
        metrics["accepted_unlabeled"] = sum(1 for pair in accepted_pairs if pair not in labeled)
    return metrics


def summarize(runs: List[dict], per_tender: Dict[str, dict], labeled: Dict[Tuple[str, str], str]) -> dict:
    all_items = [item for run in runs for item in run["items"]]
    quality = match_quality(all_items, labeled)
    alarms = [m["alarm"] for m in per_tender.values()]
    alarm_count = sum(1 for a in alarms if a["alarm"])
    unsupported = sum(1 for a in alarms if a["class"] == "unsupported")
    usage = [u for run in runs for u in run.get("usage", [])]
    seconds = [m["seconds"] for m in per_tender.values() if m.get("seconds")]
    return {
        "tenders": len(runs), "items": len(all_items),
        "coverage_ge1": coverage(all_items, 1), "coverage_ge3": coverage(all_items, 3),
        **{k: v for k, v in quality.items() if k != "unlabeled"},
        "unlabeled_accepted": len(quality["unlabeled"]),
        "alarms": alarm_count, "unsupported_alarms": unsupported,
        "unverified_doc_alarms": sum(1 for a in alarms if a["class"] == "unverified_doc"),
        "false_alarm_rate": ratio(unsupported, alarm_count),
        "doc_findings": sum(m["doc_findings"] for m in per_tender.values()),
        "cost_usd": round(sum(u["cost"] for u in usage), 5),
        "cost_real_usd": round(sum(u["cost"] for u in usage if not u["cached"]), 5),
        "cost_per_tender_usd": ratio(sum(u["cost"] for u in usage), len(runs)),
        "seconds_per_tender": round(sum(s["total"] for s in seconds) / len(seconds), 1) if seconds else None,
        "llm": llm_errors(usage, sum(run.get("parse_failures", 0) for run in runs)),
        "gemini_calls": sum(run.get("gemini_calls", 0) for run in runs),
    }
