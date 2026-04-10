# api/database.py

import os
import psycopg2
import redis
from contextlib import contextmanager

# ── PostgreSQL ────────────────────────────────────────────────────

@contextmanager
def get_db():
    """Context manager pour connexions PostgreSQL avec gestion automatique.
    
    Usage:
        with get_db() as db:
            cur = db.cursor()
            cur.execute(...)
            # commit/close gérés automatiquement
    """
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ── Stockage local (remplace MinIO) ──────────────────────────────
# Les fichiers sont sauvegardés ici par défaut, mais le chemin peut être configuré
# via la variable d'environnement UPLOAD_DIR.
# Note : sur Railway le filesystem est éphémère, donc en production il faut remplacer
# ce stockage local par un volume persistant ou un backend objet (S3/R2/etc.).
UPLOAD_DIR = os.environ.get("UPLOAD_DIR", "/app/uploads")

def ensure_upload_dir():
    os.makedirs(UPLOAD_DIR, exist_ok=True)


# ── Redis (file d'attente) ────────────────────────────────────────

def get_redis():
    return redis.from_url(os.environ["REDIS_URL"])
