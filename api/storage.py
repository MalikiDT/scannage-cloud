# api/storage.py

import os
import tempfile
import uuid
from datetime import datetime

from minio import Minio
from minio.error import S3Error
from fastapi import UploadFile, HTTPException

STORAGE_ENDPOINT = os.environ.get("STORAGE_ENDPOINT")
STORAGE_ACCESS_KEY = os.environ.get("STORAGE_ACCESS_KEY")
STORAGE_SECRET_KEY = os.environ.get("STORAGE_SECRET_KEY")
STORAGE_BUCKET = os.environ.get("STORAGE_BUCKET", "scannage-cloud")
STORAGE_SECURE = os.environ.get("STORAGE_SECURE", "true").lower() in ("1", "true", "yes")
STORAGE_ENABLED = bool(STORAGE_ENDPOINT and STORAGE_ACCESS_KEY and STORAGE_SECRET_KEY)


def get_storage_client() -> Minio:
    if not STORAGE_ENABLED:
        raise RuntimeError("Storage backend not configured")
    return Minio(
        STORAGE_ENDPOINT,
        access_key=STORAGE_ACCESS_KEY,
        secret_key=STORAGE_SECRET_KEY,
        secure=STORAGE_SECURE,
    )


def ensure_bucket() -> None:
    client = get_storage_client()
    if not client.bucket_exists(STORAGE_BUCKET):
        client.make_bucket(STORAGE_BUCKET)


def get_object_key(extension: str) -> str:
    date_path = datetime.utcnow().strftime("%Y/%m")
    return f"uploads/{date_path}/{uuid.uuid4().hex}{extension}"


def upload_file_to_storage(fichier: UploadFile, object_key: str) -> str:
    ensure_bucket()
    client = get_storage_client()

    try:
        stream = fichier.file
        stream.seek(0, os.SEEK_END)
        size = stream.tell()
        stream.seek(0)
    except Exception:
        raise HTTPException(400, "Impossible de lire le fichier uploadé")

    if size <= 0:
        raise HTTPException(400, "Fichier vide")

    content_type = fichier.content_type or "application/octet-stream"

    try:
        client.put_object(
            STORAGE_BUCKET,
            object_key,
            stream,
            size,
            content_type=content_type,
        )
    except S3Error as exc:
        raise HTTPException(500, f"Erreur de stockage objet : {exc}") from exc

    return object_key


def download_storage_object(object_key: str, target_path: str) -> str:
    ensure_bucket()
    client = get_storage_client()

    try:
        response = client.get_object(STORAGE_BUCKET, object_key)
    except S3Error as exc:
        raise RuntimeError(f"Impossible de télécharger l'objet {object_key}: {exc}") from exc

    try:
        with open(target_path, "wb") as out:
            for chunk in response.stream(32 * 1024):
                out.write(chunk)
    finally:
        response.close()
        response.release_conn()

    return target_path

def download_to_tempfile(object_key: str) -> str:
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    tmp.close()
    return download_storage_object(object_key, tmp.name)
