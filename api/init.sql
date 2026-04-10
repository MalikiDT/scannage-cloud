# api/init.sql

-- Création des tables au premier démarrage

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE IF NOT EXISTS dossiers (
    id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    numero_bl        VARCHAR(50),
    numero_declaration VARCHAR(30),
    numero_facture   VARCHAR(30),
    client_nom       VARCHAR(200),
    transitaire_nom  VARCHAR(200),
    statut           VARCHAR(30) NOT NULL DEFAULT 'incomplet',
    cree_le          TIMESTAMP NOT NULL DEFAULT NOW(),
    mis_a_jour_le    TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS documents (
    id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    dossier_id       UUID NOT NULL REFERENCES dossiers(id) ON DELETE CASCADE,
    type_document    VARCHAR(50) NOT NULL,
    nom_fichier      VARCHAR(255),
    chemin_stockage  VARCHAR(500),
    statut           VARCHAR(30) NOT NULL DEFAULT 'recu',
    score_confiance  FLOAT,
    cree_le          TIMESTAMP NOT NULL DEFAULT NOW(),
    traite_le        TIMESTAMP
);

CREATE TABLE IF NOT EXISTS pages (
    id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_id      UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    numero_page      INTEGER NOT NULL,
    chemin_image     VARCHAR(500),
    texte_ocr        TEXT,
    score_ocr        FLOAT
);

-- Index pour accélérer les recherches fréquentes
CREATE INDEX IF NOT EXISTS idx_dossiers_numero_bl ON dossiers(numero_bl);
CREATE INDEX IF NOT EXISTS idx_dossiers_statut    ON dossiers(statut);
CREATE INDEX IF NOT EXISTS idx_documents_dossier  ON documents(dossier_id);
