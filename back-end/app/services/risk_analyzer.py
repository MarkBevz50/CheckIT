"""
AI-powered corruption risk analysis for tenders.

Provides:
- Price deviation analysis (tender price vs market median)
- Discriminatory requirements detection via Gemini LLM
- Overall risk score calculation
"""

import json
import logging
from app.core.config import settings
import re
import statistics
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def calculate_price_deviation(
    tender_items: List[Dict[str, Any]],
    matched_items: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Compare tender unit prices with median market prices from store data.

    For each tender item that has store matches, compute:
      - median_market_price: median of effective store prices
      - deviation_pct: percentage difference (positive = tender is more expensive)
      - risk_level: "high" if deviation > 20%, "medium" if > 10%, "low" otherwise

    Returns a list of per-item risk assessments.
    """
    results = []

    for group in matched_items:
        tender_item = group.get("tender_item", {})
        matches = group.get("matches", [])
        item_name = tender_item.get("name", "")
        price_source = tender_item.get("price_source", "tender")

        # Market-estimated prices are themselves derived from store listings, so
        # comparing them against the store median is tautological. Skip them
        # from risk scoring but keep a visible placeholder in the breakdown so
        # the UI can show why no score was computed.
        if price_source == "market_estimate":
            results.append({
                "item_name": item_name,
                "tender_price": tender_item.get("unit_price"),
                "median_market_price": None,
                "deviation_pct": None,
                "risk_level": "excluded",
                "price_source": price_source,
                "reason": "Ціна оцінена з ринку — виключено з ризик-аналізу",
            })
            continue

        if price_source == "unknown":
            results.append({
                "item_name": item_name,
                "tender_price": None,
                "median_market_price": None,
                "deviation_pct": None,
                "risk_level": "excluded",
                "price_source": price_source,
                "reason": "Ціна не вказана — виключено з ризик-аналізу",
            })
            continue

        tender_price = None
        raw = tender_item.get("unit_price")
        if raw is not None:
            try:
                tender_price = float(raw)
            except (ValueError, TypeError):
                pass

        if not tender_price or tender_price <= 0:
            results.append({
                "item_name": item_name,
                "tender_price": tender_price,
                "median_market_price": None,
                "deviation_pct": None,
                "risk_level": "unknown",
                "reason": "Тендерна ціна відсутня або нульова",
            })
            continue

        if not matches:
            results.append({
                "item_name": item_name,
                "tender_price": tender_price,
                "median_market_price": None,
                "deviation_pct": None,
                "risk_level": "unknown",
                "reason": "Немає ринкових даних для порівняння",
            })
            continue

        # Collect effective prices from matched store products
        market_prices = []
        for m in matches:
            ep = m.get("price_on_sale") or m.get("price")
            if ep is not None:
                try:
                    market_prices.append(float(ep))
                except (ValueError, TypeError):
                    pass

        if not market_prices:
            results.append({
                "item_name": item_name,
                "tender_price": tender_price,
                "median_market_price": None,
                "deviation_pct": None,
                "risk_level": "unknown",
                "reason": "Жоден ринковий товар не має ціни",
            })
            continue

        median_price = statistics.median(market_prices)
        if median_price <= 0:
            results.append({
                "item_name": item_name,
                "tender_price": tender_price,
                "median_market_price": median_price,
                "deviation_pct": None,
                "risk_level": "unknown",
                "reason": "Медіанна ринкова ціна нульова",
            })
            continue

        deviation_pct = round((tender_price - median_price) / median_price * 100, 1)

        if abs(deviation_pct) > 20:
            risk_level = "high"
        elif abs(deviation_pct) > 10:
            risk_level = "medium"
        else:
            risk_level = "low"

        results.append({
            "item_name": item_name,
            "tender_price": tender_price,
            "median_market_price": round(median_price, 2),
            "deviation_pct": deviation_pct,
            "risk_level": risk_level,
            "reason": (
                f"Тендерна ціна {'вище' if deviation_pct > 0 else 'нижче'} "
                f"ринкової на {abs(deviation_pct)}%"
            ),
        })

    return results


async def analyze_discriminatory_requirements(specification_text: str) -> Optional[Dict[str, Any]]:
    """Detect potentially discriminatory requirements in tender specs.

    Tries Claude first; falls back to Gemini on failure / unavailability.
    Looks for requirements that may point to a specific supplier:
    - Overly specific brand/model requirements
    - Unique technical parameters only one vendor satisfies
    - Unusual packaging, color, or certification requirements

    Returns dict with findings or None if all LLMs are unavailable.
    """
    if not specification_text or len(specification_text.strip()) < 50:
        return {
            "discriminatory_requirements": [],
            "summary": "Текст специфікації занадто короткий для аналізу",
            "overall_risk": "low",
        }

    # Primary: Claude (cached system prompt)
    if settings.anthropic_api_key:
        from app.services import claude_validator
        result = await claude_validator.analyze_discriminatory_requirements(
            specification_text
        )
        if result is not None:
            return result
        logger.info(
            "Claude discriminatory analysis returned None — falling back to Gemini"
        )

    # Fallback: Gemini (legacy path)
    from app.services.gemini_validator import _get_model

    model = _get_model()
    if not model:
        logger.warning(
            "Neither Claude nor Gemini available — discriminatory analysis skipped"
        )
        return None

    prompt = f"""Ти — експерт з аналізу тендерної документації в Україні на предмет можливих корупційних ризиків.

ЗАДАЧА: Проаналізуй текст тендерної специфікації та знайди вимоги, які можуть вказувати на конкретного постачальника або обмежувати конкуренцію.

Шукай наступні ознаки:
1. Вказівка конкретного бренду/виробника без формулювання "або еквівалент"
2. Надмірно специфічні технічні параметри (наприклад, точний відтінок кольору, специфічна форма кнопки)
3. Вимоги до сертифікації, якою володіє лише один постачальник
4. Нестандартні вимоги до пакування або маркування
5. Необґрунтовано короткі терміни поставки
6. Вимоги до досвіду, що відсікають більшість учасників
7. Посилання на конкретні ТУ замість ДСТУ/ГОСТ

Поверни JSON об'єкт:
{{
  "discriminatory_requirements": [
    {{
      "text": "цитата з тексту",
      "type": "brand_lock|specific_parameter|certification|packaging|deadline|experience|other",
      "severity": "high|medium|low",
      "explanation": "чому це може бути дискримінаційним"
    }}
  ],
  "summary": "загальний висновок про рівень ризику дискримінації",
  "overall_risk": "high|medium|low"
}}

Якщо дискримінаційних вимог не знайдено — поверни порожній масив discriminatory_requirements з overall_risk = "low".

Текст специфікації:
{specification_text[:25000]}"""

    try:
        response = await model.generate_content_async(prompt)
        logger.info(f"Gemini discriminatory analysis response: {response.text[:300]}")

        try:
            data = json.loads(response.text)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass

        match = re.search(r"\{.*\}", response.text, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group())
                if isinstance(data, dict):
                    return data
            except json.JSONDecodeError:
                pass

        logger.warning(
            f"Could not parse Gemini discriminatory analysis: {response.text[:200]}"
        )
        return None

    except Exception as e:
        logger.error(f"Gemini discriminatory analysis failed: {e}")
        return None


def calculate_aggregate_risk(
    matched_items: List[Dict[str, Any]],
    tender_total: Optional[float],
) -> Optional[Dict[str, Any]]:
    """Compare the tender's headline budget against the sum of market estimates.

    Useful when individual unit prices are missing from the document and the
    only signal we have is the global ``total_amount`` / ``expected_cost``.
    Returns a single risk record describing how the tender budget aligns with
    the market — or ``None`` if there's no usable budget or no market data.
    """
    if not tender_total or tender_total <= 0:
        return None

    market_total = 0.0
    items_with_estimate = 0
    items_total = 0
    for group in matched_items:
        items_total += 1
        tender_item = group.get("tender_item", {})
        matches = group.get("matches", [])
        try:
            qty = float(tender_item.get("quantity") or 0)
        except (ValueError, TypeError):
            qty = 0
        if qty <= 0:
            continue
        # Build a price for this item: prefer the cheapest validated match
        prices = []
        for m in matches:
            ep = m.get("price_on_sale") or m.get("price")
            try:
                if ep is not None:
                    prices.append(float(ep))
            except (ValueError, TypeError):
                pass
        if not prices:
            continue
        items_with_estimate += 1
        market_total += statistics.median(prices) * qty

    if market_total <= 0 or items_with_estimate == 0:
        return None

    coverage = items_with_estimate / items_total if items_total else 0
    deviation_pct = round((tender_total - market_total) / market_total * 100, 1)
    if abs(deviation_pct) > 25:
        risk_level = "high"
    elif abs(deviation_pct) > 12:
        risk_level = "medium"
    else:
        risk_level = "low"

    if deviation_pct > 0:
        reason = (
            f"Тендерний бюджет на {abs(deviation_pct)}% вищий за сумарну "
            f"ринкову оцінку"
        )
    elif deviation_pct < 0:
        reason = (
            f"Тендерний бюджет на {abs(deviation_pct)}% нижчий за сумарну "
            f"ринкову оцінку"
        )
    else:
        reason = "Тендерний бюджет співпадає з ринковою оцінкою"

    return {
        "tender_total": round(tender_total, 2),
        "market_total": round(market_total, 2),
        "deviation_pct": deviation_pct,
        "risk_level": risk_level,
        "items_with_estimate": items_with_estimate,
        "items_total": items_total,
        "coverage_pct": round(coverage * 100, 1),
        "reason": reason,
    }


def calculate_overall_risk_score(
    price_risks: List[Dict[str, Any]],
    discriminatory_analysis: Optional[Dict[str, Any]] = None,
    aggregate_risk: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Calculate an overall risk score (0-100) based on price and discriminatory analyses.

    Scoring:
    - Price deviation contributes up to 50 points
    - Discriminatory requirements contribute up to 50 points
    - When per-item prices are missing, falls back to ``aggregate_risk`` —
      the tender budget vs. the sum of market estimates.

    Returns a summary dict with score, level, and breakdown.
    """
    price_score = 0
    excluded_count = 0
    if price_risks:
        high_count = sum(1 for r in price_risks if r.get("risk_level") == "high")
        medium_count = sum(1 for r in price_risks if r.get("risk_level") == "medium")
        total_assessed = sum(1 for r in price_risks if r.get("risk_level") in ("high", "medium", "low"))
        excluded_count = sum(1 for r in price_risks if r.get("risk_level") == "excluded")

        if total_assessed > 0:
            price_score = min(50, round(
                (high_count * 50 + medium_count * 25) / total_assessed
            ))

    # Fallback: if we have no per-item assessment at all, derive the price
    # score from the aggregate budget vs. market estimate.
    if price_score == 0 and aggregate_risk:
        agg_level = aggregate_risk.get("risk_level")
        if agg_level == "high":
            price_score = 40
        elif agg_level == "medium":
            price_score = 20
        elif agg_level == "low":
            price_score = 5

    discrim_score = 0
    if discriminatory_analysis:
        overall = discriminatory_analysis.get("overall_risk", "low")
        if overall == "high":
            discrim_score = 50
        elif overall == "medium":
            discrim_score = 25

        # Additional per-finding scoring
        findings = discriminatory_analysis.get("discriminatory_requirements", [])
        high_findings = sum(1 for f in findings if f.get("severity") == "high")
        medium_findings = sum(1 for f in findings if f.get("severity") == "medium")
        finding_score = min(50, high_findings * 15 + medium_findings * 8)
        discrim_score = max(discrim_score, finding_score)

    total_score = min(100, price_score + discrim_score)

    if total_score >= 60:
        level = "high"
    elif total_score >= 30:
        level = "medium"
    else:
        level = "low"

    return {
        "risk_score": total_score,
        "risk_level": level,
        "price_risk_score": price_score,
        "discriminatory_risk_score": discrim_score,
        "excluded_items_count": excluded_count,
        "breakdown": {
            "price_deviations": price_risks,
            "discriminatory_analysis": discriminatory_analysis,
            "aggregate_risk": aggregate_risk,
        },
    }
