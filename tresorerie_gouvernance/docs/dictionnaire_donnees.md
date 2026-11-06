# Dictionnaire de données — Trésorerie

Généré automatiquement par `dictionnaire.py`. Ne pas modifier à la main : modifier `descriptions_champs.py` puis régénérer.


## core_mouvement

| Champ | Type | Oblig. | Définition | Unité / format | Règle | Sensibilité |
|---|---|---|---|---|---|---|
| `mouvement_id` | INTEGER | Oui | Identifiant technique du mouvement bancaire. |  |  | interne |
| `compte_id` | INTEGER | Oui | Compte bancaire concerné (mdm_compte). |  | Doit exister dans mdm_compte | interne |
| `date_operation` | TEXT | Oui | Date d'opération normalisée. | date ISO | AAAA-MM-JJ; date réelle; entre 2000-01-01 et demain | confidentiel |
| `date_valeur` | TEXT | Non | Date valeur normalisée. | date ISO | Entre -5 et +30 jours de la date d'opération | confidentiel |
| `libelle_brut` | TEXT | Oui | Libellé d'origine conservé pour la traçabilité. | texte |  | confidentiel |
| `libelle_normalise` | TEXT | Oui | Libellé en majuscules, sans accent ni numéros de référence : sert à la catégorisation et à la reconnaissance de contrepartie. | texte |  | confidentiel |
| `montant_cents` | INTEGER | Oui | Montant signé du mouvement : positif = encaissement, négatif = décaissement. | cents (devise du compte) | Entier non nul; jamais de décimal | confidentiel |
| `devise_code` | TEXT | Oui | Devise ISO 4217 (ref_devise). |  | Doit exister dans ref_devise | interne |
| `type_transaction_code` | TEXT | Oui | Type d'opération bancaire (ref_type_transaction). |  | Doit exister dans ref_type_transaction | interne |
| `categorie_code` | TEXT | Oui | Catégorie du plan de trésorerie (ref_categorie_flux). |  | Doit exister dans ref_categorie_flux | interne |
| `contrepartie_id` | INTEGER | Non | Contrepartie (mdm_contrepartie) : client, fournisseur, etc. |  | Doit exister dans mdm_contrepartie | interne |
| `statut_rapprochement` | TEXT | Oui | État du rapprochement avec le relevé ou le grand livre (ref_statut_rapprochement). |  | Doit exister dans ref_statut_rapprochement | interne |
| `statut_dq` | TEXT | Oui | Résultat du contrôle qualité : les mouvements en quarantaine sont exclus des rapports. |  | ok, avertissement ou quarantaine | interne |
| `hash_transaction` | TEXT | Oui | Empreinte de (compte, date, montant, libellé normalisé, occurrence) : garantit qu'un relevé rechargé ne crée pas de doublon. |  | Unique | interne |
| `run_id` | TEXT | Non | Exécution (meta_run) qui a produit ou modifié la ligne : permet de remonter à la source. |  | Doit exister dans meta_run | interne |
| `fichier_id` | INTEGER | Non | Fichier source (meta_fichier_source) d'où provient la ligne. |  | Doit exister dans meta_fichier_source | interne |
| `stg_id` | INTEGER | Non | Ligne brute (stg_releve_ligne) dont le mouvement est issu. |  | Doit exister dans stg_releve_ligne | interne |
| `cree_le` | TEXT | Oui | Horodatage de création de la ligne (UTC). | datetime ISO |  | interne |

## core_prevision

| Champ | Type | Oblig. | Définition | Unité / format | Règle | Sensibilité |
|---|---|---|---|---|---|---|
| `prevision_id` | INTEGER | Oui | Identifiant technique de la ligne de prévision. |  |  | interne |
| `scenario_code` | TEXT | Oui | Scénario de prévision (ref_scenario). |  | Doit exister dans ref_scenario | interne |
| `compte_id` | INTEGER | Non | Compte bancaire concerné (mdm_compte). |  | Doit exister dans mdm_compte | interne |
| `date_prevue` | TEXT | Oui | Date prévue du flux. | date ISO | AAAA-MM-JJ | confidentiel |
| `categorie_code` | TEXT | Oui | Catégorie du plan de trésorerie (ref_categorie_flux). |  | Doit exister dans ref_categorie_flux | interne |
| `montant_cents` | INTEGER | Oui | Montant prévu, signé comme core_mouvement. | cents (CAD) |  | confidentiel |
| `run_id` | TEXT | Non | Exécution (meta_run) qui a produit ou modifié la ligne : permet de remonter à la source. |  | Doit exister dans meta_run | interne |
| `cree_le` | TEXT | Oui | Horodatage de création de la ligne (UTC). | datetime ISO |  | interne |

## core_solde_releve

| Champ | Type | Oblig. | Définition | Unité / format | Règle | Sensibilité |
|---|---|---|---|---|---|---|
| `solde_id` | INTEGER | Oui | Identifiant technique du solde. |  |  | interne |
| `compte_id` | INTEGER | Oui | Compte bancaire concerné (mdm_compte). |  | Doit exister dans mdm_compte | interne |
| `date_solde` | TEXT | Oui | Date à laquelle le solde est valide. | date ISO | AAAA-MM-JJ | confidentiel |
| `solde_cents` | INTEGER | Oui | Solde du compte à la date indiquée. | cents (devise du compte) |  | confidentiel |
| `source` | TEXT | Oui | Origine du solde : lu sur un relevé ou calculé par le système. |  | releve ou calcule | interne |
| `run_id` | TEXT | Non | Exécution (meta_run) qui a produit ou modifié la ligne : permet de remonter à la source. |  | Doit exister dans meta_run | interne |
| `cree_le` | TEXT | Oui | Horodatage de création de la ligne (UTC). | datetime ISO |  | interne |

## dim_date

| Champ | Type | Oblig. | Définition | Unité / format | Règle | Sensibilité |
|---|---|---|---|---|---|---|
| `date_id` | TEXT | Oui | Date au format ISO : clé de la dimension. | date ISO | Unique | interne |
| `annee` | INTEGER | Oui | Année civile. |  |  | interne |
| `trimestre` | INTEGER | Oui | Trimestre civil (1 à 4). |  |  | interne |
| `mois` | INTEGER | Oui | Mois (1 à 12). |  |  | interne |
| `jour` | INTEGER | Oui | Jour du mois (1 à 31). |  |  | interne |
| `semaine_iso` | INTEGER | Oui | Numéro de semaine ISO 8601. |  |  | interne |
| `jour_semaine` | INTEGER | Oui | Jour de la semaine ISO : 1 = lundi, 7 = dimanche. |  |  | interne |
| `est_ouvrable` | INTEGER | Oui | 1 si lundi à vendredi. Les jours fériés ne sont pas encore gérés. |  | 0 ou 1 | interne |
| `fin_de_mois` | INTEGER | Oui | 1 si dernier jour du mois. |  | 0 ou 1 | interne |

## dq_execution

| Champ | Type | Oblig. | Définition | Unité / format | Règle | Sensibilité |
|---|---|---|---|---|---|---|
| `execution_id` | TEXT | Oui | Identifiant unique d'une exécution du contrôle qualité. |  | Unique | interne |
| `run_id` | TEXT | Non | Exécution du pipeline contrôlée; vide pour un contrôle complet. |  |  | interne |
| `portee` | TEXT | Oui | Étendue du contrôle. |  | run (un run) ou complet (toutes les données) | interne |
| `execute_le` | TEXT | Oui | Moment du contrôle (UTC). | datetime ISO |  | interne |
| `score_global` | REAL | Non | Moyenne des scores des règles de sévérité bloquante ou avertissement. | % (0 à 100) |  | interne |
| `nb_regles` | INTEGER | Non | Nombre de règles actives évaluées. |  |  | interne |
| `nb_echecs` | INTEGER | Non | Nombre de règles (hors info) sous leur seuil. |  |  | interne |
| `nb_bloquants_echec` | INTEGER | Non | Nombre de règles bloquantes en échec; > 0 impose une revue avant diffusion. |  |  | interne |

## dq_regle

| Champ | Type | Oblig. | Définition | Unité / format | Règle | Sensibilité |
|---|---|---|---|---|---|---|
| `regle_id` | TEXT | Oui | Identifiant stable de la règle (DQ-DIMENSION-NNN). |  | Unique | interne |
| `nom` | TEXT | Oui | Nom court de la règle. |  |  | interne |
| `description` | TEXT | Non | Description ou commentaire libre. |  |  | interne |
| `dimension` | TEXT | Oui | Dimension DAMA mesurée. |  | completude, validite, unicite, coherence, exactitude, ponctualite ou integrite | interne |
| `cible_table` | TEXT | Oui | Table sur laquelle la règle s'applique. |  |  | interne |
| `severite` | TEXT | Oui | Conséquence d'une violation. |  | bloquante (quarantaine), avertissement (signalé) ou info (suivi seulement) | interne |
| `sql_violations` | TEXT | Oui | Requête SQL qui renvoie les identifiants des lignes en violation. |  |  | interne |
| `sql_total` | TEXT | Oui | Requête SQL qui renvoie le nombre de lignes évaluées. |  |  | interne |
| `seuil_pct` | REAL | Oui | Score minimal pour que la règle soit réussie. | % de lignes conformes | 0 à 100 | interne |
| `actif` | INTEGER | Oui | Indicateur d'activité : 1 = utilisable, 0 = désactivé (conservé pour l'historique). |  | 0 ou 1 | interne |
| `version` | INTEGER | Oui | Numéro de version de la règle; augmente à chaque modification. |  |  | interne |
| `maj_le` | TEXT | Oui | Horodatage de dernière mise à jour (UTC). | datetime ISO |  | interne |

## dq_resultat

| Champ | Type | Oblig. | Définition | Unité / format | Règle | Sensibilité |
|---|---|---|---|---|---|---|
| `resultat_id` | INTEGER | Oui | Identifiant technique du résultat. |  |  | interne |
| `execution_id` | TEXT | Oui | Exécution du contrôle qualité (dq_execution). |  | Doit exister dans dq_execution | interne |
| `regle_id` | TEXT | Oui | Règle de qualité (dq_regle). |  | Doit exister dans dq_regle | interne |
| `nb_evalue` | INTEGER | Oui | Nombre de lignes évaluées par la règle. |  |  | interne |
| `nb_violation` | INTEGER | Oui | Nombre de lignes en violation. |  |  | interne |
| `score_pct` | REAL | Oui | Part des lignes conformes. | % (0 à 100) | 100 x (1 - violations / évalués) | interne |
| `statut` | TEXT | Oui | Résultat de la règle. |  | pass si score >= seuil, sinon fail | interne |
| `detail_json` | TEXT | Non | Échantillon des identifiants en violation (JSON). |  |  | interne |

## mart_contreparties_a_valider

| Champ | Type | Oblig. | Définition | Unité / format | Règle | Sensibilité |
|---|---|---|---|---|---|---|
| `contrepartie_id` | INTEGER | Non | Contrepartie créée automatiquement qui attend une revue. |  |  | interne |
| `nom_canonique` | TEXT | Non | Nom provisoire de la contrepartie, à confirmer ou à fusionner. |  |  | interne |
| `nb_alias` |  | Non | Nombre de variantes de nom associées. |  |  | interne |
| `nb_mouvements` |  | Non | Nombre de mouvements rattachés : priorise la revue. |  |  | interne |

## mart_dq_derniere_execution

| Champ | Type | Oblig. | Définition | Unité / format | Règle | Sensibilité |
|---|---|---|---|---|---|---|
| `execution_id` | TEXT | Non | Exécution du contrôle qualité (dq_execution). |  | Doit exister dans dq_execution | interne |
| `execute_le` | TEXT | Non | Moment du dernier contrôle qualité (UTC). | datetime ISO |  | interne |
| `regle_id` | TEXT | Non | Règle de qualité (dq_regle). |  | Doit exister dans dq_regle | interne |
| `nom` | TEXT | Non | Nom de la règle de qualité. |  |  | interne |
| `dimension` | TEXT | Non | Dimension DAMA mesurée par la règle. |  |  | interne |
| `severite` | TEXT | Non | Sévérité de la règle (bloquante, avertissement, info). |  |  | interne |
| `nb_evalue` | INTEGER | Non | Nombre de lignes évaluées. |  |  | interne |
| `nb_violation` | INTEGER | Non | Nombre de lignes en violation. |  |  | interne |
| `score_pct` | REAL | Non | Part des lignes conformes. | % (0 à 100) |  | interne |
| `statut` | TEXT | Non | pass ou fail selon le seuil de la règle. |  |  | interne |

## mart_flux_mensuel

| Champ | Type | Oblig. | Définition | Unité / format | Règle | Sensibilité |
|---|---|---|---|---|---|---|
| `entite_id` | INTEGER | Non | Entité juridique concernée (mdm_entite_juridique). |  | Doit exister dans mdm_entite_juridique | interne |
| `mois` |  | Non | Mois d'opération. | AAAA-MM |  | interne |
| `famille` | TEXT | Non | Famille de l'état des flux de trésorerie. |  | exploitation, investissement, financement ou neutre | interne |
| `categorie_code` | TEXT | Non | Catégorie du plan de trésorerie (ref_categorie_flux). |  | Doit exister dans ref_categorie_flux | interne |
| `categorie_libelle` | TEXT | Non | Libellé français de la catégorie de flux. |  |  | interne |
| `encaissements_cents` |  | Non | Encaissements du mois pour la catégorie, hors transferts internes. | cents |  | confidentiel |
| `decaissements_cents` |  | Non | Décaissements du mois pour la catégorie, en valeur positive. | cents |  | confidentiel |
| `net_cents` |  | Non | Encaissements moins décaissements. | cents |  | confidentiel |

## mart_mouvement_quotidien

| Champ | Type | Oblig. | Définition | Unité / format | Règle | Sensibilité |
|---|---|---|---|---|---|---|
| `compte_id` | INTEGER | Non | Compte bancaire concerné (mdm_compte). |  | Doit exister dans mdm_compte | interne |
| `entite_id` | INTEGER | Non | Entité juridique concernée (mdm_entite_juridique). |  | Doit exister dans mdm_entite_juridique | interne |
| `date_id` | TEXT | Non | Date d'opération (lien vers dim_date). | date ISO |  | interne |
| `encaissements_cents` |  | Non | Somme des encaissements du jour pour le compte. | cents |  | confidentiel |
| `decaissements_cents` |  | Non | Somme des décaissements du jour pour le compte, en valeur positive. | cents |  | confidentiel |
| `net_cents` |  | Non | Encaissements moins décaissements. | cents |  | confidentiel |
| `nb_mouvements` |  | Non | Nombre de mouvements du jour, hors quarantaine. |  |  | interne |

## mdm_compte

| Champ | Type | Oblig. | Définition | Unité / format | Règle | Sensibilité |
|---|---|---|---|---|---|---|
| `compte_id` | INTEGER | Oui | Identifiant technique du compte bancaire (golden record). |  |  | interne |
| `entite_id` | INTEGER | Oui | Entité juridique concernée (mdm_entite_juridique). |  | Doit exister dans mdm_entite_juridique | interne |
| `banque_code` | TEXT | Oui | Institution financière (ref_banque). |  | Doit exister dans ref_banque | interne |
| `type_code` | TEXT | Oui | Type de compte (ref_compte_type). |  | Doit exister dans ref_compte_type | interne |
| `devise_code` | TEXT | Oui | Devise ISO 4217 (ref_devise). |  | Doit exister dans ref_devise | interne |
| `numero_masque` | TEXT | Oui | Numéro de compte masqué pour affichage; seuls les 4 derniers chiffres sont visibles. |  | Format ****NNNN | confidentiel |
| `numero_hash` | TEXT | Oui | Empreinte salée du numéro complet : sert à reconnaître le compte sans le stocker. |  | Unique par banque; le numéro complet n'est jamais stocké | restreint |
| `libelle` | TEXT | Non | Nom d'usage du compte. |  |  | interne |
| `date_ouverture` | TEXT | Non | Date d'ouverture du compte. | date ISO |  | interne |
| `date_fermeture` | TEXT | Non | Date de fermeture; vide si le compte est ouvert. | date ISO | NULL ou >= date_ouverture | interne |
| `actif` | INTEGER | Oui | Indicateur d'activité : 1 = utilisable, 0 = désactivé (conservé pour l'historique). |  | 0 ou 1 | interne |
| `cree_le` | TEXT | Oui | Horodatage de création de la ligne (UTC). | datetime ISO |  | interne |

## mdm_contrepartie

| Champ | Type | Oblig. | Définition | Unité / format | Règle | Sensibilité |
|---|---|---|---|---|---|---|
| `contrepartie_id` | INTEGER | Oui | Identifiant technique de la contrepartie (golden record). |  |  | interne |
| `nom_canonique` | TEXT | Oui | Nom de référence de la contrepartie, après dédoublonnage. |  |  | interne |
| `type_contrepartie` | TEXT | Oui | Nature de la contrepartie. |  | client, fournisseur, employe, gouvernement, institution_financiere, interne ou autre | interne |
| `statut_validation` | TEXT | Oui | État de la revue humaine : une création automatique commence à valider. |  | valide, a_valider ou rejete | interne |
| `source_creation` | TEXT | Oui | Origine de la création (manuel, auto, nom d'un agent). |  |  | interne |
| `fusionne_vers_id` | INTEGER | Non | Contrepartie survivante si celle-ci a été fusionnée; vide sinon. |  | Doit exister dans mdm_contrepartie et différer de l'identifiant | interne |
| `actif` | INTEGER | Oui | Indicateur d'activité : 1 = utilisable, 0 = désactivé (conservé pour l'historique). |  | 0 ou 1 | interne |
| `cree_le` | TEXT | Oui | Horodatage de création de la ligne (UTC). | datetime ISO |  | interne |

## mdm_contrepartie_alias

| Champ | Type | Oblig. | Définition | Unité / format | Règle | Sensibilité |
|---|---|---|---|---|---|---|
| `alias_id` | INTEGER | Oui | Identifiant technique de l'alias. |  |  | interne |
| `contrepartie_id` | INTEGER | Oui | Contrepartie (mdm_contrepartie) : client, fournisseur, etc. |  | Doit exister dans mdm_contrepartie | interne |
| `alias_normalise` | TEXT | Oui | Variante du nom après normalisation (majuscules, sans accent, sans numéros). |  | Unique | confidentiel |
| `alias_brut` | TEXT | Non | Libellé tel qu'il est apparu sur le relevé bancaire. |  |  | confidentiel |
| `source` | TEXT | Oui | Façon dont l'alias a été associé (auto, manuel, nom d'un agent). |  |  | interne |
| `confiance` | REAL | Oui | Degré de certitude de l'association : 1 = exact, moins = approximatif. | ratio 0 à 1 | Entre 0 et 1 | interne |
| `cree_le` | TEXT | Oui | Horodatage de création de la ligne (UTC). | datetime ISO |  | interne |

## mdm_entite_juridique

| Champ | Type | Oblig. | Définition | Unité / format | Règle | Sensibilité |
|---|---|---|---|---|---|---|
| `entite_id` | INTEGER | Oui | Identifiant technique de l'entité juridique (golden record). |  |  | interne |
| `nom_legal` | TEXT | Oui | Dénomination légale complète. |  | Unique | interne |
| `nom_court` | TEXT | Non | Nom court utilisé dans les rapports et le dashboard. |  |  | interne |
| `devise_code` | TEXT | Oui | Devise fonctionnelle de l'entité. |  | Doit exister dans ref_devise | interne |
| `actif` | INTEGER | Oui | Indicateur d'activité : 1 = utilisable, 0 = désactivé (conservé pour l'historique). |  | 0 ou 1 | interne |
| `cree_le` | TEXT | Oui | Horodatage de création de la ligne (UTC). | datetime ISO |  | interne |

## mdm_facilite

| Champ | Type | Oblig. | Définition | Unité / format | Règle | Sensibilité |
|---|---|---|---|---|---|---|
| `facilite_id` | INTEGER | Oui | Identifiant technique de la facilité de crédit ou de la dette. |  |  | interne |
| `entite_id` | INTEGER | Oui | Entité juridique concernée (mdm_entite_juridique). |  | Doit exister dans mdm_entite_juridique | interne |
| `banque_code` | TEXT | Oui | Institution financière (ref_banque). |  | Doit exister dans ref_banque | interne |
| `type_facilite` | TEXT | Oui | Nature de la facilité. |  | marge, pret_terme, carte_credit, credit_bail ou autre | interne |
| `limite_cents` | INTEGER | Non | Limite autorisée de la facilité. | cents (CAD) | >= 0 | confidentiel |
| `taux_pct` | REAL | Non | Taux d'intérêt annuel. | % par an |  | confidentiel |
| `date_echeance` | TEXT | Non | Date d'échéance ou de renouvellement. | date ISO |  | interne |
| `actif` | INTEGER | Oui | Indicateur d'activité : 1 = utilisable, 0 = désactivé (conservé pour l'historique). |  | 0 ou 1 | interne |

## mdm_site

| Champ | Type | Oblig. | Définition | Unité / format | Règle | Sensibilité |
|---|---|---|---|---|---|---|
| `site_id` | INTEGER | Oui | Identifiant technique du site. |  |  | interne |
| `entite_id` | INTEGER | Oui | Entité juridique concernée (mdm_entite_juridique). |  | Doit exister dans mdm_entite_juridique | interne |
| `nom` | TEXT | Oui | Nom du site (magasin, usine, siège). |  | Unique par entité | interne |
| `type_site` | TEXT | Oui | Nature du site. |  | magasin, usine, siege ou autre | interne |
| `actif` | INTEGER | Oui | Indicateur d'activité : 1 = utilisable, 0 = désactivé (conservé pour l'historique). |  | 0 ou 1 | interne |

## meta_champ

| Champ | Type | Oblig. | Définition | Unité / format | Règle | Sensibilité |
|---|---|---|---|---|---|---|
| `champ_id` | INTEGER | Oui | Identifiant technique de la ligne du dictionnaire. |  |  | interne |
| `table_nom` | TEXT | Oui | Nom de la table ou de la vue décrite. |  |  | interne |
| `champ_nom` | TEXT | Oui | Nom du champ décrit. |  |  | interne |
| `type_donnee` | TEXT | Non | Type SQLite déclaré (lu du schéma). |  |  | interne |
| `nullable` | INTEGER | Oui | 1 si le champ peut être vide, 0 s'il est obligatoire. |  | 0 ou 1 | interne |
| `definition_metier` | TEXT | Oui | Définition en langage métier, compréhensible par un non-informaticien. |  |  | interne |
| `unite` | TEXT | Non | Unité ou format de la valeur. |  |  | interne |
| `regle_validation` | TEXT | Non | Règle de validité applicable au champ. |  |  | interne |
| `source` | TEXT | Non | Origine de la donnée (couche ou agent qui la produit). |  |  | interne |
| `sensibilite` | TEXT | Oui | Niveau de classification de la donnée. |  | public, interne, confidentiel ou restreint | interne |
| `proprietaire` | TEXT | Non | Rôle responsable de la qualité et des changements du champ. |  |  | interne |
| `exemple` | TEXT | Non | Exemple de valeur typique. |  |  | interne |
| `version_schema` | TEXT | Non | Version du schéma de données en vigueur au moment de l'écriture. |  |  | interne |
| `maj_le` | TEXT | Oui | Horodatage de dernière mise à jour (UTC). | datetime ISO |  | interne |

## meta_fichier_source

| Champ | Type | Oblig. | Définition | Unité / format | Règle | Sensibilité |
|---|---|---|---|---|---|---|
| `fichier_id` | INTEGER | Oui | Identifiant technique du fichier reçu. |  |  | interne |
| `nom_fichier` | TEXT | Oui | Nom du fichier tel que reçu. |  |  | confidentiel |
| `hash_sha256` | TEXT | Oui | Empreinte SHA-256 du contenu : détecte un fichier déjà ingéré. |  | Unique | interne |
| `format_code` | TEXT | Non | Format du relevé source (ref_format_releve). |  | Doit exister dans ref_format_releve | interne |
| `banque_code` | TEXT | Non | Institution financière (ref_banque). |  | Doit exister dans ref_banque | interne |
| `taille_octets` | INTEGER | Non | Taille du fichier. | octets |  | interne |
| `recu_le` | TEXT | Oui | Date de réception du fichier (UTC). | datetime ISO |  | interne |
| `run_id` | TEXT | Non | Exécution (meta_run) qui a produit ou modifié la ligne : permet de remonter à la source. |  | Doit exister dans meta_run | interne |

## meta_glossaire

| Champ | Type | Oblig. | Définition | Unité / format | Règle | Sensibilité |
|---|---|---|---|---|---|---|
| `terme` | TEXT | Oui | Terme du vocabulaire métier. |  |  | interne |
| `definition` | TEXT | Oui | Définition retenue pour tout le projet. |  |  | interne |
| `synonymes` | TEXT | Non | Autres expressions équivalentes (français ou anglais). |  |  | interne |
| `reference` | TEXT | Non | Table, champ ou document auquel le terme se rattache. |  |  | interne |

## meta_run

| Champ | Type | Oblig. | Définition | Unité / format | Règle | Sensibilité |
|---|---|---|---|---|---|---|
| `run_id` | TEXT | Oui | Identifiant unique d'une exécution (agent + horodatage + suffixe aléatoire). |  | Unique | interne |
| `agent` | TEXT | Oui | Agent ou traitement exécuté (A1 à A7, orchestrateur, etc.). |  |  | interne |
| `debut` | TEXT | Oui | Début de l'exécution (UTC). | datetime ISO |  | interne |
| `fin` | TEXT | Non | Fin de l'exécution (UTC); vide tant qu'elle n'est pas terminée. | datetime ISO |  | interne |
| `statut` | TEXT | Oui | État de l'exécution. |  | en_cours, succes, echec ou partiel | interne |
| `parametres_json` | TEXT | Non | Paramètres d'exécution au format JSON (reproductibilité). |  |  | interne |
| `version_schema` | TEXT | Non | Version du schéma de données en vigueur au moment de l'écriture. |  |  | interne |

## meta_version_schema

| Champ | Type | Oblig. | Définition | Unité / format | Règle | Sensibilité |
|---|---|---|---|---|---|---|
| `version` | TEXT | Oui | Numéro de version du schéma (majeur.mineur.correctif). |  |  | interne |
| `appliquee_le` | TEXT | Oui | Date d'application de la version. | datetime ISO |  | interne |
| `description` | TEXT | Oui | Changements apportés par cette version. |  |  | interne |

## ref_banque

| Champ | Type | Oblig. | Définition | Unité / format | Règle | Sensibilité |
|---|---|---|---|---|---|---|
| `code` | TEXT | Oui | Code stable et unique de la valeur de référence (clé naturelle). |  | Unique; majuscules sans accent; on désactive un code, on ne le supprime jamais | interne |
| `libelle_fr` | TEXT | Oui | Libellé en français affiché dans les rapports. |  |  | interne |
| `libelle_en` | TEXT | Oui | Libellé en anglais. |  |  | interne |
| `description` | TEXT | Non | Description ou commentaire libre. |  |  | interne |
| `pays` | TEXT | Oui | Pays de l'institution (code ISO à 2 lettres). |  |  | interne |
| `date_debut` | TEXT | Oui | Date de début de validité de la valeur. | date ISO | AAAA-MM-JJ; défaut 1900-01-01 | interne |
| `date_fin` | TEXT | Non | Date de fin de validité; vide tant que la valeur est en vigueur. | date ISO | NULL ou >= date_debut | interne |
| `actif` | INTEGER | Oui | Indicateur d'activité : 1 = utilisable, 0 = désactivé (conservé pour l'historique). |  | 0 ou 1 | interne |

## ref_categorie_flux

| Champ | Type | Oblig. | Définition | Unité / format | Règle | Sensibilité |
|---|---|---|---|---|---|---|
| `code` | TEXT | Oui | Code stable et unique de la valeur de référence (clé naturelle). |  | Unique; majuscules sans accent; on désactive un code, on ne le supprime jamais | interne |
| `libelle_fr` | TEXT | Oui | Libellé en français affiché dans les rapports. |  |  | interne |
| `libelle_en` | TEXT | Oui | Libellé en anglais. |  |  | interne |
| `description` | TEXT | Non | Description ou commentaire libre. |  |  | interne |
| `famille` | TEXT | Oui | Famille de l'état des flux de trésorerie. |  | exploitation, investissement, financement ou neutre | interne |
| `sens` | TEXT | Oui | Sens attendu du flux : sert à détecter les signes incohérents. |  | encaissement, decaissement ou neutre | interne |
| `date_debut` | TEXT | Oui | Date de début de validité de la valeur. | date ISO | AAAA-MM-JJ; défaut 1900-01-01 | interne |
| `date_fin` | TEXT | Non | Date de fin de validité; vide tant que la valeur est en vigueur. | date ISO | NULL ou >= date_debut | interne |
| `actif` | INTEGER | Oui | Indicateur d'activité : 1 = utilisable, 0 = désactivé (conservé pour l'historique). |  | 0 ou 1 | interne |

## ref_compte_type

| Champ | Type | Oblig. | Définition | Unité / format | Règle | Sensibilité |
|---|---|---|---|---|---|---|
| `code` | TEXT | Oui | Code stable et unique de la valeur de référence (clé naturelle). |  | Unique; majuscules sans accent; on désactive un code, on ne le supprime jamais | interne |
| `libelle_fr` | TEXT | Oui | Libellé en français affiché dans les rapports. |  |  | interne |
| `libelle_en` | TEXT | Oui | Libellé en anglais. |  |  | interne |
| `description` | TEXT | Non | Description ou commentaire libre. |  |  | interne |
| `date_debut` | TEXT | Oui | Date de début de validité de la valeur. | date ISO | AAAA-MM-JJ; défaut 1900-01-01 | interne |
| `date_fin` | TEXT | Non | Date de fin de validité; vide tant que la valeur est en vigueur. | date ISO | NULL ou >= date_debut | interne |
| `actif` | INTEGER | Oui | Indicateur d'activité : 1 = utilisable, 0 = désactivé (conservé pour l'historique). |  | 0 ou 1 | interne |

## ref_devise

| Champ | Type | Oblig. | Définition | Unité / format | Règle | Sensibilité |
|---|---|---|---|---|---|---|
| `code` | TEXT | Oui | Code stable et unique de la valeur de référence (clé naturelle). |  | Unique; majuscules sans accent; on désactive un code, on ne le supprime jamais | interne |
| `libelle_fr` | TEXT | Oui | Libellé en français affiché dans les rapports. |  |  | interne |
| `libelle_en` | TEXT | Oui | Libellé en anglais. |  |  | interne |
| `description` | TEXT | Non | Description ou commentaire libre. |  |  | interne |
| `decimales` | INTEGER | Oui | Nombre de décimales usuelles de la devise. |  | Entre 0 et 4 | interne |
| `date_debut` | TEXT | Oui | Date de début de validité de la valeur. | date ISO | AAAA-MM-JJ; défaut 1900-01-01 | interne |
| `date_fin` | TEXT | Non | Date de fin de validité; vide tant que la valeur est en vigueur. | date ISO | NULL ou >= date_debut | interne |
| `actif` | INTEGER | Oui | Indicateur d'activité : 1 = utilisable, 0 = désactivé (conservé pour l'historique). |  | 0 ou 1 | interne |

## ref_format_releve

| Champ | Type | Oblig. | Définition | Unité / format | Règle | Sensibilité |
|---|---|---|---|---|---|---|
| `code` | TEXT | Oui | Code stable et unique de la valeur de référence (clé naturelle). |  | Unique; majuscules sans accent; on désactive un code, on ne le supprime jamais | interne |
| `libelle_fr` | TEXT | Oui | Libellé en français affiché dans les rapports. |  |  | interne |
| `libelle_en` | TEXT | Oui | Libellé en anglais. |  |  | interne |
| `description` | TEXT | Non | Description ou commentaire libre. |  |  | interne |
| `extension_fichier` | TEXT | Non | Extension de fichier associée au format. |  |  | interne |
| `date_debut` | TEXT | Oui | Date de début de validité de la valeur. | date ISO | AAAA-MM-JJ; défaut 1900-01-01 | interne |
| `date_fin` | TEXT | Non | Date de fin de validité; vide tant que la valeur est en vigueur. | date ISO | NULL ou >= date_debut | interne |
| `actif` | INTEGER | Oui | Indicateur d'activité : 1 = utilisable, 0 = désactivé (conservé pour l'historique). |  | 0 ou 1 | interne |

## ref_mapping_libelle

| Champ | Type | Oblig. | Définition | Unité / format | Règle | Sensibilité |
|---|---|---|---|---|---|---|
| `mapping_id` | INTEGER | Oui | Identifiant technique de la règle de correspondance. |  |  | interne |
| `motif` | TEXT | Oui | Texte ou expression à chercher dans le libellé normalisé. |  |  | interne |
| `type_motif` | TEXT | Oui | Mode de comparaison du motif. |  | contient, commence ou regex | interne |
| `categorie_code` | TEXT | Oui | Catégorie du plan de trésorerie (ref_categorie_flux). |  | Doit exister dans ref_categorie_flux | interne |
| `priorite` | INTEGER | Oui | Ordre d'application : la plus petite valeur gagne. |  | Entier | interne |
| `actif` | INTEGER | Oui | Indicateur d'activité : 1 = utilisable, 0 = désactivé (conservé pour l'historique). |  | 0 ou 1 | interne |
| `commentaire` | TEXT | Non | Justification de la règle ou cas particulier. |  |  | interne |

## ref_scenario

| Champ | Type | Oblig. | Définition | Unité / format | Règle | Sensibilité |
|---|---|---|---|---|---|---|
| `code` | TEXT | Oui | Code stable et unique de la valeur de référence (clé naturelle). |  | Unique; majuscules sans accent; on désactive un code, on ne le supprime jamais | interne |
| `libelle_fr` | TEXT | Oui | Libellé en français affiché dans les rapports. |  |  | interne |
| `libelle_en` | TEXT | Oui | Libellé en anglais. |  |  | interne |
| `description` | TEXT | Non | Description ou commentaire libre. |  |  | interne |
| `ordre` | INTEGER | Oui | Ordre d'affichage des scénarios dans les rapports. |  |  | interne |
| `date_debut` | TEXT | Oui | Date de début de validité de la valeur. | date ISO | AAAA-MM-JJ; défaut 1900-01-01 | interne |
| `date_fin` | TEXT | Non | Date de fin de validité; vide tant que la valeur est en vigueur. | date ISO | NULL ou >= date_debut | interne |
| `actif` | INTEGER | Oui | Indicateur d'activité : 1 = utilisable, 0 = désactivé (conservé pour l'historique). |  | 0 ou 1 | interne |

## ref_statut_rapprochement

| Champ | Type | Oblig. | Définition | Unité / format | Règle | Sensibilité |
|---|---|---|---|---|---|---|
| `code` | TEXT | Oui | Code stable et unique de la valeur de référence (clé naturelle). |  | Unique; majuscules sans accent; on désactive un code, on ne le supprime jamais | interne |
| `libelle_fr` | TEXT | Oui | Libellé en français affiché dans les rapports. |  |  | interne |
| `libelle_en` | TEXT | Oui | Libellé en anglais. |  |  | interne |
| `description` | TEXT | Non | Description ou commentaire libre. |  |  | interne |
| `date_debut` | TEXT | Oui | Date de début de validité de la valeur. | date ISO | AAAA-MM-JJ; défaut 1900-01-01 | interne |
| `date_fin` | TEXT | Non | Date de fin de validité; vide tant que la valeur est en vigueur. | date ISO | NULL ou >= date_debut | interne |
| `actif` | INTEGER | Oui | Indicateur d'activité : 1 = utilisable, 0 = désactivé (conservé pour l'historique). |  | 0 ou 1 | interne |

## ref_type_transaction

| Champ | Type | Oblig. | Définition | Unité / format | Règle | Sensibilité |
|---|---|---|---|---|---|---|
| `code` | TEXT | Oui | Code stable et unique de la valeur de référence (clé naturelle). |  | Unique; majuscules sans accent; on désactive un code, on ne le supprime jamais | interne |
| `libelle_fr` | TEXT | Oui | Libellé en français affiché dans les rapports. |  |  | interne |
| `libelle_en` | TEXT | Oui | Libellé en anglais. |  |  | interne |
| `description` | TEXT | Non | Description ou commentaire libre. |  |  | interne |
| `date_debut` | TEXT | Oui | Date de début de validité de la valeur. | date ISO | AAAA-MM-JJ; défaut 1900-01-01 | interne |
| `date_fin` | TEXT | Non | Date de fin de validité; vide tant que la valeur est en vigueur. | date ISO | NULL ou >= date_debut | interne |
| `actif` | INTEGER | Oui | Indicateur d'activité : 1 = utilisable, 0 = désactivé (conservé pour l'historique). |  | 0 ou 1 | interne |

## stg_rejet

| Champ | Type | Oblig. | Définition | Unité / format | Règle | Sensibilité |
|---|---|---|---|---|---|---|
| `rejet_id` | INTEGER | Oui | Identifiant technique de l'élément à revoir. |  |  | interne |
| `execution_id` | TEXT | Non | Exécution du contrôle qualité (dq_execution). |  | Doit exister dans dq_execution | interne |
| `run_id` | TEXT | Non | Exécution (meta_run) qui a produit ou modifié la ligne : permet de remonter à la source. |  | Doit exister dans meta_run | interne |
| `table_source` | TEXT | Oui | Table d'origine de l'élément rejeté ou signalé. |  |  | interne |
| `cle_source` | INTEGER | Non | Identifiant de la ligne dans sa table d'origine. |  |  | interne |
| `regle_id` | TEXT | Oui | Règle de qualité (dq_regle). |  | Doit exister dans dq_regle | interne |
| `motif` | TEXT | Oui | Raison du rejet ou du signalement (nom de la règle). |  |  | interne |
| `payload_json` | TEXT | Non | Copie de la ligne au moment du rejet (JSON), pour la revue. |  |  | confidentiel |
| `rejete_le` | TEXT | Oui | Date du rejet (UTC). | datetime ISO |  | interne |
| `statut_traitement` | TEXT | Oui | Avancement de la revue humaine ou de l'agent A6. |  | a_revoir, corrige ou ignore | interne |

## stg_releve_ligne

| Champ | Type | Oblig. | Définition | Unité / format | Règle | Sensibilité |
|---|---|---|---|---|---|---|
| `stg_id` | INTEGER | Oui | Identifiant technique de la ligne brute. |  |  | interne |
| `run_id` | TEXT | Non | Exécution (meta_run) qui a produit ou modifié la ligne : permet de remonter à la source. |  | Doit exister dans meta_run | interne |
| `fichier_id` | INTEGER | Non | Fichier source (meta_fichier_source) d'où provient la ligne. |  | Doit exister dans meta_fichier_source | interne |
| `format_code` | TEXT | Non | Format du relevé source (ref_format_releve). |  | Doit exister dans ref_format_releve | interne |
| `ligne_no` | INTEGER | Non | Numéro de ligne dans le fichier source (traçabilité). |  |  | interne |
| `compte_ref_brut` | TEXT | Non | Référence de compte telle que lue; peut contenir un numéro partiel. |  |  | restreint |
| `date_operation_brut` | TEXT | Non | Date d'opération en texte, dans le format de la banque. | texte |  | confidentiel |
| `date_valeur_brut` | TEXT | Non | Date valeur en texte, dans le format de la banque. | texte |  | confidentiel |
| `libelle_brut` | TEXT | Non | Libellé tel que lu sur le relevé, sans nettoyage. | texte |  | confidentiel |
| `montant_brut` | TEXT | Non | Montant en texte avec signe, quand la banque fournit une seule colonne. | texte |  | confidentiel |
| `debit_brut` | TEXT | Non | Montant en texte de la colonne débit, quand la banque en fournit deux. | texte |  | confidentiel |
| `credit_brut` | TEXT | Non | Montant en texte de la colonne crédit. | texte |  | confidentiel |
| `solde_brut` | TEXT | Non | Solde en texte après l'opération, si fourni. | texte |  | confidentiel |
| `devise_brut` | TEXT | Non | Devise telle que lue (symbole ou code). | texte |  | interne |
| `charge_json` | TEXT | Non | Données additionnelles extraites de la ligne (JSON), conservées sans interprétation. |  |  | confidentiel |
| `cree_le` | TEXT | Oui | Horodatage de création de la ligne (UTC). | datetime ISO |  | interne |

## Glossaire métier

| Terme | Définition | Synonymes |
|---|---|---|
| Catégorie de flux | Classement d'un mouvement dans le plan de trésorerie (exploitation, investissement, financement). |  |
| Contrepartie | Tiers à l'autre bout d'une transaction : client, fournisseur, employé, gouvernement, institution financière. | Tiers, Counterparty |
| Date d'opération | Date à laquelle la transaction a été initiée ou effectuée. | Transaction date |
| Date valeur | Date à laquelle la transaction affecte réellement le solde ou les intérêts du compte. | Value date |
| Encaisse | Liquidités immédiatement disponibles : soldes bancaires et équivalents. | Liquidités, Cash |
| Flottant | Écart temporel entre l'émission d'un paiement (ex. chèque) et son effet sur le solde bancaire. | Float |
| Golden record | Enregistrement unique de référence pour une entité maître, après dédoublonnage et fusion des variantes. | Enregistrement de référence |
| PAD | Prélèvement préautorisé : débit automatique autorisé à l'avance par le payeur. | Prélèvement préautorisé |
| Quarantaine | Statut d'un mouvement qui échoue à une règle de qualité bloquante : conservé mais exclu des rapports en attendant la revue. |  |
| Rapprochement | Contrôle consistant à faire correspondre les mouvements enregistrés avec les relevés bancaires. | Réconciliation bancaire |
| Run | Une exécution d'un agent ou d'un traitement, identifiée de façon unique pour assurer la traçabilité. | Exécution |
| Solde comptable | Solde du compte selon les écritures de la banque à une date donnée, incluant les opérations non encore disponibles. | Ledger balance |
| Solde disponible | Montant que l'entité peut réellement utiliser : solde comptable moins les retenues et fonds non encore compensés. | Available balance |
