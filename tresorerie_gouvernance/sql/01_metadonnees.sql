-- =====================================================================
-- 01 - MÉTADONNÉES (DMBOK : Metadata Management)
-- Dictionnaire de données, glossaire métier, lineage (runs + fichiers).
-- Idempotent : peut être rejoué sans effet sur les données existantes.
-- =====================================================================

CREATE TABLE IF NOT EXISTS meta_version_schema (
    version      TEXT PRIMARY KEY,
    appliquee_le TEXT NOT NULL DEFAULT (datetime('now')),
    description  TEXT NOT NULL
);

-- Dictionnaire de données : une ligne par champ de table ou de vue.
-- Alimenté par dictionnaire.py (introspection du schéma + descriptions_champs.py).
CREATE TABLE IF NOT EXISTS meta_champ (
    champ_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    table_nom         TEXT NOT NULL,
    champ_nom         TEXT NOT NULL,
    type_donnee       TEXT,
    nullable          INTEGER NOT NULL DEFAULT 1 CHECK (nullable IN (0, 1)),
    definition_metier TEXT NOT NULL,
    unite             TEXT,
    regle_validation  TEXT,
    source            TEXT,
    sensibilite       TEXT NOT NULL DEFAULT 'interne'
                      CHECK (sensibilite IN ('public', 'interne', 'confidentiel', 'restreint')),
    proprietaire      TEXT,
    exemple           TEXT,
    version_schema    TEXT,
    maj_le            TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (table_nom, champ_nom)
);

-- Glossaire métier : vocabulaire commun entre la finance, les agents et le dashboard.
CREATE TABLE IF NOT EXISTS meta_glossaire (
    terme      TEXT PRIMARY KEY,
    definition TEXT NOT NULL,
    synonymes  TEXT,
    reference  TEXT
);

-- Lineage : chaque exécution d'un agent ou d'un traitement.
CREATE TABLE IF NOT EXISTS meta_run (
    run_id          TEXT PRIMARY KEY,
    agent           TEXT NOT NULL,
    debut           TEXT NOT NULL DEFAULT (datetime('now')),
    fin             TEXT,
    statut          TEXT NOT NULL DEFAULT 'en_cours'
                    CHECK (statut IN ('en_cours', 'succes', 'echec', 'partiel')),
    parametres_json TEXT,
    version_schema  TEXT
);

-- Lineage : chaque fichier source reçu (le hash empêche de réingérer deux fois le même fichier).
CREATE TABLE IF NOT EXISTS meta_fichier_source (
    fichier_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    nom_fichier   TEXT NOT NULL,
    hash_sha256   TEXT NOT NULL UNIQUE,
    format_code   TEXT REFERENCES ref_format_releve (code),
    banque_code   TEXT REFERENCES ref_banque (code),
    taille_octets INTEGER,
    recu_le       TEXT NOT NULL DEFAULT (datetime('now')),
    run_id        TEXT REFERENCES meta_run (run_id)
);

CREATE INDEX IF NOT EXISTS idx_meta_run_agent ON meta_run (agent, debut);
