import logging

from sqlalchemy import text

from app.database import engine

logger = logging.getLogger(__name__)


async def verify_database_connection() -> bool:
    """Check that the application's database is reachable."""
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        logger.info("Database connection test successful")
        return True
    except Exception as e:
        logger.error(f"Database connection test failed: {e}")
        return False
