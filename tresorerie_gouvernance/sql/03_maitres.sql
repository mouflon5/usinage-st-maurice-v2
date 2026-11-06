-- =====================================================================
-- 03 - DONNÉES MAÎTRES (DMBOK : Master Data Management)
-- Entités stables partagées par tous les agents : une seule version de la vérité
-- ("golden record") par entité juridique, compte, contrepartie, site, facilité.
-- =====================================================================

CREATE TABLE IF NOT EXISTS mdm_entite_juridique (
    entite_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    nom_legal   TEXT NOT NULL UNIQUE,
    nom_court   TEXT,
    devise_code TEXT NOT NULL DEFAULT 'CAD' REFERENCES ref_devise (code),
    actif       INTEGER NOT NULL DEFAULT 1 CHECK (actif IN (0, 1)),
    cree_le     TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Le numéro de compte complet n'est JAMAIS stocké : seulement une version masquée
-- (affichage) et un hash salé (rapprochement / unicité).
CREATE TABLE IF NOT EXISTS mdm_compte (
    compte_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    entite_id       INTEGER NOT NULL REFERENCES mdm_entite_juridique (entite_id),
    banque_code     TEXT NOT NULL REFERENCES ref_banque (code),
    type_code       TEXT NOT NULL REFERENCES ref_compte_type (code),
    devise_code     TEXT NOT NULL DEFAULT 'CAD' REFERENCES ref_devise (code),
    numero_masque   TEXT NOT NULL,
    numero_hash     TEXT NOT NULL,
    libelle         TEXT,
    date_ouverture  TEXT,
    date_fermeture  TEXT,
    actif           INTEGER NOT NULL DEFAULT 1 CHECK (actif IN (0, 1)),
    cree_le         TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (banque_code, numero_hash),
    CHECK (date_fermeture IS NULL OR date_ouverture IS NULL OR date_fermeture >= date_ouverture)
);

-- Contrepartie : client, fournisseur, employé, gouvernement, institution financière...
-- Une contrepartie "a_valider" a été créée automatiquement et attend une revue humaine.
-- Une contrepartie fusionnée pointe vers sa survivante (fusionne_vers_id) et devient inactive.
CREATE TABLE IF NOT EXISTS mdm_contrepartie (
    contrepartie_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    nom_canonique     TEXT NOT NULL,
    type_contrepartie TEXT NOT NULL DEFAULT 'autre'
                      CHECK (type_contrepartie IN ('client', 'fournisseur', 'employe', 'gouvernement',
                                                   'institution_financiere', 'interne', 'autre')),
    statut_validation TEXT NOT NULL DEFAULT 'a_valider'
                      CHECK (statut_validation IN ('valide', 'a_valider', 'rejete')),
    source_creation   TEXT NOT NULL DEFAULT 'manuel',
    fusionne_vers_id  INTEGER REFERENCES mdm_contrepartie (contrepartie_id),
    actif             INTEGER NOT NULL DEFAULT 1 CHECK (actif IN (0, 1)),
    cree_le           TEXT NOT NULL DEFAULT (datetime('now')),
    CHECK (fusionne_vers_id IS NULL OR fusionne_vers_id <> contrepartie_id)
);

-- Alias : toutes les façons dont une contrepartie apparaît dans les relevés bancaires.
CREATE TABLE IF NOT EXISTS mdm_contrepartie_alias (
    alias_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    contrepartie_id INTEGER NOT NULL REFERENCES mdm_contrepartie (contrepartie_id),
    alias_normalise TEXT NOT NULL UNIQUE,
    alias_brut      TEXT,
    source          TEXT NOT NULL DEFAULT 'auto',
    confiance       REAL NOT NULL DEFAULT 1.0 CHECK (confiance >= 0 AND confiance <= 1),
    cree_le         TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS mdm_site (
    site_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    entite_id  INTEGER NOT NULL REFERENCES mdm_entite_juridique (entite_id),
    nom        TEXT NOT NULL,
    type_site  TEXT NOT NULL DEFAULT 'autre' CHECK (type_site IN ('magasin', 'usine', 'siege', 'autre')),
    actif      INTEGER NOT NULL DEFAULT 1 CHECK (actif IN (0, 1)),
    UNIQUE (entite_id, nom)
);

CREATE TABLE IF NOT EXISTS mdm_facilite (
    facilite_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    entite_id      INTEGER NOT NULL REFERENCES mdm_entite_juridique (entite_id),
    banque_code    TEXT NOT NULL REFERENCES ref_banque (code),
    type_facilite  TEXT NOT NULL CHECK (type_facilite IN ('marge', 'pret_terme', 'carte_credit', 'credit_bail', 'autre')),
    limite_cents   INTEGER CHECK (limite_cents IS NULL OR limite_cents >= 0),
    taux_pct       REAL,
    date_echeance  TEXT,
    actif          INTEGER NOT NULL DEFAULT 1 CHECK (actif IN (0, 1))
);

CREATE INDEX IF NOT EXISTS idx_mdm_compte_entite ON mdm_compte (entite_id);
CREATE INDEX IF NOT EXISTS idx_mdm_alias_contrepartie ON mdm_contrepartie_alias (contrepartie_id);
