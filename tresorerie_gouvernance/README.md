# Gouvernance des données — projet Trésorerie (vagues 1 et 2)

Socle inspiré du DAMA-DMBOK 2 pour `tresorerie.db` : métadonnées, données de référence, données maîtres,
qualité des données, couches stg / core / mart. Testé sur base vide et sur une base contenant déjà des tables
(19 tests, `python -m unittest test_gouvernance -v`).

## Démarrage

```
python init_db.py --db tresorerie.db                          # crée / met à niveau (non destructif)
python dq_runner.py --db tresorerie.db                        # contrôle qualité complet
python dictionnaire.py --db tresorerie.db --md docs/dictionnaire_donnees.md --xlsx docs/dictionnaire_donnees.xlsx
```

`init_db.py` ne modifie jamais vos tables existantes : tout est en `CREATE ... IF NOT EXISTS` et
`INSERT OR IGNORE`. Tous les objets du socle sont préfixés (`meta_`, `ref_`, `mdm_`, `dq_`, `stg_`, `core_`,
`dim_`, `mart_`), donc vos tables actuelles n'entrent pas dans le dictionnaire.

## Contenu

| Fichier | Rôle |
|---|---|
| `sql/01_metadonnees.sql` | Dictionnaire (`meta_champ`), glossaire, lineage (`meta_run`, `meta_fichier_source`) |
| `sql/02_reference.sql` | 9 tables `ref_*` (devise, banque, type de compte, plan de flux, type de transaction, format de relevé, statut de rapprochement, scénario, mapping de libellés) |
| `sql/03_maitres.sql` | `mdm_*` : entité, compte, contrepartie + alias, site, facilité |
| `sql/04_qualite.sql` | `dq_regle`, `dq_execution`, `dq_resultat`, `stg_rejet` (quarantaine et file de revue) |
| `sql/05_couches.sql` | `stg_releve_ligne`, `core_mouvement`, `core_solde_releve`, `core_prevision`, `dim_date` + 4 vues `mart_*` |
| `sql/06_seed_reference.sql` | Valeurs initiales (banques, plan de flux, mappings d'exemple, glossaire) |
| `dq_regles.py` | 14 règles qualité couvrant les 7 dimensions DAMA |
| `dq_runner.py` | Exécute les règles, calcule les scores, met en quarantaine, remplit la file de revue |
| `mdm_utils.py` | Normalisation, catégorisation, résolution et fusion de contreparties, chargement idempotent |
| `lineage.py` | Ouverture / fermeture de runs, enregistrement des fichiers par hash |
| `descriptions_champs.py` | Descriptions métier de chaque champ (source du dictionnaire) |
| `dictionnaire.py` | Remplit `meta_champ`, exporte Markdown et Excel |
| `init_db.py` | Applique le tout, dans l'ordre |
| `test_gouvernance.py` | 19 tests, dont l'injection d'anomalies connues |
| `docs/` | Dictionnaire généré (Markdown et Excel) |

## Conventions

- **Montants** : entiers en cents, jamais de float. `montant_cents > 0` = encaissement, `< 0` = décaissement.
- **Dates** : texte ISO `AAAA-MM-JJ`.
- **Codes de référence** : MAJUSCULES sans accent; on désactive un code (`actif = 0`, `date_fin`), on ne le supprime pas.
- **Numéros de compte** : jamais stockés en clair. `mdm_compte` garde un masque (`****1234`) et un hash salé.
  Le sel doit venir d'une variable d'environnement, pas du code.
- **Idempotence** : `core_mouvement.hash_transaction` est unique; recharger un relevé ne crée pas de doublon.
  `occurrence` distingue deux opérations identiques le même jour dans un même fichier.

## Qualité des données

Chaque règle a une sévérité et un seuil :

| Sévérité | Conséquence |
|---|---|
| `bloquante` | Le mouvement passe en `quarantaine` : exclu des vues `mart_*`, copié dans `stg_rejet` |
| `avertissement` | Le mouvement est marqué `avertissement` mais reste dans les rapports |
| `info` | Suivi seulement, exclu du score global |

Une règle réussit si son score (part des lignes conformes) atteint son seuil. Une seule violation peut donc
passer si le seuil le permet : c'est voulu pour les avertissements. Sur une base **vide**, tous les scores sont
100 % (rien à évaluer) : ce chiffre n'a de sens qu'avec des données.

Pour ajouter une règle : ajouter un dict à `REGLES` dans `dq_regles.py`, puis relancer `dq_runner.py`
(la table `dq_regle` est synchronisée; votre choix `actif` est préservé).

## Branchement sur les agents (à faire)

| Agent / composant | Branchement suggéré |
|---|---|
| Orchestrateur | `lineage.demarrer_run()` au départ, `terminer_run()` à la fin, `run_id` passé aux agents |
| A1 Acquisition | `lineage.enregistrer_fichier()` : si `deja_vu`, sauter le fichier |
| A2 Extraction | Écrire le texte brut dans `stg_releve_ligne`, puis `mdm_utils.charger_mouvement()` vers `core_mouvement` |
| A6 relecteur LLM | Lire `stg_rejet` (`a_revoir`) et `mart_contreparties_a_valider`; mettre à jour `statut_traitement` |
| Dashboard | Lire `mart_dq_derniere_execution`, `dq_execution` (tendance), `meta_run`, `mart_flux_mensuel` |
| Générateur de 1000 scénarios | Tirer ses valeurs dans les tables `ref_*` et injecter des anomalies étiquetées pour mesurer le taux de détection |

## Limites et points à confirmer

1. **Ce module est autonome.** Il a été construit sans accès à votre `tresorerie.db` réelle ni à vos agents A1 à A7.
   Il faut mapper vos tables et colonnes actuelles vers `core_mouvement`, `core_solde_releve` et `core_prevision`,
   ou adapter ces schémas à ce que vos agents écrivent déjà.
2. **Les 4 formats de relevé** de `ref_format_releve` (`PDF_TEXTE`, `PDF_IMAGE`, `CSV`, `XLSX`) sont une hypothèse.
   Remplacez-les par vos formats réels.
3. **`ref_mapping_libelle`** ne contient que des exemples génériques : à enrichir avec vos libellés bancaires.
4. **Jours fériés** : `dim_date.est_ouvrable` exclut seulement les fins de semaine.
5. **Migrations** : le schéma est en `IF NOT EXISTS`; un changement de colonne ultérieur demandera un script `ALTER`
   numéroté (la version est suivie dans `meta_version_schema`).
6. **Non couvert** (domaines DMBOK hors de ces deux vagues) : contrôle d'accès et chiffrement de la base, sauvegardes,
   métadonnées du corpus RAG, authentification du dashboard exposé par tunnel.
7. **Seuils** de `dq_regles.py` (90 à 100 %) : réglages de départ, à calibrer sur vos données réelles.
8. **Rapprochement flou** des contreparties : seuil de similarité de 0,88 (`difflib`). Un cas ambigu devient une
   contrepartie « à valider » plutôt qu'une fusion silencieuse; vérifiez la file de revue au début.
