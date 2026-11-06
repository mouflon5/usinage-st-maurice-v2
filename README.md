# Orchestrateur A1 → A2

## Ce que c'est

Un graphe LangGraph « parent » qui appelle le graphe compilé d'A1, puis — seulement
si A1 rapporte `statut == "complet"` — appelle le graphe compilé d'A2. Si A1 signale
un trou de période, le pipeline s'arrête immédiatement et A2 n'est jamais exécuté.

C'est le patron **« graphe comme nœud »** : chaque agent est appelé via `.invoke()`
à l'intérieur d'un nœud du graphe parent, plutôt que d'essayer de fusionner leurs
états (qui n'ont presque aucun champ en commun) dans un seul schéma partagé.

## Dans PyCharm

1. Ouvre ce dossier (`orchestrateur_a1_a2`) comme nouveau projet PyCharm.
2. Crée un environnement virtuel, puis :
   ```
   py -m pip install -r requirements.txt
   ```
3. Génère les 3 scénarios de test :
   ```
   py generer_donnees_test.py
   ```
4. Lance le test :
   ```
   py test_local.py
   ```
   Tu dois voir 3 résultats :
   - **Succès complet** → `statut_pipeline: complet`, 6 transactions prêtes pour A3
   - **Arrêt à A1** → `statut_pipeline: arrete_a1`, A2 jamais appelé
   - **Arrêt à A2** → `statut_pipeline: arrete_a2`, l'anomalie de solde a stoppé le pipeline

## Vers LangGraph Studio

```
langgraph dev
```

Dans Studio, le formulaire ne demande que les 4 champs d'entrée d'A1 (`compte`,
`dossier_releves`, `periode_debut`, `periode_fin`) — A2 est invoqué automatiquement
en coulisses, tu ne le vois pas comme un nœud séparé dans le graphe visuel (puisque
ce sont des appels `.invoke()` internes, pas des nœuds LangGraph natifs). Tu verras
plutôt 5 nœuds : `executer_a1`, `executer_a2`, `finaliser_succes`,
`finaliser_arret_a1`, `finaliser_arret_a2`.

Essaie les 3 dossiers de scénario un par un pour voir le court-circuit en action :
- `releves_test_succes` avec période `2026-01` à `2026-02`
- `releves_test_arret_a1` avec période `2026-01` à `2026-03`
- `releves_test_arret_a2` avec période `2026-01` à `2026-02`

## Limite de cette approche (et prochaine étape possible)

Les nœuds `executer_a1` et `executer_a2` apparaissent comme des boîtes uniques dans
Studio — tu ne peux pas voir le détail interne d'A1 (scan, analyse_couverture, etc.)
pendant l'exécution du pipeline complet, seulement le résultat final de chaque agent.

LangGraph offre une façon plus avancée d'imbriquer des graphes (les vrais
« subgraphs »), où le graphe enfant devient visible nœud par nœud dans le graphe
parent — mais ça demande que les deux graphes partagent au moins une partie de
leur schéma d'état, ce qui n'est pas le cas ici (A1 et A2 ont des champs presque
entièrement différents). Ça vaudra la peine d'explorer cette approche si tu veux un
jour un débogage plus fin, ou tu peux rester avec le patron actuel (plus simple à
comprendre) pour construire A3 à A7.

## Rappels utiles

- `pip` non reconnu → `py -m pip`
- `Unable to configure formatter 'simple'` → `py -m pip install colorama`
- Studio bloqué dans le navigateur → utilise Chrome/Edge, autorise "Local network
  access" pour `smith.langchain.com` si besoin
