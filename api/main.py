import uuid
import json
import os
from datetime import datetime

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from database import get_db, get_redis, ensure_upload_dir, UPLOAD_DIR

app = FastAPI(title="Scannage Cloud API", version="1.0")

# Autoriser les appels depuis n'importe quelle origine
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 🔥 IMPORTANT : tes routes API
app.include_router(router, prefix="/api/v1")

# 🔥 CRUCIAL : sert le frontend
app.mount("/", StaticFiles(directory="static", html=True), name="static")

TYPES_VALIDES = {
    "BAD_DAKAR_TERMINAL", "BAD_SHIPPING", "DECLARATION",
    "BILL_OF_LADING", "PROCURATION", "CNI_TRANSITAIRE",
    "CNI_CLIENT", "FACTURE"
}


@app.on_event("startup")
def startup():
    ensure_upload_dir()


# ── Interface web ─────────────────────────────────────────────────

@app.get("/")
def accueil():
    return FileResponse("/app/index.html")


# ── Créer un dossier ──────────────────────────────────────────────

# @app.post("/api/v1/dossiers", status_code=201)
# def creer_dossier(client_nom: str = Form(""), transitaire_nom: str = Form("")):
#     db = get_db()
#     cur = db.cursor()
#     dossier_id = str(uuid.uuid4())
#     cur.execute(
#         """INSERT INTO dossiers (id, client_nom, transitaire_nom, statut)
#            VALUES (%s, %s, %s, 'incomplet')""",
#         (dossier_id, client_nom, transitaire_nom)
#     )
#     db.commit()
#     cur.close()
#     db.close()
#     return {"dossier_id": dossier_id, "statut": "incomplet"}

@app.post("/api/v1/dossiers", status_code=201)
async def creer_dossier(request: Request):
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        body = await request.json()
        client_nom = body.get("client_nom", "")
        transitaire_nom = body.get("transitaire_nom", "")
    else:
        form = await request.form()
        client_nom = form.get("client_nom", "")
        transitaire_nom = form.get("transitaire_nom", "")

# ── Consulter un dossier ──────────────────────────────────────────

@app.get("/api/v1/dossiers/{dossier_id}")
def get_dossier(dossier_id: str):
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT * FROM dossiers WHERE id = %s", (dossier_id,))
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Dossier introuvable")
    cols = [d[0] for d in cur.description]
    dossier = dict(zip(cols, row))
    cur.execute(
        "SELECT id, type_document, nom_fichier, statut, score_confiance, cree_le "
        "FROM documents WHERE dossier_id = %s",
        (dossier_id,)
    )
    docs = [dict(zip([d[0] for d in cur.description], r)) for r in cur.fetchall()]
    dossier["documents"] = docs
    cur.close()
    db.close()
    return dossier


# ── Lister les dossiers ───────────────────────────────────────────

@app.get("/api/v1/dossiers")
def lister_dossiers(statut: str = None, numero_bl: str = None, page: int = 1):
    db = get_db()
    cur = db.cursor()
    query = "SELECT * FROM dossiers WHERE 1=1"
    params = []
    if statut:
        query += " AND statut = %s"
        params.append(statut)
    if numero_bl:
        query += " AND numero_bl = %s"
        params.append(numero_bl)
    query += " ORDER BY cree_le DESC LIMIT 20 OFFSET %s"
    params.append((page - 1) * 20)
    cur.execute(query, params)
    cols = [d[0] for d in cur.description]
    dossiers = [dict(zip(cols, row)) for row in cur.fetchall()]
    cur.close()
    db.close()
    return {"dossiers": dossiers, "page": page}


# ── Uploader un document ──────────────────────────────────────────

@app.post("/api/v1/dossiers/{dossier_id}/documents", status_code=202)
async def uploader_document(
    dossier_id: str,
    type_document: str = Form(...),
    fichier: UploadFile = File(...)
):
    if type_document.upper() not in TYPES_VALIDES:
        raise HTTPException(status_code=400, detail="Type invalide.")

    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT id FROM dossiers WHERE id = %s", (dossier_id,))
    if not cur.fetchone():
        raise HTTPException(status_code=404, detail="Dossier introuvable")

    document_id = str(uuid.uuid4())
    extension = os.path.splitext(fichier.filename)[1] or ".pdf"
    sous_dossier = os.path.join(UPLOAD_DIR, datetime.now().strftime("%Y/%m"))
    os.makedirs(sous_dossier, exist_ok=True)
    chemin = os.path.join(sous_dossier, f"{document_id}{extension}")

    contenu = await fichier.read()
    with open(chemin, "wb") as f:
        f.write(contenu)

    cur.execute(
        """INSERT INTO documents
           (id, dossier_id, type_document, nom_fichier, chemin_stockage, statut)
           VALUES (%s, %s, %s, %s, %s, 'en_traitement')""",
        (document_id, dossier_id, type_document.upper(), fichier.filename, chemin)
    )
    cur.execute(
        "UPDATE dossiers SET statut = 'en_traitement', mis_a_jour_le = NOW() WHERE id = %s",
        (dossier_id,)
    )
    db.commit()
    cur.close()
    db.close()

    r = get_redis()
    tache = json.dumps({
        "document_id": document_id,
        "dossier_id": dossier_id,
        "chemin": chemin,
        "type_document": type_document.upper(),
        "nom_fichier": fichier.filename
    })
    r.lpush("queue_ocr", tache)

    return {"document_id": document_id, "statut": "en_traitement"}


# ── Consulter un document ─────────────────────────────────────────

@app.get("/api/v1/documents/{document_id}")
def get_document(document_id: str):
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT * FROM documents WHERE id = %s", (document_id,))
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Document introuvable")
    cols = [d[0] for d in cur.description]
    cur.close()
    db.close()
    return dict(zip(cols, row))


# ── Corriger manuellement ─────────────────────────────────────────

@app.patch("/api/v1/dossiers/{dossier_id}")
def corriger_dossier(
    dossier_id: str,
    numero_bl: str = Form(None),
    numero_declaration: str = Form(None),
    numero_facture: str = Form(None)
):
    db = get_db()
    cur = db.cursor()
    mises_a_jour = {}
    if numero_bl:          mises_a_jour["numero_bl"] = numero_bl
    if numero_declaration: mises_a_jour["numero_declaration"] = numero_declaration
    if numero_facture:     mises_a_jour["numero_facture"] = numero_facture
    if not mises_a_jour:
        raise HTTPException(status_code=400, detail="Aucun champ fourni")
    set_clause = ", ".join(f"{k} = %s" for k in mises_a_jour)
    valeurs = list(mises_a_jour.values()) + [dossier_id]
    cur.execute(
        f"UPDATE dossiers SET {set_clause}, mis_a_jour_le = NOW() WHERE id = %s",
        valeurs
    )
    cur.execute(
        "SELECT numero_bl, numero_declaration, numero_facture FROM dossiers WHERE id = %s",
        (dossier_id,)
    )
    row = cur.fetchone()
    statut = "complet" if row and all(row) else "en_traitement"
    if statut == "complet":
        cur.execute("UPDATE dossiers SET statut = 'complet' WHERE id = %s", (dossier_id,))
    db.commit()
    cur.close()
    db.close()
    return {"dossier_id": dossier_id, "statut": statut}
