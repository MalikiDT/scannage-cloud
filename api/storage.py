# api/storage.py

import os
import tempfile
import uuid
from datetime import datetime

import boto3
from botocore.exceptions import ClientError
from fastapi import UploadFile, HTTPException

STORAGE_ENDPOINT  = os.environ.get("STORAGE_ENDPOINT")   # t3.storageapi.dev
STORAGE_ACCESS_KEY = os.environ.get("STORAGE_ACCESS_KEY")
STORAGE_SECRET_KEY = os.environ.get("STORAGE_SECRET_KEY")
STORAGE_BUCKET    = os.environ.get("STORAGE_BUCKET", "scannage-cloud")
STORAGE_REGION    = os.environ.get("STORAGE_REGION", "auto")
STORAGE_ENABLED   = bool(STORAGE_ENDPOINT and STORAGE_ACCESS_KEY and STORAGE_SECRET_KEY)


def get_storage_client():
    if not STORAGE_ENABLED:
        raise RuntimeError("Storage backend not configured")
    return boto3.client(
        "s3",
        endpoint_url=f"https://{STORAGE_ENDPOINT}",
        aws_access_key_id=STORAGE_ACCESS_KEY,
        aws_secret_access_key=STORAGE_SECRET_KEY,
        region_name=STORAGE_REGION,
    )


def ensure_bucket() -> None:
    """Vérifie que le bucket existe — sur R2/t3 il est créé via l'interface, pas le code."""
    client = get_storage_client()
    try:
        client.head_bucket(Bucket=STORAGE_BUCKET)
    except ClientError as exc:
        code = exc.response["Error"]["Code"]
        if code in ("404", "NoSuchBucket"):
            raise RuntimeError(f"Bucket '{STORAGE_BUCKET}' introuvable sur le stockage") from exc
        raise


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
            Bucket=STORAGE_BUCKET,
            Key=object_key,
            Body=stream,
            ContentLength=size,
            ContentType=content_type,
        )
    except ClientError as exc:
        raise HTTPException(500, f"Erreur de stockage : {exc}") from exc

    return object_key


def download_storage_object(object_key: str, target_path: str) -> str:
    ensure_bucket()
    client = get_storage_client()

    try:
        client.download_file(STORAGE_BUCKET, object_key, target_path)
    except ClientError as exc:
        raise RuntimeError(f"Impossible de télécharger {object_key} : {exc}") from exc

    return target_path


def download_to_tempfile(object_key: str) -> str:
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    tmp.close()
    return download_storage_object(object_key, tmp.name)
