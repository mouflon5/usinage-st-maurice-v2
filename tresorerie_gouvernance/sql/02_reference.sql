-- =====================================================================
-- 02 - DONNÉES DE RÉFÉRENCE (DMBOK : Reference & Master Data)
-- Listes de valeurs contrôlées. Codes stables en MAJUSCULES sans accent,
-- avec période de validité (date_debut / date_fin) pour garder l'historique.
-- Règle : on ne supprime jamais un code, on le désactive (actif = 0, date_fin).
-- =====================================================================

CREATE TABLE IF NOT EXISTS ref_devise (
    code       TEXT PRIMARY KEY CHECK (length(code) = 3 AND code = upper(code)),
    libelle_fr TEXT NOT NULL,
    libelle_en TEXT NOT NULL,
    description TEXT,
    decimales  INTEGER NOT NULL DEFAULT 2 CHECK (decimales BETWEEN 0 AND 4),
    date_debut TEXT NOT NULL DEFAULT '1900-01-01',
    date_fin   TEXT,
    actif      INTEGER NOT NULL DEFAULT 1 CHECK (actif IN (0, 1)),
    CHECK (date_fin IS NULL OR date_fin >= date_debut)
);

CREATE TABLE IF NOT EXISTS ref_banque (
    code       TEXT PRIMARY KEY CHECK (code = upper(code)),
    libelle_fr TEXT NOT NULL,
    libelle_en TEXT NOT NULL,
    description TEXT,
    pays       TEXT NOT NULL DEFAULT 'CA',
    date_debut TEXT NOT NULL DEFAULT '1900-01-01',
    date_fin   TEXT,
    actif      INTEGER NOT NULL DEFAULT 1 CHECK (actif IN (0, 1)),
    CHECK (date_fin IS NULL OR date_fin >= date_debut)
);

CREATE TABLE IF NOT EXISTS ref_compte_type (
    code       TEXT PRIMARY KEY CHECK (code = upper(code)),
    libelle_fr TEXT NOT NULL,
    libelle_en TEXT NOT NULL,
    description TEXT,
    date_debut TEXT NOT NULL DEFAULT '1900-01-01',
    date_fin   TEXT,
    actif      INTEGER NOT NULL DEFAULT 1 CHECK (actif IN (0, 1)),
    CHECK (date_fin IS NULL OR date_fin >= date_debut)
);

-- Plan de trésorerie : classification des flux (état des flux de trésorerie).
CREATE TABLE IF NOT EXISTS ref_categorie_flux (
    code       TEXT PRIMARY KEY CHECK (code = upper(code)),
    libelle_fr TEXT NOT NULL,
    libelle_en TEXT NOT NULL,
    description TEXT,
    famille    TEXT NOT NULL CHECK (famille IN ('exploitation', 'investissement', 'financement', 'neutre')),
    sens       TEXT NOT NULL CHECK (sens IN ('encaissement', 'decaissement', 'neutre')),
    date_debut TEXT NOT NULL DEFAULT '1900-01-01',
    date_fin   TEXT,
    actif      INTEGER NOT NULL DEFAULT 1 CHECK (actif IN (0, 1)),
    CHECK (date_fin IS NULL OR date_fin >= date_debut)
);

CREATE TABLE IF NOT EXISTS ref_type_transaction (
    code       TEXT PRIMARY KEY CHECK (code = upper(code)),
    libelle_fr TEXT NOT NULL,
    libelle_en TEXT NOT NULL,
    description TEXT,
    date_debut TEXT NOT NULL DEFAULT '1900-01-01',
    date_fin   TEXT,
    actif      INTEGER NOT NULL DEFAULT 1 CHECK (actif IN (0, 1)),
    CHECK (date_fin IS NULL OR date_fin >= date_debut)
);

CREATE TABLE IF NOT EXISTS ref_format_releve (
    code       TEXT PRIMARY KEY CHECK (code = upper(code)),
    libelle_fr TEXT NOT NULL,
    libelle_en TEXT NOT NULL,
    description TEXT,
    extension_fichier TEXT,
    date_debut TEXT NOT NULL DEFAULT '1900-01-01',
    date_fin   TEXT,
    actif      INTEGER NOT NULL DEFAULT 1 CHECK (actif IN (0, 1)),
    CHECK (date_fin IS NULL OR date_fin >= date_debut)
);

CREATE TABLE IF NOT EXISTS ref_statut_rapprochement (
    code       TEXT PRIMARY KEY CHECK (code = upper(code)),
    libelle_fr TEXT NOT NULL,
    libelle_en TEXT NOT NULL,
    description TEXT,
    date_debut TEXT NOT NULL DEFAULT '1900-01-01',
    date_fin   TEXT,
    actif      INTEGER NOT NULL DEFAULT 1 CHECK (actif IN (0, 1)),
    CHECK (date_fin IS NULL OR date_fin >= date_debut)
);

CREATE TABLE IF NOT EXISTS ref_scenario (
    code       TEXT PRIMARY KEY CHECK (code = upper(code)),
    libelle_fr TEXT NOT NULL,
    libelle_en TEXT NOT NULL,
    description TEXT,
    ordre      INTEGER NOT NULL DEFAULT 0,
    date_debut TEXT NOT NULL DEFAULT '1900-01-01',
    date_fin   TEXT,
    actif      INTEGER NOT NULL DEFAULT 1 CHECK (actif IN (0, 1)),
    CHECK (date_fin IS NULL OR date_fin >= date_debut)
);

-- Table de correspondance : libellé bancaire normalisé -> catégorie de flux.
-- Modifiable sans toucher au code. La plus petite priorité s'applique en premier.
CREATE TABLE IF NOT EXISTS ref_mapping_libelle (
    mapping_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    motif         TEXT NOT NULL,
    type_motif    TEXT NOT NULL DEFAULT 'contient' CHECK (type_motif IN ('contient', 'commence', 'regex')),
    categorie_code TEXT NOT NULL REFERENCES ref_categorie_flux (code),
    priorite      INTEGER NOT NULL DEFAULT 100,
    actif         INTEGER NOT NULL DEFAULT 1 CHECK (actif IN (0, 1)),
    commentaire   TEXT,
    UNIQUE (motif, type_motif)
);
