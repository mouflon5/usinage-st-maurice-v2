"""Rapports des agents : pour chaque passage du pipeline, un rapport lisible par agent (A1 à A8) et un rapport complet exportable.

Les données viennent des événements que le moteur de démonstration enregistre à chaque agent (demo.db) : statut, durée, message, tableaux
de détail. En mode Simple on montre la synthèse (une ligne par agent) ; en mode Expert, le détail (tableaux, contrôles, relecture).
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime

import pandas as pd
import streamlit as st

from demo_live import moteur as M

AGENTS = [("A1", "Acquisition", "executer_a1"), ("A2", "Extraction", "executer_a2"), ("A3", "Classement et chargement", "executer_a3"),
          ("A4", "Prévision", "executer_a4"), ("A5", "Écarts", "executer_a5"), ("A6", "Contrôle", "executer_a6"),
          ("A8", "Relecture", "executer_a8"), ("A7", "Rapports", "executer_a7")]
ROLES = {
    "A1": "Trouve les relevés du compte et détecte les mois manquants.",
    "A2": "Lit les documents, extrait les opérations et rejoue la continuité des soldes.",
    "A3": "Écarte les doublons, classe chaque ligne (règles, puis LLM pour le résidu) et charge le journal.",
    "A4": "Prévoit les encaissements et les décaissements (SARIMAX) et le flux net des six prochains mois.",
    "A5": "Compare le réel au budget et à la prévision, explique les écarts importants.",
    "A6": "Refait onze contrôles indépendants ; seul point de sortie : il approuve, approuve avec réserves ou bloque.",
    "A8": "Relit le travail des autres agents et signale des réserves sans jamais bloquer.",
    "A7": "Produit le classeur Excel et le brouillon du rapport mensuel R0.",
}
ICONES = {"ok": "✅", "res": "⚠️", "stop": "⛔", "non": "▫️"}
VERDICTS = {"complet": "Pipeline réussi : les rapports sont produits.", "complet_avec_reserves": "Terminé avec réserves : à lire avant de signer.",
            "a_arbitrer": "Arbitrage humain requis : des lignes n'ont pas pu être classées avec certitude.",
            "arrete_a1": "Arrêt à A1 : le relevé est incomplet ; rien n'a été écrit.", "arrete_a2": "Arrêt à A2 : extraction douteuse ; rien n'a été écrit.",
            "arrete_a4": "Arrêt à A4 : historique inutilisable.", "arrete_a5": "Arrêt à A5 : écarts non calculables.",
            "bloque_a6": "Bloqué par A6 : un contrôle bloquant a échoué ; rien ne sort.", "rejete_humain": "Rejeté lors de l'approbation humaine.",
            "arrete": "Arrêté par l'utilisateur.", "exception": "Incident technique."}


# --------------------------------------------------------------------------- #
# Lecture des passages
# --------------------------------------------------------------------------- #
def _connexion():
    # connexion normale (pas « ro ») : en mode WAL, une lecture seule échoue quand le dernier écrivain ferme la base
    return sqlite3.connect(M.DB_EVENEMENTS, timeout=10) if os.path.isfile(M.DB_EVENEMENTS) else None


def passages() -> list[dict]:
    c = _connexion()
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
    c = _connexion()
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


def classe(statut: str | None) -> str:
    if statut in (None, ""):
        return "non"
    if statut in ("complet", "approuve", "ok", "approuver"):
        return "ok"
    if statut in ("reserves", "a_arbitrer", "degrade", "indisponible", "complet_avec_reserves"):
        return "res"
    return "stop"


# --------------------------------------------------------------------------- #
# Construction des rapports
# --------------------------------------------------------------------------- #
def _argent(v) -> str:
    return "—" if v is None else f"{v:,.0f} $".replace(",", " ")


def _table(rows, colonnes: dict[str, str]) -> pd.DataFrame:
    """Sous-ensemble et renommage des colonnes d'une liste de dictionnaires."""
    df = pd.DataFrame(rows)
    cols = [c for c in colonnes if c in df.columns]
    return df[cols].rename(columns=colonnes)


def rapport_agent(e: dict | None, code: str, nom: str) -> dict:
    """Rapport d'un agent : {code, nom, role, statut, classe, duree, message, blocs} ; blocs = [(titre, DataFrame | texte)]."""
    r = {"code": code, "nom": nom, "role": ROLES[code], "statut": None, "classe": "non", "duree": None, "message": "Cet agent n'a pas été exécuté dans ce passage.",
         "blocs": []}
    if e is None:
        return r
    d, res = e["detail"], e["detail"].get("resume", {})
    r.update(statut=e["statut"], classe=classe(e["statut"]), duree=e["duree"], message=e["message"] or "")
    b, noeud = r["blocs"], e["noeud"]
    sorties = res.get("sorties") or {}
    if sorties:
        b.append(("Ce que l'agent a produit", pd.DataFrame({"Élément": [k.replace("_", " ") for k in sorties], "Quantité": [str(v) for v in sorties.values()]})))
    if noeud == "executer_a2" and d.get("exemples"):
        b.append((f"{d.get('nb_transactions')} opération(s) extraite(s), aperçu", _table(d["exemples"], {"date": "Date", "description": "Description", "montant": "Montant"})))
    elif noeud == "executer_a3":
        for cle, titre, cols in (("classees", "Lignes classées et écrites au journal", {"date": "Date", "description": "Description", "montant": "Montant", "categorie": "Catégorie", "methode": "Méthode"}),
                                 ("a_classer", "Lignes escaladées à classer par un humain", {"date": "Date", "description": "Description", "montant": "Montant", "suggestion": "Suggestion"}),
                                 ("doublons", "Doublons ignorés", {"date": "Date", "description": "Description", "montant": "Montant", "origine": "Origine"})):
            if d.get(cle):
                b.append((titre, _table(d[cle], cols)))
    elif noeud == "executer_a4":
        if d.get("series"):
            fn = d.get("flux_net_prevu") or {}
            periodes = fn.get("periodes") or [f"M+{i + 1}" for i in range(len(next(iter(d["series"].values()))))]
            df = pd.DataFrame({"Mois": periodes, **{k: v for k, v in d["series"].items()}})
            if fn.get("valeurs"):
                df["Flux net prévu"] = fn["valeurs"]
            b.append(("Prévisions mensuelles ($)", df))
    elif noeud == "executer_a5":
        if d.get("ecarts"):
            df = _table(d["ecarts"], {"libelle": "Poste", "reel": "Réel", "budget": "Budget", "prevu": "Prévu", "jugement_budget": "Jugement vs budget", "jugement_prevision": "Jugement vs prévision"})
            b.append(("Écarts du mois", df))
        com = d.get("commentaire")
        if isinstance(com, dict):
            if com.get("resume"):
                b.append(("Commentaire de l'agent", com["resume"]))
            if com.get("points"):
                b.append(("Points clés", "\n".join(f"- {p}" for p in com["points"])))
        elif isinstance(com, str):
            b.append(("Commentaire de l'agent", com))
    elif noeud == "executer_a6" and res.get("controles"):
        ctr = res["controles"]
        b.append((f"Contrôles : {sum(1 for c in ctr if c['ok'])} sur {len(ctr)} réussis",
                  pd.DataFrame([{"Résultat": "✓" if c["ok"] else "✕", "Contrôle": c["id"], "Libellé": c["libelle"], "Gravité": c["gravite"], "Détail": c["detail"]} for c in ctr])))
    elif noeud == "executer_a8" and res.get("relecture"):
        rl = res["relecture"]
        if rl.get("notes"):
            b.append((f"Notes de la relecture (origine : {rl.get('origine')})", pd.DataFrame({"Critère": list(rl["notes"]), "Note sur 5": list(rl["notes"].values())})))
        if rl.get("constats"):
            b.append(("Constats", pd.DataFrame([{"Réf.": c.get("ref"), "Gravité": c.get("gravite"), "Constat": c.get("texte") or c.get("constat")} for c in rl["constats"]])))
        else:
            b.append(("Constats", "Aucune réserve."))
        if rl.get("rejetes"):
            b.append(("Constats rejetés par les garde-fous", f"{len(rl['rejetes'])} constat(s) citait une référence ou un chiffre inexistant."))
    elif noeud == "executer_a7" and d.get("fichiers"):
        b.append(("Fichiers produits", "\n".join(f"- {os.path.basename(f)}" for f in d["fichiers"])))
    return r


def rapports_passage(run: dict, evts: list[dict]) -> dict:
    """Tous les rapports d'un passage : verdict, un rapport par agent, KPI avant et après."""
    par_noeud = {e["noeud"]: e for e in evts if e["type"] == "agent"}
    fin = next((e for e in reversed(evts) if e["type"] == "fin"), None)
    dem = next((e for e in evts if e["type"] == "demarrage"), None)
    kp = [e["kpi"] for e in evts if e["kpi"]]
    return {"run": run, "demarrage": dem["detail"] if dem else {}, "fin": fin["detail"] if fin else {},
            "statut": (fin["detail"].get("statut_pipeline") if fin else None), "agents": [rapport_agent(par_noeud.get(n), c, nom) for c, nom, n in AGENTS],
            "kpi_avant": kp[0] if kp else None, "kpi_apres": kp[-1] if kp else None}


def markdown(rp: dict) -> str:
    """Rapport complet d'un passage, en Markdown (tableaux inclus)."""
    run, dem, fin = rp["run"], rp["demarrage"], rp["fin"]
    L = [f"# Rapport des agents — {run['titre']}", "", f"- Passage : `{run['run_id']}` ({run['debut'][:19].replace('T', ' ')})",
         f"- Compte : {dem.get('compte', '—')} · période {dem.get('periode', '—')}", f"- Verdict : **{VERDICTS.get(rp['statut'], rp['statut'] or 'en cours')}**"]
    if fin.get("message"):
        L += ["", fin["message"]]
    for a in rp["agents"]:
        L += ["", f"## {a['code']} · {a['nom']} — {ICONES[a['classe']]} {a['statut'] or 'non exécuté'}", "", f"*{a['role']}*", "", a["message"]]
        if a["duree"] is not None:
            L += ["", f"Durée : {a['duree']:.2f} s"]
        for titre, contenu in a["blocs"]:
            L += ["", f"### {titre}", ""]
            L.append(_tableau_md(contenu) if isinstance(contenu, pd.DataFrame) else str(contenu))
    L += ["", f"_Rapport généré le {datetime.now():%Y-%m-%d %H:%M}._"]
    return "\n".join(L) + "\n"


def _tableau_md(df: pd.DataFrame) -> str:
    def cellule(v) -> str:
        if isinstance(v, float):
            v = f"{v:,.2f}".replace(",", " ")
        return str(v).replace("|", "\\|").replace("\n", " ")
    L = ["| " + " | ".join(cellule(c) for c in df.columns) + " |", "|" + "|".join("---" for _ in df.columns) + "|"]
    L += ["| " + " | ".join(cellule(v) for v in ligne) + " |" for ligne in df.itertuples(index=False)]
    return "\n".join(L)


# --------------------------------------------------------------------------- #
# Affichage
# --------------------------------------------------------------------------- #
def _synthese(rp: dict):
    run, dem = rp["run"], rp["demarrage"]
    verdict = VERDICTS.get(rp["statut"], f"{rp['statut']}" if rp["statut"] else "Passage en cours")
    cl = {"complet": "ok", "complet_avec_reserves": "res"}.get(rp["statut"], "stop" if rp["statut"] else "non")
    box = {"ok": st.success, "res": st.warning, "stop": st.error, "non": st.info}[cl]
    box(f"**{verdict}**  \n{rp['fin'].get('message') or ''}".replace("$", "\\$"))
    st.caption(f"Compte {dem.get('compte', '—')} · période {dem.get('periode', '—')} · passage du {run['debut'][:16].replace('T', ' ')} · mode {run['mode']}")


def _carte(a: dict, detail: bool):
    titre = f"{ICONES[a['classe']]} {a['code']} · {a['nom']}" + (f" — {a['statut']}" if a["statut"] else "") + (f"  ({a['duree']:.1f} s)" if a["duree"] else "")
    if not detail:
        st.markdown(f"**{titre}**  \n{a['message']}".replace("$", "\\$"))
        return
    with st.expander(titre, expanded=a["classe"] in ("res", "stop")):
        st.caption(a["role"])
        st.write(a["message"].replace("$", "\\$"))
        for t, contenu in a["blocs"]:
            st.markdown(f"**{t}**")
            if isinstance(contenu, pd.DataFrame):
                st.dataframe(contenu, hide_index=True, width="stretch")
            else:
                st.markdown(str(contenu).replace("$", "\\$"))


def afficher(expert: bool):
    tous = passages()
    if not tous:
        st.info("Aucun passage pour l'instant. Lancez une démonstration ou déposez vos relevés : chaque passage produit un rapport par agent.")
        return
    ids = [r["run_id"] for r in tous]
    if st.session_state.get("rap_passage") not in ids:
        st.session_state["rap_passage"] = ids[0]
    st.selectbox("Passage", ids, key="rap_passage", format_func=lambda r: next(
        (f"{x['titre']} — {x['statut']} — {x['debut'][:16].replace('T', ' ')}" for x in tous if x["run_id"] == r), r))
    run = next(r for r in tous if r["run_id"] == st.session_state["rap_passage"])
    rp = rapports_passage(run, evenements(run["run_id"]))
    _synthese(rp)

    kp0, kp1 = rp["kpi_avant"], rp["kpi_apres"]
    if kp0 and kp1:
        cols = st.columns(4)
        for col, (cle, lib) in zip(cols, (("solde_actuel", "Solde actuel"), ("creux", "Creux 13 semaines"), ("flux_net_2026", "Flux net 2026"), ("ecart_budget_annee", "Écart vs budget"))):
            if kp0.get(cle) is not None and kp1.get(cle) is not None:
                d = kp1[cle] - kp0[cle]
                col.metric(lib, _argent(kp1[cle]), delta=(_argent(d) if abs(d) > 0.5 else None), border=True)

    st.subheader("Rapport de chaque agent")
    for a in rp["agents"]:
        _carte(a, detail=expert)
    if not expert:
        st.caption("Le mode Expert montre le détail de chaque agent : tableaux, contrôles, notes de la relecture.")
    st.download_button("⬇ Rapport complet des agents (Markdown)", markdown(rp), file_name=f"rapport_agents_{run['run_id']}.md", mime="text/markdown",
                       icon=":material/download:")
