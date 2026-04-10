# Scannage Cloud

Application de traitement automatique de documents douaniers pour la gestion des dossiers d'importation.
Le lien de la plateforme : [https://scannage-cloud-production.up.railway.app/]

## Architecture

- **API FastAPI** : Interface REST pour l'upload et la gestion des dossiers
- **Worker OCR** : Traitement asynchrone des documents scannés
- **Base PostgreSQL** : Stockage des métadonnées et résultats d'extraction
- **Redis** : File d'attente pour le traitement OCR
- **Stockage local** : Fichiers uploadés (remplacer par S3/R2 en production)

## Structure des fichiers

```
api/
├── main.py          # API FastAPI (routes, upload)
├── worker.py        # Worker OCR avec retry et dead letter queue
├── database.py      # Connexions PostgreSQL/Redis avec context manager
└── init.sql         # Schéma de base de données

pipeline_ocr/
├── pipeline.py      # Orchestrateur principal
├── detector.py      # Détection PDF natif/scanné
├── extractor_native.py  # Extraction texte PDF natif
├── extractor_scan.py    # OCR avec Tesseract + preprocessing
└── parser.py        # Extraction des numéros métier (BL, déclaration, facture)

static/
└── index.html       # Interface web simple

requirements.txt     # Dépendances Python
docker-compose.yml   # Environnement de développement
Dockerfile           # Image de production
```

## Installation et démarrage

### Prérequis
- Python 3.9+
- PostgreSQL
- Redis
- Tesseract OCR

### Démarrage rapide
```bash
# Installation
pip install -r requirements.txt

docker-compose up -d
```

### En local avec MinIO
La configuration Docker locale inclut un service MinIO. Les variables d'environnement sont déjà injectées dans `docker-compose.yml` pour l'API et le worker.

- MinIO console : http://localhost:9001
- MinIO API : http://localhost:9000

### Variables d'environnement manuelles
Si vous exécutez l'API ou le worker sans Docker :
```bash
export DATABASE_URL="postgresql://user:pass@localhost:5432/scannage"
export REDIS_URL="redis://localhost:6379"
export STORAGE_ENDPOINT="http://localhost:9000"
export STORAGE_ACCESS_KEY="scannage_admin"
export STORAGE_SECRET_KEY="changez_ce_mot_de_passe"
export STORAGE_BUCKET="scannage-cloud"
export STORAGE_SECURE="false"
```

### Démarrage
```bash
python api/main.py
python api/worker.py
```

### Vérification
```bash
curl http://localhost:8000/health
```

## API

### Créer un dossier
```bash
POST /api/v1/dossiers
Content-Type: application/json

{"client_nom": "ABC Corp", "transitaire_nom": "XYZ Logistics"}
```

### Uploader un document
```bash
POST /api/v1/dossiers/{dossier_id}/documents
Content-Type: multipart/form-data

type_document: BILL_OF_LADING
fichier: @document.pdf
```

### Lister les dossiers
```bash
GET /api/v1/dossiers?page=1
```

### Consulter un dossier
```bash
GET /api/v1/dossiers/{dossier_id}
```

## Types de documents supportés

- `BAD_DAKAR_TERMINAL` : Bordereau d'arrivée Dakar Terminal
- `BAD_SHIPPING` : Bordereau d'arrivée shipping
- `DECLARATION` : Déclaration douanière
- `BILL_OF_LADING` : Connaissement maritime
- `PROCURATION` : Procuration douanière
- `CNI_TRANSITAIRE` : Carte nationale d'identité transitaire
- `CNI_CLIENT` : Carte nationale d'identité client
- `FACTURE` : Facture commerciale

## Extraction automatique

Le système extrait automatiquement :
- Numéro de connaissement (BL)
- Numéro de déclaration douanière
- Numéro de facture

## Production

- Utiliser un stockage objet (S3, R2) au lieu du stockage local
- Configurer les variables d'environnement pour la base et Redis
- Déployer avec Docker sur Railway ou équivalent
- Monitorer les logs et la file d'attente Redis

## Développement

```bash
# Tests
python pipeline/pipeline.py chemin/vers/document.pdf FACTURE

# Debug OCR
python pipeline/extractor_scan.py chemin/vers/document.pdf
```
