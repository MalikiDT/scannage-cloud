# Plan de test - Scannage Cloud

## 1. Setup de l'environnement de test

### Étape 1.1 - Démarrer les services
```bash
docker-compose up -d
```
Vérifier :
- PostgreSQL démarre sans erreur
- Redis démarre sans erreur
- Les ports sont accessibles (5432, 6379)

### Étape 1.2 - Initialiser la base de données
```bash
psql $DATABASE_URL < api/init.sql
```
Vérifier :
- Tables créées (dossiers, documents)
- Pas d'erreur SQL

### Étape 1.3 - Démarrer l'API
```bash
python api/main.py
```
Vérifier :
- Serveur écoute sur http://localhost:8000
- Interface web accessible via http://localhost:8000

### Étape 1.4 - Démarrer le worker
```bash
python api/worker.py
```
Vérifier :
- Message "Worker OCR démarré"
- "Waiting for tasks..." s'affiche en boucle

---

## 2. Tests d'API basiques

### Test 2.1 - Créer un dossier
```bash
curl -X POST http://localhost:8000/api/v1/dossiers \
  -H "Content-Type: application/json" \
  -d '{"client_nom": "Test Client", "transitaire_nom": "Test Transitaire"}'
```
Vérifier :
- Réponse HTTP 201
- Réponse contient `dossier_id` (UUID)
- Base de données : vérifier l'insertion
  ```bash
  psql $DATABASE_URL -c "SELECT id, client_nom, statut FROM dossiers LIMIT 1;"
  ```

### Test 2.2 - Lister les dossiers
```bash
curl http://localhost:8000/api/v1/dossiers?page=1
```
Vérifier :
- Réponse HTTP 200
- Réponse contient un tableau `dossiers`
- Le dossier créé en 2.1 apparaît

### Test 2.3 - Consulter un dossier
```bash
curl http://localhost:8000/api/v1/dossiers/{DOSSIER_ID}
```
Vérifier :
- Réponse HTTP 200
- Contient les champs : `id`, `client_nom`, `transitaire_nom`, `statut`
- `statut` = "incomplet"

---

## 3. Tests d'upload de fichier

### Test 3.1 - Upload d'un petit PDF valide
Prépare un fichier PDF test (~500 KB)
```bash
curl -X POST http://localhost:8000/api/v1/dossiers/{DOSSIER_ID}/documents \
  -F "type_document=BILL_OF_LADING" \
  -F "fichier=@test.pdf"
```
Vérifier :
- Réponse HTTP 202
- Réponse contient `document_id`
- Réponse contient `statut: "en_traitement"`
- Fichier existe dans `/app/uploads/YYYY/MM/`
- Base de données :
  ```bash
  psql $DATABASE_URL -c "SELECT id, statut, chemin_stockage FROM documents LIMIT 1;"
  ```

### Test 3.2 - Limites de fichier
Crée un fichier test de 60 MB (dépasse la limite 50 MB)
```bash
dd if=/dev/zero of=large.bin bs=1M count=60
curl -X POST http://localhost:8000/api/v1/dossiers/{DOSSIER_ID}/documents \
  -F "type_document=BILL_OF_LADING" \
  -F "fichier=@large.bin"
```
Vérifier :
- Réponse HTTP 413 "Fichier trop volumineux"
- Document n'est pas créé en base
- Fichier temporaire n'existe pas

### Test 3.3 - Type de document invalide
```bash
curl -X POST http://localhost:8000/api/v1/dossiers/{DOSSIER_ID}/documents \
  -F "type_document=INVALID_TYPE" \
  -F "fichier=@test.pdf"
```
Vérifier :
- Réponse HTTP 400 "Type invalide"

### Test 3.4 - Dossier inexistant
```bash
curl -X POST http://localhost:8000/api/v1/dossiers/invalid-id/documents \
  -F "type_document=BILL_OF_LADING" \
  -F "fichier=@test.pdf"
```
Vérifier :
- Réponse HTTP 404 "Dossier introuvable"
- Fichier n'est pas créé

---

## 4. Tests du pipeline OCR

### Test 4.1 - Vérifier le traitement OCR
Après avoir uploadé un document (test 3.1), attendre 10 secondes
```bash
# Vérifier dans les logs du worker
# Chercher "Processing document {ID}"
# Chercher "TASK RECEIVED"

# Vérifier en base
psql $DATABASE_URL -c "SELECT id, statut, score_confiance, traite_le FROM documents WHERE id = '{DOC_ID}';"
```
Vérifier :
- `statut` est devenu "traite" (pas d'erreur)
- `score_confiance` est entre 0.0 et 1.0
- `traite_le` est rempli
- Les logs du worker affichent "Processing document {ID}"

### Test 4.2 - Vérifier l'extraction de données
```bash
psql $DATABASE_URL -c "SELECT numero_bl, numero_declaration, numero_facture FROM dossiers WHERE id = '{DOSSIER_ID}';"
```
Vérifier :
- Pour BILL_OF_LADING : `numero_bl` doit être rempli
- Pour DECLARATION : `numero_declaration` doit être rempli
- Pour FACTURE : `numero_facture` doit être rempli

### Test 4.3 - Document scanné de mauvaise qualité
Upload un document avec OCR très faible (image floue, compressée)
Attendre le traitement
Vérifier :
- `score_confiance` < 0.3
- Les logs du worker montrent "Retry ... for transient error" (si applicable)
- Le document est finalement marqué "traite" ou "erreur"

---

## 5. Tests de robustesse - Worker

### Test 5.1 - Vérifier la gestion des erreurs
Crée un document avec un type "FACTURE" et un PDF sans numéro de facture
Upload et attendre le traitement
Vérifier :
- `statut` = "traite"
- `score_confiance` >= 0.0
- Le worker n'a pas crashé
- Pas de message d'erreur fatale en logs

### Test 5.2 - Vérifier le restart du worker
Avec un document en attente dans la file Redis :
1. Arrête le worker : `Ctrl+C`
2. Vérifier la file :
   ```bash
   redis-cli -u $REDIS_URL llen queue_ocr_processing
   ```
3. Redémarre le worker
Vérifier :
- Les tâches en attente ("queue_ocr_processing") sont remises en "queue_ocr"
- Le worker traite les tâches
- Pas de duplication

### Test 5.3 - Dead letter queue
Crée un document avec un fichier corrompu (ex: un fichier texte renommé en .pdf)
Upload
Attendre le traitement
Vérifier :
- `statut` = "erreur"
- Message en logs : "Permanent failure ... after 3 attempts"
- La tâche est dans "queue_ocr_dead"
  ```bash
  redis-cli -u $REDIS_URL llen queue_ocr_dead
  ```

---

## 6. Tests d'intégration complets

### Test 6.1 - Workflow complet BAD_DAKAR_TERMINAL
1. Créer un dossier
2. Uploader 2 documents :
   - Document 1 : DECLARATION (contient "2026 15T 32563")
   - Document 2 : BILL_OF_LADING (contient "304448001001")
3. Attendre 20 secondes (traitement OCR)
4. Consulter le dossier
Vérifier :
- `numero_bl` est rempli
- `numero_declaration` est rempli
- `statut` = "complet" (tous les champs requis sont présents)

### Test 6.2 - Workflow incomplet
1. Créer un dossier
2. Uploader un seul document DECLARATION
3. Attendre le traitement
4. Consulter le dossier
Vérifier :
- `numero_declaration` est rempli
- `numero_bl` est NULL
- `statut` = "incomplet" (manque le B/L)

### Test 6.3 - Pagination
Crée 25 dossiers
```bash
curl http://localhost:8000/api/v1/dossiers?page=1  # 20 résultats
curl http://localhost:8000/api/v1/dossiers?page=2  # 5 résultats
```
Vérifier :
- Page 1 : 20 éléments
- Page 2 : 5 éléments
- Les dossiers sont ordonnés par `cree_le DESC`

---

## 7. Tests de logging et observabilité

### Test 7.1 - Logs structurés de l'API
```bash
# Depuis les logs de l'API
# Chercher des messages du format :
# 2026-04-08 20:30:45,123 [INFO] api: Document uploaded...
```
Vérifier :
- Niveau de log correct (INFO, WARNING, ERROR)
- Timestamp présent
- Message lisible

### Test 7.2 - Logs structurés du worker
```bash
# Depuis les logs du worker
# Chercher :
# - "Processing document {ID} (dossier=..., path=...)"
# - "OCR failed for {ID}: {error}" avec stack trace
```
Vérifier :
- Stack trace complet en cas d'erreur
- Les champs du message sont clairs

---

## 8. Checklist finale

- [ ] API démarre sans erreur
- [ ] Worker démarre sans erreur
- [ ] Upload petits fichiers OK
- [ ] Limite 50 MB respectée
- [ ] OCR traite les documents
- [ ] Extraction de numéros fonctionne
- [ ] Statut "complet" détecté correctement
- [ ] Erreurs traitées sans crash
- [ ] Logs structurés et lisibles
- [ ] Dead letter queue fonctionne
- [ ] Restart worker ne duplique pas les tâches
- [ ] Pagination fonctionne

---

## 9. Checklist avant production

- [ ] Remplacer stockage local par S3/R2
- [ ] Configurer variables d'environnement (DATABASE_URL, REDIS_URL, UPLOAD_DIR)
- [ ] Tester sur base de données production (vide)
- [ ] Tester avec la charge réelle (nombre de documents attendus)
- [ ] Configurer les alertes logs
- [ ] Mettre en place la sauvegarde des uploads
- [ ] Tester le rollback (déploiement précédent)
