"""Vue « Architecture d'affaires » de la démonstration.

Assemble la page HTML interactive (dossier demo_live/architecture/) en un seul document, en y injectant les données de
trésorerie lues dans la base de la démonstration au moment de l'affichage (journal général, facilités, gouvernance).
"""
import os
import re

import streamlit as st

from demo_live import architecture_data, theme_global

DOSSIER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "architecture")
_BALISE = re.compile(r'<script src="([^"]+)"></script>')


def construire_html(db_path, theme: str | None = None):
    """Retourne le document complet : scripts inlinés, données de trésorerie en direct.
    `theme` = « dark » ou « light » impose le thème de la page (son sélecteur le reflète) ; None : choix mémorisé de la page."""
    with open(os.path.join(DOSSIER, "index.html"), encoding="utf-8") as f:
        page = f.read()
    if theme in ("dark", "light"):
        page = page.replace("<head>", f'<head>\n<script>try{{localStorage.setItem("hz-theme","{theme}")}}catch(e){{}}</script>', 1)

    def remplacer(m):
        nom = m.group(1)
        if nom == "donnees_tresorerie.js":
            return architecture_data.en_script(db_path)          # données en direct plutôt que l'instantané
        with open(os.path.join(DOSSIER, nom), encoding="utf-8") as g:
            return "<script>\n" + g.read().replace("</script>", "<\\/script>") + "\n</script>"

    return _BALISE.sub(remplacer, page)


def afficher(db_path, hauteur=1500):
    st.caption("Architecture d'affaires de Groupe Usinage Saint-Maurice (BIZBOK v11), alimentée par la base de la démonstration : "
               "flux de trésorerie reliés aux capacités, processus N1 à N5, feuille de route avec dépendances. "
               "Lancez un scénario puis rouvrez cette vue : les montants et la gouvernance se rafraîchissent.")
    try:
        import cycle_achats
        cycle_achats.assurer(db_path)                                  # l'exemple du cycle achats-décaissements alimente la vue « Achats-décaissements »
    except Exception:                                                  # noqa: BLE001  la vue reste utilisable sans l'exemple
        pass
    try:
        html = construire_html(db_path, theme_global.parametre())
    except Exception as ex:                                       # noqa: BLE001
        st.error(f"Impossible de construire la vue : {type(ex).__name__}: {ex}")
        return
    st.components.v1.html(html, height=hauteur, scrolling=True)
