import os
import psycopg2
import redis
from minio import Minio

# ── PostgreSQL ────────────────────────────────────────────────────

def get_db():
    return psycopg2.connect(os.environ["DATABASE_URL"])


# ── MinIO (stockage fichiers) ─────────────────────────────────────

def get_minio():
    url = os.environ["MINIO_URL"].replace("http://", "")
    return Minio(
        url,
        access_key=os.environ["MINIO_USER"],
        secret_key=os.environ["MINIO_PASSWORD"],
        secure=False
    )

BUCKET_NAME = "documents"

def ensure_bucket():
    client = get_minio()
    if not client.bucket_exists(BUCKET_NAME):
        client.make_bucket(BUCKET_NAME)


# ── Redis (file d'attente) ────────────────────────────────────────

def get_redis():
    return redis.from_url(os.environ["REDIS_URL"])
