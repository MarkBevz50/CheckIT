"""
Automatic tender type classifier.

Uses Gemini LLM for semantic classification with regex fallback
when the model is unavailable.
"""

from app.core.config import settings
import asyncio
import json
import logging
import re
from typing import Any, Dict, List, Optional

from app.schemas.tender import TenderType
from app.services.llm_validator import is_service_item

logger = logging.getLogger(__name__)

_WORK_PATTERNS = re.compile(
    r'(?i)\bбудівництво\b|'
    r'\bреконструкція\b|'
    r'\bкапітальний\s+ремонт\b|'
    r'\bпроектн[іи]\b|'
    r'\bпроектування\b|'
    r'\bмонтажн[іи]\b|'
    r'\bбудівельн[іи]\b|'
    r'\bземляні роботи\b|'
    r'\bпрокладання\b'
)


def _classify_by_regex(items: List[Dict[str, Any]]) -> TenderType:
    """Classify tender type based on item names using regex patterns (fallback)."""
    if not items:
        return TenderType.PRODUCT

    service_count = 0
    work_count = 0
    product_count = 0

    for item in items:
        name = item.get("name", "") or item.get("description", "") or ""
        if _WORK_PATTERNS.search(name):
            work_count += 1
        elif is_service_item(name):
            service_count += 1
        else:
            product_count += 1

    if work_count > product_count and work_count >= service_count:
        return TenderType.WORK
    if service_count > product_count:
        return TenderType.SERVICE
    if service_count > 0 and product_count > 0:
        return TenderType.MIXED
    return TenderType.PRODUCT


async def _classify_by_llm(items: List[Dict[str, Any]]) -> Optional[TenderType]:
    """Use an LLM to semantically classify tender type from item names and CPV codes.

    Tries Claude first; falls back to Gemini if Claude is unavailable.
    """
    import os

    # Build item descriptions for the prompt
    items_text = ""
    for i, item in enumerate(items[:30], 1):  # Limit to 30 items
        name = item.get("name", "") or item.get("description", "") or ""
        cpv = item.get("dk_code", "") or item.get("cpv", "") or ""
        unit = item.get("unit_name", "")
        cpv_part = f" (CPV: {cpv})" if cpv else ""
        unit_part = f" [{unit}]" if unit else ""
        items_text += f"{i}. {name}{cpv_part}{unit_part}\n"

    if not items_text.strip():
        return None

    system_prompt = """Ти — експерт з класифікації тендерних закупівель в Україні.

ЗАДАЧА: Визнач тип тендера на основі переліку товарів/послуг/робіт.

Типи тендерів:
- "product" — закупівля фізичних товарів (продукти харчування, обладнання, канцтовари, матеріали тощо)
- "service" — закупівля послуг (обслуговування, оренда, перевезення, страхування, консалтинг тощо)
- "work" — будівельні/монтажні/ремонтні роботи (будівництво, реконструкція, капітальний ремонт тощо)
- "mixed" — якщо тендер містить позиції різних типів (наприклад, товари + послуги)

Враховуй коди CPV (ДК 021), якщо вони є:
- CPV 44-45: будівельні матеріали та роботи
- CPV 50-51: ремонт та встановлення
- CPV 60-66: транспортні послуги, фінансові послуги
- CPV 70-79: послуги (нерухомість, IT, юридичні тощо)
- CPV 09-43: товари

Відповідай ТІЛЬКИ одним словом з варіантів: product, service, work, mixed"""

    type_map = {
        "product": TenderType.PRODUCT,
        "service": TenderType.SERVICE,
        "work": TenderType.WORK,
        "mixed": TenderType.MIXED,
    }

    # ── Primary: Claude ────────────────────────────────────────────────
    if settings.anthropic_api_key:
        try:
            from app.services import claude_validator

            client = claude_validator._get_client()
            if client is not None:
                msg = await client.messages.create(
                    model=claude_validator._model(),
                    max_tokens=10,
                    system=[
                        {
                            "type": "text",
                            "text": system_prompt,
                            "cache_control": {"type": "ephemeral"},
                        }
                    ],
                    messages=[
                        {
                            "role": "user",
                            "content": f"Перелік позицій тендера:\n{items_text}",
                        }
                    ],
                )
                result_text = "".join(
                    b.text for b in msg.content if getattr(b, "type", None) == "text"
                ).strip().lower().strip('"\'.,! ')
                logger.info(f"Claude classification result: '{result_text}'")
                mapped = type_map.get(result_text)
                if mapped is not None:
                    return mapped
                logger.info("Claude returned non-mapped value — falling back to Gemini")
        except Exception as e:
            logger.warning(f"Claude classification failed — falling back to Gemini: {e}")

    # ── Fallback: Gemini ───────────────────────────────────────────────
    from app.services.gemini_validator import _get_model

    model = _get_model()
    if not model:
        return None

    prompt = f"""{system_prompt}

Перелік позицій тендера:
{items_text}"""

    try:
        response = await model.generate_content_async(prompt)
        result_text = response.text.strip().lower().strip('"\'.,! ')
        logger.info(f"Gemini classification result: '{result_text}'")
        return type_map.get(result_text)
    except Exception as e:
        logger.warning(f"Gemini classification failed: {e}")
        return None


def classify_tender_type(items: List[Dict[str, Any]]) -> TenderType:
    """Classify tender type based on item names.

    Tries Gemini LLM first for semantic classification,
    falls back to regex patterns if unavailable.
    """
    if not items:
        return TenderType.PRODUCT

    # Try LLM classification
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # We're already in an async context — can't use asyncio.run()
        # Fall back to regex
        logger.info("Async loop running, using regex classifier")
        return _classify_by_regex(items)

    try:
        llm_result = asyncio.run(_classify_by_llm(items))
        if llm_result is not None:
            logger.info(f"LLM classified tender as: {llm_result.value}")
            return llm_result
    except Exception as e:
        logger.warning(f"LLM classification error, falling back to regex: {e}")

    # Fallback to regex
    return _classify_by_regex(items)


async def classify_tender_type_async(items: List[Dict[str, Any]]) -> TenderType:
    """Async version of classify_tender_type. Preferred when called from async context."""
    if not items:
        return TenderType.PRODUCT

    llm_result = await _classify_by_llm(items)
    if llm_result is not None:
        logger.info(f"LLM classified tender as: {llm_result.value}")
        return llm_result

    return _classify_by_regex(items)
