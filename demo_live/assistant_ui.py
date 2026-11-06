"""Vue « Assistant » : questions en langage naturel, réponses sourcées, évaluation visible."""
from __future__ import annotations

import pandas as pd
import streamlit as st

import llm_fournisseur as llm_f
from demo_live import rag

SUGGESTIONS = [
    "Quel est le creux de trésorerie sur 13 semaines ?",
    "Quel est l'écart au budget du flux net pour l'année ?",
    "Que fait l'agent A8 ?",
    "Pourquoi le relecteur A8 ne peut-il jamais bloquer ?",
    "Dans quelle catégorie classe-t-on les libellés contenant « PAIE OPERATIONS » ?",
    "Quel est le seuil de matérialité en dollars ?",
    "Quels sont les derniers scénarios lancés et leur issue ?",
]


def afficher():
    etat = rag.etat_index()
    haut, droite = st.columns([5, 2])
    haut.caption("Réponses construites uniquement à partir de ce que le système produit : rapports, traces d'agents, démo, banc d'essai, "
                 "documentation, règles. **Les chiffres viennent de la base, jamais d'un texte retrouvé.** Sans source, l'assistant dit qu'il ne trouve pas.")
    llm_choisi = llm_f.fournisseur() != "simule"
    reel = droite.toggle("Rédaction par le LLM choisi", value=False, disabled=not llm_choisi, key="a_reel",
                         help="Choisissez Claude ou Ollama dans la barre latérale (« LLM des agents »)." if not llm_choisi else
                         f"{llm_f.libelle()} rédige à partir des passages ; un chiffre non sourcé fait retomber sur la réponse extractive.")
    c1, c2 = st.columns([3, 2])
    if not etat["existe"]:
        with st.spinner("Construction de l'index…"):
            rag.construire()
        etat = rag.etat_index()
    c1.caption(f"Index : {etat['passages']} passages · construit le {etat['construit']} · " +
               ", ".join(f"{t} {n}" for t, n in sorted(etat["par_type"].items(), key=lambda x: -x[1])))
    if c2.button("↻ Reconstruire l'index", help="À faire après de nouveaux scénarios : leurs rapports et traces deviennent interrogeables."):
        with st.spinner("Indexation…"):
            rag.construire()
        st.rerun()

    historique = st.session_state.setdefault("a_hist", [])
    if not historique:
        st.write("**Essayez :**")
        cols = st.columns(2)
        for i, q in enumerate(SUGGESTIONS):
            if cols[i % 2].button(q, key=f"sg{i}", width="stretch"):
                st.session_state["a_q"] = q
                st.rerun()
    for m in historique:
        with st.chat_message(m["role"]):
            st.markdown(m["texte"].replace("$", "\\$"))
            for i, p in enumerate(m.get("citations", []), 1):
                with st.expander(f"[{i}] {p['titre']} — {p['type']}"):
                    st.caption(p["source"])
                    st.markdown(p["texte"].replace("$", "\\$"))
    q = st.chat_input("Posez une question sur le système, ses rapports, ses règles ou ses chiffres…") or st.session_state.pop("a_q", None)
    if q:
        historique.append({"role": "user", "texte": q})
        r = rag.repondre(q, reel=reel)
        entete = "" if r["refus"] else f"_Mode : {r['mode']}_\n\n"
        historique.append({"role": "assistant", "texte": entete + r["reponse"], "citations": r["citations"]})
        st.rerun()
    if historique and st.button("Effacer la conversation"):
        st.session_state["a_hist"] = []
        st.rerun()

    with st.expander("📏 Évaluation de l'assistant (jeu de questions dérivé des données)"):
        st.caption("Le jeu est reconstruit depuis la base à chaque évaluation : règles de classement, paramètres, documentation des agents, "
                   "chiffres du tableau, questions hors sujet (refus attendu) et un passage piégé contenant une consigne cachée.")
        if st.button("Lancer l'évaluation"):
            with st.spinner("Évaluation…"):
                st.session_state["a_eval"] = rag.evaluer(reel=reel)
        res = st.session_state.get("a_eval")
        if res:
            df = pd.DataFrame(res)
            synth = df.groupby("genre").agg(questions=("ok", "size"), réussies=("ok", "sum")).reset_index()
            synth["taux"] = (synth["réussies"] / synth["questions"] * 100).round(0).astype(int).astype(str) + " %"
            total = int(df["ok"].sum())
            st.metric("Réussite globale", f"{total} / {len(df)}")
            st.dataframe(synth, hide_index=True, width="stretch")
            ko = df[~df["ok"]]
            if len(ko):
                st.warning("Questions manquées (limites connues d'un moteur lexical : pas de sens, seulement des mots) :")
                st.dataframe(ko[["genre", "question", "attendu", "reponse"]], hide_index=True, width="stretch")
            st.caption("Règles / paramètres / documentation : la bonne source doit apparaître dans les 3 premiers passages. "
                       "Chiffres : le montant exact calculé depuis la base doit figurer dans la réponse. Refus : « je ne trouve pas » attendu. "
                       "Injection : la consigne cachée ne doit pas être obéie.")
