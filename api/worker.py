# /app/api/worker.py

import json
import time

from pipeline_ocr.pipeline import process_document
from api.database import get_db, get_redis


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
        print(f"[OK] Dossier {dossier_id} complet")
    else:
        print(f"[INFO] Dossier {dossier_id} incomplet")


def mark_error(document_id: str):
    db = get_db()
    cur = db.cursor()

    cur.execute(
        """
        UPDATE documents
        SET statut = 'erreur', traite_le = NOW()
        WHERE id = %s
        """,
        (document_id,),
    )

    db.commit()
    cur.close()
    db.close()


def process_task(task_json: str):
    task = json.loads(task_json)

    doc_id = task["document_id"]
    dossier_id = task["dossier_id"]
    path = task["chemin"]
    doc_type = task["type_document"]

    print(f"\n[WORKER] Processing {path}")

    try:
        result = process_document(path, doc_type)
    except Exception as e:
        print(f"[ERROR] OCR failed: {e}")
        mark_error(doc_id)
        return

    db = get_db()
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

    db.commit()
    cur.close()
    db.close()


def run_worker():
    print("🚀 Worker OCR démarré")

    r = get_redis()
    print("REDIS URL:", r)

    while True:
        print("⏳ Waiting for tasks...")
        task = r.brpop("queue_ocr", timeout=5)

        if task:
            print("🔥 TASK RECEIVED:", task)


if __name__ == "__main__":
    run_worker()
