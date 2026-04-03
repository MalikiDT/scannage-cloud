import uuid, json, os
from datetime import datetime
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from database import get_db, get_redis, ensure_upload_dir, UPLOAD_DIR

app = FastAPI(title="Scannage Cloud API", version="1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

TYPES_VALIDES = {"BAD_DAKAR_TERMINAL","BAD_SHIPPING","DECLARATION","BILL_OF_LADING","PROCURATION","CNI_TRANSITAIRE","CNI_CLIENT","FACTURE"}

@app.on_event("startup")
def startup():
    ensure_upload_dir()

@app.get("/")
def accueil():
    return FileResponse("/app/index.html")

@app.post("/api/v1/dossiers", status_code=201)
async def creer_dossier(request: Request):
    ct = request.headers.get("content-type","")
    if "application/json" in ct:
        b = await request.json()
        client_nom, transitaire_nom = b.get("client_nom",""), b.get("transitaire_nom","")
    else:
        f = await request.form()
        client_nom, transitaire_nom = f.get("client_nom",""), f.get("transitaire_nom","")
    db = get_db(); cur = db.cursor()
    did = str(uuid.uuid4())
    cur.execute("INSERT INTO dossiers (id,client_nom,transitaire_nom,statut) VALUES (%s,%s,%s,'incomplet')",(did,client_nom,transitaire_nom))
    db.commit(); cur.close(); db.close()
    return {"dossier_id": did, "statut": "incomplet"}

@app.get("/api/v1/dossiers")
def lister_dossiers(statut: str=None, numero_bl: str=None, page: int=1):
    db=get_db(); cur=db.cursor()
    q="SELECT * FROM dossiers WHERE 1=1"; p=[]
    if statut: q+=" AND statut=%s"; p.append(statut)
    if numero_bl: q+=" AND numero_bl=%s"; p.append(numero_bl)
    q+=" ORDER BY cree_le DESC LIMIT 20 OFFSET %s"; p.append((page-1)*20)
    cur.execute(q,p)
    cols=[d[0] for d in cur.description]
    rows=[dict(zip(cols,r)) for r in cur.fetchall()]
    cur.close(); db.close()
    return {"dossiers": rows, "page": page}

@app.get("/api/v1/dossiers/{dossier_id}")
def get_dossier(dossier_id: str):
    db=get_db(); cur=db.cursor()
    cur.execute("SELECT * FROM dossiers WHERE id=%s",(dossier_id,))
    row=cur.fetchone()
    if not row: raise HTTPException(404,"Dossier introuvable")
    cols=[d[0] for d in cur.description]; d=dict(zip(cols,row))
    cur.execute("SELECT id,type_document,nom_fichier,statut,score_confiance,cree_le FROM documents WHERE dossier_id=%s",(dossier_id,))
    d["documents"]=[dict(zip([x[0] for x in cur.description],r)) for r in cur.fetchall()]
    cur.close(); db.close(); return d

@app.post("/api/v1/dossiers/{dossier_id}/documents", status_code=202)
async def uploader_document(dossier_id: str, type_document: str=Form(...), fichier: UploadFile=File(...)):
    if type_document.upper() not in TYPES_VALIDES: raise HTTPException(400,"Type invalide")
    db=get_db(); cur=db.cursor()
    cur.execute("SELECT id FROM dossiers WHERE id=%s",(dossier_id,))
    if not cur.fetchone(): raise HTTPException(404,"Dossier introuvable")
    did=str(uuid.uuid4()); ext=os.path.splitext(fichier.filename)[1] or ".pdf"
    sd=os.path.join(UPLOAD_DIR,datetime.now().strftime("%Y/%m")); os.makedirs(sd,exist_ok=True)
    chemin=os.path.join(sd,f"{did}{ext}")
    with open(chemin,"wb") as f: f.write(await fichier.read())
    cur.execute("INSERT INTO documents (id,dossier_id,type_document,nom_fichier,chemin_stockage,statut) VALUES (%s,%s,%s,%s,%s,'en_traitement')",(did,dossier_id,type_document.upper(),fichier.filename,chemin))
    cur.execute("UPDATE dossiers SET statut='en_traitement',mis_a_jour_le=NOW() WHERE id=%s",(dossier_id,))
    db.commit(); cur.close(); db.close()
    get_redis().lpush("queue_ocr",json.dumps({"document_id":did,"dossier_id":dossier_id,"chemin":chemin,"type_document":type_document.upper(),"nom_fichier":fichier.filename}))
    return {"document_id": did, "statut": "en_traitement"}

@app.patch("/api/v1/dossiers/{dossier_id}")
def corriger_dossier(dossier_id: str, numero_bl: str=Form(None), numero_declaration: str=Form(None), numero_facture: str=Form(None)):
    db=get_db(); cur=db.cursor()
    maj={}
    if numero_bl: maj["numero_bl"]=numero_bl
    if numero_declaration: maj["numero_declaration"]=numero_declaration
    if numero_facture: maj["numero_facture"]=numero_facture
    if not maj: raise HTTPException(400,"Aucun champ")
    cur.execute(f"UPDATE dossiers SET {', '.join(f'{k}=%s' for k in maj)},mis_a_jour_le=NOW() WHERE id=%s",list(maj.values())+[dossier_id])
    cur.execute("SELECT numero_bl,numero_declaration,numero_facture FROM dossiers WHERE id=%s",(dossier_id,))
    row=cur.fetchone(); statut="complet" if row and all(row) else "en_traitement"
    if statut=="complet": cur.execute("UPDATE dossiers SET statut='complet' WHERE id=%s",(dossier_id,))
    db.commit(); cur.close(); db.close()
    return {"dossier_id":dossier_id,"statut":statut}
