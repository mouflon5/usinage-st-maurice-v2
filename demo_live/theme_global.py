"""Thème clair / sombre unique pour TOUT le projet.

Un seul choix (barre latérale, « 🎨 Thème »), mémorisé dans demo_live/donnees/config_theme.json, qui s'applique :
  * à l'application Streamlit elle-même (couleurs natives, recalculées à chaud) et à ses cartes personnalisées ;
  * aux pages servies par le serveur du tableau (tableau de trésorerie, agents, diagrammes), via `?theme=dark|light` dans l'URL ;
  * à la page d'architecture d'affaires (injectée dans la page).
Les pages qui ont leur propre sélecteur le masquent quand le thème leur est imposé par l'application.
"""
from __future__ import annotations

import json
import os

CHEMIN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "donnees", "config_theme.json")
THEMES = ("clair", "sombre")

# couleurs natives de Streamlit pour chaque thème (le bleu acier sert d'accent dans les deux)
STREAMLIT = {
    "clair": {"theme.base": "light", "theme.primaryColor": "#1f5f8b", "theme.backgroundColor": "#ffffff",
              "theme.secondaryBackgroundColor": "#eef3f8", "theme.textColor": "#1b2430"},
    "sombre": {"theme.base": "dark", "theme.primaryColor": "#5aa9d6", "theme.backgroundColor": "#10151b",
               "theme.secondaryBackgroundColor": "#1a222b", "theme.textColor": "#e7ecf2"},
}
# cartes personnalisées de l'application (chaîne d'agents, verdict)
CARTES = {
    "clair": {"fond": "#ffffff", "bordure": "#d9dde3", "discret": "#5b6573", "verdict": "#f6f7f9"},
    "sombre": {"fond": "#1a222b", "bordure": "#2f3b48", "discret": "#9fb0c2", "verdict": "#1a222b"},
}


def lire() -> str:
    try:
        with open(CHEMIN, encoding="utf-8") as f:
            t = json.load(f).get("theme")
        return t if t in THEMES else "clair"
    except Exception:
        return "clair"


def ecrire(theme: str) -> None:
    os.makedirs(os.path.dirname(CHEMIN), exist_ok=True)
    with open(CHEMIN, "w", encoding="utf-8") as f:
        json.dump({"theme": theme}, f)


def est_sombre() -> bool:
    return lire() == "sombre"


def cartes() -> dict:
    return CARTES[lire()]


def parametre() -> str:
    """Valeur du paramètre d'URL `theme` pour les pages embarquées."""
    return "dark" if est_sombre() else "light"


def avec_parametre(url: str) -> str:
    return url + ("&" if "?" in url else "?") + "theme=" + parametre()


def appliquer_streamlit(theme: str | None = None) -> bool:
    """Positionne les couleurs natives de Streamlit. Retourne True si elles ont changé (il faut alors relancer le script)."""
    from streamlit import config
    voulu = STREAMLIT[theme or lire()]
    change = False
    for cle, valeur in voulu.items():
        if config.get_option(cle) != valeur:
            config.set_option(cle, valeur)
            change = True
    return change


def selecteur() -> str:
    """Sélecteur de la barre latérale. Retourne le thème en vigueur."""
    import streamlit as st
    actuel = lire()
    if appliquer_streamlit(actuel):                       # premier passage d'une session : couleurs mémorisées
        st.rerun()
    with st.sidebar:
        choix = st.radio("🎨 Thème", THEMES, index=THEMES.index(actuel), horizontal=True, key="theme_choix",
                         format_func=lambda t: "☀ Clair" if t == "clair" else "☾ Sombre",
                         help="S'applique à toute l'application, au tableau de trésorerie, aux diagrammes, à l'architecture d'affaires et à la page des agents.")
    if choix != actuel:
        ecrire(choix)
        appliquer_streamlit(choix)
        st.rerun()
    return actuel
