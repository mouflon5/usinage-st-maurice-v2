# Mettre l'application en ligne (sans ordinateur allumé)

GitHub stocke le code ; un hébergeur de conteneurs fait tourner l'application. Le `Dockerfile` du dépôt démarre
Streamlit, le serveur du tableau et un proxy (Caddy) derrière **un seul lien**.

## Hugging Face Spaces (gratuit)

1. Créer un compte sur https://huggingface.co, puis **New Space** : SDK **Docker** → *Blank*, visibilité *Public*.
2. Dans **Settings → Variables and secrets**, ajouter le secret `ANTHROPIC_API_KEY` (et fixer une limite de dépense
   dans la console Anthropic : tout visiteur peut déclencher des appels LLM).
3. Pousser le code vers le Space (le jeton d'accès s'obtient dans *Settings → Access Tokens*, droit *write*) :

```bash
git remote add space https://huggingface.co/spaces/<utilisateur>/<nom-du-space>
git push space main
```

4. Ajouter en tête du `README.md` **du Space** (pas obligatoire sur GitHub) :

```yaml
---
title: Usinage St-Maurice v2
sdk: docker
app_port: 7860
---
```

L'application est servie sur `https://<utilisateur>-<nom-du-space>.hf.space`. Le premier démarrage prend quelques minutes.

## Limites en ligne

- La vue « LangSmith Studio » dépend d'un serveur local et ne fonctionne pas en ligne.
- L'espace disque du conteneur est temporaire : la base de démo repart de zéro à chaque redémarrage.
