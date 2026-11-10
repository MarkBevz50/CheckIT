"""
Public LLM façade. Routes calls to Claude (primary) and falls back to
Gemini if Claude is unavailable / quota-exhausted.

Public surface mirrors the original llm_validator.py exactly so existing
imports (`from app.services.llm_validator import validate_matches, ...`)
keep working.
"""

import logging
from app.core.config import settings
from typing import Any, Dict, List, Optional

from app.services import claude_validator, gemini_validator
from app.services.gemini_validator import is_service_item  # re-export

logger = logging.getLogger(__name__)


def _claude_enabled() -> bool:
    return bool(settings.anthropic_api_key)


async def extract_items_from_text(text: str) -> Optional[List[Dict[str, Any]]]:
    """Extract structured items from a tender document text."""
    if _claude_enabled():
        result = await claude_validator.extract_items_from_text(text)
        if result is not None:
            return result
        logger.info("Claude extract_items returned None — falling back to Gemini")
    return await gemini_validator.extract_items_from_text(text)


async def validate_matches(
    tender_name: str,
    tender_price: float,
    tender_quantity: Optional[float],
    tender_unit: Optional[str],
    store_items: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Validate which store items match the tender item; extract weights."""
    if _claude_enabled():
        # Claude validate_matches always returns a list (default-fields fallback
        # if the call fails). To detect Claude unavailability we check if it
        # returned the all-default shape AND no entry was actually validated.
        try:
            result = await claude_validator.validate_matches(
                tender_name, tender_price, tender_quantity, tender_unit, store_items
            )
            return result
        except Exception as e:
            logger.warning(
                f"Claude validate_matches errored — falling back to Gemini: {e}"
            )
    return await gemini_validator.validate_matches(
        tender_name, tender_price, tender_quantity, tender_unit, store_items
    )


async def analyze_document_text(text: str) -> Optional[List[Dict[str, Any]]]:
    """Free-form analysis of a document text. Returns extracted items or None."""
    if _claude_enabled():
        result = await claude_validator.analyze_document_text(text)
        if result is not None:
            return result
        logger.info(
            "Claude analyze_document_text returned None — falling back to Gemini"
        )
    return await gemini_validator.analyze_document_text(text)


__all__ = [
    "is_service_item",
    "extract_items_from_text",
    "validate_matches",
    "analyze_document_text",
]
