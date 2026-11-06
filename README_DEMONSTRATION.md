# Démonstration en direct — tout le système au même endroit

```
python lancer_demo.py              # démarre le tableau de trésorerie (port 8765) + le poste de démonstration (port 8501)
python lancer_demo.py --reset      # repart d'une base de démo neuve
python -m demo_live.repetition     # répétition générale : joue les 12 scénarios et vérifie l'issue (≈ 35 s)
python test_demo.py                # tests : données du tableau, effet de trésorerie, RAG
```
Fermer avec Ctrl+C dans la fenêtre du lanceur. Ne modifie jamais `tresorerie.db` : la démo travaille sur sa propre copie
(`demo_live/donnees/base_demo.db`).

## Les cinq vues

| Vue | Ce qu'elle montre |
|---|---|
| 🎬 Démo en direct | Choisir un scénario, **Lancer**. A1 → A8 → A7 s'allument un par un ; chaque agent se déplie (lignes classées, doublons, écarts, 11 contrôles, réserves A8). Indicateurs avant/après. **Pas à pas**, **Pause**, **Arrêter**, **Approbation humaine**. « Afficher le tableau à côté » met ton tableau en regard. |
| 📊 Trésorerie | **Ton tableau HTML, mise en page inchangée** (R0–R8), alimenté par la base de démo. Il se recharge seul à chaque étape et garde l'onglet affiché. |
| 🧭 Pilotage | Le poste de pilotage du banc d'essai (lots de 1000 scénarios, performance, relecteur A8). |
| 📑 Rapports | R0 (texte) et classeur Excel produits par A7 pour chaque passage, plus les rapports d'origine. Téléchargement. |
| 💬 Assistant | Questions en langage naturel (RAG), réponses citées, évaluation intégrée. |

## Ce qui bouge dans ton tableau, et pourquoi
La base de démo est **cumulative** : chaque scénario s'ajoute au précédent. « Remettre à zéro » recommence ; « Annuler le dernier » restaure l'état d'avant.
Les données du tableau (`const D`) sont recalculées par `donnees_tableau.py` à chaque chargement :

* **R4, R5, R6, R1, kpi, méta** : recalculés exactement depuis la base (validés chiffre par chiffre contre ton tableau d'origine).
* **Effet de trésorerie** : la somme des écritures ajoutées depuis la base d'origine décale le solde de départ. Solde actuel, creux, semaines sous le seuil, cone du rolling forecast (R2), trajectoires R0/R3/R7 suivent.
* **Mois clôturé** : le moteur passe le mois traité en « réel » dans la grille d'écarts (paramètre `ecarts.dernier_mois_reel`).
* **R8 (SARIMAX)** : lit la base de démo en direct.

## Limites à connaître (dites-les si on te pose la question)
1. R3/R7 (simulations) ne sont **pas relancées** : leurs distributions sont décalées du montant de trésorerie ajouté (exact, les soldes sont additifs) ; les probabilités de passer sous le seuil / à découvert sont **recalées par interpolation** sur la distribution d'origine (approximation).
2. Les textes de commentaire de R0 (verdict, décisions) sont ceux de ton tableau ; seuls les chiffres des constats sont mis à jour.
3. Les lignes d'un scénario **s'ajoutent** à un mois qui contient déjà des écritures (octobre 2026, déjà alimenté dans la base d'origine) : le tableau reflète donc « octobre + relevé ».
4. Sans Internet : les graphiques utilisent le Plotly du paquet `plotly` (inclus dans requirements) ; les polices Google se rabattent sur les polices système.
5. Mode simulé par défaut (gratuit, déterministe). Le vrai LLM s'active par l'interrupteur « Vrai LLM » si `ANTHROPIC_API_KEY` existe.
6. Lancement détaché du moteur sous Windows : prévu (CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS) mais non testé sur Windows ; le journal d'un passage est dans `demo_live/donnees/journaux/`.

## Les 12 scénarios de démonstration
Relevé normal · Fournisseurs et commerçants · Achats ambigus (arbitrage) · **Deux achats identiques (A8 réserve : doublon silencieux)** ·
**Remboursement de crédit (A8 réserve : signe)** · Collision de mots-clés · Gros volume · Défaut : mois manquant (A1 arrête) ·
Défaut : solde incohérent (A2 arrête) · Chaos : base corrompue (A6 bloque) · Chaos : consigne cachée dans un libellé · Chaos : le LLM en panne.
Les relevés sont générés avec une graine fixe : **toujours les mêmes** d'une présentation à l'autre. Tu peux aussi déposer tes propres PDF.

## Déroulé suggéré (10 minutes)
1. « Relevé normal », tableau à côté : les indicateurs bougent à A3, A5, A7 ; ouvrir le R0 dans Rapports.
2. « Deux achats identiques » en **pas à pas** : A3 écarte un doublon sans le dire, A8 le signale (« le LLM ne décide pas, il alerte »).
3. « Base corrompue » : A6 bloque, rien ne sort, la base de démo n'est pas touchée.
4. « Achats ambigus » avec **Approbation humaine** : approuver, puis rejeter sur un second passage.
5. Assistant : « Quel est le creux de trésorerie ? » (chiffre calculé, jamais deviné), « Que fait A8 ? » (cité), une question hors sujet (refus).
6. Pilotage : un lot de 1000 scénarios déjà exécuté, performance et rappel d'A8.

## RAG — ce qu'il fait
* **Texte** : index SQLite FTS5 (BM25, sans accents) de R0, traces d'agents, passages de la démo, résultats du banc d'essai, documentation, catégories/mots-clés/paramètres, exemples de libellés. « Reconstruire l'index » après de nouveaux scénarios.
* **Chiffres** : fonctions fixes sur la base ; jamais un nombre retrouvé dans un texte.
* **Garde-fous** : passage = donnée (consignes cachées neutralisées) ; en mode Claude, tout nombre doit exister dans le contexte sinon retour à la réponse extractive ; sans source → « je ne trouve pas ».
* **Évaluation** (dans la vue) : 36 questions dérivées des données — 35 réussies, une manquée (« mot de passe de la base », un mot de la question existe dans le corpus : limite d'un moteur lexical). Pour un sens plus fin : ajouter des vecteurs (embeddings locaux) — non fait.

## Trois diagrammes interactifs (onglets « Flux des agents », « Processus cible », « Système RAG »)

- **🕸 Flux des agents** : A1→A8 avec, sur chaque flèche, ce qui est transmis (nombre de transactions, lignes classées, contrôles OK, réserves…), les lectures/écritures dans SQLite, les agents qui utilisent un LLM, le détail de chaque agent au clic, les rapports qui en dépendent, et des métriques (durée par agent contre moyenne, effet sur le tableau, issues des passages).
- **🧩 Processus cible** : le processus N1 en quatre couloirs (contrôleur, orchestration, agents IA, outils déterministes). Le jeton avance avec le passage choisi, le journal décrit chaque échange, les métriques montrent la part humaine. Reconstruit d'après la description du processus cible ; à aligner sur le fichier draw.io si besoin.
- **🔎 Système RAG** : architecture (analyse, outils de chiffres, BM25, filtre de couverture, neutralisation, rédaction, refus), chemin surligné de chaque question, boutons *Poser la question*, *Évaluer*, *Reconstruire l'index*, et métriques (latence par étape, taux de refus, qualité par type de question, MRR, composition de l'index).

Chaque diagramme a une barre de rejeu : choisir un passage, déplacer le curseur, lire pas à pas, ou « Suivre le direct ». Les pages sont aussi accessibles seules : `http://127.0.0.1:8765/diagrammes/flux.html` (`cible.html`, `rag.html`).

## Vue « 📈 Performance » : agents et modèles LLM

Quatre onglets (page autonome : `http://127.0.0.1:8765/diagrammes/performance.html`) :

- **Synthèse** : passages joués, conformité aux issues attendues, durée médiane, appels LLM, coût, taux de rejet des garde-fous ; pipeline A1→A8 coloré selon la santé de chaque agent ; issues des passages ; part des lignes classées par règles / LLM / escalade humaine.
- **Agents** : pour chacun, part des passages qui l'atteignent, issues (OK / réserve / arrêt), durée p50/p90/max, courbe des dernières durées, motifs d'arrêt ; réussite des 11 contrôles d'A6.
- **Modèles LLM** : appels par agent et par modèle, erreurs, latence p50/p95, jetons entrée/sortie, coût, confiance moyenne et taux d'acceptation (A3), histogramme des confiances, coût par passage.
- **Garde-fous** : vérifications et rejets (nombres non sourcés, références inconnues), filtre de confiance d'A3, pannes du LLM, escalades vers l'humain.
- **Banc d'essai** : si `banc_essai/resultats/resultats.db` existe (`python -m banc_essai.executeur --n 1000 --seed 7`) : verdicts, qualité des lignes (mal classées, surconfiance, fantômes), durées par agent, jetons réels.

Le bouton **Lancer une rafale** joue les 12 scénarios à la suite sans effacer l'historique.

Mesure : `suivi_llm.py` note chaque appel LLM (réel ou simulé) dans la base de démo, uniquement quand la démo tourne. En mode simulé les jetons sont estimés (1 jeton ≈ 4 caractères) et le coût est « équivalent » ; les tarifs sont indicatifs, à ajuster dans `suivi_llm.py` (`PRIX`) ou via la variable `SUIVI_PRIX_JSON`. Les latences simulées ne représentent pas celles de l'API : lancez un passage en mode « LLM réel » pour les mesurer.
Test : `python test_suivi.py`.

## Diagrammes alignés sur l'architecture v1.5 (pages 3 à 6 du drawio)

- **Processus cible** : 5 couloirs, passerelles « Contrôle bloquant ? » (escalade) et « Réserves ? » (arbitrage humain) qui s'allument selon le run. Les éléments pointillés « cible » ne sont pas implémentés. OpenClaw est volontairement omis ; A8 (relecteur LLM) est marqué « ajout démo ».
- **Flux** : agents A1→A8 + mémoire partagée (dépôt, grand livre, référentiel, journal, registre des exceptions). Cliquer sur un agent montre ce qu'il lit/écrit. Bandeau LLM Ops en bas.
- **RAG** : 4 blocs (corpus, indexation, récupération hybride, ancrage/évaluation) avec badges démo / partiel / cible et carte « écart ». Cible : vecteurs denses, RRF, cross-encoder, filtres durs, SHA-256, métadonnées.
- **Performance = boucle LLM Ops** : onglets Trace, Observation, Évaluation, Diagnostic, Porte, Publication. Seuils dans `CRITERES_SEUILS` (api_diagrammes.py). La publication d'une configuration (table `publications`) n'est possible que si la porte est verte ; coûts et latences en mode simulé sont « équivalents », non réels.
