import os
import psycopg2
import redis

# ── PostgreSQL ────────────────────────────────────────────────────

def get_db():
    return psycopg2.connect(os.environ["DATABASE_URL"])


# ── Stockage local (remplace MinIO) ──────────────────────────────
# Les fichiers sont sauvegardés dans /app/uploads/

UPLOAD_DIR = "/app/uploads"

def ensure_upload_dir():
    os.makedirs(UPLOAD_DIR, exist_ok=True)


# ── Redis (file d'attente) ────────────────────────────────────────

def get_redis():
    return redis.from_url(os.environ["REDIS_URL"])
