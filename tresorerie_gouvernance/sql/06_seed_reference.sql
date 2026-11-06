-- =====================================================================
-- 06 - VALEURS INITIALES des données de référence et du glossaire
-- INSERT OR IGNORE : ne remplace jamais une valeur déjà modifiée par l'utilisateur.
-- À ajuster selon votre réalité (surtout ref_format_releve et ref_mapping_libelle).
-- =====================================================================

INSERT OR IGNORE INTO ref_devise (code, libelle_fr, libelle_en, decimales) VALUES
 ('CAD', 'Dollar canadien',  'Canadian dollar', 2),
 ('USD', 'Dollar américain', 'US dollar',       2),
 ('EUR', 'Euro',             'Euro',            2);

INSERT OR IGNORE INTO ref_banque (code, libelle_fr, libelle_en) VALUES
 ('DESJ',   'Desjardins',                 'Desjardins'),
 ('BNC',    'Banque Nationale du Canada', 'National Bank of Canada'),
 ('RBC',    'Banque Royale du Canada',    'Royal Bank of Canada'),
 ('TD',     'Banque Toronto-Dominion',    'Toronto-Dominion Bank'),
 ('BMO',    'Banque de Montréal',         'Bank of Montreal'),
 ('SCOTIA', 'Banque Scotia',              'Scotiabank'),
 ('CIBC',   'Banque CIBC',                'CIBC'),
 ('AUTRE',  'Autre institution',          'Other institution');

INSERT OR IGNORE INTO ref_compte_type (code, libelle_fr, libelle_en) VALUES
 ('EXPLOITATION', 'Compte d''exploitation', 'Operating account'),
 ('PAIE',         'Compte de paie',         'Payroll account'),
 ('DEVISES',      'Compte en devises',      'Foreign currency account'),
 ('EPARGNE',      'Compte d''épargne',      'Savings account'),
 ('MARGE',        'Marge de crédit',        'Line of credit'),
 ('CARTE_CREDIT', 'Carte de crédit',        'Credit card'),
 ('PLACEMENT',    'Placement',              'Investment');

INSERT OR IGNORE INTO ref_categorie_flux (code, libelle_fr, libelle_en, famille, sens) VALUES
 ('ENC_CLIENTS',               'Encaissements clients',                 'Customer receipts',            'exploitation',   'encaissement'),
 ('ENC_SUBVENTIONS',           'Subventions et crédits reçus',          'Grants and credits received',  'exploitation',   'encaissement'),
 ('ENC_REMB_TAXES',            'Remboursements de taxes (TPS/TVQ)',     'Sales tax refunds',            'exploitation',   'encaissement'),
 ('ENC_INTERETS',              'Intérêts reçus',                        'Interest received',            'exploitation',   'encaissement'),
 ('ENC_AUTRES',                'Autres encaissements d''exploitation',  'Other operating receipts',     'exploitation',   'encaissement'),
 ('DEC_FOURNISSEURS',          'Paiements aux fournisseurs',            'Supplier payments',            'exploitation',   'decaissement'),
 ('DEC_SALAIRES',              'Salaires et avantages',                 'Payroll',                      'exploitation',   'decaissement'),
 ('DEC_CHARGES_SOCIALES',      'Retenues à la source et charges sociales', 'Payroll deductions and contributions', 'exploitation', 'decaissement'),
 ('DEC_LOYER',                 'Loyers',                                'Rent',                         'exploitation',   'decaissement'),
 ('DEC_SERVICES_PUBLICS',      'Services publics',                      'Utilities',                    'exploitation',   'decaissement'),
 ('DEC_ASSURANCES',            'Assurances',                            'Insurance',                    'exploitation',   'decaissement'),
 ('DEC_TAXES_VENTE',           'Remises de TPS/TVQ',                    'Sales tax remittances',        'exploitation',   'decaissement'),
 ('DEC_IMPOTS',                'Impôts sur le résultat',                'Income taxes',                 'exploitation',   'decaissement'),
 ('DEC_FRAIS_BANCAIRES',       'Frais bancaires',                       'Bank fees',                    'exploitation',   'decaissement'),
 ('DEC_AUTRES',                'Autres décaissements d''exploitation',  'Other operating payments',     'exploitation',   'decaissement'),
 ('INV_ACQUISITION_IMMOB',     'Acquisition d''immobilisations',        'Capital expenditures',         'investissement', 'decaissement'),
 ('INV_CESSION_IMMOB',         'Cession d''immobilisations',            'Disposal of fixed assets',     'investissement', 'encaissement'),
 ('FIN_EMPRUNT_ENCAISSEMENT',  'Encaissement d''emprunt',               'Loan proceeds',                'financement',    'encaissement'),
 ('FIN_EMPRUNT_REMBOURSEMENT', 'Remboursement de capital d''emprunt',   'Loan principal repayment',     'financement',    'decaissement'),
 ('FIN_INTERETS_PAYES',        'Intérêts payés',                        'Interest paid',                'financement',    'decaissement'),
 ('FIN_DIVIDENDES',            'Dividendes versés',                     'Dividends paid',               'financement',    'decaissement'),
 ('FIN_APPORT_CAPITAL',        'Apport en capital',                     'Capital contribution',         'financement',    'encaissement'),
 ('TRF_INTERNE',               'Transfert entre comptes de l''entité',  'Internal transfer',            'neutre',         'neutre'),
 ('NON_CLASSE',                'Non classé (à catégoriser)',            'Unclassified',                 'neutre',         'neutre');

INSERT OR IGNORE INTO ref_type_transaction (code, libelle_fr, libelle_en) VALUES
 ('VIREMENT', 'Virement',                    'Transfer'),
 ('DEPOT',    'Dépôt',                       'Deposit'),
 ('RETRAIT',  'Retrait',                     'Withdrawal'),
 ('CHEQUE',   'Chèque',                      'Cheque'),
 ('PAD',      'Prélèvement préautorisé',     'Pre-authorized debit'),
 ('INTERAC',  'Paiement Interac',            'Interac payment'),
 ('CARTE',    'Achat par carte',             'Card purchase'),
 ('FRAIS',    'Frais bancaires',             'Bank fee'),
 ('INTERET',  'Intérêts',                    'Interest'),
 ('AUTRE',    'Autre',                       'Other');

-- Hypothèse : 4 formats d'entrée. À remplacer par vos 4 formats réels si différents.
INSERT OR IGNORE INTO ref_format_releve (code, libelle_fr, libelle_en, extension_fichier) VALUES
 ('PDF_TEXTE', 'PDF avec texte extractible', 'Text-based PDF',        '.pdf'),
 ('PDF_IMAGE', 'PDF numérisé (OCR requis)',  'Scanned PDF (OCR)',     '.pdf'),
 ('CSV',       'Fichier CSV de la banque',   'Bank CSV export',       '.csv'),
 ('XLSX',      'Fichier Excel',              'Excel file',            '.xlsx');

INSERT OR IGNORE INTO ref_statut_rapprochement (code, libelle_fr, libelle_en) VALUES
 ('NON_RAPPROCHE', 'Non rapproché',        'Unreconciled'),
 ('RAPPROCHE',     'Rapproché',            'Reconciled'),
 ('PARTIEL',       'Partiellement rapproché', 'Partially reconciled'),
 ('EXCLU',         'Exclu du rapprochement',  'Excluded');

INSERT OR IGNORE INTO ref_scenario (code, libelle_fr, libelle_en, ordre) VALUES
 ('BASE',        'Scénario de base', 'Base case',    1),
 ('OPTIMISTE',   'Scénario optimiste', 'Upside case', 2),
 ('PESSIMISTE',  'Scénario pessimiste', 'Downside case', 3),
 ('STRESS',      'Scénario de stress', 'Stress case', 4);

-- Exemples de correspondances : à enrichir avec vos propres libellés bancaires.
-- Les motifs sont comparés au libellé NORMALISÉ (majuscules, sans accent ni numéros).
INSERT OR IGNORE INTO ref_mapping_libelle (motif, type_motif, categorie_code, priorite, commentaire) VALUES
 ('VIREMENT ENTRE COMPTES', 'contient', 'TRF_INTERNE',              50,  'Priorité haute : évite de classer un transfert comme flux externe'),
 ('^PAIE( |$)',             'regex',    'DEC_SALAIRES',             100, 'Regex pour ne pas capter PAIEMENT FACTURE'),
 ('HYDRO',                  'contient', 'DEC_SERVICES_PUBLICS',     100, NULL),
 ('LOYER',                  'contient', 'DEC_LOYER',                100, NULL),
 ('ASSURANCE',              'contient', 'DEC_ASSURANCES',           100, NULL),
 ('FRAIS MENSUELS',         'contient', 'DEC_FRAIS_BANCAIRES',      100, NULL),
 ('FRAIS DE SERVICE',       'contient', 'DEC_FRAIS_BANCAIRES',      100, NULL),
 ('REMBOURSEMENT PRET',     'contient', 'FIN_EMPRUNT_REMBOURSEMENT', 100, NULL),
 ('DIVIDENDE',              'contient', 'FIN_DIVIDENDES',           100, NULL);

INSERT OR IGNORE INTO meta_glossaire (terme, definition, synonymes, reference) VALUES
 ('Solde comptable',  'Solde du compte selon les écritures de la banque à une date donnée, incluant les opérations non encore disponibles.', 'Ledger balance', 'Relevé bancaire'),
 ('Solde disponible', 'Montant que l''entité peut réellement utiliser : solde comptable moins les retenues et fonds non encore compensés.', 'Available balance', 'Relevé bancaire'),
 ('Date d''opération','Date à laquelle la transaction a été initiée ou effectuée.', 'Transaction date', NULL),
 ('Date valeur',      'Date à laquelle la transaction affecte réellement le solde ou les intérêts du compte.', 'Value date', NULL),
 ('Encaisse',         'Liquidités immédiatement disponibles : soldes bancaires et équivalents.', 'Liquidités, Cash', NULL),
 ('Flottant',         'Écart temporel entre l''émission d''un paiement (ex. chèque) et son effet sur le solde bancaire.', 'Float', NULL),
 ('PAD',              'Prélèvement préautorisé : débit automatique autorisé à l''avance par le payeur.', 'Prélèvement préautorisé', NULL),
 ('Contrepartie',     'Tiers à l''autre bout d''une transaction : client, fournisseur, employé, gouvernement, institution financière.', 'Tiers, Counterparty', 'mdm_contrepartie'),
 ('Rapprochement',    'Contrôle consistant à faire correspondre les mouvements enregistrés avec les relevés bancaires.', 'Réconciliation bancaire', NULL),
 ('Catégorie de flux','Classement d''un mouvement dans le plan de trésorerie (exploitation, investissement, financement).', NULL, 'ref_categorie_flux'),
 ('Run',              'Une exécution d''un agent ou d''un traitement, identifiée de façon unique pour assurer la traçabilité.', 'Exécution', 'meta_run'),
 ('Quarantaine',      'Statut d''un mouvement qui échoue à une règle de qualité bloquante : conservé mais exclu des rapports en attendant la revue.', NULL, 'dq_regle'),
 ('Golden record',    'Enregistrement unique de référence pour une entité maître, après dédoublonnage et fusion des variantes.', 'Enregistrement de référence', 'mdm_contrepartie');
