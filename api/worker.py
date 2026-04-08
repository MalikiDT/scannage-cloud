# /app/api/worker.py

import json
import logging
import os
import time

from pipeline_ocr.pipeline import process_document
from api.database import get_db, get_redis

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("worker")


def update_dossier(cur, dossier_id: str, data: dict):
    fields = ["numero_bl", "numero_declaration", "numero_facture"]

    for field in fields:
        value = data.get(field)
        if value:
            cur.execute(
                f"""
                UPDATE dossiers
                SET {field} = %s, mis_a_jour_le = NOW()
                WHERE id = %s AND {field} IS NULL
                """,
                (value, dossier_id),
            )

    cur.execute(
        """
        SELECT numero_bl, numero_declaration, numero_facture
        FROM dossiers WHERE id = %s
        """,
        (dossier_id,),
    )

    row = cur.fetchone()

    if row and all(row):
        cur.execute(
            "UPDATE dossiers SET statut = 'complet' WHERE id = %s",
            (dossier_id,),
        )
        logger.info("Dossier %s complet", dossier_id)
    else:
        logger.info("Dossier %s incomplet", dossier_id)


def mark_error(document_id: str):
    with get_db() as db:
        cur = db.cursor()
        cur.execute(
            """
            UPDATE documents
            SET statut = 'erreur', traite_le = NOW()
            WHERE id = %s
            """,
            (document_id,),
        )


def process_task(task_json: str):
    task = json.loads(task_json)

    doc_id = task["document_id"]
    dossier_id = task["dossier_id"]
    path = task["chemin"]
    doc_type = task["type_document"]

    logger.info("Processing document %s (dossier=%s, path=%s)", doc_id, dossier_id, path)

    try:
        result = process_document(path, doc_type)
    except Exception as e:
        logger.exception("OCR failed for %s", doc_id)
        mark_error(doc_id)
        return

    with get_db() as db:
        cur = db.cursor()

        cur.execute(
            """
            UPDATE documents
            SET statut = %s, score_confiance = %s, traite_le = NOW()
            WHERE id = %s
            """,
            (
                "erreur" if result.get("erreur") else "traite",
                result["score_confiance"],
                doc_id,
            ),
        )

        if not result.get("erreur"):
            update_dossier(cur, dossier_id, result["donnees_extraites"])


def process_task_with_retry(task_json: str, max_retries: int = 3):
    task = json.loads(task_json)
    for attempt in range(max_retries):
        try:
            process_task(task_json)
            return
        except Exception as exc:
            if attempt == max_retries - 1:
                logger.exception("Permanent failure for document %s after %d attempts", task["document_id"], max_retries)
                mark_error(task["document_id"])
                raise
            backoff = 2 ** attempt
            logger.warning(
                "Retry %d/%d for document %s after transient error: %s",
                attempt + 1,
                max_retries,
                task["document_id"],
                exc,
                exc_info=True,
            )
            time.sleep(backoff)


def run_worker():
    logger.info("🚀 Worker OCR démarré")

    r = get_redis()
    logger.info("REDIS URL: %s", os.environ.get("REDIS_URL", "<unknown>"))

    pending = r.lrange("queue_ocr_processing", 0, -1)
    if pending:
        logger.warning("Re-enqueue %d tasks from queue_ocr_processing", len(pending))
        for item in pending:
            r.lpush("queue_ocr", item)
        r.delete("queue_ocr_processing")

    while True:
        logger.info("⏳ Waiting for tasks...")
        task = r.brpoplpush("queue_ocr", "queue_ocr_processing", timeout=5)

        if not task:
            continue

        logger.info("🔥 TASK RECEIVED: %s", task)

        try:
            process_task_with_retry(task.decode())
            r.lrem("queue_ocr_processing", 1, task)
        except Exception:
            logger.exception("Task failed permanently, moving to dead letter queue")
            r.lpush("queue_ocr_dead", task)
            r.lrem("queue_ocr_processing", 1, task)


if __name__ == "__main__":
    run_worker()
