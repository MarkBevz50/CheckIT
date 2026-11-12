import logging
from io import BytesIO
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Depends, File, UploadFile, Query
from fastapi.middleware.cors import CORSMiddleware
from openpyxl import load_workbook
from pydantic import BaseModel

from app.routers.prozorro_router import prozorro_router
from app.routers.tender_router import tender_router
from app.routers.ai_assistant import router as assistant_router
from app.services.parser_service import search_products_async, get_available_stores

# Ensure tender models are registered with Base.metadata
import app.models.tender  # noqa: F401




# Local imports
from .routers.authorization import router as auth_router, get_current_user
from .core.config import settings
from .database import Base, engine
from .db_test import verify_database_connection
# ... решта коду без змін

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="CheckIT API",
    description="API for tender checking and analysis",
    version="1.0.0"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:3000",
        "http://localhost",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:3000",
        "http://frontend",
        "http://frontend:80",
        settings.frontend_url,
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Database initialization
async def init_db():
    try:
        if not await verify_database_connection():
            raise Exception("Database connection verification failed")

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            logger.info("Database tables created successfully")

            # Lightweight idempotent migrations for schema changes that
            # `create_all` cannot perform on existing tables.
            await conn.exec_driver_sql(
                "ALTER TABLE tender_items "
                "ADD COLUMN IF NOT EXISTS price_source VARCHAR(20) "
                "NOT NULL DEFAULT 'tender'"
            )
            await conn.exec_driver_sql(
                "ALTER TABLE tender_items ALTER COLUMN unit_price DROP NOT NULL"
            )
            logger.info("Schema migrations applied")

        return engine
    except Exception as e:
        logger.error(f"Database initialization failed: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Database initialization failed: {str(e)}"
        )

@app.on_event("startup")
async def startup():
    try:
        await init_db()
        logger.info("Application startup completed successfully")
    except Exception as e:
        logger.error(f"Application startup failed: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Application startup failed: {str(e)}"
        )

app.include_router(assistant_router)
# Include routers with authentication
# The /auth prefix is declared once, on the router itself (authorization.py)
app.include_router(auth_router, tags=["Authentication"])
app.include_router(prozorro_router)
app.include_router(tender_router)


@app.get("/", tags=["Root"])
async def home() -> dict:
    return {
        "message": "Welcome to CheckIT API",
        "documentation": "/docs"
    }

def parse_excel_file(file_content: bytes):
    try:
        workbook = load_workbook(filename=BytesIO(file_content))
        sheet = workbook.active
        
        headers = [cell.value for cell in sheet[1]]
        required_columns = ['Назва товару', 'Кількість', 'Ціна', 'Сума']
        
        if not all(col in headers for col in required_columns):
            raise ValueError("Excel file is missing required columns")
        
        col_indices = {header: idx for idx, header in enumerate(headers)}
        
        data = []
        for row_idx, row in enumerate(sheet.iter_rows(min_row=2, values_only=True), start=2):
            quantity = row[col_indices['Кількість']]
            price = row[col_indices['Ціна']]
            total = row[col_indices['Сума']]
            
            if quantity is None or price is None or total is None:
                logger.info(f"Skipping row {row_idx} due to empty values")
                continue
                
            try:
                row_data = {
                    'product_name': row[col_indices['Назва товару']],
                    'original_quantity': int(quantity),
                    'original_price_uah': float(price),
                    'original_total_uah': float(total),
                    'rozetka_results': []  # Залишаємо для сумісності, але не використовуємо тут
                }
                data.append(row_data)
            except (ValueError, TypeError) as e:
                logger.warning(f"Skipping row {row_idx} due to invalid data: {str(e)}")
                continue
        
        if not data:
            raise ValueError("No valid data found in the Excel file")
            
        return data
        
    except Exception as e:
        raise ValueError(f"Error parsing Excel file: {str(e)}")

@app.post("/excel-page")
async def upload_excel(
    file: UploadFile = File(...),
    stores: str = Query(default="rozetka", description="Comma-separated store keys: rozetka,silpo,epicentr"),
    current_user: str = Depends(get_current_user),
):
    """
    Upload an Excel file with tender items and compare prices from selected stores.
    """
    store_list = [s.strip() for s in stores.split(",") if s.strip()]
    if not store_list:
        store_list = ["rozetka"]

    try:
        file_content = await file.read()
        excel_data = parse_excel_file(file_content)

        # Search products across stores asynchronously
        store_data = []
        for row in excel_data:
            product_name = row['product_name']
            logger.info(f"Searching for: '{product_name}' in stores: {store_list}")
            try:
                results = await search_products_async(
                    product_name=product_name,
                    stores=store_list,
                    n=1,
                    fast_parse=False,
                    ignore_price_format=True,
                )
                store_data.extend(results)
                logger.info(f"Found {len(results)} products for '{product_name}'")
            except Exception as e:
                logger.warning(f"No result for '{product_name}': {str(e)}")
                continue

        return {
            "status": "success",
            "message": "Products found",
            "excel_data": excel_data,
            "store_data": store_data,
            "stores_used": store_list,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error in upload_excel: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
