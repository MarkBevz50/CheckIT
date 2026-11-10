from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base

from app.core.config import settings

# The one async engine used by the whole application
engine = create_async_engine(
    settings.database_url,
    echo=settings.db_echo,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
)

# Фабрика сесій для роботи з БД
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, class_=AsyncSession)

# Базовий клас моделей
Base = declarative_base()

# Функція для отримання сесії (залежність FastAPI)
async def get_db():
    async with SessionLocal() as session:
        yield session
