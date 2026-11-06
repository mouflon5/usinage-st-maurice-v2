# Trésorerie SMA — démo multi-agents (A1 → A7)

Pipeline LangGraph : relevés PDF → extraction → classement/chargement SQLite → prévision SARIMAX →
écarts (réel / budget / prévision) → contrôle indépendant → (approbation humaine) → rapport Excel + R0.

| Agent | Rôle | LLM ? |
|---|---|---|
| A1 Acquisition | trouve les relevés, détecte les mois manquants | non |
| A2 Extraction | lit les PDF (pdfplumber), rejoue la continuité des soldes | non |
| A3 Réconciliation | doublons, règles `mots_cles`, puis Claude Haiku sur le résidu (liste fermée, seuil 0,8), chargement atomique | résidu seulement |
| A4 Prévision | SARIMAX (même moteur que R8), repli naïf saisonnier, alertes de backtest | non |
| A5 Écarts | réel vs budget vs prévision sans fuite de données, causes en SQL, commentaire | rédaction seulement |
| A6 Contrôle | 11 contrôles refaits indépendamment ; **seul point de sortie** ; bloque ou approuve | non |
| A7 Reporting | classeur Excel (R0–R5 + contrôles) et brouillon R0 | synthèse seulement |

Principe : **le LLM ne calcule jamais**. Tout chiffre rédigé par un LLM est vérifié (A5, A7, puis A6) ;
un nombre absent du tableau source fait rejeter le texte et basculer sur un gabarit.

## Installation
```
python -m pip install -r requirements.txt
copy .env.exemple .env      # puis y mettre ANTHROPIC_API_KEY (facultatif : sans clé = mode simulé)
copy tresorerie.db tresorerie_demo.db
```

## Voir le fonctionnement dans LangSmith Studio
`langgraph dev` → graphe **orchestrateur**. Entrée (YAML) :
```
compte: Desjardins EOP
dossier_releves: releves_scenario1
periode_debut: 2026-09
periode_fin: 2026-09
db_path: tresorerie_demo.db
approbation_humaine: true
```
(`python generer_scenario1.py` crée le relevé.) Avec `approbation_humaine: true`, le graphe s'arrête avant
A7 : reprendre avec `{"decision": "approuver", "commentaire": "OK"}` ou `{"decision": "rejeter", ...}`.
Chaque agent est aussi exposé seul : `a3_reconciliation`, `a4_prevision`, `a5_ecarts`, `a6_controle`, `a7_reporting`.

## Voir les agents dans ton tableau de bord
```
python lancer_dashboard.py
```
Ouvre le tableau de bord sur la **base de démo** (`tresorerie_demo.db`) et ajoute un bouton **Agents ▸** en bas à droite.
La page `/agents` montre le dernier passage du pipeline (chaîne A1→A7, écarts, prévision, contrôles A6, écritures) et
permet de revoir les passages précédents. Chaque passage écrit sa trace dans `sorties/` (dossier courant).
Après un passage (Studio ou scénarios), clique **Rafraîchir**. R8 lit la base en direct ; R0–R7 sont des chiffres
précalculés dans le HTML et ne changent pas. Ferme le tableau de bord (Ctrl+C) avant de relancer `langgraph dev`
si tu veux libérer le port.

## Scénarios aléatoires (reproductibles)
```
python lancer_scenarios.py --source tresorerie.db --seed 42 --n 10
```
Dix types de scénarios (normal, doublon, ligne résolue par précédent, ligne inconnue, solde cassé, ligne
illisible, mois manquant, base corrompue, gros écart). L'« attendu » est fixé avant l'exécution ;
`sorties_scenarios/resultats_scenarios.md|csv` compare attendu et obtenu. La copie de démo est recréée
avant chaque scénario ; `tresorerie.db` n'est jamais modifiée. `--reel` utilise Claude si la clé est présente.

## Tests
`python test_a3.py` (A3 sur base synthétique) et `python test_pipeline.py tresorerie.db` (approbation
humaine, rejet, rejet d'un chiffre inventé par un faux LLM).

## Script d'entrevue (5 minutes)
1. Scénario normal dans Studio : montrer A1→A5 puis la porte A6 (11 contrôles) et l'approbation.
2. `base_corrompue` : tout réussit en amont, **A6 bloque** — c'est le but du contrôle indépendant.
3. `residu_inconnu` : A3 escalade au lieu de deviner.
4. Le tableau attendu vs obtenu + le fichier Excel produit.

## Limites à dire franchement
- Le mode LLM réel (Claude) n'a été testé qu'avec un faux modèle ; le mode simulé est déterministe.
- Données synthétiques ; le budget n'existe que pour 2026 ; la clé anti-doublon des 37 lignes déjà dans
  `journal_saisie` a un format plus ancien (description tronquée) : seules les nouvelles lignes sont dédoublonnées.
- Les intervalles SARIMAX (config `enforce_stationarity=False`) explosent sur certaines séries : A4 les remplace par ± z × RMSE du backtest et l'écrit dans la page Agents.
- Prévision SARIMAX sans validation croisée large (backtest 6 mois) ; MAPE affiché, seuil d'alerte 25 %.
- Les attendus des scénarios sont écrits par moi, pas par un tiers : c'est une démonstration, pas une validation.

## Architecture d'affaires du groupe (vue « 🏛 Architecture d'affaires »)
Architecture d'affaires de Groupe Usinage Saint-Maurice selon le BIZBOK v11, alimentée par la base de la démonstration :
carte des capacités (dont la trésorerie et les données), flux de valeur (dont « Piloter la trésorerie », qui correspond aux
agents A1 à A8), quatre processus détaillés de N1 à N5, carte de l'information (concepts de `tresorerie.db`), feuille de route
des initiatives avec dépendances et retards simulés, et un onglet « Trésorerie ↔ architecture » qui relie les catégories du
journal général aux capacités, produits, parties prenantes et à la gouvernance des données.
Code : `demo_live/architecture/` (page) et `demo_live/architecture_ui.py` / `architecture_data.py` (intégration).
Version autonome : `demo_live/architecture/architecture_autonome.html` (instantané des données au moment de la génération).
