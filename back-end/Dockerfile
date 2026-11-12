FROM python:3.12-slim

# System deps: OCR (tesseract with Ukrainian and English, ghostscript for ocrmypdf)
# and LibreOffice (for .doc conversion)
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-ukr \
    tesseract-ocr-eng \
    ghostscript \
    libreoffice-writer \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python dependencies: everything is pinned in requirements.txt (generated from requirements.in)
COPY back-end/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r /tmp/requirements.txt

# Copy source code
COPY back-end/ /app/back-end/
COPY scraper/ /app/scraper/

# Add project root + back-end to PYTHONPATH
ENV PYTHONPATH=/app:/app/back-end

WORKDIR /app/back-end

EXPOSE 8000

# Apply database migrations, then start the server
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
