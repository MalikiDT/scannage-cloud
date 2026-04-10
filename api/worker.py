# /app/api/worker.py

import json
import logging
import os
import tempfile
import time

from pipeline_ocr.pipeline import process_document
from api.database import get_db, get_redis
from api.storage import STORAGE_ENABLED, download_to_tempfile

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("worker")


# ─── Helpers DB ───────────────────────────────────────────────────────────────

def update_dossier(cur, dossier_id: str, data: dict):
    """Met à jour les champs extraits du dossier (sans écraser une valeur déjà présente)."""
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
        "SELECT numero_bl, numero_declaration, numero_facture FROM dossiers WHERE id = %s",
        (dossier_id,),
    )
    row = cur.fetchone()

    if row and all(row):
        cur.execute("UPDATE dossiers SET statut = 'complet' WHERE id = %s", (dossier_id,))
        logger.info("Dossier %s → complet", dossier_id)
    else:
        missing = [f for f, v in zip(fields, row or []) if not v]
        cur.execute(
        "UPDATE dossiers SET statut = 'incomplet', mis_a_jour_le = NOW() WHERE id = %s",
        (dossier_id,)
        )
        logger.info("Dossier %s → incomplet (manquants : %s)", dossier_id, missing)


def mark_error(document_id: str):
    """Marque un document en erreur — appelé uniquement après épuisement des retries."""
    with get_db() as db:
        cur = db.cursor()
        cur.execute(
            "UPDATE documents SET statut = 'erreur', traite_le = NOW() WHERE id = %s",
            (document_id,),
        )
    logger.warning("Document %s marqué erreur", document_id)


# ─── Traitement ───────────────────────────────────────────────────────────────

def _get_pdf_path(task: dict) -> tuple[str, bool]:
    if STORAGE_ENABLED and task.get("storage_key"):
        temp_path = download_to_tempfile(task["storage_key"])
        return temp_path, True

    # Compatibilité avec d'anciennes tâches stockées en chemin local
    return task["chemin"], False


def process_task(task_json: str):
    """
    Traite une tâche OCR du début à la fin.

    Laisse toutes les exceptions remonter — c'est process_task_with_retry
    qui décide si on réessaie ou si on abandonne.
    """
    task = json.loads(task_json)
    doc_id     = task["document_id"]
    dossier_id = task["dossier_id"]
    doc_type   = task["type_document"]

    pdf_path, cleanup = _get_pdf_path(task)

    logger.info("Début traitement document=%s dossier=%s", doc_id, dossier_id)

    try:
        result = process_document(pdf_path, doc_type)
    finally:
        if cleanup and os.path.exists(pdf_path):
            try:
                os.remove(pdf_path)
            except OSError:
                logger.warning("Impossible de supprimer le fichier temporaire %s", pdf_path)

    statut = "erreur" if result.get("erreur") else "traite"
    logger.info(
        "OCR terminé document=%s méthode=%s score=%.2f statut=%s erreur=%s",
        doc_id,
        result.get("methode"),
        result.get("score_confiance", 0.0),
        statut,
        result.get("erreur"),
    )

    # Écriture en base — dans une seule transaction (UPDATE doc + UPDATE dossier)
    with get_db() as db:
        cur = db.cursor()
        cur.execute(
            """
            UPDATE documents
            SET statut = %s, score_confiance = %s, traite_le = NOW()
            WHERE id = %s
            """,
            (statut, result["score_confiance"], doc_id),
        )
        if not result.get("erreur"):
            update_dossier(cur, dossier_id, result["donnees_extraites"])


def process_task_with_retry(task_json: str, max_retries: int = 3):
    """
    Enveloppe process_task avec un backoff exponentiel.

    Retries déclenchés uniquement sur les erreurs inattendues (exception non captée).
    Les erreurs métier (score bas, champ non trouvé) sont gérées dans process_task
    et n'en sortent pas comme exceptions.
    """
    task   = json.loads(task_json)
    doc_id = task["document_id"]

    for attempt in range(max_retries):
        try:
            process_task(task_json)
            return  # succès

        except Exception as exc:
            is_last = attempt == max_retries - 1

            if is_last:
                logger.error(
                    "Échec définitif document=%s après %d tentatives : %s",
                    doc_id, max_retries, exc,
                    exc_info=True,
                )
                mark_error(doc_id)
                raise  # laisse remonter → dead letter queue dans run_worker

            backoff = 2 ** attempt  # 1s, 2s, 4s
            logger.warning(
                "Erreur transitoire document=%s tentative %d/%d, retry dans %ds : %s",
                doc_id, attempt + 1, max_retries, backoff, exc,
            )
            time.sleep(backoff)


# ─── Boucle principale ────────────────────────────────────────────────────────

def run_worker():
    logger.info("Worker OCR démarré (PID %s)", os.getpid())
    logger.info("REDIS_URL = %s", os.environ.get("REDIS_URL", "<non défini>"))

    r = get_redis()

    # Au démarrage : re-enqueue les tâches bloquées dans la processing queue
    # (laissées là par un crash précédent du worker)
    pending = r.lrange("queue_ocr_processing", 0, -1)
    if pending:
        logger.warning(
            "%d tâche(s) bloquée(s) dans queue_ocr_processing → re-enqueue",
            len(pending),
        )
        for item in pending:
            r.lpush("queue_ocr", item)
        r.delete("queue_ocr_processing")

    logger.info("En attente de tâches...")

    while True:
       # brpoplpush : compatible Redis 6.0+ (Railway)
        # Déplace atomiquement : queue_ocr (droite) → queue_ocr_processing (gauche)
        task = r.brpoplpush("queue_ocr", "queue_ocr_processing", timeout=5)

        if not task:
            continue  # timeout, on reboucle

        logger.info("Tâche reçue : %s", task)

        try:
            process_task_with_retry(task.decode())
            # Succès : retire de la processing queue
            r.lrem("queue_ocr_processing", 1, task)
            logger.info("Tâche terminée avec succès")

        except Exception:
            # Échec définitif après tous les retries : dead letter queue
            logger.exception("Tâche abandonnée → queue_ocr_dead")
            r.lpush("queue_ocr_dead", task)
            r.lrem("queue_ocr_processing", 1, task)


if __name__ == "__main__":
    run_worker()
