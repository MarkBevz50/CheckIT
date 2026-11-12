"""
Claude-based LLM validator. Mirrors the public surface of llm_validator.py
(extract_items_from_text, validate_matches, analyze_document_text,
analyze_discriminatory_requirements) but routes through the Anthropic SDK.

Uses prompt caching on the stable system instructions of each prompt — the
heavy rule list is reused across many requests, only the per-call payload
(text/items) lives after the cache breakpoint.

Configured via env:
  ANTHROPIC_API_KEY       — required
  ANTHROPIC_BASE_URL      — proxy URL (e.g. https://llm-router.monobank.com.ua)
  ANTHROPIC_MODEL         — fast model for per-product validation (default haiku-4.5)
  ANTHROPIC_MODEL_SMART   — heavier model for document analysis (default sonnet-4.6)
"""

import json
import logging
from app.core.config import settings
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_client = None  # lazy-initialised AsyncAnthropic


def _get_client():
    """Lazy-init AsyncAnthropic. Returns None if SDK or API key is missing."""
    global _client
    if _client is not None:
        return _client

    api_key = settings.anthropic_api_key
    if not api_key:
        logger.info("ANTHROPIC_API_KEY not set — Claude validator disabled")
        return None

    try:
        import anthropic

        _client = anthropic.AsyncAnthropic(api_key=api_key)
        logger.info(
            f"Anthropic client initialised (fast={settings.llm_fast_model}, "
            f"smart={settings.llm_smart_model}, document_tier={settings.llm_document_tier})"
        )
        return _client
    except Exception as e:
        logger.warning(f"Failed to initialise Anthropic client: {e}")
        return None


def _model() -> str:
    """Fast model (per-product validation, classification)."""
    return settings.llm_fast_model


def _smart_model() -> str:
    return settings.llm_smart_model


def _document_model() -> str:
    """Model for document analysis: fast unless LLM_DOCUMENT_TIER=smart."""
    return _smart_model() if settings.llm_document_tier == "smart" else _model()


# max_tokens limits. Haiku 5.5's tokenizer yields ~30% more tokens than Haiku 4.5,
# so the previous 8000 / 2000 / 4000 were raised by that margin.
MAX_TOKENS_EXTRACT = 10500
MAX_TOKENS_VALIDATE = 2600
MAX_TOKENS_DISCRIM = 5200

# Prompts above this size use a pricier tier, so warn well before it (Haiku 5.5: >100k).
INPUT_TOKENS_WARN = 80_000


def _log_usage(label: str, message, max_tokens: int) -> None:
    """Log token usage and warn about truncated output or very large prompts."""
    usage = message.usage
    cache_read = usage.cache_read_input_tokens or 0
    cache_create = usage.cache_creation_input_tokens or 0
    total_input = usage.input_tokens + cache_read + cache_create
    logger.info(
        f"Claude {label}: cache_read={cache_read} cache_create={cache_create} "
        f"input={usage.input_tokens} output={usage.output_tokens}"
    )
    if message.stop_reason == "max_tokens":
        logger.warning(
            f"Claude {label}: output truncated at max_tokens={max_tokens} (response may be invalid JSON)"
        )
    if total_input > INPUT_TOKENS_WARN:
        logger.warning(
            f"Claude {label}: prompt is {total_input} tokens (> {INPUT_TOKENS_WARN}); "
            "above 100000 a higher price tier applies"
        )


def _is_quota_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return (
        "quota" in msg
        or "rate" in msg and "limit" in msg
        or "429" in msg
        or "resource_exhausted" in msg
    )


def _extract_text(message) -> str:
    """Pull plain text out of a Claude Message response."""
    parts = []
    for block in message.content:
        if getattr(block, "type", None) == "text":
            parts.append(block.text)
    return "".join(parts)


def _parse_json_response(text: str, expect_list: bool = True) -> Optional[Any]:
    """Parse a JSON list/dict from a Claude response, with regex fallback."""
    text = text.strip()
    # Strip ```json ... ``` fences if the model added them despite instructions
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

    try:
        data = json.loads(text)
        if expect_list and isinstance(data, list):
            return data
        if not expect_list and isinstance(data, dict):
            return data
        return data
    except json.JSONDecodeError:
        pass

    pattern = r"\[.*\]" if expect_list else r"\{.*\}"
    match = re.search(pattern, text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    logger.warning(f"Failed to parse Claude JSON response: {text[:200]}")
    return None


# ─── Stable system prompts (cached) ──────────────────────────────────
#
# These are the prefix-stable parts that get a cache_control breakpoint.
# Volatile per-request data lives in the user message after the breakpoint.

_VALIDATE_SYSTEM = """Ти — суворий експерт з порівняння товарів для тендерних закупівель в Україні.

ЗАДАЧА: Визначити, чи кожен знайдений товар є ТИМ САМИМ конкретним продуктом що й тендерний товар.

ПРАВИЛА ОЦІНКИ is_relevant — будь ДУЖЕ СУВОРИМ:

RELEVANT (true) — ТІЛЬКИ якщо товар є тим самим конкретним продуктом або його прямим аналогом:
- "Масло вершкове 72%" ↔ "Масло вершкове Селянське 72.5%" → true (той самий тип, схожі характеристики)
- "Папір А4 500 аркушів" ↔ "Папір офісний А4 80г/м2" → true (той самий тип товару)
- "Цукор білий 1кг" ↔ "Цукор білий кристалічний" → true

NOT RELEVANT (false) — якщо:
- Товари мають спільні слова але це РІЗНІ категорії: "Бензин А-95" ↔ "Ареометр для бензину" → false
- Послуга vs товар: "Послуги з харчування" ↔ "Засіб для миття посуду" → false
- Різний тип послуги: "Послуги з харчування" ↔ "Послуга з параметризації лічильників" → false
- Загальне слово збігається але продукт інший: "Набір пінцетів" ↔ "Послуги харчування" → false
- Аксесуар/інструмент для товару а не сам товар: "Кава мелена" ↔ "Кавомолка" → false
- Цемент ↔ Бетон → false (різні матеріали)

При сумніві — став false. Краще пропустити підходящий товар, ніж включити непідходящий.

Для кожного товару також визнач:
- "store_weight_g" (number|null): вага/об'єм товару з НАЗВИ МАГАЗИНУ в грамах/мл. "500г"→500, "1кг"→1000, "1.5л"→1500, "250мл"→250. null якщо не вказано.
- "tender_weight_g" (number|null): вага/об'єм з НАЗВИ ТЕНДЕРУ в грамах/мл. null якщо не вказано.

Відповідай ТІЛЬКИ JSON-масивом без коментарів і без markdown-обгортки:
[{"index": 1, "is_relevant": false, "store_weight_g": null, "tender_weight_g": null}, ...]"""


_EXTRACT_SYSTEM = """Ти — експерт з аналізу тендерної документації в Україні.

ЗАДАЧА: Знайди у тексті специфікації перелік товарів/послуг із цінами та кількостями.

Поверни JSON-масив об'єктів із полями:
- "name" (string) — назва товару/послуги
- "quantity" (number) — кількість
- "unit_name" (string) — одиниця виміру (шт, кг, л, упак, тощо)
- "unit_price" (number) — ціна за одиницю
- "total_price" (number) — загальна вартість позиції

ПРАВИЛА:
- Використовуй ціну БЕЗ ПДВ, якщо вказано обидві
- Повертай числа, а не рядки
- Пропускай рядки з підсумками, заголовками, нумерацією
- Якщо товарів не знайдено — поверни порожній масив []
- Не вигадуй дані — витягуй тільки те, що є в тексті

Відповідай ТІЛЬКИ JSON-масивом без коментарів і без markdown-обгортки."""


_DISCRIM_SYSTEM = """Ти — експерт з аналізу тендерної документації України на предмет корупційних ризиків.

ЗАДАЧА: знайти у тексті дискримінаційні вимоги, що можуть вказувати на завчасно обраного постачальника.

ШУКАЙ ТАКІ ОЗНАКИ:
1. Надмірно специфічні вимоги до бренду / моделі / артикула
2. Унікальні комбінації характеристик (під одного виробника)
3. Вимога до точного географічного розташування виробництва
4. Несуттєві вимоги до сертифікатів / ліцензій, які мають мало хто
5. Нереалістичні строки виконання (фавор тих, хто вже готувався)
6. Незвично короткий період подачі пропозицій
7. Складні / непрозорі формули оцінки

Поверни JSON-об'єкт у форматі:
{
  "overall_risk": "high" | "medium" | "low",
  "discriminatory_requirements": [
    {
      "type": "коротка назва (brand_specificity, geographic, certification, тощо)",
      "severity": "high" | "medium" | "low",
      "text": "цитата з тексту",
      "explanation": "пояснення українською: чому це дискримінаційно"
    }
  ]
}

Якщо ризиків не виявлено — поверни {"overall_risk": "low", "discriminatory_requirements": []}.
Відповідай ТІЛЬКИ JSON-об'єктом без коментарів і без markdown-обгортки."""


# ─── Public API: extract items ─────────────────────────────────────────


async def extract_items_from_text(text: str) -> Optional[List[Dict[str, Any]]]:
    """Extract structured tender items from a document text via Claude."""
    client = _get_client()
    if not client:
        return None

    try:
        message = await client.messages.create(
            model=_document_model(),
            max_tokens=MAX_TOKENS_EXTRACT,
            system=[
                {
                    "type": "text",
                    "text": _EXTRACT_SYSTEM,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[
                {
                    "role": "user",
                    "content": f"Текст документації:\n\n{text[:30000]}",
                }
            ],
        )
    except Exception as e:
        if _is_quota_error(e):
            logger.warning(f"Claude rate-limited on extract_items_from_text: {e}")
        else:
            logger.error(f"Claude failed on extract_items_from_text: {e}")
        return None

    raw = _extract_text(message)
    _log_usage("extract_items", message, MAX_TOKENS_EXTRACT)
    data = _parse_json_response(raw, expect_list=True)
    if data is None:
        return None
    logger.info(f"Claude extracted {len(data)} items from text")
    return data


# ─── Public API: validate store matches ────────────────────────────────

# Tender items matching these patterns are services, not physical products
_SERVICE_PATTERNS = re.compile(
    r"(?i)^послуг[иіа]\b|"
    r"\bпослуг[иіа]\s+з\b|"
    r"\bобслуговування\b|"
    r"\bремонт\b.*\bобладнання\b|"
    r"\bоренд[аи]\b|"
    r"\bперевезення\b|"
    r"\bтранспортування\b|"
    r"\bстрахування\b|"
    r"\bнавчання\b|"
    r"\bпроектування\b|"
    r"\bмонтаж\b|"
    r"\bдемонтаж\b"
)


def is_service_item(name: str) -> bool:
    """Check if a tender item is a service rather than a physical product."""
    return bool(_SERVICE_PATTERNS.search(name))


def _build_validate_user_message(
    tender_name: str,
    tender_price: float,
    tender_quantity: Optional[float],
    tender_unit: Optional[str],
    store_items: List[Dict[str, Any]],
) -> str:
    items_text = ""
    for i, item in enumerate(store_items, 1):
        price = item.get("price_on_sale") or item.get("price") or "?"
        items_text += (
            f"{i}. [{item.get('store_name', '?')}] "
            f'"{item.get("title", "?")}" — {price} грн\n'
        )

    qty_info = ""
    if tender_quantity and tender_unit:
        qty_info = f"\nКількість: {tender_quantity} {tender_unit}"

    return (
        f'Тендерний товар: "{tender_name}"\n'
        f"Ціна за одиницю: {tender_price} грн{qty_info}\n\n"
        f"Знайдені товари в магазинах:\n{items_text}"
    )


def _set_default_fields(store_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Set default LLM fields when validation is skipped (Claude unavailable)."""
    for item in store_items:
        item["is_relevant"] = True
        item["store_weight_g"] = None
        item["tender_weight_g"] = None
        item["price_per_unit"] = None
        item["tender_price_per_unit"] = None
    return store_items


async def validate_matches(
    tender_name: str,
    tender_price: float,
    tender_quantity: Optional[float],
    tender_unit: Optional[str],
    store_items: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Use Claude to filter store matches + extract weights for normalisation.

    Returns store_items enriched with is_relevant, store_weight_g, tender_weight_g,
    price_per_unit, tender_price_per_unit. Falls back to "all relevant" if Claude
    is unavailable (better to show something with a warning than nothing).
    """
    client = _get_client()
    if client is None or not store_items:
        return _set_default_fields(store_items)

    user_message = _build_validate_user_message(
        tender_name, tender_price, tender_quantity, tender_unit, store_items
    )

    try:
        message = await client.messages.create(
            model=_model(),
            max_tokens=MAX_TOKENS_VALIDATE,
            system=[
                {
                    "type": "text",
                    "text": _VALIDATE_SYSTEM,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user_message}],
        )
    except Exception as e:
        if _is_quota_error(e):
            logger.warning(
                f"Claude rate-limited validating '{tender_name[:60]}': {e}"
            )
        else:
            logger.warning(f"Claude failed validating '{tender_name[:60]}': {e}")
        return _set_default_fields(store_items)

    _log_usage(f"validate '{tender_name[:60]}'", message, MAX_TOKENS_VALIDATE)

    raw = _extract_text(message)
    llm_results = _parse_json_response(raw, expect_list=True)
    if llm_results is None:
        return _set_default_fields(store_items)

    llm_map = {}
    for entry in llm_results:
        if isinstance(entry, dict):
            idx = entry.get("index")
            if idx is not None:
                llm_map[idx] = entry

    enriched = []
    for i, item in enumerate(store_items, 1):
        llm_entry = llm_map.get(i, {})
        is_relevant = llm_entry.get("is_relevant", False)
        store_weight_g = llm_entry.get("store_weight_g")
        tender_weight_g = llm_entry.get("tender_weight_g")

        effective_price = (
            float(item.get("price_on_sale"))
            if item.get("price_on_sale")
            else float(item.get("price"))
            if item.get("price")
            else None
        )

        price_per_unit = None
        tender_price_per_unit = None
        if store_weight_g and store_weight_g > 0 and effective_price is not None:
            price_per_unit = round(effective_price / store_weight_g * 1000, 2)
        if tender_weight_g and tender_weight_g > 0 and tender_price:
            tender_price_per_unit = round(tender_price / tender_weight_g * 1000, 2)

        item["is_relevant"] = is_relevant
        item["store_weight_g"] = store_weight_g
        item["tender_weight_g"] = tender_weight_g
        item["price_per_unit"] = price_per_unit
        item["tender_price_per_unit"] = tender_price_per_unit
        enriched.append(item)

    relevant_count = sum(1 for e in enriched if e["is_relevant"])
    logger.info(
        f"Claude validation for '{tender_name[:60]}': "
        f"{relevant_count}/{len(enriched)} relevant"
    )
    return enriched


# ─── Public API: discriminatory requirements ───────────────────────────


async def analyze_discriminatory_requirements(
    specification_text: str,
) -> Optional[Dict[str, Any]]:
    """Analyse a tender specification for discriminatory requirements."""
    client = _get_client()
    if not client:
        return None

    try:
        message = await client.messages.create(
            model=_document_model(),
            max_tokens=MAX_TOKENS_DISCRIM,
            system=[
                {
                    "type": "text",
                    "text": _DISCRIM_SYSTEM,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[
                {
                    "role": "user",
                    "content": f"Текст специфікації:\n\n{specification_text[:30000]}",
                }
            ],
        )
    except Exception as e:
        if _is_quota_error(e):
            logger.warning(f"Claude rate-limited on discriminatory analysis: {e}")
        else:
            logger.error(f"Claude failed on discriminatory analysis: {e}")
        return None

    _log_usage("discrim", message, MAX_TOKENS_DISCRIM)

    raw = _extract_text(message)
    return _parse_json_response(raw, expect_list=False)


# ─── Public API: free-form document text analysis ──────────────────────


async def analyze_document_text(text: str) -> Optional[List[Dict[str, Any]]]:
    """Free-form analysis of tender documentation text. Same return shape as
    extract_items_from_text but with looser specifications."""
    return await extract_items_from_text(text)
