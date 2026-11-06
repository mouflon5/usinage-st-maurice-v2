# Banc d'essai et poste de pilotage du système multi-agents (A1 → A7 + relecteur A8)

Teste l'orchestrateur sur **1000 scénarios** variés (10 banques, 4 mises en page de relevé, fournisseurs industriels,
commerçants, pannes injectées) et mesure où il réussit, où il refuse prudemment et où il se trompe **sans le dire**.

## Lancer
```
python -m pip install -r requirements.txt
python -m banc_essai.executeur --seed 7 --n 1000 --workers 2     # mode simulé : aucun appel API
streamlit run banc_essai/tableau_de_bord.py                       # poste de pilotage : lancer / observer / évaluer
```
Le plus simple : n'ouvrir que le tableau de bord et lancer les lots depuis l'onglet **Contrôle** (voir plus bas).
Options utiles : `--sans-a8` (même lot sans le relecteur, pour comparer) · `--ids a,b --forcer` (rejouer des scénarios précis) ·
`--categories nominal,chaos` · `--n 50` (essai rapide) · `--types jumeaux` (un seul type) · `--run-id lot1000` (reprendre un lot interrompu) ·
`--reel` (appelle Claude : A3 sur le résidu, A5 et A7 pour la rédaction ; **coûte des jetons**, commencer par `--n 20`).
`tresorerie.db` n'est jamais modifiée : chaque scénario travaille sur une copie jetable.

## Ce que contient un scénario
Un générateur à graine fixe (`banc_essai/generateur.py`) fabrique de vrais PDF et fixe **avant l'exécution** :
- la **vérité** : quelles lignes doivent finir en base et dans quelle catégorie (ou à l'arbitrage) ;
- l'**attendu** : les statuts de pipeline acceptables ;
- les **pannes** à injecter : LLM en panne / catégorie inventée / réponse fausse et sûre d'elle, SARIMAX en panne, base verrouillée, base absente, base corrompue.

| Catégorie | Part | Exemples |
|---|---|---|
| nominal | 50 % | relevé normal, commerçants (Canadian Tire, Tim Hortons…), achats ambigus, multi-mois, 150 lignes, 1 ligne |
| limite | 25 % | découvert, 1er/dernier jour du mois, montants de 0,01 $ à 2,5 M$, achats identiques le même jour, accents, notes de crédit, collisions de mots-clés |
| défectueux | 15 % | mois manquant, PDF corrompu/vide, ligne illisible, solde cassé, lignes manquantes en fin de relevé, format inconnu, fichier d'un autre mois/compte |
| chaos | 10 % | base corrompue, LLM en panne, injection dans un libellé, SARIMAX en panne, base verrouillée |

## Comment on juge (verdicts)
On compare ce qui est **écrit en base** à la vérité, puis le statut final aux statuts acceptables.
- Critique : `PLANTAGE`, `DONNEES_FAUSSES` (ligne perdue ou fantôme), `MAL_CLASSE`, `ECRITURE_PARTIELLE`, `DEFAUT_NON_DETECTE`.
- Avertissement : `SURCONFIANCE`, `ESCALADE_INATTENDUE`, `ARRET_PRUDENT`, `STATUT_INATTENDU`.
- Info : `ARRET_AUTRE_AGENT`.

Un échec marqué « limite connue » est réel mais déjà identifié (ex. un LLM sûr de lui et faux ne peut pas être détecté par des contrôles déterministes).

En mode simulé, la classification du résidu (A3) est l'heuristique par similarité de `llm_outils.py`, pas Claude : les taux de classement
mesurés ne sont donc pas ceux du vrai modèle. Relancer avec `--reel` sur un échantillon pour les comparer.

## Ce qui a changé dans A1 / A2 (pour accepter plus de conditions)
- **A1** accepte 4 conventions de nom : `Compte_2026-05.pdf`, `Compte - 2026-05.pdf`, `Compte_202605.pdf`, `Compte_05-2026.pdf`. Deux relevés pour la même période arrêtent le pipeline.
- **A2** lit 4 mises en page via `formats_releves.py` : F1 ligne signée (inchangé), F2 Débit/Crédit, F3 date courte + DR/CR, F4 montants entre parenthèses. Les colonnes sont lues par position, d'après l'en-tête du tableau.
- Nouveaux contrôles d'A2 (toujours « arrêter plutôt que deviner ») : dates dans la période du nom de fichier (`A2_VERIFIER_PERIODE=0` pour désactiver), compte de l'en-tête = compte du nom de fichier, soldes d'ouverture et de clôture quand le relevé les imprime, PDF sans contenu reconnu refusé (avant : accepté avec 0 transaction).
- **Les mises en page sont des modèles représentatifs, pas des copies des relevés réels** de ces banques : avant d'y compter, valider avec un vrai PDF de chacune.

## A8 — le relecteur LLM dans le pipeline (nouveau)
Placé **après A6** (et aussi avant un arbitrage humain, quand A4–A6 n'ont pas tourné). A6 vérifie que les chiffres sont justes ;
A8 donne un second avis qualitatif : une ligne classée dans une catégorie surprenante, des achats identiques écartés comme doublons,
un commentaire qui affirme plus que le tableau.
- **Il ne peut qu'ajouter des réserves** : le pipeline devient « complet_avec_reserves » et A7 imprime la réserve dans le rapport. Il ne bloque
  jamais, ne débloque jamais, ne modifie aucune donnée. Le blocage reste réservé aux 11 contrôles déterministes d'A6.
- **Garde-fous sur le LLM** : chaque constat doit citer une référence existante (L12 = ligne classée, D3 = doublon écarté, A6:C7 = contrôle),
  avoir une gravité connue et ne contenir aucun nombre absent du dossier ; sinon il est rejeté (et listé à part dans le tableau de bord).
  Les libellés bancaires sont traités comme des données, jamais comme des instructions.
- **Mode simulé** (par défaut sans clé API) : règles déterministes — signe incompatible avec la nature, précédent le plus proche d'une autre
  catégorie, mot-clé qui n'apparaît qu'à l'intérieur d'un autre mot (ERP dans SUPERPRIX), ligne identique à une autre du même relevé écartée comme doublon.
  **Mode réel** (`LLM_MODE=reel`, clé API) : Claude (`A8_MODELE`, défaut claude-sonnet-5-5) relit le dossier avec les mêmes garde-fous.
- Variables : `A8_ACTIF=0` (désactiver) · `A8_ECHEC_EST_RESERVE=0` (si le LLM est en panne, ne rien ajouter ; par défaut une réserve « relecture non effectuée »).
- Le banc d'essai mesure A8 contre la vérité terrain : défauts signalés (rappel), alertes justifiées (précision), fausses alertes, lignes citées à bon escient.

## Poste de pilotage (tableau de bord)
`streamlit run banc_essai/tableau_de_bord.py` — quatre onglets :
| Onglet | Ce qu'on y fait |
|---|---|
| Contrôle | Lancer un lot (taille, graine, workers, simulé/réel, relecteur A8 oui/non, catégories et types), ⏸ pause, ▶ reprise, ⏹ arrêt propre, ⛔ arrêt immédiat, reprendre les scénarios restants, supprimer un lot ; fil des derniers scénarios en direct |
| Vue d'ensemble | Réussite par type / banque / format / catégorie, parcours des scénarios (jusqu'où ils vont), façons de se terminer, classement des lignes |
| Scénarios & agents | Un scénario à la fois : A1 → A2 → A3 → A4 → A5 → A6 → A8 → approbation → A7 (statut, durée, volumes transmis), chronologie, « qui a passé quoi à qui », ligne par ligne attendu vs obtenu, 11 contrôles d'A6, constats d'A8 (et avis écartés), défauts constatés ; bouton ↻ Rejouer |
| Performance | Latence par agent (médiane, p95), débit, distribution des durées, jetons (mode réel), évaluation d'A8, comparaison de deux lots (même graine : scénario par scénario) |
L'exécuteur est un processus séparé : fermer la page ne l'arrête pas. Les commandes passent par la base `resultats.db` (colonne `commande`),
l'exécuteur y écrit un battement de cœur chaque seconde ; sans battement depuis 20 s, le tableau de bord le déclare arrêté.
