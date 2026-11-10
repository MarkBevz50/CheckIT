import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, status, Depends, Query
from pydantic import BaseModel
import requests
from datetime import datetime
from app.core.config import settings
from app.database import get_db
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.models.model import User
from app.models.tender import Tender, TenderItem

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/assistant", tags=["Assistant"])

# Hugging Face API ключ
HUGGINGFACE_API_KEY = settings.huggingface_api_key or None
HUGGINGFACE_MODEL_URL = "https://api-inference.huggingface.co/models/HuggingFaceH4/zephyr-7b-beta"

class AssistantRequest(BaseModel):
    task: str
    message: Optional[str] = None

class AssistantResponse(BaseModel):
    status: str
    response: Optional[str] = None
    timestamp: str
    risk_score: Optional[int] = None
    risk_details: Optional[Dict[str, Any]] = None

def query_huggingface_api(message: str) -> str:
    """
    Використовує API Hugging Face для генерації відповіді.
    """
    headers = {"Authorization": f"Bearer {HUGGINGFACE_API_KEY}"}
    prompt = f"""<|system|>You are an assistant for the CheckIT project, a platform designed to analyze and compare tender proposals, both public and private. Your role is to provide accurate and detailed answers about the project's functionality, features, and technical aspects. The platform includes features like user registration, CRUD operations, XPath analysis for web scraping, AI-powered assistance, and integration with Prozorro for tender analysis. If the user's question is unrelated to the project, politely inform them that you can only assist with questions about CheckIT. Use Ukrainian to answer(Not Russian)<|endoftext|><|user|>{message}<|endoftext|><|assistant|>"""
    try:
        response = requests.post(
            HUGGINGFACE_MODEL_URL,
            headers=headers,
            json={
                "inputs": prompt,
                "parameters": {
                    "max_new_tokens": 100,
                    "temperature": 0.7,
                    "return_full_text": False
                }
            },
            timeout=10
        )

        if response.status_code != 200:
            raise Exception(f"Помилка API Hugging Face: {response.status_code}, {response.text}")

        result = response.json()

        # Перевіряємо, чи результат є списком
        if isinstance(result, list) and len(result) > 0:
            return result[0].get("generated_text", "Не вдалося згенерувати відповідь.")
        else:
            raise Exception("Неправильний формат відповіді від Hugging Face API.")

    except requests.exceptions.Timeout:
        raise Exception("Запит до Hugging Face API перевищив час очікування.")
    except Exception as e:
        raise Exception(f"Помилка при використанні Hugging Face API: {str(e)}")

@router.post("/perform-task", response_model=AssistantResponse)
async def perform_task(request: AssistantRequest, db: AsyncSession = Depends(get_db)):
    """
    Багатофункціональний помічник для виконання завдань.
    """
    try:
        task = request.task.lower()
        message = request.message

        if task == "time":
            # Повертає поточний час
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            return AssistantResponse(
                status="success",
                response=f"Поточний час: {current_time}",
                timestamp=current_time
            )

        elif task == "chat":
            # Використовує Hugging Face API для відповіді на запит
            if not message:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Для завдання 'chat' необхідно надати повідомлення."
                )

            try:
                response_text = query_huggingface_api(message)
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Помилка при використанні Hugging Face API: {str(e)}"
                )

            return AssistantResponse(
                status="success",
                response=response_text,
                timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            )

        elif task == "help":
            # Повертає список доступних завдань
            return AssistantResponse(
                status="success",
                response=(
                    "Доступні завдання:\n"
                    "- `time`: Повертає поточний час.\n"
                    "- `chat`: Відповідає на ваші запити за допомогою AI.\n"
                    "- `user_count`: Повертає кількість зареєстрованих користувачів.\n"
                    "- `help`: Показує список доступних завдань."
                ),
                timestamp=datetime.now().strftime("%Y-%м-%d %H:%М:%S")
            )

        elif task == "user_count":
            # Повертає кількість зареєстрованих користувачів
            result = await db.execute(select(User))
            users = result.scalars().all()
            user_count = len(users)
            return AssistantResponse(
                status="success",
                response=f"Кількість зареєстрованих користувачів на нашому сервісі: {user_count}",
                timestamp=datetime.now().strftime("%Y-%м-%d %H:%М:%S")
            )

        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Невідоме завдання: {task}. Використовуйте 'help' для списку доступних завдань."
            )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Помилка сервера: {str(e)}"
        )


@router.post("/analyze-risks")
async def analyze_risks(
    tender_id: int = Query(..., description="ID тендера для аналізу ризиків"),
    stores: str = Query(default="rozetka,silpo,epicentr", description="Магазини для порівняння цін"),
    db: AsyncSession = Depends(get_db),
):
    """Analyze corruption risks for a tender: price deviations + discriminatory requirements."""
    from app.routers.authorization import get_current_user
    from app.services.risk_analyzer import (
        calculate_price_deviation,
        calculate_aggregate_risk,
        analyze_discriminatory_requirements,
        calculate_overall_risk_score,
    )
    from app.services.parser_service import search_and_validate_items
    from app.prozorro_functionality.prozorro import get_contract, get_document_urls, parse_documents

    # Fetch tender
    result = await db.execute(select(Tender).where(Tender.id == tender_id))
    tender = result.scalar_one_or_none()
    if not tender:
        raise HTTPException(status_code=404, detail="Тендер не знайдено")

    store_list = [s.strip() for s in stores.split(",") if s.strip()]

    # Convert items to dicts
    items_for_search = [
        {
            "name": item.name,
            "quantity": item.quantity,
            "unit_name": item.unit_name,
            "unit_price": item.unit_price,
            "price_source": item.price_source,
        }
        for item in tender.items
    ]

    # 1. Price comparison
    try:
        matched_items = await search_and_validate_items(
            items=items_for_search,
            stores=store_list,
            n=3,
        )
        price_risks = calculate_price_deviation(items_for_search, matched_items)
    except Exception as e:
        logger.error(f"Price comparison failed for tender #{tender_id}: {e}")
        price_risks = []
        matched_items = []

    # 1b. Aggregate budget vs market — useful when per-item prices are missing
    tender_total = tender.total_amount or tender.expected_cost
    aggregate_risk = calculate_aggregate_risk(matched_items, tender_total)

    # 2. Discriminatory requirements analysis
    discrim_analysis = None
    if tender.prozorro_id:
        try:
            hex_id = tender.prozorro_id
            if hex_id.upper().startswith("UA-"):
                from app.routers.prozorro_router import convert_ua_to_hex_id
                hex_id = await convert_ua_to_hex_id(hex_id.upper())

            contract = get_contract(hex_id)
            documents = contract.get("documents", []) if contract else []
            if documents:
                doc_refs = get_document_urls(documents)
                items_from_docs = await parse_documents(doc_refs)
                # Combine all text from items for analysis
                spec_text = " ".join(
                    str(item.get("name", "")) + " " + str(item.get("specifications", ""))
                    for item in items_from_docs
                )
                if spec_text.strip():
                    discrim_analysis = await analyze_discriminatory_requirements(spec_text)
        except Exception as e:
            logger.warning(f"Discriminatory analysis failed for tender #{tender_id}: {e}")

    # 3. Overall risk score
    risk_result = calculate_overall_risk_score(price_risks, discrim_analysis, aggregate_risk)

    return AssistantResponse(
        status="success",
        response=f"Аналіз ризиків для тендера '{tender.title}' завершено. Рівень ризику: {risk_result['risk_level']}",
        timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        risk_score=risk_result["risk_score"],
        risk_details=risk_result,
    )