"""Page d'accueil : où en est l'entreprise, en quatre cartes cliquables, et ce qu'il faut retenir.

Simple : cartes, points à retenir et actions courantes. Expert : en plus, accès directs aux outils d'analyse.
"""
from __future__ import annotations

import os
import sqlite3

import streamlit as st

import projection_metaux as pm
from demo_live import metaux_ui, moteur as M, navigation_ui as NAV, rapports_agents_ui as RA


def _argent(v) -> str:
    return "—" if v is None else (("−" if v < 0 else "") + f"{abs(v):,.0f} $".replace(",", " "))


def _kpi_dernier_passage(passages: list[dict]) -> tuple[dict | None, dict | None]:
    """(dernier passage terminé, ses indicateurs de fin)."""
    run = next((r for r in passages if r["statut"] == "termine"), None)
    if not run:
        return None, None
    kp = [e["kpi"] for e in RA.evenements(run["run_id"]) if e["kpi"]]
    return run, (kp[-1] if kp else None)


def _tresorerie_depart(chemin: str) -> float | None:
    try:
        c = sqlite3.connect(f"file:{chemin}?mode=ro", uri=True, timeout=10)
        try:
            r = c.execute("SELECT valeur FROM parametres WHERE domaine='forecast' AND cle='solde_depart'").fetchone()
        finally:
            c.close()
        return float(r[0]) if r else None
    except sqlite3.Error:
        return None


def _carte(titre: str, valeur: str, legende: str, cible: str, etiquette: str, statut: str | None = None, cle: str = ""):
    with st.container(border=True):
        st.caption(titre)
        st.markdown(f"### {valeur}")
        if statut:
            {"ok": st.success, "res": st.warning, "stop": st.error}.get(statut, st.info)(legende.replace("$", "\\$"), icon=":material/circle:")
        else:
            st.caption(legende.replace("$", "\\$"))
        st.button(etiquette, key=f"acc_{cle or cible}", on_click=NAV.aller, args=(cible,), width="stretch")


def afficher():
    chemin = M.BASE_DEMO
    passages = RA.passages()
    run, kp = _kpi_dernier_passage(passages)
    seuil = pm.seuil_securite(chemin) if os.path.isfile(chemin) else None
    ess = metaux_ui.resume_central(chemin) if os.path.isfile(chemin) else None

    st.header("Bonjour, voici où vous en êtes")
    st.caption("Les chiffres viennent de la base de démonstration. Cliquez une carte pour ouvrir le détail.")

    solde = kp.get("solde_actuel") if kp else _tresorerie_depart(chemin)
    creux = kp.get("creux") if kp else None
    a, b = st.columns(2)
    with a:
        if solde is None:
            _carte("Trésorerie", "—", "Aucun solde disponible.", "📊 Trésorerie", "Ouvrir la trésorerie", cle="tre")
        else:
            bas = seuil is not None and (creux if creux is not None else solde) < seuil
            leg = (f"Creux sur 13 semaines : {_argent(creux)}. " if creux is not None else "") + (f"Seuil de sécurité : {_argent(seuil)}." if seuil else "")
            _carte("Trésorerie", _argent(solde), leg, "📊 Trésorerie", "Ouvrir la trésorerie", statut="res" if bas else "ok", cle="tre")
    with b:
        if ess is None:
            _carte("Prix des métaux", "—", "Projection indisponible.", "🔩 Prix des métaux", "Ouvrir la projection", cle="ess")
        else:
            depasse = seuil is not None and ess["pire"] < -seuil
            _carte("Prix des métaux", metaux_ui.kg(ess['achat0']),
                   f"Panier de matières, dans {ess['horizon']} mois : de {metaux_ui.kg(ess['achat_bas'])} à {metaux_ui.kg(ess['achat_haut'])} selon le scénario. Effet central sur l'encaisse : {_argent(ess['cash'])}."
                   + (" Le pire scénario dépasse le seuil de sécurité." if depasse else ""),
                   "🔩 Prix des métaux", "Ouvrir la projection", statut="res" if depasse else "ok", cle="ess")
    c, d = st.columns(2)
    with c:
        if not passages:
            _carte("Agents", "Aucun passage", "Lancez une démonstration ou déposez vos relevés.", "🎬 Démo en direct", "Lancer une démonstration", cle="ag")
        else:
            p = passages[0]
            fin = next((e for e in reversed(RA.evenements(p["run_id"])) if e["type"] == "fin"), None)
            code = fin["detail"].get("statut_pipeline") if fin else None
            cl = {"complet": "ok", "complet_avec_reserves": "res"}.get(code, "stop" if code else None)
            _carte("Agents", p["titre"], RA.VERDICTS.get(code, "Passage en cours."), "🎬 Démo en direct", "Voir le dernier passage", statut=cl, cle="ag")
    with d:
        nb = len(passages)
        _carte("Rapports", f"{nb} passage{'s' if nb > 1 else ''}", "Un rapport par agent (A1 à A8) et le rapport mensuel de chaque passage.", "📑 Rapports",
               "Ouvrir les rapports", cle="rap")

    points = []
    if ess and seuil is not None and ess["pire"] < -seuil:
        points.append(f"Prix des métaux : dans le pire scénario, l'encaisse recule de {_argent(-ess['pire'])}, au-delà du seuil de {_argent(seuil)}.")
    if run:
        fin = next((e for e in reversed(RA.evenements(run["run_id"])) if e["type"] == "fin"), None)
        if fin:
            cons = [c for c in (fin["detail"].get("a8_constats") or []) if c.get("gravite") == "reserve"]
            if fin["detail"].get("statut_pipeline") == "complet_avec_reserves":
                points.append("Le dernier passage s'est terminé avec réserves : lisez le rapport de l'agent A6 avant de signer.")
            if cons:
                points.append(f"La relecture (A8) signale {len(cons)} réserve(s).")
    if passages and passages[0]["statut"] in ("approbation",):
        points.append("Un passage attend votre approbation.")
    if points:
        with st.container(border=True):
            st.markdown("**À retenir**")
            for p in points:
                st.markdown(f"- {p}".replace("$", "\\$"))

    st.subheader("Que voulez-vous faire ?")
    x, y, z = st.columns(3)
    x.button("📥 Importer des relevés", on_click=NAV.aller, args=("📥 Mes documents",), width="stretch", key="acc_doc")
    y.button("📒 Lire les états financiers", on_click=NAV.aller, args=("📒 États financiers",), width="stretch", key="acc_eta")
    z.button("📑 Lire les rapports des agents", on_click=NAV.aller, args=("📑 Rapports",), width="stretch", key="acc_rap2")
    if NAV.expert():
        st.subheader("Outils d'analyse")
        cols = st.columns(4)
        for col, (vue, txt) in zip(cols, (("🧠 Raisonnement", "Pourquoi chaque agent a décidé"), ("📈 Performance", "Durées, coûts, qualité"),
                                         ("🛡 Gouvernance des données", "Dictionnaire, traçabilité, qualité"), ("🔎 Système RAG", "Questions sur le système"))):
            with col, st.container(border=True):
                st.caption(txt)
                st.button(vue, key=f"acc_exp_{vue}", on_click=NAV.aller, args=(vue,), width="stretch")
