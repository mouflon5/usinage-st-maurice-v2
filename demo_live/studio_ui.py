"""Vue « LangSmith Studio » : voir le comportement des agents et leurs graphes LangGraph dans Studio.

LangSmith Studio est l'interface web de LangChain pour observer et rejouer des graphes. Elle se connecte à un serveur local
(`langgraph dev`, port 2024) qui expose les graphes déclarés dans langgraph.json : le pipeline complet (orchestrateur) et les agents A3 à A8.
Cette page démarre et arrête ce serveur, indique son état et ouvre Studio. Le statut Expert la montre dans le groupe « Agents ».
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import urllib.request
import webbrowser

import streamlit as st

from demo_live import moteur as M, navigation_ui as NAV

PAGE = "🔬 LangSmith Studio"
PORT = 2024
URL_API = f"http://127.0.0.1:{PORT}"
URL_STUDIO = f"https://smith.langchain.com/studio/?baseUrl={URL_API}"
PID = os.path.join(M.DONNEES, "studio.pid")
JOURNAL = os.path.join(M.DONNEES, "studio.log")
GRAPHES = {
    "orchestrateur": ("Pipeline complet A1 → A8", "Le fil de bout en bout : chaque agent, l'arrêt éventuel et l'approbation humaine avant le rapport."),
    "a3_reconciliation": ("A3 · Classement et chargement", "Doublons, règles de mots-clés, puis LLM pour le résidu ; chargement atomique du journal."),
    "a4_prevision": ("A4 · Prévision", "Prévisions SARIMAX des encaissements et des décaissements, repli et alertes de backtest."),
    "a5_ecarts": ("A5 · Écarts", "Réel contre budget et prévision, causes et commentaire vérifié."),
    "a6_controle": ("A6 · Contrôle", "Les onze contrôles indépendants : le seul point de sortie du pipeline."),
    "a7_reporting": ("A7 · Rapports", "Classeur Excel et brouillon du rapport mensuel R0."),
    "a8_relecture": ("A8 · Relecture", "Relecture du travail des autres agents : réserves signalées, jamais bloquantes."),
}
ENTREE_EXEMPLE = """compte: Desjardins EOP
dossier_releves: releves_scenario1
periode_debut: 2026-09
periode_fin: 2026-09
db_path: tresorerie_demo.db
approbation_humaine: true"""


def en_marche() -> bool:
    try:
        with urllib.request.urlopen(URL_API + "/ok", timeout=1.5) as r:
            return r.status == 200
    except Exception:                                   # noqa: BLE001
        return False


def _pid() -> int | None:
    try:
        return int(open(PID).read().strip())
    except (OSError, ValueError):
        return None


def _vivant(pid: int | None) -> bool:
    if not pid:
        return False
    if os.name == "nt":                                 # os.kill(pid, 0) terminerait le processus sous Windows
        import ctypes
        k = ctypes.windll.kernel32
        h = k.OpenProcess(0x1000, False, pid)           # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        code = ctypes.c_ulong()
        ok = k.GetExitCodeProcess(h, ctypes.byref(code))
        k.CloseHandle(h)
        return bool(ok) and code.value == 259           # STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def cli_disponible() -> bool:
    return importlib.util.find_spec("langgraph_cli") is not None


def graphes_declares() -> list[str]:
    try:
        with open(os.path.join(M.RACINE, "langgraph.json"), encoding="utf-8") as f:
            return list(json.load(f).get("graphs", {}))
    except (OSError, ValueError):
        return list(GRAPHES)


def demarrer() -> None:
    os.makedirs(M.DONNEES, exist_ok=True)
    cmd = [sys.executable, "-m", "langgraph_cli", "dev", "--no-browser", "--port", str(PORT)]
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    with open(JOURNAL, "w", encoding="utf-8") as journal:
        p = subprocess.Popen(cmd, cwd=M.RACINE, stdout=journal, stderr=subprocess.STDOUT, env=env,
                             creationflags=0x08000200 if os.name == "nt" else 0)      # CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP
    with open(PID, "w") as f:
        f.write(str(p.pid))
    st.session_state["studio_attend"] = True            # relancer la page dès que le serveur répond, pour activer le bouton de Studio


def arreter() -> None:
    pid = _pid()
    if pid and _vivant(pid):
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)    # tue aussi le processus de rechargement
        else:
            os.kill(pid, 15)
    try:
        os.remove(PID)
    except OSError:
        pass


def _queue_journal(n: int = 8) -> str:
    try:
        lignes = [l for l in open(JOURNAL, encoding="utf-8", errors="replace").read().splitlines() if l.strip()]
    except OSError:
        return ""
    return "\n".join(lignes[-n:])


def ouvrir_studio() -> None:
    """Ouvre Studio dans le navigateur PAR DÉFAUT du système (l'application tourne sur votre machine).

    Le navigateur intégré à l'application Claude ne peut pas joindre un serveur local depuis une page https (« Failed to fetch ») :
    Studio doit s'ouvrir dans Chrome, Edge ou Firefox.
    """
    webbrowser.open(URL_STUDIO)


def bouton_acces(cle: str) -> None:
    """Bouton d'accès à Studio pour les autres vues : ouvre Studio si le serveur tourne, sinon mène à cette page."""
    if en_marche():
        st.button("🔬 Ouvrir LangSmith Studio", key=f"studio_ouvrir_{cle}", on_click=ouvrir_studio,
                  help="Ouvre Studio dans votre navigateur par défaut : voir le comportement des agents et leurs graphes.")
    else:
        st.button("🔬 LangSmith Studio", key=f"studio_{cle}", on_click=NAV.aller, args=(PAGE,),
                  help="Voir le comportement des agents et leurs graphes dans LangSmith Studio.")


def _etat():
    marche = en_marche()
    mien = _vivant(_pid())
    if marche and st.session_state.pop("studio_attend", False):
        st.rerun()
    if marche:
        st.success(f"Le serveur des graphes tourne sur {URL_API}" + ("" if mien else " (démarré hors de l'application)."), icon=":material/check_circle:")
    elif mien:
        st.info("Démarrage du serveur… quelques secondes.", icon=":material/hourglass_top:")
    else:
        st.warning("Le serveur des graphes n'est pas démarré.", icon=":material/power_off:")
    journal = _queue_journal() if (mien and not marche) else ""
    if journal:
        st.code(journal, language=None)
    return marche, mien


def afficher() -> None:
    st.caption("LangSmith Studio affiche les graphes des agents, l'exécution nœud par nœud, les états échangés et permet de rejouer ou de reprendre "
               "un passage (par exemple à l'approbation humaine).")
    if not cli_disponible():
        st.error("L'outil `langgraph-cli` n'est pas installé dans l'environnement de l'application. Installez-le avec "
                 "`pip install -U \"langgraph-cli[inmem]\"`, puis relancez l'application.")
        return
    marche0 = en_marche()
    suivi = st.fragment(run_every=2 if (_vivant(_pid()) and not marche0) else None)(_etat)
    with st.container(border=True):
        st.subheader("1. Démarrer le serveur")
        marche, mien = suivi() or (marche0, _vivant(_pid()))
        a, b, c = st.columns([1, 1, 2])
        a.button("▶ Démarrer", disabled=marche0 or _vivant(_pid()), on_click=demarrer, width="stretch", key="studio_start")
        b.button("■ Arrêter", disabled=not _vivant(_pid()), on_click=arreter, width="stretch", key="studio_stop",
                 help="Arrête le serveur démarré depuis cette page.")
        c.caption("Le serveur lit `langgraph.json` et se recharge tout seul quand le code d'un agent change.")
    with st.container(border=True):
        st.subheader("2. Ouvrir Studio")
        st.button("🔬 Ouvrir LangSmith Studio dans mon navigateur", type="primary", disabled=not marche0, on_click=ouvrir_studio, key="studio_ouvrir",
                  help="Ouvre Studio dans le navigateur par défaut de votre ordinateur." if marche0 else "Démarrez d'abord le serveur.")
        st.caption("Studio est une page web de LangChain : elle demande une connexion Internet et de se connecter à un compte LangSmith (gratuit), "
                   "puis dialogue depuis votre navigateur avec le serveur local ci-dessus.")
        st.warning("Ouvrez Studio dans **Chrome, Edge ou Firefox**, pas dans le navigateur intégré de l'application Claude : celui-ci ne peut pas joindre "
                   "un serveur local depuis une page https et affiche « Failed to initialize Studio / Failed to fetch ». Brave et Safari bloquent "
                   "aussi parfois l'accès à localhost.", icon=":material/info:")
        st.caption("Adresse à copier dans le navigateur de votre choix :")
        st.code(URL_STUDIO, language=None)
    st.subheader("Graphes disponibles")
    declares = graphes_declares()
    import pandas as pd
    st.dataframe(pd.DataFrame([{"Graphe": g, "Ce qu'il montre": GRAPHES.get(g, ("", ""))[0], "À observer": GRAPHES.get(g, ("", ""))[1]} for g in declares]),
                 hide_index=True, width="stretch")
    with st.expander("Exemple d'entrée pour lancer l'orchestrateur dans Studio"):
        st.code(ENTREE_EXEMPLE, language="yaml")
        st.caption("Créez d'abord le relevé d'exemple et la base de test, sans toucher à la base de démonstration : `python generer_scenario1.py`, "
                   "puis copiez `tresorerie.db` en `tresorerie_demo.db`. Avec `approbation_humaine: true`, le graphe s'arrête avant A7 : reprenez avec "
                   "`{\"decision\": \"approuver\", \"commentaire\": \"OK\"}`.")
    st.caption("Les passages lancés depuis Studio ne s'affichent pas dans « Démo en direct » : ils ont leur propre historique dans Studio.")
