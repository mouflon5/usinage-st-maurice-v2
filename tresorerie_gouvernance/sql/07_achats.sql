-- =====================================================================
-- 07 - CYCLE ACHATS-DÉCAISSEMENTS (DMBOK : Reference & Master Data, Data Modeling, Data Warehousing)
-- Du besoin d'achat au paiement du fournisseur : commande, réception, facture, appariement à trois
-- voies (commande / réception / facture), lot de paiement à double approbation, écritures comptables.
-- Mêmes conventions que le reste du modèle : montants en cents (entiers), dates ISO, codes en MAJUSCULES,
-- tables maîtres (mdm_), de référence (ref_), transactionnelles (core_) et vues de restitution (mart_).
-- =====================================================================

CREATE TABLE IF NOT EXISTS ref_condition_paiement (
    code            TEXT PRIMARY KEY CHECK (code = upper(code)),
    libelle_fr      TEXT NOT NULL,
    libelle_en      TEXT NOT NULL,
    description     TEXT,
    jours_net       INTEGER NOT NULL CHECK (jours_net >= 0),
    jours_escompte  INTEGER CHECK (jours_escompte IS NULL OR jours_escompte >= 0),
    escompte_pct    REAL CHECK (escompte_pct IS NULL OR (escompte_pct >= 0 AND escompte_pct <= 100)),
    date_debut      TEXT NOT NULL DEFAULT '1900-01-01',
    date_fin        TEXT,
    actif           INTEGER NOT NULL DEFAULT 1 CHECK (actif IN (0, 1)),
    CHECK (date_fin IS NULL OR date_fin >= date_debut)
);

CREATE TABLE IF NOT EXISTS ref_compte_comptable (
    code            TEXT PRIMARY KEY,
    libelle_fr      TEXT NOT NULL,
    libelle_en      TEXT NOT NULL,
    description     TEXT,
    classe          TEXT NOT NULL CHECK (classe IN ('actif', 'passif', 'charge')),
    date_debut      TEXT NOT NULL DEFAULT '1900-01-01',
    date_fin        TEXT,
    actif           INTEGER NOT NULL DEFAULT 1 CHECK (actif IN (0, 1)),
    CHECK (date_fin IS NULL OR date_fin >= date_debut)
);

-- Fournisseur : une seule fiche maître par fournisseur. Le rattachement à mdm_contrepartie relie la fiche
-- aux libellés des relevés bancaires (rapprochement). Un fournisseur 'a_valider' n'est pas payable ;
-- 'suspendu' signale une anomalie (ex. changement de coordonnées bancaires non confirmé par rappel).
CREATE TABLE IF NOT EXISTS mdm_fournisseur (
    fournisseur_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    nom_legal             TEXT NOT NULL UNIQUE,
    contrepartie_id       INTEGER REFERENCES mdm_contrepartie (contrepartie_id),
    famille_achat         TEXT NOT NULL CHECK (famille_achat IN ('matiere_premiere', 'transport', 'fournitures',
                                                                  'service_public', 'sous_traitance', 'services_professionnels')),
    condition_code        TEXT NOT NULL REFERENCES ref_condition_paiement (code),
    categorie_code        TEXT NOT NULL DEFAULT 'DEC_FOURNISSEURS' REFERENCES ref_categorie_flux (code),
    statut                TEXT NOT NULL DEFAULT 'a_valider' CHECK (statut IN ('a_valider', 'actif', 'suspendu', 'inactif')),
    no_tps                TEXT,
    no_tvq                TEXT,
    courriel_facturation  TEXT,
    compte_bancaire_masque TEXT,
    coordonnees_modifiees_le TEXT,
    rappel_verifie        INTEGER NOT NULL DEFAULT 0 CHECK (rappel_verifie IN (0, 1)),
    note_globale          REAL CHECK (note_globale IS NULL OR (note_globale >= 0 AND note_globale <= 5)),
    approuve_par          TEXT,
    approuve_le           TEXT,
    cree_le               TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS mdm_fournisseur_evaluation (
    evaluation_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    fournisseur_id  INTEGER NOT NULL REFERENCES mdm_fournisseur (fournisseur_id),
    trimestre       TEXT NOT NULL CHECK (trimestre GLOB '[0-9][0-9][0-9][0-9]-T[1-4]'),
    note_qualite    REAL NOT NULL CHECK (note_qualite BETWEEN 0 AND 5),
    note_delai      REAL NOT NULL CHECK (note_delai BETWEEN 0 AND 5),
    note_prix       REAL NOT NULL CHECK (note_prix BETWEEN 0 AND 5),
    note_conformite REAL NOT NULL CHECK (note_conformite BETWEEN 0 AND 5),
    commentaire     TEXT,
    UNIQUE (fournisseur_id, trimestre)
);

CREATE TABLE IF NOT EXISTS core_commande_achat (
    commande_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    no_commande         TEXT NOT NULL UNIQUE,
    fournisseur_id      INTEGER NOT NULL REFERENCES mdm_fournisseur (fournisseur_id),
    site_id             INTEGER REFERENCES mdm_site (site_id),
    site_livraison      TEXT NOT NULL,
    demandeur           TEXT NOT NULL,
    date_commande       TEXT NOT NULL CHECK (date_commande GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    date_livraison_prevue TEXT NOT NULL,
    statut              TEXT NOT NULL CHECK (statut IN ('attente_approbation', 'approuvee', 'recue_partielle', 'recue', 'close', 'annulee')),
    montant_ht_cents    INTEGER NOT NULL CHECK (montant_ht_cents >= 0),
    approuve_par        TEXT,
    approuve_le         TEXT,
    niveau_approbation  INTEGER NOT NULL DEFAULT 1 CHECK (niveau_approbation BETWEEN 1 AND 3),
    cree_le             TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS core_commande_achat_ligne (
    ligne_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    commande_id         INTEGER NOT NULL REFERENCES core_commande_achat (commande_id),
    no_ligne            INTEGER NOT NULL CHECK (no_ligne >= 1),
    produit             TEXT NOT NULL,
    unite               TEXT NOT NULL,
    quantite            REAL NOT NULL CHECK (quantite > 0),
    prix_unitaire_cents REAL NOT NULL CHECK (prix_unitaire_cents >= 0),
    montant_cents       INTEGER NOT NULL CHECK (montant_cents >= 0),
    compte_code         TEXT NOT NULL REFERENCES ref_compte_comptable (code),
    UNIQUE (commande_id, no_ligne)
);

-- Une ligne de réception = ce qui est entré au magasin (pesée ou comptage) ou le service constaté.
CREATE TABLE IF NOT EXISTS core_reception (
    reception_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ligne_id            INTEGER NOT NULL REFERENCES core_commande_achat_ligne (ligne_id),
    no_bon_livraison    TEXT NOT NULL,
    date_reception      TEXT NOT NULL CHECK (date_reception GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    quantite_recue      REAL NOT NULL CHECK (quantite_recue >= 0),
    conforme            INTEGER NOT NULL DEFAULT 1 CHECK (conforme IN (0, 1)),
    recu_par            TEXT NOT NULL,
    commentaire         TEXT,
    cree_le             TEXT NOT NULL DEFAULT (datetime('now'))
);

-- commande_id NULL = facture sans bon de commande (permis seulement pour les achats récurrents préautorisés).
CREATE TABLE IF NOT EXISTS core_facture_fournisseur (
    facture_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    no_facture          TEXT NOT NULL,
    fournisseur_id      INTEGER NOT NULL REFERENCES mdm_fournisseur (fournisseur_id),
    commande_id         INTEGER REFERENCES core_commande_achat (commande_id),
    date_facture        TEXT NOT NULL CHECK (date_facture GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    date_reception_facture TEXT NOT NULL,
    date_echeance       TEXT NOT NULL,
    date_limite_escompte TEXT,
    montant_ht_cents    INTEGER NOT NULL CHECK (montant_ht_cents >= 0),
    tps_cents           INTEGER NOT NULL DEFAULT 0 CHECK (tps_cents >= 0),
    tvq_cents           INTEGER NOT NULL DEFAULT 0 CHECK (tvq_cents >= 0),
    total_cents         INTEGER NOT NULL CHECK (total_cents >= 0),
    escompte_cents      INTEGER NOT NULL DEFAULT 0 CHECK (escompte_cents >= 0),
    ecart_prix_pct      REAL,
    ecart_quantite_pct  REAL,
    statut              TEXT NOT NULL CHECK (statut IN ('recue', 'appariee', 'ecart', 'approuvee', 'en_lot', 'payee', 'contestee')),
    approuve_par        TEXT,
    approuve_le         TEXT,
    motif_ecart         TEXT,
    cree_le             TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS core_lot_paiement (
    lot_id              INTEGER PRIMARY KEY AUTOINCREMENT,
    no_lot              TEXT NOT NULL UNIQUE,
    date_paiement       TEXT NOT NULL CHECK (date_paiement GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    mode_paiement       TEXT NOT NULL CHECK (mode_paiement IN ('EFT', 'CHEQUE', 'CARTE', 'PREAUTORISE')),
    compte_id           INTEGER REFERENCES mdm_compte (compte_id),
    statut              TEXT NOT NULL CHECK (statut IN ('prepare', 'approuve_1', 'approuve', 'execute', 'annule')),
    prepare_par         TEXT NOT NULL,
    approbateur_1       TEXT,
    approbateur_2       TEXT,
    cree_le             TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS core_paiement_fournisseur (
    paiement_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    lot_id              INTEGER NOT NULL REFERENCES core_lot_paiement (lot_id),
    facture_id          INTEGER NOT NULL REFERENCES core_facture_fournisseur (facture_id),
    fournisseur_id      INTEGER NOT NULL REFERENCES mdm_fournisseur (fournisseur_id),
    montant_cents       INTEGER NOT NULL CHECK (montant_cents >= 0),
    escompte_pris_cents INTEGER NOT NULL DEFAULT 0 CHECK (escompte_pris_cents >= 0),
    statut_rapprochement TEXT NOT NULL DEFAULT 'NON_RAPPROCHE' REFERENCES ref_statut_rapprochement (code),
    mouvement_id        INTEGER REFERENCES core_mouvement (mouvement_id),
    cree_le             TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Journal du cycle : une écriture = au moins deux lignes dont le total des débits égale celui des crédits.
CREATE TABLE IF NOT EXISTS core_ecriture_achat (
    ligne_ecriture_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    no_ecriture         TEXT NOT NULL,
    date_ecriture       TEXT NOT NULL CHECK (date_ecriture GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    evenement           TEXT NOT NULL CHECK (evenement IN ('reception', 'facture', 'paiement')),
    document_ref        TEXT NOT NULL,
    compte_code         TEXT NOT NULL REFERENCES ref_compte_comptable (code),
    debit_cents         INTEGER NOT NULL DEFAULT 0 CHECK (debit_cents >= 0),
    credit_cents        INTEGER NOT NULL DEFAULT 0 CHECK (credit_cents >= 0),
    libelle             TEXT,
    CHECK (debit_cents = 0 OR credit_cents = 0)
);

CREATE INDEX IF NOT EXISTS ix_facture_fournisseur ON core_facture_fournisseur (fournisseur_id, statut);
CREATE INDEX IF NOT EXISTS ix_commande_fournisseur ON core_commande_achat (fournisseur_id);
CREATE INDEX IF NOT EXISTS ix_ecriture_ref ON core_ecriture_achat (document_ref);

-- ---------------------------------------------------------------------
-- Vues de restitution
-- ---------------------------------------------------------------------
-- Appariement à trois voies : quantité commandée, reçue et facturée, prix commandé et facturé, par facture.
DROP VIEW IF EXISTS mart_appariement_3_voies;
CREATE VIEW mart_appariement_3_voies AS
SELECT f.facture_id, f.no_facture, fo.nom_legal AS fournisseur, c.no_commande,
       f.montant_ht_cents AS facture_ht_cents,
       (SELECT SUM(l.montant_cents) FROM core_commande_achat_ligne l WHERE l.commande_id = f.commande_id) AS commande_ht_cents,
       (SELECT CAST(ROUND(SUM(r.quantite_recue * l.prix_unitaire_cents)) AS INTEGER)
          FROM core_reception r JOIN core_commande_achat_ligne l ON l.ligne_id = r.ligne_id
         WHERE l.commande_id = f.commande_id) AS recu_ht_cents,
       f.ecart_prix_pct, f.ecart_quantite_pct, f.statut, f.motif_ecart
  FROM core_facture_fournisseur f
  JOIN mdm_fournisseur fo ON fo.fournisseur_id = f.fournisseur_id
  LEFT JOIN core_commande_achat c ON c.commande_id = f.commande_id;

-- Échéancier des comptes fournisseurs : ce qui reste à payer, ancienneté par rapport à aujourd'hui.
DROP VIEW IF EXISTS mart_echeancier_fournisseurs;
CREATE VIEW mart_echeancier_fournisseurs AS
SELECT f.facture_id, fo.nom_legal AS fournisseur, fo.famille_achat, f.no_facture, f.date_facture, f.date_echeance,
       f.date_limite_escompte, f.total_cents, f.escompte_cents, f.statut,
       CAST(julianday(date('now')) - julianday(f.date_echeance) AS INTEGER) AS jours_retard
  FROM core_facture_fournisseur f
  JOIN mdm_fournisseur fo ON fo.fournisseur_id = f.fournisseur_id
 WHERE f.statut NOT IN ('payee', 'contestee');

-- ---------------------------------------------------------------------
-- Valeurs de référence du cycle
-- ---------------------------------------------------------------------
INSERT OR IGNORE INTO ref_condition_paiement (code, libelle_fr, libelle_en, description, jours_net, jours_escompte, escompte_pct) VALUES
 ('COMPTANT', 'Comptant', 'Cash', 'Payable à la réception ou prélevé à l''avance (assurances, primes).', 0, NULL, NULL),
 ('N30', 'Net 30 jours', 'Net 30', 'Payable 30 jours après la date de la facture.', 30, NULL, NULL),
 ('N45', 'Net 45 jours', 'Net 45', 'Payable 45 jours après la date de la facture.', 45, NULL, NULL),
 ('2_10_N30', '2 % à 10 jours, net 30', '2/10 net 30', 'Escompte de 2 % si payé dans les 10 jours, sinon net à 30 jours.', 30, 10, 2.0);

INSERT OR IGNORE INTO ref_compte_comptable (code, libelle_fr, libelle_en, description, classe) VALUES
 ('1000', 'Encaisse — Desjardins exploitation', 'Cash — operating account', 'Compte bancaire d''exploitation.', 'actif'),
 ('1210', 'TPS à recevoir (crédit de taxe sur les intrants)', 'GST receivable', 'TPS payée aux fournisseurs, récupérable.', 'actif'),
 ('1220', 'TVQ à recevoir (remboursement de taxe sur les intrants)', 'QST receivable', 'TVQ payée aux fournisseurs, récupérable.', 'actif'),
 ('1300', 'Stocks de matières premières', 'Raw materials inventory', 'Acier, aluminium, inox et titane en barres et en plaques.', 'actif'),
 ('1310', 'Stocks d''outillage et de fournitures', 'Tooling and supplies inventory', 'Plaquettes, fraises, outils de coupe et consommables.', 'actif'),
 ('2100', 'Comptes fournisseurs', 'Accounts payable', 'Factures reçues et approuvées, non encore payées.', 'passif'),
 ('2105', 'Achats reçus non facturés', 'Goods received not invoiced', 'Réceptions dont la facture n''est pas encore arrivée.', 'passif'),
 ('5100', 'Achats de matières premières', 'Raw material purchases', 'Coût des matières achetées pour la production.', 'charge'),
 ('5190', 'Écart sur prix d''achat', 'Purchase price variance', 'Différence entre le prix facturé et le prix commandé.', 'charge'),
 ('5200', 'Fret et transport', 'Freight', 'Transport ferroviaire et routier des produits.', 'charge'),
 ('5300', 'Sous-traitance et services', 'Subcontracting and services', 'Traitement thermique, galvanisation, formation.', 'charge'),
 ('5400', 'Énergie et télécommunications', 'Utilities', 'Électricité, téléphonie et TI.', 'charge'),
 ('5900', 'Escomptes sur achats', 'Purchase discounts', 'Escomptes de paiement rapide obtenus des fournisseurs.', 'charge');
