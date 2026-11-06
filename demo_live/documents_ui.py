"""Vue « Mes documents » : faire passer de VRAIS relevés (PDF, CSV, Excel) dans la chaîne d'agents, sans scénario.

Étapes : 1) déposer les fichiers ; 2) vérifier ce que le système y lit (compte, période, format, lignes, rejets, continuité des soldes) ;
3) choisir où écrire (copie isolée de la base = sans risque) ; 4) lancer — le passage s'affiche dans « Démo en direct »,
puis l'onglet « Raisonnement » explique chaque décision.
"""
from __future__ import annotations

import os
import re
import shutil
from datetime import datetime

import pandas as pd
import streamlit as st

import classer_documents as ID
import llm_fournisseur as llm_f
from demo_live import moteur as M
from formats_releves import EXTENSIONS, analyser_nom_fichier, lire_releve

VUE_DIRECT = "🎬 Démo en direct"


_INTERDITS = re.compile(r'[\\/:*?"<>|]')


def _nom_valide(compte: str, periode: str, ext: str) -> str:
    return f"{_INTERDITS.sub('', compte).strip()} - {periode}{ext}"


def _apercu(chemin: str) -> dict:
    """Ce que A2 verrait dans ce fichier, sans rien écrire."""
    try:
        lec = lire_releve(chemin)
    except Exception as e:                                          # noqa: BLE001
        return {"format": "illisible", "lignes": 0, "rejetees": [f"{type(e).__name__}: {e}"], "soldes": "—", "periode": ""}
    trans = sorted(lec.transactions, key=lambda t: t["date"])
    cassures = sum(1 for a, b in zip(trans, trans[1:]) if abs(round(a["solde"] + b["montant"], 2) - b["solde"]) > 0.01)
    mois = sorted({t["date"][:7] for t in trans})
    return {"format": lec.format or "non reconnu", "lignes": len(trans), "rejetees": lec.rejetees[:10], "nb_rejetees": len(lec.rejetees),
            "soldes": "✓ continus" if trans and not cassures else (f"✕ {cassures} rupture(s)" if cassures else "—"),
            "periode": ", ".join(mois), "echantillon": trans[:5]}


def _lecture_llm_ui(a: dict, chemin: str):
    """Mise en page non reconnue : sur demande, le LLM transcrit le document ; chaque ligne est vérifiée contre le texte
    (voir lecture_llm.py) et rien n'entre dans le pipeline sans validation explicite."""
    import lecture_llm as LL
    from formats_releves import empreinte_fichier
    cle = "lecllm_" + a["fichier"]
    with st.container(border=True):
        if a["format"] == "LLM":
            st.success(f"**{a['fichier']}** — lecture par le LLM validée : {a['lignes']} opération(s), soldes {a['soldes']}.")
            if st.button("Retirer cette lecture", key=cle + "_retirer"):
                LL.retirer_lecture(chemin)
                st.session_state.pop(cle, None)
                st.rerun()
            return
        st.markdown(f"**🤖 {a['fichier']}** — mise en page non reconnue par le lecteur déterministe")
        st.caption("Le LLM transcrit le document ; chaque ligne est ensuite vérifiée contre le texte et le montant est recalculé "
                   "depuis les soldes. Vous validez le résultat avant qu'il entre dans le pipeline.")
        simule = llm_f.fournisseur() == "simule"
        if st.session_state.get("doc_auto_lecture", True) and not simule and cle not in st.session_state:
            with st.spinner(f"Lecture de « {a['fichier']} » par {llm_f.libelle()} (quelques minutes)…"):
                st.session_state[cle] = LL.lire_avec_llm(chemin)
            essai = st.session_state[cle]
            utilisables = [s for s in essai["sections"] if LL.section_utilisable(s)] if not essai["erreur"] else []
            if utilisables:       # toutes les lignes ont passé la vérification : la lecture est retenue sans clic
                LL.enregistrer_lecture(chemin, max(utilisables, key=lambda s: len(s["transactions"])))
                st.session_state.pop(cle, None)
                st.rerun()
        if st.button("Faire lire ce document par le LLM", key=cle + "_go", disabled=simule):
            with st.spinner(f"Lecture par {llm_f.libelle()}…"):
                st.session_state[cle] = LL.lire_avec_llm(chemin)
        if simule:
            st.caption("Choisissez Claude ou Ollama dans la barre latérale : le mode simulé n'appelle aucun modèle.")
        res = st.session_state.get(cle)
        if not res or res.get("sha256") != empreinte_fichier(chemin):
            return
        if res["erreur"]:
            st.error(res["erreur"])
            return
        if not res["sections"]:
            st.warning("Le LLM n'a trouvé aucune opération dans ce document.")
            return
        sections = res["sections"]
        st.dataframe(pd.DataFrame([{"Section": s["nom"], "Lignes vérifiées": len(s["transactions"]), "Lignes rejetées": len(s["rejetees"]),
                                    "Montant nul (ignorées)": len(s["ignorees"])} for s in sections]), hide_index=True, width="stretch")
        meilleure = max(range(len(sections)), key=lambda i: len(sections[i]["transactions"]))
        choix = st.selectbox("Section à traiter dans ce passage", range(len(sections)), index=meilleure,
                             format_func=lambda i: sections[i]["nom"], key=cle + "_section")
        s = sections[choix]
        if s["rejetees"]:
            st.error(f"{len(s['rejetees'])} ligne(s) refusée(s) par la vérification : cette section ne peut pas être utilisée (rien n'est deviné).")
            with st.expander("Lignes refusées et raison"):
                st.dataframe(pd.DataFrame(s["rejetees"]), hide_index=True, width="stretch")
        if s["transactions"]:
            with st.expander(f"Lignes vérifiées ({len(s['transactions'])})", expanded=not s["rejetees"]):
                st.dataframe(pd.DataFrame(s["transactions"]), hide_index=True, width="stretch")
        if len(sections) > 1:
            st.caption("Les autres sections sont d'autres comptes du même relevé : elles ne sont pas chargées dans ce passage.")
        if st.button("✅ Utiliser cette lecture", type="primary", key=cle + "_valider", disabled=not LL.section_utilisable(s)):
            LL.enregistrer_lecture(chemin, s)
            st.session_state.pop(cle, None)
            st.rerun()


def _lancer():
    """Callback du bouton : fige les fichiers dans un dossier propre au passage, lance le moteur, bascule sur la vue en direct."""
    ss = st.session_state
    rid = f"d{datetime.now():%H%M%S}_documents"
    try:
        dossier = os.path.join(M.DONNEES, "uploads", rid)
        shutil.copytree(ss["doc_dossier_courant"], dossier)
        M.lancer(rid, dossier=dossier, compte=ss["doc_compte"], debut=ss["doc_debut"], fin=ss["doc_fin"], pas_a_pas=ss["doc_pas"],
                 delai=ss["doc_delai"], approbation=ss["doc_appro"], fournisseur=llm_f.fournisseur(),
                 modele=os.environ.get("LLM_MODELE", "") or None, isolee=ss["doc_isolee"])
        ss["run_vu"] = rid
        ss["vue"] = VUE_DIRECT
    except Exception as ex:                                         # noqa: BLE001
        ss["doc_erreur"] = str(ex)


def afficher():
    st.markdown("### 📥 Mes documents financiers")
    st.caption("Déposez vos relevés bancaires : **PDF** (4 mises en page reconnues), **CSV** ou **Excel** (colonnes date, libellé, montant "
               "ou débit/crédit, solde). Aucun scénario, aucune donnée inventée : les agents travaillent sur vos fichiers.")
    fichiers = st.file_uploader("Relevés", type=[e.lstrip(".") for e in EXTENSIONS], accept_multiple_files=True, key="doc_fichiers",
                                label_visibility="collapsed")
    if st.session_state.get("doc_erreur"):
        st.error("Lancement impossible : " + st.session_state.pop("doc_erreur"))
    if not fichiers:
        st.info("Nom attendu : `Compte - AAAA-MM.pdf` (ou `Compte_AAAA-MM.csv`…). Un fichier au nom différent peut être renommé ci-dessous.")
        return

    # --- 1. identification (compte, période) : modifiable quand le nom n'est pas reconnu
    t1, t2 = st.columns(2)
    t1.toggle("A1 classe par LLM les documents au nom non reconnu", value=True, key="doc_auto_a1",
              help="Le LLM lit le début du document et propose le compte et le mois ; le mois doit figurer dans le document.")
    t2.toggle("Lecture automatique par LLM des mises en page inconnues", value=True, key="doc_auto_lecture",
              help="Si le lecteur déterministe ne reconnaît pas la mise en page, le LLM transcrit le document. La lecture n'est "
                   "retenue automatiquement que si CHAQUE ligne passe la vérification contre le texte ; sinon vous décidez.")
    brut = os.path.join(M.DONNEES, "uploads", st.session_state.setdefault("doc_brut_id", f"b{datetime.now():%H%M%S}"))
    os.makedirs(brut, exist_ok=True)
    avec_llm = llm_f.fournisseur() != "simule"
    lignes, connus = [], []
    for f in fichiers:
        chemin_brut = os.path.join(brut, f.name)
        with open(chemin_brut, "wb") as fh:
            fh.write(f.getbuffer())
        info = analyser_nom_fichier(f.name)
        if info:
            lignes.append({"Fichier": f.name, "Compte": info[0], "Période (AAAA-MM)": info[1], "Classé par": "nom du fichier"})
            connus.append(info[0])
            continue
        if not st.session_state.get("doc_auto_a1", True):
            raison, ident_llm = "classement automatique désactivé", None
        elif not avec_llm:
            raison, ident_llm = "aucun LLM sélectionné (barre latérale)", None
        else:
            with st.spinner(f"A1 classe « {f.name} » ({llm_f.libelle()})…"):
                ident_llm = ID.identifier_document(chemin_brut, connus)
            raison = ident_llm["raison"]
        if ident_llm and ident_llm["ok"]:
            connus.append(ident_llm["compte"])
            lignes.append({"Fichier": f.name, "Compte": ident_llm["compte"], "Période (AAAA-MM)": ident_llm["periode"],
                           "Classé par": f"A1 (LLM, confiance {ident_llm['confiance']:.2f})"})
        else:
            lignes.append({"Fichier": f.name, "Compte": "", "Période (AAAA-MM)": "", "Classé par": "à compléter : " + raison})
    st.markdown("**1. Identification**")
    st.caption("A1 range les relevés par compte et par période : d'après le nom du fichier, sinon par le LLM. "
               "Corrigez ou complétez au besoin.")
    ident = st.data_editor(pd.DataFrame(lignes), hide_index=True, width="stretch", disabled=["Fichier", "Classé par"], key="doc_ident")
    erreurs = [r["Fichier"] for _, r in ident.iterrows() if not r["Compte"] or not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", str(r["Période (AAAA-MM)"]))]
    if erreurs:
        st.warning("Compte ou période invalide pour : " + ", ".join(erreurs))
        return

    # --- 2. dépôt dans un dossier de travail + aperçu de lecture
    rid_dossier = st.session_state.setdefault("doc_dossier_id", f"u{datetime.now():%H%M%S}")
    dossier = os.path.join(M.DONNEES, "uploads", rid_dossier)
    os.makedirs(dossier, exist_ok=True)
    for nom_actuel in os.listdir(dossier):
        os.remove(os.path.join(dossier, nom_actuel))
    apercus = []
    for f, (_, r) in zip(fichiers, ident.iterrows()):
        nouveau = _nom_valide(r["Compte"], r["Période (AAAA-MM)"], os.path.splitext(f.name)[1].lower())
        chemin = os.path.join(dossier, nouveau)
        with open(chemin, "wb") as fh:
            fh.write(f.getbuffer())
        apercus.append({"fichier": nouveau, "compte": r["Compte"], "periode_nom": r["Période (AAAA-MM)"], **_apercu(chemin)})
    st.session_state["doc_dossier_courant"] = dossier

    st.markdown("**2. Ce que le système lit**")
    st.dataframe(pd.DataFrame([{"Fichier": a["fichier"], "Format": a["format"], "Lignes lues": a["lignes"],
                                "Lignes rejetées": a.get("nb_rejetees", 0), "Soldes": a["soldes"], "Mois des dates": a["periode"]}
                               for a in apercus]), hide_index=True, width="stretch")
    for a in apercus:
        if a.get("nb_rejetees"):
            st.warning(f"**{a['fichier']}** — {a['nb_rejetees']} ligne(s) non reconnue(s) : le pipeline s'arrêtera à A2 plutôt que de deviner. "
                       "Exemples : " + " ¦ ".join(a["rejetees"][:3]))
        elif a["periode"] and a["periode"] != a["periode_nom"]:
            st.warning(f"**{a['fichier']}** — les dates du document couvrent {a['periode']}, le nom indique {a['periode_nom']} : A2 refusera.")
    for a in apercus:
        if a["format"] in ("non reconnu", "illisible") or a.get("nb_rejetees") or a["format"] == "LLM":
            _lecture_llm_ui(a, os.path.join(dossier, a["fichier"]))
    with st.expander("Aperçu des premières lignes lues"):
        for a in apercus:
            if a.get("echantillon"):
                st.caption(a["fichier"])
                st.dataframe(pd.DataFrame(a["echantillon"]), hide_index=True, width="stretch")

    # --- 3. compte et période à traiter
    comptes = sorted(ident["Compte"].unique())
    st.markdown("**3. Passage**")
    c1, c2, c3 = st.columns([2, 1, 1])
    compte = c1.selectbox("Compte à traiter", comptes, key="doc_compte")
    periodes = sorted(ident.loc[ident["Compte"] == compte, "Période (AAAA-MM)"])
    debut = c2.selectbox("Du", periodes, index=0, key="doc_debut")
    fin = c3.selectbox("Au", periodes, index=len(periodes) - 1, key="doc_fin")
    if len(comptes) > 1:
        st.caption("Un passage traite un seul compte : relancez pour les autres.")

    o1, o2, o3 = st.columns(3)
    o1.toggle("Copie isolée de la base (recommandé)", value=True, key="doc_isolee",
              help="Les agents écrivent dans une copie jetable : la base de démo et le tableau de trésorerie ne changent pas. "
                   "Désactivez pour que vos documents alimentent le tableau.")
    o2.toggle("Pas à pas", value=False, key="doc_pas")
    o3.toggle("Approbation humaine avant les rapports", value=False, key="doc_appro")
    st.slider("Pause entre agents (s)", 0.0, 5.0, 0.6, 0.1, key="doc_delai", disabled=st.session_state.get("doc_pas", False))
    st.caption(f"LLM utilisé : **{llm_f.libelle()}** (changeable dans la barre latérale).")
    actif = M.run_actif()
    st.button("▶ Lancer sur mes documents", type="primary", disabled=bool(actif) or debut > fin, on_click=_lancer, key="doc_lancer")
    if actif:
        st.info("Un passage est déjà en cours : attendez sa fin (vue « Démo en direct »).")
    if debut > fin:
        st.error("La période de début est postérieure à la période de fin.")
