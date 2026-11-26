"""risk_analyzer: price deviation, aggregate risk and the overall score."""

import pytest

from app.services.risk_analyzer import (
    calculate_aggregate_risk,
    calculate_overall_risk_score,
    calculate_price_deviation,
)


def group(name="Сир", price=100.0, source="tender", quantity=1, market=()):
    return {
        "tender_item": {"name": name, "unit_price": price, "price_source": source, "quantity": quantity},
        "matches": [{"price": p} for p in market],
    }


def assess(g):
    return calculate_price_deviation([], [g])[0]


# ---- calculate_price_deviation ----------------------------------------

@pytest.mark.parametrize(
    "tender_price, market, level, deviation",
    [
        (100.0, [100.0], "low", 0.0),
        (110.0, [100.0], "low", 10.0),  # exactly 10% is still low
        (111.0, [100.0], "medium", 11.0),
        (120.0, [100.0], "medium", 20.0),  # exactly 20% is still medium
        (121.0, [100.0], "high", 21.0),
        (79.0, [100.0], "high", -21.0),  # cheaper than market is also a deviation
        (100.0, [90.0, 100.0, 300.0], "low", 0.0),  # median, not mean
    ],
)
def test_deviation_thresholds(tender_price, market, level, deviation):
    result = assess(group(price=tender_price, market=market))
    assert result["risk_level"] == level
    assert result["deviation_pct"] == deviation


def test_median_market_price_is_reported():
    result = assess(group(price=100.0, market=[80.0, 100.0, 120.0]))
    assert result["median_market_price"] == 100.0


def test_reason_says_higher_or_lower():
    assert "вище" in assess(group(price=150.0, market=[100.0]))["reason"]
    assert "нижче" in assess(group(price=50.0, market=[100.0]))["reason"]


def test_sale_price_wins_over_regular_price():
    g = group(price=100.0)
    g["matches"] = [{"price": 200.0, "price_on_sale": 100.0}]
    assert assess(g)["deviation_pct"] == 0.0


@pytest.mark.parametrize("source", ["market_estimate", "unknown"])
def test_estimated_and_unknown_prices_are_excluded(source):
    result = assess(group(source=source, market=[100.0]))
    assert result["risk_level"] == "excluded"
    assert result["deviation_pct"] is None


@pytest.mark.parametrize("price", [None, 0, -5, "abc"])
def test_missing_or_invalid_tender_price_is_unknown(price):
    assert assess(group(price=price, market=[100.0]))["risk_level"] == "unknown"


def test_no_matches_is_unknown():
    result = assess(group(market=[]))
    assert result["risk_level"] == "unknown"
    assert "ринкових даних" in result["reason"]


def test_matches_without_prices_are_unknown():
    g = group()
    g["matches"] = [{"price": None}, {"price": "abc"}, {}]
    assert assess(g)["risk_level"] == "unknown"


def test_zero_median_is_unknown():
    assert assess(group(price=50.0, market=[0.0, 0.0]))["risk_level"] == "unknown"


def test_each_group_gets_its_own_result():
    results = calculate_price_deviation([], [group("a", 100, market=[100]), group("b", 200, market=[100])])
    assert [r["item_name"] for r in results] == ["a", "b"]
    assert [r["risk_level"] for r in results] == ["low", "high"]


# ---- calculate_aggregate_risk -----------------------------------------

@pytest.mark.parametrize("total", [None, 0, -1])
def test_aggregate_needs_a_positive_budget(total):
    assert calculate_aggregate_risk([group(quantity=2, market=[100.0])], total) is None


def test_aggregate_needs_market_data():
    assert calculate_aggregate_risk([group(quantity=2, market=[])], 1000.0) is None
    assert calculate_aggregate_risk([group(quantity=0, market=[100.0])], 1000.0) is None


@pytest.mark.parametrize(
    "budget, level",
    [(1000.0, "low"), (1120.0, "low"), (1130.0, "medium"), (1250.0, "medium"), (1260.0, "high"), (700.0, "high")],
)
def test_aggregate_thresholds(budget, level):
    # market total = median 100 * quantity 10 = 1000
    result = calculate_aggregate_risk([group(quantity=10, market=[100.0])], budget)
    assert result["risk_level"] == level
    assert result["market_total"] == 1000.0


def test_aggregate_coverage_counts_items_with_estimate():
    groups = [group("a", quantity=1, market=[100.0]), group("b", quantity=1, market=[])]
    result = calculate_aggregate_risk(groups, 100.0)
    assert result["items_with_estimate"] == 1
    assert result["items_total"] == 2
    assert result["coverage_pct"] == 50.0


def test_aggregate_reason_texts():
    groups = [group(quantity=1, market=[100.0])]
    assert "вищий" in calculate_aggregate_risk(groups, 150.0)["reason"]
    assert "нижчий" in calculate_aggregate_risk(groups, 50.0)["reason"]
    assert "співпадає" in calculate_aggregate_risk(groups, 100.0)["reason"]


# ---- calculate_overall_risk_score -------------------------------------

def risk(level):
    return {"risk_level": level}


def test_empty_inputs_give_zero_score():
    result = calculate_overall_risk_score([])
    assert result["risk_score"] == 0
    assert result["risk_level"] == "low"


def test_price_score_counts_high_and_medium_among_assessed():
    # 1 high (50) + 1 medium (25) + 2 low over 4 assessed items -> round(75 / 4) = 19
    result = calculate_overall_risk_score([risk("high"), risk("medium"), risk("low"), risk("low")])
    assert result["price_risk_score"] == 19
    assert result["risk_level"] == "low"


def test_price_score_is_capped_at_50():
    assert calculate_overall_risk_score([risk("high")] * 3)["price_risk_score"] == 50


def test_excluded_and_unknown_items_are_not_assessed():
    result = calculate_overall_risk_score([risk("excluded"), risk("excluded"), risk("unknown")])
    assert result["price_risk_score"] == 0
    assert result["excluded_items_count"] == 2


@pytest.mark.parametrize("level, score", [("high", 40), ("medium", 20), ("low", 5)])
def test_aggregate_risk_is_the_fallback_when_no_item_is_assessed(level, score):
    result = calculate_overall_risk_score([risk("excluded")], aggregate_risk=risk(level))
    assert result["price_risk_score"] == score


def test_aggregate_risk_is_ignored_when_items_were_assessed():
    result = calculate_overall_risk_score([risk("high")], aggregate_risk=risk("low"))
    assert result["price_risk_score"] == 50


@pytest.mark.parametrize("overall, score", [("high", 50), ("medium", 25), ("low", 0)])
def test_discriminatory_overall_level(overall, score):
    result = calculate_overall_risk_score([], {"overall_risk": overall})
    assert result["discriminatory_risk_score"] == score


def test_discriminatory_findings_can_raise_the_score():
    analysis = {
        "overall_risk": "low",
        "discriminatory_requirements": [{"severity": "high"}, {"severity": "high"}, {"severity": "medium"}],
    }
    # 2 * 15 + 8 = 38 beats the overall level (0)
    assert calculate_overall_risk_score([], analysis)["discriminatory_risk_score"] == 38


def test_discriminatory_score_is_capped_at_50():
    analysis = {"overall_risk": "low", "discriminatory_requirements": [{"severity": "high"}] * 10}
    assert calculate_overall_risk_score([], analysis)["discriminatory_risk_score"] == 50


@pytest.mark.parametrize(
    "price, discrim, level",
    [
        (None, None, "low"),
        ("high", None, "medium"),  # 50 -> medium
        ("medium", {"overall_risk": "medium"}, "medium"),  # 25 + 25 = 50
        ("high", {"overall_risk": "high"}, "high"),  # 100
        (None, {"overall_risk": "medium"}, "low"),  # 25 -> low
    ],
)
def test_overall_level_from_combined_score(price, discrim, level):
    price_risks = [risk(price)] if price else []
    result = calculate_overall_risk_score(price_risks, discrim)
    assert result["risk_level"] == level


def test_total_score_is_capped_at_100():
    analysis = {"overall_risk": "high", "discriminatory_requirements": [{"severity": "high"}] * 5}
    assert calculate_overall_risk_score([risk("high")], analysis)["risk_score"] == 100


def test_breakdown_contains_all_inputs():
    prices, analysis, aggregate = [risk("low")], {"overall_risk": "low"}, {"risk_level": "low"}
    breakdown = calculate_overall_risk_score(prices, analysis, aggregate)["breakdown"]
    assert breakdown == {
        "price_deviations": prices,
        "discriminatory_analysis": analysis,
        "aggregate_risk": aggregate,
    }
