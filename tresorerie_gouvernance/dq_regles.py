"""Règles de qualité des données (DMBOK : Data Quality).

Chaque règle fournit deux requêtes SQL :
  - sql_violations : renvoie une colonne = identifiant des lignes en violation
  - sql_total      : renvoie le nombre de lignes évaluées

Paramètre commun : :run_id. Quand il est NULL, la règle s'applique à toute la table.
Les règles qui comparent plusieurs périodes ou plusieurs lignes (soldes, transferts, doublons)
regardent toujours l'ensemble des données, mais ne signalent que les lignes du run demandé
lorsque la cible est core_mouvement.

Pour ajouter une règle : ajouter un dict à REGLES et incrémenter 'version' si une règle existante change.
dq_runner.charger_regles() synchronise la table dq_regle (sans écraser le champ 'actif').

Dimensions DAMA couvertes : complétude, validité, unicité, cohérence, exactitude, ponctualité, intégrité.
"""

F = "(:run_id IS NULL OR m.run_id = :run_id)"

REGLES = [
    # ------------------------------------------------------------ Complétude
    {
        "regle_id": "DQ-COM-001",
        "nom": "Mouvement non classé dans le plan de trésorerie",
        "description": "La catégorie de flux est NON_CLASSE : aucune correspondance dans ref_mapping_libelle.",
        "dimension": "completude", "cible_table": "core_mouvement", "severite": "avertissement", "seuil_pct": 90,
        "sql_violations": f"SELECT m.mouvement_id FROM core_mouvement m WHERE m.categorie_code = 'NON_CLASSE' AND {F}",
        "sql_total": f"SELECT COUNT(*) FROM core_mouvement m WHERE {F}",
    },
    {
        "regle_id": "DQ-COM-002",
        "nom": "Libellé bancaire vide",
        "description": "Le libellé brut est vide : impossible de catégoriser ou d'identifier la contrepartie.",
        "dimension": "completude", "cible_table": "core_mouvement", "severite": "avertissement", "seuil_pct": 95,
        "sql_violations": f"SELECT m.mouvement_id FROM core_mouvement m WHERE trim(m.libelle_brut) = '' AND {F}",
        "sql_total": f"SELECT COUNT(*) FROM core_mouvement m WHERE {F}",
    },
    {
        "regle_id": "DQ-COM-003",
        "nom": "Contrepartie manquante sur un flux client ou fournisseur",
        "description": "Les flux ENC_CLIENTS et DEC_FOURNISSEURS doivent être rattachés à une contrepartie.",
        "dimension": "completude", "cible_table": "core_mouvement", "severite": "avertissement", "seuil_pct": 95,
        "sql_violations": (
            "SELECT m.mouvement_id FROM core_mouvement m "
            "WHERE m.categorie_code IN ('ENC_CLIENTS', 'DEC_FOURNISSEURS') "
            f"AND m.contrepartie_id IS NULL AND {F}"
        ),
        "sql_total": (
            "SELECT COUNT(*) FROM core_mouvement m "
            f"WHERE m.categorie_code IN ('ENC_CLIENTS', 'DEC_FOURNISSEURS') AND {F}"
        ),
    },
    # -------------------------------------------------------------- Validité
    {
        "regle_id": "DQ-VAL-001",
        "nom": "Date d'opération invalide ou hors plage",
        "description": "Date inexistante au calendrier, antérieure à 2000-01-01 ou postérieure à demain.",
        "dimension": "validite", "cible_table": "core_mouvement", "severite": "bloquante", "seuil_pct": 100,
        "sql_violations": (
            "SELECT m.mouvement_id FROM core_mouvement m "
            "WHERE (date(m.date_operation) IS NOT m.date_operation "
            "OR m.date_operation < '2000-01-01' OR m.date_operation > date('now', '+1 day')) "
            f"AND {F}"
        ),
        "sql_total": f"SELECT COUNT(*) FROM core_mouvement m WHERE {F}",
    },
    {
        "regle_id": "DQ-VAL-002",
        "nom": "Montant nul",
        "description": "Un mouvement bancaire de 0 $ est presque toujours une erreur d'extraction.",
        "dimension": "validite", "cible_table": "core_mouvement", "severite": "bloquante", "seuil_pct": 100,
        "sql_violations": f"SELECT m.mouvement_id FROM core_mouvement m WHERE m.montant_cents = 0 AND {F}",
        "sql_total": f"SELECT COUNT(*) FROM core_mouvement m WHERE {F}",
    },
    {
        "regle_id": "DQ-VAL-003",
        "nom": "Date valeur incohérente avec la date d'opération",
        "description": "Date valeur invalide, antérieure de plus de 5 jours ou postérieure de plus de 30 jours à la date d'opération.",
        "dimension": "validite", "cible_table": "core_mouvement", "severite": "avertissement", "seuil_pct": 98,
        "sql_violations": (
            "SELECT m.mouvement_id FROM core_mouvement m "
            "WHERE m.date_valeur IS NOT NULL AND ("
            "date(m.date_valeur) IS NOT m.date_valeur "
            "OR julianday(m.date_valeur) < julianday(m.date_operation) - 5 "
            "OR julianday(m.date_valeur) > julianday(m.date_operation) + 30) "
            f"AND {F}"
        ),
        "sql_total": f"SELECT COUNT(*) FROM core_mouvement m WHERE m.date_valeur IS NOT NULL AND {F}",
    },
    {
        "regle_id": "DQ-VAL-004",
        "nom": "Devise du mouvement différente de celle du compte",
        "description": "Le mouvement doit être dans la devise du compte bancaire.",
        "dimension": "validite", "cible_table": "core_mouvement", "severite": "bloquante", "seuil_pct": 100,
        "sql_violations": (
            "SELECT m.mouvement_id FROM core_mouvement m "
            "JOIN mdm_compte c ON c.compte_id = m.compte_id "
            f"WHERE m.devise_code <> c.devise_code AND {F}"
        ),
        "sql_total": f"SELECT COUNT(*) FROM core_mouvement m WHERE {F}",
    },
    # --------------------------------------------------------------- Unicité
    {
        "regle_id": "DQ-UNI-001",
        "nom": "Mouvement possiblement présent dans deux fichiers",
        "description": ("Même compte, même date, même montant que un mouvement issu d'un autre fichier : "
                        "probable chevauchement de relevés avec libellés différents."),
        "dimension": "unicite", "cible_table": "core_mouvement", "severite": "avertissement", "seuil_pct": 98,
        "sql_violations": (
            "SELECT m.mouvement_id FROM core_mouvement m WHERE EXISTS ("
            "SELECT 1 FROM core_mouvement o WHERE o.compte_id = m.compte_id "
            "AND o.date_operation = m.date_operation AND o.montant_cents = m.montant_cents "
            "AND o.mouvement_id <> m.mouvement_id "
            "AND COALESCE(o.fichier_id, -1) <> COALESCE(m.fichier_id, -1)) "
            f"AND {F}"
        ),
        "sql_total": f"SELECT COUNT(*) FROM core_mouvement m WHERE {F}",
    },
    # ------------------------------------------------------------- Intégrité
    {
        "regle_id": "DQ-INT-001",
        "nom": "Contrepartie fusionnée ou inactive encore référencée",
        "description": "Un mouvement pointe vers une contrepartie fusionnée ou désactivée au lieu de sa survivante.",
        "dimension": "integrite", "cible_table": "core_mouvement", "severite": "avertissement", "seuil_pct": 100,
        "sql_violations": (
            "SELECT m.mouvement_id FROM core_mouvement m "
            "JOIN mdm_contrepartie p ON p.contrepartie_id = m.contrepartie_id "
            f"WHERE (p.fusionne_vers_id IS NOT NULL OR p.actif = 0) AND {F}"
        ),
        "sql_total": f"SELECT COUNT(*) FROM core_mouvement m WHERE m.contrepartie_id IS NOT NULL AND {F}",
    },
    {
        "regle_id": "DQ-INT-002",
        "nom": "Mouvement postérieur à la fermeture du compte",
        "description": "La date d'opération dépasse la date de fermeture du compte dans mdm_compte.",
        "dimension": "integrite", "cible_table": "core_mouvement", "severite": "avertissement", "seuil_pct": 100,
        "sql_violations": (
            "SELECT m.mouvement_id FROM core_mouvement m "
            "JOIN mdm_compte c ON c.compte_id = m.compte_id "
            f"WHERE c.date_fermeture IS NOT NULL AND m.date_operation > c.date_fermeture AND {F}"
        ),
        "sql_total": f"SELECT COUNT(*) FROM core_mouvement m WHERE {F}",
    },
    # ------------------------------------------------------------- Cohérence
    {
        "regle_id": "DQ-COH-001",
        "nom": "Signe du montant incohérent avec le sens de la catégorie",
        "description": ("Un encaissement négatif ou un décaissement positif. Peut être légitime "
                        "(remboursement) mais mérite une revue."),
        "dimension": "coherence", "cible_table": "core_mouvement", "severite": "avertissement", "seuil_pct": 95,
        "sql_violations": (
            "SELECT m.mouvement_id FROM core_mouvement m "
            "JOIN ref_categorie_flux f ON f.code = m.categorie_code "
            "WHERE ((f.sens = 'encaissement' AND m.montant_cents < 0) "
            "OR (f.sens = 'decaissement' AND m.montant_cents > 0)) "
            f"AND {F}"
        ),
        "sql_total": (
            "SELECT COUNT(*) FROM core_mouvement m "
            "JOIN ref_categorie_flux f ON f.code = m.categorie_code "
            f"WHERE f.sens <> 'neutre' AND {F}"
        ),
    },
    {
        "regle_id": "DQ-COH-002",
        "nom": "Transfert interne sans contrepartie symétrique",
        "description": ("Un transfert entre comptes de la même entité doit avoir un mouvement de signe opposé "
                        "et de même montant, dans un autre compte, à ±3 jours."),
        "dimension": "coherence", "cible_table": "core_mouvement", "severite": "avertissement", "seuil_pct": 95,
        "sql_violations": (
            "SELECT m.mouvement_id FROM core_mouvement m "
            "JOIN mdm_compte c ON c.compte_id = m.compte_id "
            "WHERE m.categorie_code = 'TRF_INTERNE' AND NOT EXISTS ("
            "SELECT 1 FROM core_mouvement o JOIN mdm_compte co ON co.compte_id = o.compte_id "
            "WHERE o.categorie_code = 'TRF_INTERNE' AND o.compte_id <> m.compte_id "
            "AND co.entite_id = c.entite_id AND o.montant_cents = -m.montant_cents "
            "AND abs(julianday(o.date_operation) - julianday(m.date_operation)) <= 3) "
            f"AND {F}"
        ),
        "sql_total": f"SELECT COUNT(*) FROM core_mouvement m WHERE m.categorie_code = 'TRF_INTERNE' AND {F}",
    },
    # ------------------------------------------------------------ Exactitude
    {
        "regle_id": "DQ-EXA-001",
        "nom": "Écart entre soldes de relevé consécutifs et mouvements",
        "description": ("Pour deux soldes de relevé consécutifs d'un même compte : solde final - solde initial "
                        "doit égaler la somme des mouvements entre les deux dates. Le premier solde d'un compte "
                        "n'est pas vérifiable."),
        "dimension": "exactitude", "cible_table": "core_solde_releve", "severite": "bloquante", "seuil_pct": 100,
        "sql_violations": (
            "WITH s AS (SELECT solde_id, compte_id, date_solde, solde_cents, "
            "LAG(date_solde) OVER w AS date_prec, LAG(solde_cents) OVER w AS solde_prec "
            "FROM core_solde_releve WHERE source = 'releve' "
            "WINDOW w AS (PARTITION BY compte_id ORDER BY date_solde)) "
            "SELECT s.solde_id FROM s WHERE s.date_prec IS NOT NULL "
            "AND s.solde_cents - s.solde_prec <> COALESCE(("
            "SELECT SUM(m.montant_cents) FROM core_mouvement m WHERE m.compte_id = s.compte_id "
            "AND m.date_operation > s.date_prec AND m.date_operation <= s.date_solde), 0)"
        ),
        "sql_total": (
            "WITH s AS (SELECT solde_id, LAG(date_solde) OVER w AS date_prec "
            "FROM core_solde_releve WHERE source = 'releve' "
            "WINDOW w AS (PARTITION BY compte_id ORDER BY date_solde)) "
            "SELECT COUNT(*) FROM s WHERE date_prec IS NOT NULL"
        ),
    },
    # ----------------------------------------------------------- Ponctualité
    {
        "regle_id": "DQ-PON-001",
        "nom": "Compte actif sans mouvement depuis plus de 7 jours",
        "description": "Signale un relevé probablement manquant (ou un compte dormant à désactiver).",
        "dimension": "ponctualite", "cible_table": "mdm_compte", "severite": "info", "seuil_pct": 100,
        "sql_violations": (
            "SELECT c.compte_id FROM mdm_compte c WHERE c.actif = 1 AND COALESCE(("
            "SELECT MAX(m.date_operation) FROM core_mouvement m WHERE m.compte_id = c.compte_id), '0000-00-00') "
            "< date('now', '-7 day')"
        ),
        "sql_total": "SELECT COUNT(*) FROM mdm_compte c WHERE c.actif = 1",
    },
    # ------------------------------------------- Cycle achats-décaissements
    {
        "regle_id": "DQ-UNI-010",
        "nom": "Facture fournisseur en double",
        "description": "Même fournisseur et même numéro de facture déjà enregistrés : risque de double paiement.",
        "dimension": "unicite", "cible_table": "core_facture_fournisseur", "severite": "avertissement", "seuil_pct": 100,
        "sql_violations": (
            "SELECT f.facture_id FROM core_facture_fournisseur f WHERE EXISTS (SELECT 1 FROM core_facture_fournisseur g "
            "WHERE g.fournisseur_id = f.fournisseur_id AND g.no_facture = f.no_facture AND g.facture_id < f.facture_id)"
        ),
        "sql_total": "SELECT COUNT(*) FROM core_facture_fournisseur",
    },
    {
        "regle_id": "DQ-COH-010",
        "nom": "Total de la facture différent du montant + TPS + TVQ",
        "description": "Le total à payer doit égaler le montant avant taxes plus les deux taxes.",
        "dimension": "coherence", "cible_table": "core_facture_fournisseur", "severite": "avertissement", "seuil_pct": 100,
        "sql_violations": "SELECT f.facture_id FROM core_facture_fournisseur f WHERE f.total_cents <> f.montant_ht_cents + f.tps_cents + f.tvq_cents",
        "sql_total": "SELECT COUNT(*) FROM core_facture_fournisseur",
    },
    {
        "regle_id": "DQ-COH-011",
        "nom": "Facture sans bon de commande hors achats préautorisés",
        "description": "Seuls les services publics et les achats récurrents préautorisés peuvent être facturés sans commande.",
        "dimension": "coherence", "cible_table": "core_facture_fournisseur", "severite": "avertissement", "seuil_pct": 100,
        "sql_violations": (
            "SELECT f.facture_id FROM core_facture_fournisseur f JOIN mdm_fournisseur o ON o.fournisseur_id = f.fournisseur_id "
            "WHERE f.commande_id IS NULL AND o.famille_achat NOT IN ('service_public', 'services_professionnels')"
        ),
        "sql_total": "SELECT COUNT(*) FROM core_facture_fournisseur",
    },
    {
        "regle_id": "DQ-EXA-010",
        "nom": "Écart d'appariement accepté sans motif ni approbateur",
        "description": "Une facture hors tolérance (prix 2 %, quantité 1 %) ne peut être approuvée ou payée sans motif et sans approbateur.",
        "dimension": "exactitude", "cible_table": "core_facture_fournisseur", "severite": "avertissement", "seuil_pct": 100,
        "sql_violations": (
            "SELECT f.facture_id FROM core_facture_fournisseur f WHERE f.statut IN ('approuvee', 'en_lot', 'payee') "
            "AND (ABS(COALESCE(f.ecart_prix_pct, 0)) > 2 OR ABS(COALESCE(f.ecart_quantite_pct, 0)) > 1) "
            "AND (f.approuve_par IS NULL OR f.motif_ecart IS NULL)"
        ),
        "sql_total": "SELECT COUNT(*) FROM core_facture_fournisseur f WHERE f.statut IN ('approuvee', 'en_lot', 'payee')",
    },
    {
        "regle_id": "DQ-INT-010",
        "nom": "Paiement supérieur au total de la facture",
        "description": "Montant décaissé plus escompte pris au-delà du total de la facture : surpaiement.",
        "dimension": "integrite", "cible_table": "core_paiement_fournisseur", "severite": "avertissement", "seuil_pct": 100,
        "sql_violations": (
            "SELECT p.paiement_id FROM core_paiement_fournisseur p JOIN core_facture_fournisseur f ON f.facture_id = p.facture_id "
            "WHERE p.montant_cents + p.escompte_pris_cents > f.total_cents"
        ),
        "sql_total": "SELECT COUNT(*) FROM core_paiement_fournisseur",
    },
    {
        "regle_id": "DQ-VAL-010",
        "nom": "Fournisseur actif sans approbation ou aux coordonnées bancaires non vérifiées",
        "description": "Un fournisseur payable doit avoir une fiche approuvée ; un changement de coordonnées bancaires doit être confirmé par rappel.",
        "dimension": "validite", "cible_table": "mdm_fournisseur", "severite": "avertissement", "seuil_pct": 100,
        "sql_violations": (
            "SELECT o.fournisseur_id FROM mdm_fournisseur o WHERE o.statut = 'actif' "
            "AND (o.approuve_par IS NULL OR (o.coordonnees_modifiees_le IS NOT NULL AND o.rappel_verifie = 0))"
        ),
        "sql_total": "SELECT COUNT(*) FROM mdm_fournisseur o WHERE o.statut = 'actif'",
    },
]
