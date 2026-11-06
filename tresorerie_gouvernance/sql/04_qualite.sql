-- =====================================================================
-- 04 - QUALITÉ DES DONNÉES (DMBOK : Data Quality)
-- Règles (dq_regle), exécutions (dq_execution), résultats (dq_resultat)
-- et file de quarantaine / revue (stg_rejet).
-- Les règles elles-mêmes sont versionnées dans dq_regles.py et chargées par dq_runner.py.
-- =====================================================================

CREATE TABLE IF NOT EXISTS dq_regle (
    regle_id       TEXT PRIMARY KEY,
    nom            TEXT NOT NULL,
    description    TEXT,
    dimension      TEXT NOT NULL CHECK (dimension IN ('completude', 'validite', 'unicite', 'coherence',
                                                      'exactitude', 'ponctualite', 'integrite')),
    cible_table    TEXT NOT NULL,
    severite       TEXT NOT NULL CHECK (severite IN ('bloquante', 'avertissement', 'info')),
    sql_violations TEXT NOT NULL,
    sql_total      TEXT NOT NULL,
    seuil_pct      REAL NOT NULL DEFAULT 100 CHECK (seuil_pct >= 0 AND seuil_pct <= 100),
    actif          INTEGER NOT NULL DEFAULT 1 CHECK (actif IN (0, 1)),
    version        INTEGER NOT NULL DEFAULT 1,
    maj_le         TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS dq_execution (
    execution_id       TEXT PRIMARY KEY,
    run_id             TEXT REFERENCES meta_run (run_id),
    portee             TEXT NOT NULL CHECK (portee IN ('run', 'complet')),
    execute_le         TEXT NOT NULL DEFAULT (datetime('now')),
    score_global       REAL,
    nb_regles          INTEGER,
    nb_echecs          INTEGER,
    nb_bloquants_echec INTEGER
);

CREATE TABLE IF NOT EXISTS dq_resultat (
    resultat_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    execution_id TEXT NOT NULL REFERENCES dq_execution (execution_id),
    regle_id     TEXT NOT NULL REFERENCES dq_regle (regle_id),
    nb_evalue    INTEGER NOT NULL,
    nb_violation INTEGER NOT NULL,
    score_pct    REAL NOT NULL,
    statut       TEXT NOT NULL CHECK (statut IN ('pass', 'fail')),
    detail_json  TEXT,
    UNIQUE (execution_id, regle_id)
);

-- File de quarantaine / revue : éléments à examiner par un humain (ou par l'agent A6).
-- regle_id n'a pas de clé étrangère : les rejets à l'entrée utilisent le préfixe "PRE-".
CREATE TABLE IF NOT EXISTS stg_rejet (
    rejet_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    execution_id       TEXT REFERENCES dq_execution (execution_id),
    run_id             TEXT REFERENCES meta_run (run_id),
    table_source       TEXT NOT NULL,
    cle_source         INTEGER,
    regle_id           TEXT NOT NULL,
    motif              TEXT NOT NULL,
    payload_json       TEXT,
    rejete_le          TEXT NOT NULL DEFAULT (datetime('now')),
    statut_traitement  TEXT NOT NULL DEFAULT 'a_revoir' CHECK (statut_traitement IN ('a_revoir', 'corrige', 'ignore'))
);

CREATE INDEX IF NOT EXISTS idx_dq_resultat_regle ON dq_resultat (regle_id);
CREATE INDEX IF NOT EXISTS idx_stg_rejet_statut ON stg_rejet (statut_traitement, regle_id);
