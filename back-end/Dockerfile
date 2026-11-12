FROM python:3.11-slim

# System deps: OCR tools + LibreOffice (for .doc conversion)
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-ukr \
    tesseract-ocr-eng \
    libreoffice-writer \
    libffi-dev \
    libpq-dev \
    gcc \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy and install backend dependencies
COPY back-end/requirements.txt /tmp/backend-requirements.txt
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r /tmp/backend-requirements.txt

# Install PyMuPDF (fitz) + ocrmypdf for PDF text extraction and OCR
RUN pip install --no-cache-dir \
    PyMuPDF \
    ocrmypdf

# Install additional packages needed for async DB and Excel parsing
RUN pip install --no-cache-dir "sqlalchemy[asyncio]" asyncpg python-dotenv openpyxl pandas

# Ensure email-validator is present (pydantic[email] needs it)
RUN pip install --no-cache-dir email-validator

# Google Gemini API for LLM-based product validation
RUN pip install --no-cache-dir google-generativeai

# Anthropic SDK for Claude (primary LLM with prompt caching)
RUN pip install --no-cache-dir anthropic

# Redis async client for caching
RUN pip install --no-cache-dir "redis>=5.0.0"

# Copy source code
COPY back-end/ /app/back-end/
COPY scraper/ /app/scraper/

# Add project root + back-end to PYTHONPATH
ENV PYTHONPATH=/app:/app/back-end

WORKDIR /app/back-end

EXPOSE 8000

# Apply database migrations, then start the server
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
