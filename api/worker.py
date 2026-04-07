"""
Worker OCR — tourne en permanence en arrière-plan.
Il attend des tâches dans la file Redis, télécharge le fichier
depuis MinIO, lance le pipeline OCR, et met à jour la base de données.
"""

import json
import os
import sys
import tempfile
import time

# On ajoute le dossier pipeline_ocr au chemin Python
# sys.path.insert(0, "/app/pipeline_ocr")
sys.path.insert(0, "/app/pipeline_ocr")

from pipeline import process_document
from database import get_db, get_redis, UPLOAD_DIR

def mettre_a_jour_dossier(cur, dossier_id: str, donnees: dict):
    """
    Met à jour les numéros dans le dossier si on a trouvé quelque chose
    de mieux que ce qui est déjà en base (on ne remplace pas par None).
    Passe le statut à 'complet' si les 3 numéros sont renseignés.
    """
    champs = ["numero_bl", "numero_declaration", "numero_facture"]
    for champ in champs:
        valeur = donnees.get(champ)
        if valeur:
            cur.execute(
                f"UPDATE dossiers SET {champ} = %s, mis_a_jour_le = NOW() "
                f"WHERE id = %s AND {champ} IS NULL",
                (valeur, dossier_id)
            )

    # Vérifier si le dossier est complet
    cur.execute(
        "SELECT numero_bl, numero_declaration, numero_facture FROM dossiers WHERE id = %s",
        (dossier_id,)
    )
    row = cur.fetchone()
    if row and all(row):
        cur.execute(
            "UPDATE dossiers SET statut = 'complet' WHERE id = %s",
            (dossier_id,)
        )
        print(f"  Dossier {dossier_id} : COMPLET")
    else:
        manquants = [champs[i] for i, v in enumerate(row or []) if not v]
        print(f"  Dossier {dossier_id} : manque encore {manquants}")


def traiter_tache(tache_json: str):
    tache = json.loads(tache_json)
    document_id = tache["document_id"]
    dossier_id  = tache["dossier_id"]
    chemin      = tache["chemin"]
    type_doc    = tache["type_document"]
    nom_fichier = tache.get("nom_fichier", "")

    print(f"\nTraitement : {nom_fichier} ({type_doc})")

    # ✅ Fichier déjà local
    tmp_path = chemin

    # Lancer le pipeline OCR
    try:
        resultat = process_document(tmp_path, type_doc)
    except Exception as e:
        print(f"  Erreur pipeline : {e}")
        _marquer_erreur(document_id, str(e))
        return

    print(f"  Méthode : {resultat['methode']} | "
          f"Confiance : {resultat['score_confiance']:.0%} | "
          f"Données : {resultat['donnees_extraites']}")

    db = get_db()
    cur = db.cursor()

    cur.execute(
        """UPDATE documents
           SET statut = %s, score_confiance = %s, traite_le = NOW()
           WHERE id = %s""",
        (
            "erreur" if resultat.get("erreur") else "traite",
            resultat["score_confiance"],
            document_id
        )
    )

    if not resultat.get("erreur") and resultat["donnees_extraites"]:
        mettre_a_jour_dossier(cur, dossier_id, resultat["donnees_extraites"])

    db.commit()
    cur.close()
    db.close()


def _marquer_erreur(document_id: str, message: str):
    try:
        db = get_db()
        cur = db.cursor()
        cur.execute(
            "UPDATE documents SET statut = 'erreur', traite_le = NOW() WHERE id = %s",
            (document_id,)
        )
        db.commit()
        cur.close()
        db.close()
    except Exception:
        pass


# ── Boucle principale ─────────────────────────────────────────────

print("Worker OCR démarré. En attente de tâches...")

while True:
    try:
        r = get_redis()
        # Attendre une tâche (timeout 5 secondes, puis on reboucle)
        tache = r.brpop("queue_ocr", timeout=5)
        if tache:
            _, tache_json = tache
            traiter_tache(tache_json.decode())
    except Exception as e:
        print(f"Erreur worker : {e}")
        time.sleep(3)
