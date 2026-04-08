# /app/api/main.py

import logging
import uuid, json, os
from datetime import datetime
from contextlib import asynccontextmanager

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from api.database import get_db, get_redis, ensure_upload_dir, UPLOAD_DIR

MAX_UPLOAD_SIZE = 50 * 1024 * 1024  # 50 Mo


# ─── Lifespan ─────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Startup...")
    ensure_upload_dir()
    yield
    logger.info("Shutdown...")


# ─── App (UNE SEULE FOIS) ─────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("api")

app = FastAPI(
    title="Scannage Cloud API",
    version="1.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)


# ─── Constantes ───────────────────────────────────────────

TYPES_VALIDES = {
    "BAD_DAKAR_TERMINAL","BAD_SHIPPING","DECLARATION",
    "BILL_OF_LADING","PROCURATION","CNI_TRANSITAIRE",
    "CNI_CLIENT","FACTURE"
}


async def save_upload_file(fichier: UploadFile, chemin: str, max_size: int = MAX_UPLOAD_SIZE) -> int:
    total = 0
    with open(chemin, "wb") as f:
        while True:
            chunk = await fichier.read(1024 * 1024)
            if not chunk:
                break

            total += len(chunk)
            if total > max_size:
                raise HTTPException(413, "Fichier trop volumineux")

            f.write(chunk)
    return total


# ─── Routes ──────────────────────────────────────────────

@app.post("/api/v1/dossiers", status_code=201)
async def creer_dossier(request: Request):
    ct = request.headers.get("content-type","")

    if "application/json" in ct:
        b = await request.json()
        client_nom = b.get("client_nom","")
        transitaire_nom = b.get("transitaire_nom","")
    else:
        f = await request.form()
        client_nom = f.get("client_nom","")
        transitaire_nom = f.get("transitaire_nom","")

    did = str(uuid.uuid4())

    with get_db() as db:
        cur = db.cursor()
        cur.execute(
            "INSERT INTO dossiers (id,client_nom,transitaire_nom,statut) VALUES (%s,%s,%s,'incomplet')",
            (did,client_nom,transitaire_nom)
        )

    return {"dossier_id": did, "statut": "incomplet"}

@app.get("/api/v1/dossiers")
def lister_dossiers(page: int = 1):
    with get_db() as db:
        cur = db.cursor()

        cur.execute(
            """
            SELECT * FROM dossiers
            ORDER BY cree_le DESC
            LIMIT 20 OFFSET %s
            """,
            ((page - 1) * 20,)
        )

        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]

    return {"dossiers": rows}

@app.post("/api/v1/dossiers/{dossier_id}/documents", status_code=202)
async def uploader_document(
    dossier_id: str,
    type_document: str = Form(...),
    fichier: UploadFile = File(...)
):
    type_document = type_document.upper()
    if type_document not in TYPES_VALIDES:
        raise HTTPException(400, "Type invalide")

    did = str(uuid.uuid4())
    ext = os.path.splitext(fichier.filename)[1] or ".pdf"
    sd = os.path.join(UPLOAD_DIR, datetime.now().strftime("%Y/%m"))
    os.makedirs(sd, exist_ok=True)
    chemin = os.path.join(sd, f"{did}{ext}")

    try:
        await save_upload_file(fichier, chemin)

        with get_db() as db:
            cur = db.cursor()

            cur.execute("SELECT id FROM dossiers WHERE id=%s", (dossier_id,))
            if not cur.fetchone():
                raise HTTPException(404, "Dossier introuvable")

            cur.execute(
                """INSERT INTO documents 
                (id,dossier_id,type_document,nom_fichier,chemin_stockage,statut)
                VALUES (%s,%s,%s,%s,%s,'en_traitement')""",
                (did, dossier_id, type_document, fichier.filename, chemin)
            )

            cur.execute(
                "UPDATE dossiers SET statut='en_traitement',mis_a_jour_le=NOW() WHERE id=%s",
                (dossier_id,),
            )

            get_redis().lpush(
                "queue_ocr",
                json.dumps({
                    "document_id": did,
                    "dossier_id": dossier_id,
                    "chemin": chemin,
                    "type_document": type_document,
                    "nom_fichier": fichier.filename,
                }),
            )

    except HTTPException:
        raise
    except Exception as exc:
        if chemin and os.path.exists(chemin):
            try:
                os.remove(chemin)
            except OSError:
                pass
        logger.exception("Upload failed for dossier %s", dossier_id)
        raise HTTPException(500, "Erreur interne lors de l'upload") from exc

    return {"document_id": did, "statut": "en_traitement"}

@app.get("/api/v1/dossiers/{dossier_id}")
def get_dossier(dossier_id: str):
    with get_db() as db:
        cur = db.cursor()

        cur.execute("SELECT * FROM dossiers WHERE id=%s", (dossier_id,))
        row = cur.fetchone()

        if not row:
            raise HTTPException(404, "Dossier introuvable")

        cols = [d[0] for d in cur.description]
        dossier = dict(zip(cols, row))

        cur.execute(
            """
            SELECT id, type_document, nom_fichier, statut, score_confiance, cree_le
            FROM documents WHERE dossier_id=%s
            """,
            (dossier_id,)
        )

        dossier["documents"] = [
            dict(zip([x[0] for x in cur.description], r))
            for r in cur.fetchall()
        ]

    return dossier

# ─── Static ──────────────────────────────────────────────

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app.mount(
    "/static",
    StaticFiles(directory=os.path.join(BASE_DIR, "static")),
    name="static"
)

@app.get("/")
def serve_index():
    return FileResponse(os.path.join(BASE_DIR, "static", "index.html"))
