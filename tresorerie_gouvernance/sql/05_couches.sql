-- =====================================================================
-- 05 - COUCHES DE DONNÉES (DMBOK : Data Modeling & Design, Data Warehousing & BI)
--   stg_  : zone d'arrivée, texte brut tel que lu par A1/A2 (aucune interprétation)
--   core_ : données normalisées, typées, contrôlées, avec lineage
--   dim_  : dimensions
--   mart_ : vues de restitution (alimentent R0 à R7 et le dashboard)
-- Convention monétaire : entiers en cents, JAMAIS de float. Dates : texte ISO AAAA-MM-JJ.
-- Convention de signe  : montant_cents > 0 = encaissement, < 0 = décaissement.
-- =====================================================================

CREATE TABLE IF NOT EXISTS stg_releve_ligne (
    stg_id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id              TEXT REFERENCES meta_run (run_id),
    fichier_id          INTEGER REFERENCES meta_fichier_source (fichier_id),
    format_code         TEXT REFERENCES ref_format_releve (code),
    ligne_no            INTEGER,
    compte_ref_brut     TEXT,
    date_operation_brut TEXT,
    date_valeur_brut    TEXT,
    libelle_brut        TEXT,
    montant_brut        TEXT,
    debit_brut          TEXT,
    credit_brut         TEXT,
    solde_brut          TEXT,
    devise_brut         TEXT,
    charge_json         TEXT,
    cree_le             TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS core_mouvement (
    mouvement_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    compte_id             INTEGER NOT NULL REFERENCES mdm_compte (compte_id),
    date_operation        TEXT NOT NULL CHECK (date_operation GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    date_valeur           TEXT CHECK (date_valeur IS NULL OR date_valeur GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    libelle_brut          TEXT NOT NULL,
    libelle_normalise     TEXT NOT NULL,
    montant_cents         INTEGER NOT NULL,
    devise_code           TEXT NOT NULL REFERENCES ref_devise (code),
    type_transaction_code TEXT NOT NULL DEFAULT 'AUTRE' REFERENCES ref_type_transaction (code),
    categorie_code        TEXT NOT NULL DEFAULT 'NON_CLASSE' REFERENCES ref_categorie_flux (code),
    contrepartie_id       INTEGER REFERENCES mdm_contrepartie (contrepartie_id),
    statut_rapprochement  TEXT NOT NULL DEFAULT 'NON_RAPPROCHE' REFERENCES ref_statut_rapprochement (code),
    statut_dq             TEXT NOT NULL DEFAULT 'ok' CHECK (statut_dq IN ('ok', 'avertissement', 'quarantaine')),
    hash_transaction      TEXT NOT NULL UNIQUE,
    run_id                TEXT REFERENCES meta_run (run_id),
    fichier_id            INTEGER REFERENCES meta_fichier_source (fichier_id),
    stg_id                INTEGER REFERENCES stg_releve_ligne (stg_id),
    cree_le               TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS core_solde_releve (
    solde_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    compte_id   INTEGER NOT NULL REFERENCES mdm_compte (compte_id),
    date_solde  TEXT NOT NULL CHECK (date_solde GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    solde_cents INTEGER NOT NULL,
    source      TEXT NOT NULL DEFAULT 'releve' CHECK (source IN ('releve', 'calcule')),
    run_id      TEXT REFERENCES meta_run (run_id),
    cree_le     TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (compte_id, date_solde, source)
);

CREATE TABLE IF NOT EXISTS core_prevision (
    prevision_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    scenario_code  TEXT NOT NULL REFERENCES ref_scenario (code),
    compte_id      INTEGER REFERENCES mdm_compte (compte_id),
    date_prevue    TEXT NOT NULL CHECK (date_prevue GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    categorie_code TEXT NOT NULL REFERENCES ref_categorie_flux (code),
    montant_cents  INTEGER NOT NULL,
    run_id         TEXT REFERENCES meta_run (run_id),
    cree_le        TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS dim_date (
    date_id      TEXT PRIMARY KEY,
    annee        INTEGER NOT NULL,
    trimestre    INTEGER NOT NULL,
    mois         INTEGER NOT NULL,
    jour         INTEGER NOT NULL,
    semaine_iso  INTEGER NOT NULL,
    jour_semaine INTEGER NOT NULL,
    est_ouvrable INTEGER NOT NULL,
    fin_de_mois  INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_stg_ligne_run     ON stg_releve_ligne (run_id);
CREATE INDEX IF NOT EXISTS idx_stg_ligne_fichier ON stg_releve_ligne (fichier_id);
CREATE INDEX IF NOT EXISTS idx_mouv_compte_date  ON core_mouvement (compte_id, date_operation);
CREATE INDEX IF NOT EXISTS idx_mouv_categorie    ON core_mouvement (categorie_code);
CREATE INDEX IF NOT EXISTS idx_mouv_contrepartie ON core_mouvement (contrepartie_id);
CREATE INDEX IF NOT EXISTS idx_mouv_run          ON core_mouvement (run_id);
CREATE INDEX IF NOT EXISTS idx_prev_scenario     ON core_prevision (scenario_code, date_prevue);

-- ---------------------------------------------------------------------
-- Vues de restitution (mart_). Les mouvements en quarantaine en sont exclus.
-- ---------------------------------------------------------------------
DROP VIEW IF EXISTS mart_mouvement_quotidien;
CREATE VIEW mart_mouvement_quotidien AS
SELECT m.compte_id,
       c.entite_id,
       m.date_operation AS date_id,
       SUM(CASE WHEN m.montant_cents > 0 THEN m.montant_cents ELSE 0 END)  AS encaissements_cents,
       SUM(CASE WHEN m.montant_cents < 0 THEN -m.montant_cents ELSE 0 END) AS decaissements_cents,
       SUM(m.montant_cents)                                               AS net_cents,
       COUNT(*)                                                           AS nb_mouvements
FROM core_mouvement m
JOIN mdm_compte c ON c.compte_id = m.compte_id
WHERE m.statut_dq <> 'quarantaine'
GROUP BY m.compte_id, c.entite_id, m.date_operation;

-- Flux consolidés par entité : les transferts internes sont exclus (ils s'annulent).
DROP VIEW IF EXISTS mart_flux_mensuel;
CREATE VIEW mart_flux_mensuel AS
SELECT c.entite_id,
       substr(m.date_operation, 1, 7) AS mois,
       f.famille,
       m.categorie_code,
       f.libelle_fr AS categorie_libelle,
       SUM(CASE WHEN m.montant_cents > 0 THEN m.montant_cents ELSE 0 END)  AS encaissements_cents,
       SUM(CASE WHEN m.montant_cents < 0 THEN -m.montant_cents ELSE 0 END) AS decaissements_cents,
       SUM(m.montant_cents)                                               AS net_cents
FROM core_mouvement m
JOIN mdm_compte c ON c.compte_id = m.compte_id
JOIN ref_categorie_flux f ON f.code = m.categorie_code
WHERE m.statut_dq <> 'quarantaine'
  AND m.categorie_code <> 'TRF_INTERNE'
GROUP BY c.entite_id, substr(m.date_operation, 1, 7), f.famille, m.categorie_code, f.libelle_fr;

-- Dernière exécution de la qualité des données, règle par règle (pour le dashboard).
DROP VIEW IF EXISTS mart_dq_derniere_execution;
CREATE VIEW mart_dq_derniere_execution AS
SELECT r.execution_id,
       e.execute_le,
       r.regle_id,
       g.nom,
       g.dimension,
       g.severite,
       r.nb_evalue,
       r.nb_violation,
       r.score_pct,
       r.statut
FROM dq_resultat r
JOIN dq_execution e ON e.execution_id = r.execution_id
JOIN dq_regle g ON g.regle_id = r.regle_id
WHERE r.execution_id = (SELECT execution_id FROM dq_execution ORDER BY rowid DESC LIMIT 1);

-- File de revue MDM : contreparties créées automatiquement et non validées.
DROP VIEW IF EXISTS mart_contreparties_a_valider;
CREATE VIEW mart_contreparties_a_valider AS
SELECT p.contrepartie_id,
       p.nom_canonique,
       (SELECT COUNT(*) FROM mdm_contrepartie_alias a WHERE a.contrepartie_id = p.contrepartie_id) AS nb_alias,
       (SELECT COUNT(*) FROM core_mouvement m WHERE m.contrepartie_id = p.contrepartie_id)         AS nb_mouvements
FROM mdm_contrepartie p
WHERE p.statut_validation = 'a_valider' AND p.actif = 1 AND p.fusionne_vers_id IS NULL;
