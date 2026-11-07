"""Poste de démonstration — tout le système au même endroit.

    python lancer_demo.py            (démarre le tableau de trésorerie ET cette page)

Barre latérale « LLM des agents » : simulé, Claude (API) ou Ollama (modèles locaux) pour A3, A5, A7, A8 et l'assistant.

Vues :
  Démo en direct   choisir un scénario, le lancer, regarder les agents travailler (pas à pas possible),
                   voir les indicateurs bouger, approuver à la main si demandé ; tableau de trésorerie à côté (option)
  Mes documents    vos vrais relevés (PDF, CSV, Excel) dans la chaîne d'agents, sans scénario, avec aperçu de lecture
  Raisonnement     pourquoi chaque agent et chaque LLM a décidé ainsi : prompts, réponses, preuves, garde-fous, rejeu sur un autre modèle
  Trésorerie       TON tableau de bord HTML (R0–R8), identique, alimenté par la base de démo : il se recharge seul
  Prix des métaux    projection du prix de l'acier, de l'aluminium, de l'inox et du cuivre, du prix d'achat et de l'effet sur la trésorerie (scénarios bas / central / haut)
  Pilotage         le poste de pilotage du banc d'essai (lots de scénarios, performance, relecteur A8)
  Rapports         rapports produits par A7 pour chaque passage (R0 en texte, classeur Excel) et rapports d'origine
  Gouvernance des données   graphiques interactifs : dictionnaire, traçabilité (graphe des flux), référence, maîtres, qualité, couches
  Architecture     architecture d'affaires du groupe (BIZBOK) alimentée par la base : capacités, flux, processus N1-N5, feuille de route
  Assistant        questions en langage naturel sur tout ce que le système sait (RAG avec citations)
"""
from __future__ import annotations

import json
import os
import runpy
import sqlite3
import sys
import time
from datetime import datetime

import pandas as pd
import streamlit as st

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RACINE not in sys.path:
    sys.path.insert(0, RACINE)
os.chdir(RACINE)
import llm_fournisseur as llm_f  # noqa: E402
from demo_live import (accueil_ui, achats_ui, budget_ui, couts_ui, documents_ui, groupe_ui, metaux_ui, etats_ui, llm_ui, moteur as M, navigation_ui as NAV,  # noqa: E402
                       raisonnement_ui, rapports_agents_ui, studio_ui, theme_global)

try:
    st.set_page_config(page_title="Groupe Usinage Saint-Maurice — trésorerie multi-agents", layout="wide")
except Exception:
    pass
if theme_global.appliquer_streamlit():      # couleurs natives du thème mémorisé : une relance suffit pour qu'elles soient envoyées au navigateur
    st.rerun()

URL_TABLEAU = os.environ.get("DEMO_TABLEAU_URL", "http://127.0.0.1:8765/")      # adresse vue du serveur (test de santé)
# Adresses vues du NAVIGATEUR (iframes). En local ce sont les mêmes ; en ligne (Dockerfile + Caddy) elles passent par le même hôte.
URL_TABLEAU_PUBLIC = os.environ.get("DEMO_URL_PUBLIQUE_TABLEAU", URL_TABLEAU)
URL_RACINE_PUBLIQUE = os.environ.get("DEMO_URL_PUBLIQUE_RACINE", URL_TABLEAU.rstrip("/"))
VERT, GRIS, JAUNE, ROUGE, BLEU = "#0ca30c", "#8f9aa8", "#fab219", "#d03b3b", "#2a78d6"

TH = theme_global.cartes()
st.markdown(f"""<style>
.block-container{{padding-top:1.4rem;max-width:100%}}
.chaine{{display:flex;gap:6px;flex-wrap:wrap;margin:.2rem 0 .8rem 0}}
.agent{{flex:1 1 0;min-width:88px;border:1px solid {TH['bordure']};border-top:4px solid {GRIS};border-radius:8px;padding:6px 8px;background:{TH['fond']}}}
.agent b{{font-size:.95rem}} .agent small{{display:block;color:{TH['discret']};line-height:1.15}}
.agent.ok{{border-top-color:{VERT}}} .agent.res{{border-top-color:{JAUNE}}} .agent.stop{{border-top-color:{ROUGE}}}
.agent.cours{{border-top-color:{BLEU};box-shadow:0 0 0 2px {BLEU}33}}
.puce{{display:inline-block;padding:2px 10px;border-radius:999px;font-size:.82rem;font-weight:600;color:#fff}}
.verdict{{border-left:6px solid {GRIS};padding:.6rem 1rem;background:{TH['verdict']};border-radius:4px;margin:.4rem 0}}
[data-testid="stMetricValue"]{{font-size:1.25rem}} [data-testid="stMetricValue"] div{{white-space:normal;overflow:visible;text-overflow:clip}}
</style>""", unsafe_allow_html=True)


# --------------------------------------------------------------------------- #
# Outils
# --------------------------------------------------------------------------- #
def esc(t) -> str:
    """Le dollar ouvre une formule en Markdown : on l'échappe dans tout texte libre affiché."""
    return str(t).replace("$", "\\$") if t else ""


def eur(v, signe=False) -> str:
    if v is None:
        return "—"
    s = f"{abs(v):,.0f}".replace(",", " ")
    pre = ("−" if v < 0 else ("+" if signe and v > 0 else ""))
    return f"{pre}{s} $"


def connexion():
    # connexion normale (pas « ro ») : en mode WAL, une lecture seule échoue quand le dernier écrivain ferme la base
    return sqlite3.connect(M.DB_EVENEMENTS, timeout=10) if os.path.isfile(M.DB_EVENEMENTS) else None


def runs() -> list[dict]:
    c = connexion()
    if c is None:
        return []
    try:
        c.row_factory = sqlite3.Row
        return [dict(r) for r in c.execute("SELECT * FROM runs ORDER BY debut DESC")]
    except sqlite3.Error:
        return []
    finally:
        c.close()


def evenements(run_id: str) -> list[dict]:
    c = connexion()
    if c is None:
        return []
    try:
        c.row_factory = sqlite3.Row
        out = []
        for r in c.execute("SELECT * FROM evenements WHERE run_id=? ORDER BY id", (run_id,)):
            d = dict(r)
            d["detail"] = json.loads(d["detail"]) if d["detail"] else {}
            d["kpi"] = json.loads(d["kpi"]) if d["kpi"] else None
            out.append(d)
        return out
    except sqlite3.Error:
        return []
    finally:
        c.close()


def vivant(r: dict) -> bool:
    return r["statut"] in M.ACTIFS


def classe(agent: str, statut: str | None) -> str:
    """ok / res (réserve) / stop (arrêt) selon l'agent et son statut."""
    if statut in (None, ""):
        return "ok"
    if statut in ("complet", "approuve", "ok", "approuver"):
        return "ok"
    if statut in ("reserves", "a_arbitrer", "degrade", "indisponible", "complet_avec_reserves"):
        return "res"
    return "stop"


NOMS_NOEUDS = {"executer_a1": "A1 · Acquisition", "executer_a2": "A2 · Extraction", "executer_a3": "A3 · Classement et chargement",
               "executer_a4": "A4 · Prévision", "executer_a5": "A5 · Écarts", "executer_a6": "A6 · Contrôle",
               "executer_a8": "A8 · Relecture", "executer_a7": "A7 · Rapports", "approbation_humaine": "Approbation humaine"}
LIBELLE = {"non": "– non exécuté", "ok": "✓ terminé", "res": "⚠ réserve", "stop": "✕ arrêt", "cours": "● en cours", "att": "· en attente"}
AGENTS = [("A1", "Acquisition"), ("A2", "Extraction"), ("A3", "Classement"), ("A4", "Prévision"),
          ("A5", "Écarts"), ("A6", "Contrôle"), ("A8", "Relecture"), ("A7", "Rapports")]


def chaine(evts: list[dict], actif: bool):
    etat = {}
    for e in evts:
        if e["type"] == "agent" and e["agent"]:
            etat[e["agent"]] = classe(e["agent"], e["statut"])
    cases, prochain_pris = [], False
    for code, nom in AGENTS:
        s = etat.get(code)
        if s is None:
            if actif and not prochain_pris:
                s, prochain_pris = "cours", True
            else:
                s = "att"
        if s == "att" and not actif:
            s = "non"
        css = {"ok": "ok", "res": "res", "stop": "stop", "cours": "cours", "att": "", "non": ""}[s]
        cases.append(f'<div class="agent {css}"><b>{code}</b> {nom}<small>{LIBELLE[s]}</small></div>')
    st.markdown('<div class="chaine">' + "".join(cases) + "</div>", unsafe_allow_html=True)


TUILES = [("solde_actuel", "Solde actuel", True), ("creux", "Creux 13 sem.", True), ("flux_net_2026", "Flux net 2026", True),
          ("ecart_budget_annee", "Écart vs budget", True), ("coussin_requis", "Coussin requis", True),
          ("nb_ecritures", "Écritures au journal", False), ("a_classer", "Lignes à classer", False)]


def tuiles(evts: list[dict]):
    kp = [e["kpi"] for e in evts if e["kpi"]]
    if not kp:
        return
    avant, apres = kp[0], kp[-1]
    n = 4 if st.session_state.get("d_cote") else len(TUILES)
    cols = st.columns(n) + (st.columns(n) if n < len(TUILES) else [])
    for col, (cle, lib, argent) in zip(cols, TUILES):
        a, b = avant.get(cle), apres.get(cle)
        if a is None or b is None:
            continue
        d = b - a
        fmt = eur if argent else (lambda v, signe=False: f"{v:,.0f}".replace(",", " "))
        col.metric(lib, fmt(b), delta=(fmt(d, True) if abs(d) > 0.5 else None), delta_color="off" if cle in ("nb_ecritures", "a_classer") else "normal")


def tableau(lignes, colonnes):
    if lignes:
        st.dataframe(pd.DataFrame(lignes)[colonnes] if colonnes else pd.DataFrame(lignes), hide_index=True, width="stretch")


def detail_agent(e: dict):
    d, n = e["detail"], e["noeud"]
    res = d.get("resume", {})
    if e["message"]:
        st.write(esc(e["message"]))
    if n == "executer_a2" and d.get("exemples"):
        st.caption(f"{d.get('nb_transactions')} transaction(s) extraite(s) — aperçu :")
        tableau(d["exemples"], ["date", "description", "montant"])
    elif n == "executer_a3":
        if d.get("classees"):
            st.caption("Lignes classées et écrites au journal")
            tableau(d["classees"], ["date", "description", "montant", "categorie", "methode"])
        if d.get("a_classer"):
            st.caption("Lignes escaladées (« À classer ») — l'humain tranche")
            tableau(d["a_classer"], ["date", "description", "montant", "suggestion"])
        if d.get("doublons"):
            st.caption("Doublons ignorés")
            tableau(d["doublons"], ["date", "description", "montant", "origine"])
    elif n == "executer_a5" and d.get("ecarts"):
        tableau(d["ecarts"], ["libelle", "reel", "budget", "prevu", "jugement_budget", "jugement_prevision"])
        if d.get("commentaire"):
            st.info(json.dumps(d["commentaire"], ensure_ascii=False)[:700] if not isinstance(d["commentaire"], str) else d["commentaire"])
    elif n == "executer_a6" and res.get("controles"):
        tableau([{"": "✓" if c["ok"] else "✕", "Contrôle": c["id"], "Libellé": c["libelle"], "Gravité": c["gravite"], "Détail": c["detail"]}
                 for c in res["controles"]], None)
    elif n == "executer_a8" and res.get("relecture"):
        rl = res["relecture"]
        st.caption(f"Origine : {rl.get('origine')} — le relecteur ne bloque jamais, il ne fait que signaler des réserves.")
        if rl.get("constats"):
            tableau([{"Réf.": c.get("ref"), "Gravité": c.get("gravite"), "Constat": c.get("texte") or c.get("constat")}
                     for c in rl["constats"]], None)
        else:
            st.success("Aucune réserve.")
        if rl.get("rejetes"):
            st.caption(f"{len(rl['rejetes'])} constat(s) rejeté(s) par les garde-fous (référence ou chiffre inexistant).")
    elif n == "executer_a7" and d.get("fichiers"):
        for f in d["fichiers"]:
            st.write("📄", os.path.basename(f))


def verdict(evts: list[dict], run: dict):
    fin = next((e for e in reversed(evts) if e["type"] == "fin"), None)
    if not fin:
        return
    rs = fin["detail"]
    code = rs.get("statut_pipeline")
    texte = {"complet": ("ok", "Pipeline réussi — les rapports sont produits."),
             "complet_avec_reserves": ("res", "Terminé avec réserves — à lire avant de signer."),
             "a_arbitrer": ("res", "Arbitrage humain requis — des lignes n'ont pas pu être classées avec certitude."),
             "arrete_a1": ("stop", "Arrêt à A1 — le relevé est incomplet ; rien n'a été écrit."),
             "arrete_a2": ("stop", "Arrêt à A2 — extraction douteuse ; rien n'a été écrit."),
             "arrete_a4": ("stop", "Arrêt à A4 — historique inutilisable."),
             "arrete_a5": ("stop", "Arrêt à A5 — écarts non calculables."),
             "bloque_a6": ("stop", "Bloqué par A6 — un contrôle bloquant a échoué ; rien ne sort."),
             "rejete_humain": ("stop", "Rejeté lors de l'approbation humaine."),
             "arrete": ("stop", "Arrêté par l'utilisateur."), "exception": ("stop", "Incident technique.")}.get(code, ("res", str(code)))
    couleur = {"ok": VERT, "res": JAUNE, "stop": ROUGE}[texte[0]]
    st.markdown(f'<div class="verdict" style="border-left-color:{couleur}"><b>{texte[1]}</b><br>{esc(rs.get("message"))}</div>',
                unsafe_allow_html=True)
    cons = [c for c in (rs.get("a8_constats") or []) if c.get("gravite") == "reserve"]
    if cons:
        st.warning("**Relecteur A8** : " + " · ".join(f"{c.get('ref')} — {c.get('texte') or c.get('constat')}" for c in cons[:4]))


# --------------------------------------------------------------------------- #
# Vue 1 — Démo en direct
# --------------------------------------------------------------------------- #
def formulaire_lancement():
    cles = [c["cle"] for c in M.CATALOGUE]
    expert = NAV.expert()
    if expert:
        cle = st.radio("Scénario", cles, format_func=lambda k: M.PAR_CLE[k]["titre"], key="d_cle", label_visibility="collapsed")
    else:
        cle = st.selectbox("Scénario", cles, format_func=lambda k: M.PAR_CLE[k]["titre"], key="d_cle")
    c = M.PAR_CLE[cle]
    st.caption(f"{c['resume']}  \n**Attendu :** {c['attendu']}")
    if expert:
        a, b = st.columns(2)
        pas = a.toggle("Pas à pas", value=False, key="d_pas", help="Le moteur attend votre clic « Suivant » après chaque agent.")
        appro = b.toggle("Approbation humaine", value=False, key="d_appro", help="Le pipeline s'arrête avant A7 et attend votre décision.")
        delai = st.slider("Pause entre agents (s)", 0.0, 5.0, 1.2, 0.1, key="d_delai", disabled=pas)
        st.caption(f"LLM : **{llm_f.libelle()}** — à changer dans « 🤖 LLM des agents ». Vos propres relevés : « 📥 Mes documents ».")
    else:
        pas, appro, delai = False, False, 1.2
        st.caption(f"LLM : **{llm_f.libelle()}**. Vos propres relevés : « 📥 Mes documents ». Pas à pas et approbation : statut Expert.")
    actif = M.run_actif()
    if st.button("▶ Lancer", type="primary", disabled=bool(actif), width="stretch"):
        rid = f"d{datetime.now():%H%M%S}_{cle}"
        try:
            M.lancer(rid, scenario=cle, pas_a_pas=pas, delai=delai, approbation=appro,
                     fournisseur=llm_f.fournisseur(), modele=os.environ.get("LLM_MODELE", "") or None)
            st.session_state["run_vu"] = rid
            st.rerun()
        except Exception as ex:
            st.error(str(ex))
    st.divider()
    x, y = st.columns(2)
    if x.button("↺ Remettre à zéro", width="stretch", disabled=bool(actif), help="Recopie la base d'origine : la démo repart du début."):
        M.reinitialiser()
        st.session_state.pop("run_vu", None)
        st.rerun()
    dernier = next((r for r in runs() if r["statut"] in ("termine", "arrete", "erreur", "interrompu")), None)
    if y.button("⎌ Annuler le dernier", width="stretch", disabled=bool(actif) or not dernier,
                help="Restaure la base telle qu'elle était juste avant le dernier scénario."):
        if dernier and M.annuler_dernier(dernier["run_id"]):
            st.toast("Dernier scénario annulé.")
            st.rerun()


def commandes_actives(run: dict, evts: list[dict]):
    if not vivant(run):
        return
    rid = run["run_id"]
    attend_appro = run["statut"] == "approbation"
    if attend_appro:
        ap = next((e for e in reversed(evts) if e["type"] == "approbation"), None)
        st.warning("**Approbation humaine demandée** — le rapport n'est pas encore produit.")
        if ap:
            d = ap["detail"]
            st.write(f"Verdict A6 : **{d.get('verdict_a6')}** — {d.get('message_a6') or ''}")
            ra = d.get("relecture_a8") or {}
            if ra.get("constats"):
                st.write("Relecture A8 : " + " · ".join(f"{c.get('ref')} — {c.get('texte') or c.get('constat')}" for c in ra["constats"][:5]))
            if d.get("ecarts"):
                tableau(d["ecarts"], ["libelle", "reel", "budget", "prevu"])
        a, b, _ = st.columns([1, 1, 3])
        if a.button("✓ Approuver", type="primary"):
            M.envoyer(rid, "approuver", {"commentaire": "approuvé pendant la démonstration"})
            st.rerun()
        if b.button("✕ Rejeter"):
            M.envoyer(rid, "rejeter", {"commentaire": "rejeté pendant la démonstration"})
            st.rerun()
        return
    a, b, c_, d_ = st.columns(4)
    if run["pas_a_pas"] and run["statut"] == "en_attente":
        if a.button("⏭ Suivant", type="primary", width="stretch"):
            M.envoyer(rid, "suivant")
    if run["statut"] == "en_pause":
        if b.button("▶ Reprendre", width="stretch"):
            M.envoyer(rid, "reprendre")
    elif not run["pas_a_pas"]:
        if b.button("⏸ Pause", width="stretch"):
            M.envoyer(rid, "pause")
    if run["pas_a_pas"] and run["statut"] == "en_attente":
        if c_.button("⏵⏵ Continuer sans pause", width="stretch"):
            M.envoyer(rid, "reprendre")
    if d_.button("■ Arrêter", width="stretch"):
        M.envoyer(rid, "arreter")


def en_direct(run_id: str):
    tous = {r["run_id"]: r for r in runs()}
    run = tous.get(run_id)
    if not run:
        st.info("Choisissez un scénario et cliquez sur **Lancer**.")
        return
    evts = evenements(run_id)
    puces = {"en_cours": (BLEU, "en cours"), "en_attente": (BLEU, "attend « Suivant »"), "en_pause": (JAUNE, "en pause"),
             "approbation": (JAUNE, "attend votre décision"), "termine": (VERT, "terminé"), "arrete": (GRIS, "arrêté"),
             "erreur": (ROUGE, "erreur"), "interrompu": (ROUGE, "interrompu"), "annule": (GRIS, "annulé")}
    coul, lib = puces.get(run["statut"], (GRIS, run["statut"]))
    st.markdown(f"### {run['titre']}  <span class='puce' style='background:{coul}'>{lib}</span>", unsafe_allow_html=True)
    dem = next((e for e in evts if e["type"] == "demarrage"), None)
    if dem:
        d = dem["detail"]
        llm = d.get("llm") or {}
        st.caption(f"{dem['message']}  ·  compte {d.get('compte')} · période {d.get('periode')} · mode {run['mode']}"
                   + (f" · LLM {llm.get('fournisseur')} ({llm.get('modele')})" if llm else ""))
    chaine(evts, vivant(run) and run["statut"] != "approbation")
    commandes_actives(run, evts)
    tuiles(evts)
    verdict(evts, run)
    st.markdown("**Déroulé**")
    for e in evts:
        if e["type"] == "agent":
            ic = {"ok": "✅", "res": "⚠️", "stop": "⛔"}[classe(e["agent"], e["statut"])] if e["agent"] else "▫️"
            nom = NOMS_NOEUDS.get(e["noeud"], e["noeud"].replace("finaliser_", "Fin : ").replace("_", " "))
            if NAV.expert():
                with st.expander(f"{ic} {nom} — {e['statut'] or ''}  ({e['duree']:.2f} s)",
                                 expanded=(e is evts[-1] and vivant(run))):
                    detail_agent(e)
            elif e["agent"]:
                st.markdown(f"{ic} **{nom}** — {esc(e['message'] or e['statut'] or '')}")
        elif e["type"] in ("approbation", "decision", "erreur", "annule"):
            st.info(f"{e['type'].capitalize()} — {e['message'] or ''}")
    if not NAV.expert() and evts:
        st.caption("Le détail de chaque agent est dans « 📑 Rapports » (statut Simple) ou ici, en statut Expert.")
        st.button("Lire les rapports des agents", key="dem_rapports", on_click=NAV.aller, args=("📑 Rapports",))
    if vivant(run) and not evts:
        st.caption("Génération du relevé et démarrage…")
    if vivant(run):
        st.session_state["_etait_actif"] = True
    elif st.session_state.get("_etait_actif"):      # le passage vient de finir : réafficher toute la page (liste, boutons)
        st.session_state["_etait_actif"] = False
        st.rerun()


def vue_demo():
    with st.expander("▶ Lancer un scénario", expanded=not runs()):
        formulaire_lancement()
        if NAV.expert():
            st.toggle("Afficher le tableau de trésorerie à côté", key="d_cote", help="Se recharge seul à chaque étape.")
    if NAV.expert():
        studio_ui.bouton_acces("demo")
    tous = runs()
    ids = [r["run_id"] for r in tous]
    actif = M.run_actif()
    if actif:
        st.session_state["run_vu"] = actif[0]
    if ids:
        if st.session_state.get("run_vu") not in ids:
            st.session_state["run_vu"] = ids[0]
        st.selectbox("Passage affiché", ids, key="run_vu", label_visibility="collapsed",
                     format_func=lambda r: next((f"{x['titre']} — {x['statut']} — {x['debut'][11:19]}" for x in tous if x["run_id"] == r), r))
    frag = st.fragment(run_every=1.2 if actif else None)(lambda: en_direct(st.session_state.get("run_vu", "")))
    if NAV.expert() and st.session_state.get("d_cote"):
        g, d = st.columns([6, 6])
        with g:
            frag()
        with d:
            iframe_tableau(900)
    else:
        frag()


def iframe_tableau(hauteur: int):
    url = theme_global.avec_parametre(URL_TABLEAU_PUBLIC)    # le thème choisi dans la barre latérale est imposé à la page
    if hasattr(st, "iframe"):
        st.iframe(url, height=hauteur)
    else:
        st.components.v1.iframe(url, height=hauteur, scrolling=True)
    st.link_button("Ouvrir le tableau dans un onglet", url)


# --------------------------------------------------------------------------- #
# Vue 2 — Trésorerie (ton HTML)
# --------------------------------------------------------------------------- #
def vue_tresorerie():
    st.caption("Ton tableau de bord, mise en page inchangée. Les chiffres sont recalculés depuis la base de démo : "
               "lance un scénario (vue « Démo en direct ») et la page se recharge toute seule à chaque étape.")
    try:
        import urllib.request
        urllib.request.urlopen(URL_TABLEAU + "api/health", timeout=2).read()
    except Exception:
        st.error(f"Le serveur du tableau ne répond pas ({URL_TABLEAU}). Démarrez la démo avec `python lancer_demo.py`.")
        return
    iframe_tableau(1150)


# --------------------------------------------------------------------------- #
# Vue 3 — Pilotage (banc d'essai)
# --------------------------------------------------------------------------- #
def vue_pilotage():
    runpy.run_path(os.path.join(RACINE, "banc_essai", "tableau_de_bord.py"), run_name="pilotage_integre")


# --------------------------------------------------------------------------- #
# Vue 4 — Rapports
# --------------------------------------------------------------------------- #
def rapports_de(dossier: str) -> list[str]:
    out = []
    for racine, _, fs in os.walk(dossier):
        out += [os.path.join(racine, f) for f in fs]
    return sorted(out)


def vue_rapports():
    t1, t2 = st.tabs(["🤖 Rapports des agents", "📄 Rapport mensuel et classeurs"])
    with t1:
        rapports_agents_ui.afficher(NAV.expert())
    with t2:
        rapports_fichiers()


def rapports_fichiers():
    sources = {}
    for r in runs():
        d = os.path.join(M.DONNEES, "runs", r["run_id"], "sorties")
        if os.path.isdir(d) and rapports_de(d):
            sources[f"Démo · {r['titre']} · {r['debut'][11:19]}"] = d
    for nom in ("sorties", "sorties_scenarios"):
        d = os.path.join(RACINE, nom)
        if os.path.isdir(d):
            sources[f"Rapports d'origine · {nom}/"] = d
    if not sources:
        st.info("Aucun rapport pour l'instant : lancez un scénario complet.")
        return
    choix = st.selectbox("Source", list(sources))
    fichiers = [f for f in rapports_de(sources[choix]) if f.endswith((".md", ".xlsx"))]
    if not fichiers:
        st.info("Pas de rapport dans cette source.")
        return
    for f in fichiers:
        nom = os.path.relpath(f, sources[choix])
        with st.expander(f"📄 {nom}", expanded=f.endswith(".md") and len(fichiers) <= 4):
            with open(f, "rb") as fh:
                st.download_button("Télécharger", fh.read(), file_name=os.path.basename(f), key="dl_" + f)
            if f.endswith(".md"):
                st.markdown(open(f, encoding="utf-8").read().replace("$", "\\$"))
            else:
                try:
                    classeur = pd.read_excel(f, sheet_name=None)
                    for feuille, df in classeur.items():
                        st.caption(f"Feuille « {feuille} »")
                        st.dataframe(df.head(200), hide_index=True, width="stretch")
                except Exception as ex:
                    st.warning(f"Aperçu impossible : {ex}")


# --------------------------------------------------------------------------- #
# Vue 5 — Assistant (RAG)
# --------------------------------------------------------------------------- #
def vue_assistant():
    try:
        from demo_live import assistant_ui
    except Exception as ex:                       # noqa: BLE001
        st.info(f"L'assistant n'est pas encore disponible ({type(ex).__name__}: {ex}).")
        return
    assistant_ui.afficher()


# --------------------------------------------------------------------------- #
# Assemblage
# --------------------------------------------------------------------------- #
def vue_diagramme(page: str, legende: str, hauteur: int):
    st.caption(legende)
    url = theme_global.avec_parametre(URL_RACINE_PUBLIQUE + "/diagrammes/" + page)
    if hasattr(st, "iframe"):
        st.iframe(url, height=hauteur)
    else:
        st.components.v1.iframe(url, height=hauteur, scrolling=True)
    st.link_button("Ouvrir ce diagramme dans un onglet", url)


def vue_flux():
    studio_ui.bouton_acces("flux")
    vue_diagramme("flux.html", "Flux de données entre les agents A1 à A8, rapports associés et métriques. Rejouez un passage étape par étape ou suivez le direct.", 1250)


def vue_cible():
    studio_ui.bouton_acces("cible")
    vue_diagramme("cible.html", "Processus cible en quatre couloirs (contrôleur, orchestration, agents IA, outils déterministes), animé par les événements du passage.", 1000)


def vue_rag():
    vue_diagramme("rag.html", "Architecture du système RAG, chemin de chaque question et métriques de performance. Vous pouvez poser une question ou lancer l'évaluation depuis le diagramme.", 1500)


def vue_performance():
    vue_diagramme("performance.html", "Performance des agents et des modèles LLM : durées, taux d'arrêt, appels, jetons, coût, confiance, garde-fous, qualité du banc d'essai.", 1500)


def vue_gouvernance():
    from demo_live import gouvernance_ui
    gouvernance_ui.afficher(M.BASE_DEMO)


def vue_architecture():
    from demo_live import architecture_ui
    architecture_ui.afficher(M.BASE_DEMO)


PAGES = {NAV.ACCUEIL: accueil_ui.afficher,
         "📊 Trésorerie": vue_tresorerie, "📒 États financiers": etats_ui.afficher, "🏢 Consolidation du groupe": groupe_ui.afficher, "🧾 Achats et paiements": achats_ui.afficher, "💰 Coûts de revient": couts_ui.afficher, "📅 Planification budgétaire": budget_ui.afficher,"🔩 Prix des métaux": metaux_ui.afficher, "📑 Rapports": vue_rapports,
         "📥 Mes documents": documents_ui.afficher, "🎬 Démo en direct": vue_demo, "🧠 Raisonnement": raisonnement_ui.afficher,
         "🕸 Flux des agents": vue_flux, "🧩 Processus cible": vue_cible, studio_ui.PAGE: studio_ui.afficher,
         "📈 Performance": vue_performance, "🧭 Pilotage": vue_pilotage, "🔎 Système RAG": vue_rag,
         "🛡 Gouvernance des données": vue_gouvernance, "🏛 Architecture d'affaires": vue_architecture, "💬 Assistant": vue_assistant}
assert documents_ui.VUE_DIRECT in PAGES and NAV.ACCUEIL in PAGES
assert {v for _, items in NAV.MENU for v, _ in items} == set(PAGES), "le menu et les pages doivent correspondre"
st.markdown(NAV.CSS, unsafe_allow_html=True)
M.preparer_base()
NAV.entete()
vue = NAV.menu(PAGES)
with st.sidebar:
    st.divider()
    theme_global.selecteur()
    if NAV.expert():
        llm_ui.selecteur()
    else:
        llm_ui._initialiser()                                  # le choix du LLM est appliqué même quand son réglage est masqué
        st.caption(f"LLM des agents : {llm_f.libelle()}")
NAV.fil_ariane(vue)
PAGES[vue]()
