"""Navigation latérale par métier et deux statuts d'utilisation.

  Simple  lecture et pilotage : accueil, trésorerie, états financiers, prix des métaux, rapports, documents, démonstration, assistant
  Expert  tous les outils d'analyse : raisonnement des agents, flux, performance, banc d'essai, RAG, gouvernance, architecture d'affaires

Le statut est mémorisé dans demo_live/donnees/config_mode.json. La vue courante est dans st.session_state["vue"] (la clé est le libellé de la
vue, comme avant) ; les autres modules la changent avec `aller()` ou en écrivant cette clé dans un rappel de bouton.
"""
from __future__ import annotations

import json
import os

import streamlit as st

CHEMIN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "donnees", "config_mode.json")
MODES = ("Simple", "Expert")
ACCUEIL = "🏠 Accueil"
# (groupe, [(vue, réservée à l'expert)]) ; le libellé de chaque vue est aussi sa clé dans PAGES (application.py)
MENU = [
    ("Piloter", [(ACCUEIL, False), ("📊 Trésorerie", False), ("📒 États financiers", False), ("🏢 Consolidation du groupe", False), ("🧾 Achats et paiements", False), ("💰 Coûts de revient", False), ("📅 Planification budgétaire", False), ("📑 Rapports", False), ("🏛 Architecture d'affaires", True)]),
    ("Agents", [("📥 Mes documents", False), ("🎬 Démo en direct", False), ("🧠 Raisonnement", True), ("🕸 Flux des agents", True), ("🧩 Processus cible", True),
                ("🔬 LangSmith Studio", True)]),
    ("Analyse et qualité", [("🔩 Prix des métaux", False), ("📈 Performance", True), ("🧭 Pilotage", True), ("🔎 Système RAG", True),
                            ("🛡 Gouvernance des données", True)]),
    ("Aide", [("💬 Assistant", False)]),
]
DESCRIPTION = {"Simple": "Lire les résultats et piloter l'essentiel.", "Expert": "Tous les outils d'analyse, les réglages et le détail des agents."}


def _lire() -> str:
    try:
        with open(CHEMIN, encoding="utf-8") as f:
            m = json.load(f).get("mode")
        return m if m in MODES else "Simple"
    except Exception:                                   # noqa: BLE001
        return "Simple"


def _ecrire(mode: str) -> None:
    os.makedirs(os.path.dirname(CHEMIN), exist_ok=True)
    with open(CHEMIN, "w", encoding="utf-8") as f:
        json.dump({"mode": mode}, f)


def mode() -> str:
    if st.session_state.get("mode") not in MODES:
        st.session_state["mode"] = _lire()
    return st.session_state["mode"]


def expert() -> bool:
    return mode() == "Expert"


def aller(vue: str) -> None:
    """Rappel de bouton : ouvre une vue."""
    st.session_state["vue"] = vue


def _changer_mode() -> None:
    _ecrire(st.session_state["mode"])


def groupe_de(vue: str) -> str:
    return next((g for g, items in MENU if any(v == vue for v, _ in items)), "")


def vues_disponibles() -> list[str]:
    return [v for _, items in MENU for v, exp in items if expert() or not exp]


def entete() -> None:
    """Marque et choix du statut, en haut de la barre latérale."""
    mode()
    with st.sidebar:
        st.markdown("#### Groupe Usinage Saint-Maurice")
        st.caption("Trésorerie multi-agents · cas fictif de démonstration")
        st.radio("Statut", MODES, key="mode", horizontal=True, on_change=_changer_mode, label_visibility="collapsed",
                 help="Simple : lecture et pilotage de l'essentiel. Expert : tous les outils d'analyse.")
        st.caption(DESCRIPTION[mode()])


def menu(pages: dict) -> str:
    """Menu groupé de la barre latérale. Retourne la vue courante (toujours une vue disponible dans le statut actuel)."""
    dispo = [v for v in vues_disponibles() if v in pages]
    if st.session_state.get("vue") not in dispo:
        st.session_state["vue"] = ACCUEIL
    courante = st.session_state["vue"]
    with st.sidebar:
        for groupe, items in MENU:
            visibles = [v for v, exp in items if v in dispo]
            if not visibles:
                continue
            st.markdown(f'<div class="nav-groupe">{groupe}</div>', unsafe_allow_html=True)
            for v in visibles:
                st.button(v, key=f"nav_{v}", type="primary" if v == courante else "tertiary", width="stretch", on_click=aller, args=(v,))
        if not expert():
            st.caption("Plus d'outils en mode Expert : raisonnement des agents, flux, performance, gouvernance, architecture d'affaires.")
    return courante


CSS = """<style>
[data-testid="stSidebar"] .nav-groupe{font-size:.72rem;letter-spacing:.06em;text-transform:uppercase;opacity:.65;margin:.9rem 0 .15rem .2rem}
[data-testid="stSidebar"] .stButton button{min-height:2.1rem;padding:.2rem .6rem}
[data-testid="stSidebar"] .stButton button>div,[data-testid="stSidebar"] .stButton button [data-testid="stMarkdownContainer"]{width:100%;justify-content:flex-start !important}
[data-testid="stSidebar"] .stButton button p{font-size:.92rem;text-align:left !important;width:100%}
.carte-titre{font-size:.8rem;opacity:.7;margin-bottom:.1rem}
</style>"""


def fil_ariane(vue: str) -> None:
    g = groupe_de(vue)
    st.markdown(f'<div class="carte-titre">{g} / {vue.split(" ", 1)[-1]} · statut {mode()}</div>', unsafe_allow_html=True)
