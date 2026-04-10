# Dockerfile

# ── Build ────────────────────────────────────────────────────────────────────
FROM python:3.11-slim

# Dépendances système OCR
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-fra \
    tesseract-ocr-por \
    poppler-utils \
    libgl1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dépendances Python en premier (layer mis en cache si requirements.txt inchangé)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Code applicatif
COPY api/        ./api/
COPY pipeline_ocr/ ./pipeline_ocr/

# Dossier uploads (écrasé par le volume en production)
RUN mkdir -p /app/uploads

# Utilisateur non-root (bonne pratique sécurité)
RUN useradd --no-create-home --shell /bin/false appuser \
    && chown -R appuser /app
USER appuser

# ── Défaut : API ──────────────────────────────────────────────────────────────
# Le service worker surcharge ce CMD dans docker-compose.yml
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
