# Groupe Usinage Saint-Maurice — système multi-agents de trésorerie, version 2

**Groupe Usinage Saint-Maurice inc.** est une entreprise **fictive** d'usinage de précision et d'ensembles mécanosoudés à Trois-Rivières (Mauricie) :
usinage sur mesure, contrats récurrents (aéro et rail), pièces de rechange et service, prototypage et ingénierie. Les noms de clients, de fournisseurs et de
banques sont inventés ; seuls les types de produits, de services et de matières s'inspirent du secteur.

Cette version reprend **toutes les fonctionnalités de `orchestrateur_harnault_v2`** (menu groupé Simple / Expert, états financiers dynamiques, achats et
paiements, coûts de revient, consolidation, gouvernance des données, architecture d'affaires, prix de marché) avec les **données, produits, services et
processus de l'usinage**. Les projets `orchestrateur_live` (la première version de ce groupe) et `orchestrateur_harnault_v2` ne sont pas modifiés.

## Ce qui a changé par rapport à Harnault Énergies v2

| Élément | Harnault Énergies | Groupe Usinage Saint-Maurice |
|---|---|---|
| Activité | distribution d'énergie, Berthierville | usinage de précision, Trois-Rivières |
| Revenus | carburants, aviation et flottes, mazout et propane, lubrifiants | usinage sur mesure, contrats aéro et rail, pièces de rechange, prototypage |
| Coût des produits | achats de produits pétroliers | matières premières (acier, aluminium, inox, titane) |
| Actifs | camions-citernes, réservoirs, stations | centres d'usinage CNC, postes de soudure, machine à mesurer |
| Fournisseurs | raffineries, transporteurs ferroviaires | Acier Russel, Alcan, Métaux Solutions, Kennametal, Sandvik, galvanisation, traitement thermique |
| Marché suivi | pétrole WTI, essence à la pompe | aluminium, acier (indice), nickel, cuivre, change |
| Coûts de revient | litre de carburant, dépôt, livraison | pièce usinée, centres d'usinage CNC, soudure, contrôle, ingénierie |
| Consolidation (3 divisions) | carburants, chauffage, lubrifiants | usinage de précision, pièces de rechange, prototypage |
| Architecture d'affaires | unités, capacités et flux « produit livré » | 14 unités, 54 capacités, 6 flux de valeur, flux « pièce usinée » (original usinage, avec le cycle achats-décaissements de v2) et flux « Spécialiser un agent de trésorerie » (processus N1 à N5, 56 tâches) |

Ce qui ne change pas : les **montants, les dates et la structure de la base** (le journal est celui de l'original usinage), les 25 catégories (nature et ordre),
la logique des agents A1 à A8, les contrôles et le choix du LLM (simulé, Claude ou Ollama). L'identité visuelle passe du vert énergie au bleu acier.

## Navigation et statuts Simple / Expert
Menu latéral groupé : *Piloter* (accueil, trésorerie, états financiers, consolidation du groupe, achats et paiements, coûts de revient, planification budgétaire, rapports, architecture d'affaires), *Agents*,
*Analyse et qualité* (prix des métaux, performance, pilotage du banc d'essai, système RAG, gouvernance des données) et *Aide*. Le statut (Simple ou Expert),
en haut du menu, est mémorisé dans `demo_live/donnees/config_mode.json`.

## Prix des métaux (menu Analyse et qualité)
Remplace la vue « Prix de l'essence » : la matière représente le plus gros poste du coût des produits, et son prix suit le marché mondial en dollars américains.
- **Données** : séries FRED publiques, importées dans la base (`ref_serie_marche`, `core_prix_marche`) — aluminium, nickel, cuivre (depuis 1992), indice des prix de l'acier
  (depuis 1939), minerai de fer, zinc et change CAD/USD. Mise à jour : bouton de la vue, ou `python -m prevision_metaux.base --db tresorerie.db --fred`.
- **Chaîne** (`projection_metaux.py`) : prix du métal (ou panier : acier 50 %, aluminium 25 %, inox 15 %, cuivre 10 %) → prix d'achat chez le distributeur (une part suit le
  marché et le change, le reste est fixe) → achats de matières → ventes (clauses d'indexation des contrats aéro et rail, soumissions, avec délai) → volume → encaisse,
  décalée par les jours de créances et de fournisseurs. Scénarios bas / central / haut, sensibilité, envoi aux états financiers.
- **Modèles** (`prevision_metaux/`) : marche aléatoire réglable, ARIMA, GARCH et ensemble, évalués par backtest walk-forward ; aucun paquet d'apprentissage profond.
  Recalcul : `python -m prevision_metaux.calcul --update`. Résultats dans `donnees_externes/metaux/<cible>/`.
- Tests : `python test_projection_metaux.py`.

## Raisonnement des agents en réseau de neurones (menu Agents → Raisonnement, onglet « 🕸 Réseau de neurones »)
`raisonnement_graphe.py` (moteur) et `demo_live/reseau_ui.py` (dessin Plotly) montrent un passage comme un réseau : entrées → agents A1 à A8 → décision humaine → rapports, avec pour A3, A5, A8 et A7 un neurone LLM
(hexagone, ouvert s'il est simulé) et son garde-fou (losange), puis 14 neurones d'indicateurs reliés aux agents qui les produisent et entre eux (flux → solde → creux → coussin…). L'épaisseur d'une flèche est le volume transmis,
sa couleur le verdict (conforme, à surveiller, critique) ; un indicateur est cerclé de vert ou de rouge selon que le passage l'a fait bouger dans le bon ou le mauvais sens. On clique un neurone (ou on le choisit dans la liste)
pour mettre en évidence son voisinage et lire sa règle, sa décision, ses échanges LLM, ses raisons de rejet, ce qu'il reçoit et ce qu'il transmet ; le curseur « Étape du passage » rejoue le raisonnement agent par agent.
Sans passage, la structure du réseau s'affiche quand même. Tests : `test_reseau_raisonnement.py` (28).

## Coûts de revient (menu Piloter, `demo_live/couts_ui.py`, `couts_revient.py`, `couts_rapports.py`)
Revue par un contrôleur CPA de manufacture : **moins de méthodes, mieux choisies**. Chaque onglet s'ouvre sur un bandeau (la question, la méthode, la décision éclairée, à qui elle sert). Dix onglets, dans l'ordre du raisonnement :
- **Tableau de bord** : neuf indicateurs à seuils (dont la fiabilité des soumissions), constats, matrice de positionnement des lignes, distorsion du coût, puis le **cadre de gestion** : six méthodes piliers, quatre compléments et cinq méthodes écartées avec la raison.
- **Du compte au produit** : diagramme de flux du poste comptable (5010, 6030, 5210, 6xxx, 7xxx, 8010) aux centres, puis aux produits ; coût complet par composante.
- **Rentabilité (ABC)** : centres d'analyse (taux par centre) contre ABC, carte de chaleur des charges indirectes, distorsion.
- **Prix** : cascade du prix à la marge, trois planchers (variable, spécifique, complet) et prix cible.
- **Devis contre réel** (nouveau) : coût par commande — marge soumise contre marge réelle, écart par élément (matière, main-d'œuvre, machine, sous-traitance, reprises), précision d'estimation par ligne, cascade d'une commande.
- **Décisions à la marge** : marge sur coûts variables, point mort par ligne, levier, tornado, abandon d'une ligne et **commande spéciale** (coûts pertinents, coût d'opportunité si la capacité est pleine).
- **Standards et écarts** : matière (prix, quantité), main-d'œuvre (taux, rendement), frais variables et **frais fixes (écart de budget et écart de volume, sous-imputation)**, règle d'investigation, cartes de contrôle, écart de prix entre marché et achat.
- **Capacité et contraintes** : sous-activité par centre (imputation rationnelle) et mix par heure-machine (théorie des contraintes), valeur d'une heure de plus.
- **Coût cible et qualité** : coût admissible et feature costing ; activités selon leur valeur (ABM) et coût de la qualité.
- **Rapports** : stratégique (conseil, annuel), tactique (directeurs, mensuel) et opérationnel (atelier, hebdomadaire), avec indicateurs à seuils, messages, analyse, plan d'action chiffré et export PDF, HTML ou Markdown. Les rapports intègrent maintenant la fiabilité des soumissions, les frais fixes et les commandes à surveiller.
Retiré : les unités de valeur ajoutée (UVA, inducteur composite aux coefficients arbitraires) et l'onglet « Panorama » (remplacé par le cadre du tableau de bord). Montants fictifs et modifiables, aucune écriture en base.
Tests : `test_couts_revient.py`, `test_couts_rapports.py`.

## Planification budgétaire (menu Piloter, `demo_live/budget_ui.py`, `budget_planification.py`, `process_mining.py`)
Budget de l'exercice 2027 par trois approches réconciliées, sur les mêmes chiffres que les coûts de revient (ventes de 18,1 M$, frais indirects de 7,1 M$). Six onglets :
- **Processus** : le cycle budgétaire en couloirs (direction, gestionnaires d'unités, responsables de centres, contrôle de gestion, comité, conseil), chaque étape portant son chiffre recalculé, la boucle de négociation, l'étape en cours selon la date du jour et le calendrier (diagramme de Gantt).
- **Top-down** : croissance, marge et productivité cibles ; l'enveloppe des frais indirects est un résidu, répartie vers les lignes et les centres (diagramme de Sankey).
- **Bottom-up** : hypothèses par ligne (volume, prix, productivité) et inflations ; pont du résultat de base au résultat demandé, capacité du centre CNC, frais indirects par centre avec la prudence des gestionnaires.
- **Base zéro** : 39 paquets de décision à trois niveaux (minimum obligatoire, actuel, amélioré), notés selon quatre critères pondérables, classés par valeur par k$ ; ligne de coupure à l'enveloppe.
- **Réconciliation** : leviers chiffrés du résultat ascendant au budget retenu (retrait de la prudence, base zéro, productivité, prix), tours de négociation, budget maître (base, top-down, bottom-up, retenu) et phasage mensuel.
- **Process mining** : journal d'événements **synthétique** et reproductible pour deux processus (achats et paiements, commande de fabrication). Carte des suivis directs avec curseur de complexité (épaisseur = fréquence, couleur = attente), variantes, goulots, délais de bout en bout, conformité au modèle par alignement (étapes sautées, reprises, ordre inversé), séparation des tâches, diagramme à points, coût des reprises. Le coût des reprises alimente un paquet de la base zéro (appariement automatisé des factures).
Montants fictifs et modifiables, aucune écriture en base. Tests : `test_budget_planification.py` (18).

## Consolidation du groupe (menu Piloter, `consolidation_groupe.py`, `demo_live/groupe_ui.py`, `test_consolidation_groupe.py`)
Le cas intégrateur du chiffrier du cours (`Chiffrier_consolidation_Groupe_Saint-Maurice.xlsx`, NCECF, exercice clos le 31 décembre 2025) : société mère, Usinage et Immeubles à 100 %, Soudure Bécancour à 80 %
(acquise le 1er avril 2025, participation ne donnant pas le contrôle de 20 %) et USM Precision, filiale américaine en USD. Les neuf étapes du classeur : balances de vérification, conversion au cours de clôture
(écart de conversion en résidu), acquisition et répartition du prix (écarts de juste valeur, impôts différés, écart d'acquisition de 1 163 000 $, comparaison avec la quote-part IFRS), les 19 écritures de consolidation
avec leur explication, chiffrier, PNDC (résultat attribuable de 61 304,50 $, solde de 1 111 304,50 $), états consolidés (produits de 33 690 000 $, résultat net de 2 579 522,50 $) et les huit contrôles.
Tout se recalcule quand on change une hypothèse (détention, impôt, cours de change, juste valeur, profit non réalisé amont ou aval, soldes intersociétés). Un décalage de coupure fait échouer le contrôle de réciprocité.
Le moteur reproduit exactement les résultats du classeur (testés) et renforce deux contrôles (résidus intersociétés et billet : valeurs absolues de chaque côté). Données indépendantes de la base de trésorerie.

## Consolidation de trois divisions (vue « États financiers », `consolidation.py`, `demo_live/consolidation_ui.py`, `test_consolidation.py`)
Onglets « 🏢 Consolidé (3 divisions) » et « 🧮 Écritures de consolidation ». Trois divisions d'une même société : *Usinage de précision* (usine, machines CNC, soudure, siège),
*Pièces de rechange et service*, *Prototypage et ingénierie*. Les états existants sont répartis entre les divisions, puis les opérations internes sont ajoutées dans les livres de
chacune : pièces cédées au prix de cession, temps-machine refacturé, frais de gestion, prêt et intérêts, soldes à recevoir et à payer, marge interne dans les stocks. Huit
écritures d'élimination (EC-1 à EC-8) ramènent la somme des divisions aux états existants : le consolidé les retrouve ligne par ligne (18 contrôles, 200 combinaisons aléatoires testées).
Hypothèses : aucune participation entre divisions (ni élimination de titres, ni écart d'acquisition, ni part sans contrôle), une seule déclaration d'impôt (pas d'impôt différé sur la marge interne).
Le cas juridique complet du Groupe Saint-Maurice (société mère, Soudure Bécancour à 80 %, filiale américaine en USD) est dans la vue « Consolidation du groupe ».

## Achats et paiements (menu Piloter, `demo_live/achats_ui.py`, `cycle_achats.py`)
Cycle achats-décaissements complet sur des achats d'usinage : matières (acier, aluminium, inox, titane), outillage, sous-traitance (traitement thermique, galvanisation), transport, services.
Réception avec contrôle de la matière (pesée, certificat), appariement à trois voies, délégation d'autorité à trois niveaux, lots de paiement à double approbation, escomptes.

## Lancement
```
python lancer_demo.py                    # tableau de trésorerie (port 8765) + poste de démonstration (port 8501)
python -m streamlit run demo_live/application.py
```
Tests : `test_couts_revient.py`, `test_couts_rapports.py`, `test_consolidation.py`, `test_consolidation_groupe.py`, `test_projection_metaux.py`, `test_etats_financiers.py`, `test_cycle_achats.py`, `test_balance_verification.py`,
`test_demo.py`, `tresorerie_gouvernance/test_gouvernance.py`. La base (`tresorerie.db`) est celle de l'original usinage, avec en plus les séries de marché.
