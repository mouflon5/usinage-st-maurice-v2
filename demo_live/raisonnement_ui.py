"""Vue « Raisonnement » : comprendre POURQUOI chaque agent et chaque LLM a décidé ce qu'il a décidé (pas de boîte noire).

Tout vient de deux sources écrites pendant le passage :
  * `evenements`  ce que chaque agent a produit et son verdict (statut, message, contrôles, constats) ;
  * `llm_traces`  chaque échange avec un modèle : prompt exact, réponse exacte, réflexion éventuelle du modèle, puis la décision
                  que l'agent en a tirée (acceptée / escaladée / rejetée par garde-fou) et sa raison.
Les outils : parcours de décision, lignes classées avec leurs précédents, échanges bruts, vérificateur de nombres, rejeu sur un autre modèle.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3

import pandas as pd
import streamlit as st

import llm_fournisseur as llm_f
import llm_outils
from demo_live import moteur as M, reseau_ui

ROLES = {
    "A1": ("Acquisition", "Compare les périodes attendues aux périodes couvertes par les noms de fichiers. Un trou ou deux relevés pour la même période arrêtent la chaîne."),
    "A2": ("Extraction", "Lit chaque document ; toute ligne non reconnue est REJETÉE (jamais devinée) ; vérifie la continuité des soldes, la période et le compte. Une anomalie arrête la chaîne."),
    "A3": ("Classement et chargement", "Écarte les doublons, classe par mots-clés, puis soumet seulement le résidu au LLM : sa réponse n'est écrite au journal que si la catégorie existe et si la confiance dépasse le seuil."),
    "A4": ("Prévision", "Modèle statistique SARIMAX sur l'historique du journal. Aucun LLM."),
    "A5": ("Écarts", "Les écarts sont calculés en SQL. Le LLM ne fait que rédiger le commentaire ; tout nombre absent du tableau fait rejeter son texte."),
    "A6": ("Contrôle", "Onze contrôles déterministes. Un contrôle bloquant arrête tout : rien ne sort."),
    "A8": ("Relecture", "Second avis qualitatif. Il peut ajouter des réserves, jamais bloquer ni modifier ; ses constats doivent citer une référence et des nombres qui existent."),
    "A7": ("Rapports", "Produit les rapports ; la synthèse rédigée par le LLM est vérifiée nombre par nombre."),
}
NOMBRE = re.compile(r"\d+(?:[   ]\d{3})*(?:[.,]\d+)?")
DECISION_OK = ("acceptée", "accepté")


# --------------------------------------------------------------------------- #
# Accès aux données
# --------------------------------------------------------------------------- #
def _lire(sql: str, params: tuple = ()) -> pd.DataFrame:
    if not os.path.isfile(M.DB_EVENEMENTS):
        return pd.DataFrame()
    c = sqlite3.connect(M.DB_EVENEMENTS, timeout=10)
    try:
        return pd.read_sql_query(sql, c, params=params)
    except Exception:                                               # table pas encore créée
        return pd.DataFrame()
    finally:
        c.close()


def _enregistrements(df: pd.DataFrame) -> list[dict]:
    """Lignes sous forme de dict, avec None (et non NaN) pour les valeurs SQL NULL."""
    return [{k: (None if pd.isna(v) else v) for k, v in r.items()} for r in df.to_dict("records")]


def _runs() -> list[dict]:
    return _enregistrements(_lire("SELECT run_id, titre, statut, mode, debut FROM runs ORDER BY debut DESC"))


def _evenements(run_id: str) -> list[dict]:
    out = []
    for e in _enregistrements(_lire("SELECT * FROM evenements WHERE run_id=? ORDER BY id", (run_id,))):
        e["detail"] = json.loads(e["detail"]) if e.get("detail") else {}
        out.append(e)
    return out


def _traces(run_id: str) -> list[dict]:
    out = []
    for t in _enregistrements(_lire("SELECT * FROM llm_traces WHERE run_id=? ORDER BY id", (run_id,))):
        t["meta"] = json.loads(t["meta"]) if t.get("meta") else {}
        out.append(t)
    return out


def _appels(run_id: str) -> pd.DataFrame:
    return _lire("SELECT type, agent, modele, mode, duree_ms, tok_in, tok_out, estime, cout, statut, meta FROM llm_appels WHERE run_id=?", (run_id,))


def _json(texte: str) -> dict:
    try:
        d = json.loads(texte)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _reel(t: dict) -> bool:
    return t["fournisseur"] != "simule"


def _esc(s) -> str:
    return str(s or "").replace("$", "\\$")


# --------------------------------------------------------------------------- #
# Bandeau de synthèse
# --------------------------------------------------------------------------- #
def _bandeau(evts, traces, appels):
    dem = next((e for e in evts if e["type"] == "demarrage"), None)
    llm = (dem or {}).get("detail", {}).get("llm") or {}
    reels = [t for t in traces if _reel(t)]
    refus = [t for t in traces if t.get("decision") and not t["decision"].startswith(DECISION_OK)]
    erreurs = [t for t in traces if t.get("statut") == "erreur"]
    c = st.columns(5)
    c[0].metric("LLM", llm.get("fournisseur", "—"), help=f"Modèle : {llm.get('modele', '—')}")
    c[1].metric("Échanges avec un modèle", len(reels))
    c[2].metric("Décisions par règles", len(traces) - len(reels))
    c[3].metric("Réponses écartées par l'agent", len(refus), help="Escaladées, rejetées par un garde-fou ou remplacées par un gabarit.")
    c[4].metric("Pannes de modèle", len(erreurs))
    if not appels.empty and (appels["type"] == "appel").any():
        a = appels[appels["type"] == "appel"]
        synth = a.groupby(["agent", "modele"]).agg(appels=("agent", "size"), durée_moy_ms=("duree_ms", "mean"), jetons_in=("tok_in", "sum"),
                                                   jetons_out=("tok_out", "sum"), coût_usd=("cout", "sum"), erreurs=("statut", lambda s: int((s == "erreur").sum()))).reset_index()
        synth["durée_moy_ms"] = synth["durée_moy_ms"].round(0)
        synth["coût_usd"] = synth["coût_usd"].round(4)
        with st.expander("Coût et latence par agent et par modèle"):
            st.dataframe(synth, hide_index=True, width="stretch")
            st.caption("Jetons estimés (1 pour 4 caractères) quand le modèle ne les renvoie pas. Un modèle Ollama est local : coût nul.")


# --------------------------------------------------------------------------- #
# Onglet 1 — parcours de décision
# --------------------------------------------------------------------------- #
def _echange_resume(t: dict) -> str:
    quoi = "règle" if not _reel(t) else f"{t['fournisseur']} · {t['modele']}"
    dec = t.get("decision") or "—"
    return f"{quoi} → **{dec}**" + (f" — {_esc(t['decision_detail'])}" if t.get("decision_detail") else "")


def _parcours(evts, traces):
    agents = [e for e in evts if e["type"] == "agent"]
    if not agents:
        st.info("Ce passage n'a pas encore terminé d'agent.")
        return
    sequence = " → ".join(f"{e['agent'] or e['noeud'].replace('finaliser_', 'fin ')} ({e['statut'] or '·'})" for e in agents)
    st.markdown(f"**Chemin suivi** : {_esc(sequence)}")
    fin = next((e for e in reversed(evts) if e["type"] == "fin"), None)
    if fin:
        st.markdown(f"**Verdict** : `{fin['detail'].get('statut_pipeline')}` — {_esc(fin['detail'].get('message'))}")
    st.caption("Chaque carte répond à trois questions : que fait cet agent (sa règle), qu'a-t-il décidé, sur quelle preuve.")
    for e in agents:
        code = e["agent"]
        if not code:
            continue
        nom, regle = ROLES.get(code, (code, ""))
        res = e["detail"].get("resume", {})
        mes = [t for t in traces if t["agent"] == code]
        with st.expander(f"{code} · {nom} — {e['statut'] or ''}  ({(e['duree'] or 0):.2f} s)", expanded=bool(mes) and code in ("A3", "A5", "A8")):
            st.markdown(f"**Sa règle.** {regle}")
            if e.get("message"):
                st.markdown(f"**Sa décision.** {_esc(e['message'])}")
            sorties = res.get("sorties")
            if sorties:
                st.caption("A transmis : " + ", ".join(f"{n} {k}" for k, n in sorties.items()))
            if code == "A6" and res.get("controles"):
                st.markdown("**Preuves — les contrôles**")
                st.dataframe(pd.DataFrame([{"": "✓" if c["ok"] else "✕", "Contrôle": c["id"], "Ce qu'il vérifie": c["libelle"],
                                            "Gravité": c["gravite"], "Constat": c["detail"]} for c in res["controles"]]),
                             hide_index=True, width="stretch")
            if code == "A8" and res.get("relecture"):
                rl = res["relecture"]
                st.markdown(f"**Preuves — constats retenus ({len(rl.get('constats', []))}) et rejetés ({len(rl.get('rejetes', []))})** · origine : {rl.get('origine')}")
                for c in rl.get("constats", []):
                    st.markdown(f"- `{c.get('ref')}` [{c.get('gravite')}] {_esc(c.get('texte'))}")
                for c in rl.get("rejetes", []):
                    st.markdown(f"- ~~`{c.get('ref')}` {_esc(c.get('texte'))}~~ — **rejeté** : {_esc(c.get('raison'))}")
            if code == "A3":
                _resume_a3(e)
            if mes and code != "A3":
                st.markdown("**Échanges avec un modèle ou règle de gabarit**")
                for t in mes:
                    st.markdown("- " + _echange_resume(t))
                st.caption("Le détail (prompt, réponse, réflexion) est dans l'onglet « Échanges avec le LLM ».")


def _resume_a3(e):
    d = e["detail"]
    nb_cl, nb_res, nb_dbl = len(d.get("classees", [])), len(d.get("a_classer", [])), len(d.get("doublons", []))
    par_methode = pd.Series([c.get("methode") or "?" for c in d.get("classees", [])]).value_counts()
    st.markdown("**Preuves — comment chaque ligne a été traitée** : "
                + ", ".join(f"{n} par **{m}**" for m, n in par_methode.items())
                + f" · {nb_res} escaladée(s) à l'humain · {nb_dbl} doublon(s) écarté(s).")
    st.caption("« regle » = mot-clé de la table mots_cles (déterministe). « llm » / « simule » = le résidu soumis au modèle. "
               "Onglet « Lignes classées (A3) » pour le détail ligne par ligne.")


# --------------------------------------------------------------------------- #
# Onglet 2 — lignes classées (A3)
# --------------------------------------------------------------------------- #
def _lignes_a3(traces):
    a3 = [t for t in traces if t["agent"] == "A3"]
    if not a3:
        st.info("Aucune ligne n'a eu besoin du modèle dans ce passage : les règles de mots-clés ont tout classé (ou rien n'a atteint A3).")
        return
    lignes = []
    for t in a3:
        rep, meta = _json(t["reponse"]), t["meta"]
        prec = meta.get("precedents", [])
        lignes.append({"id": t["id"], "Date": meta.get("date"), "Description": meta.get("description"), "Montant": meta.get("montant"),
                       "Source": "règle simulée" if not _reel(t) else f"{t['modele']}", "Catégorie proposée": rep.get("categorie"),
                       "Confiance": rep.get("confiance"), "Décision": t.get("decision"), "Raison": t.get("decision_detail"),
                       "Précédent le plus proche": (prec[0]["categorie"] if prec else None),
                       "Accord avec le précédent": (None if not prec or not rep.get("categorie") else prec[0]["categorie"] == rep["categorie"]),
                       "_valide": rep.get("categorie") != "À classer" and not any(x in (t.get("decision_detail") or "") for x in ("absente de la liste", "échec")),
                       "_seuil": meta.get("seuil", llm_outils.SEUIL_CONFIANCE)})
    df = pd.DataFrame(lignes)
    seuil0 = float(df["_seuil"].iloc[0])
    seuil = st.slider("Et si le seuil de confiance était…", 0.0, 1.0, seuil0, 0.05, key="rs_seuil",
                      help="Simulation : recalcule la décision d'après les confiances enregistrées, sans rappeler le modèle.")
    df["Décision avec ce seuil"] = df.apply(lambda r: "acceptée" if r["_valide"] and (r["Confiance"] or 0) >= seuil else "escaladée", axis=1)
    bascule = int((df["Décision avec ce seuil"] != df["Décision"].fillna("")).sum())
    c = st.columns(3)
    c[0].metric("Lignes traitées par le modèle", len(df))
    c[1].metric(f"Acceptées au seuil {seuil:.2f}", int((df["Décision avec ce seuil"] == "acceptée").sum()))
    c[2].metric("Décisions qui changeraient", bascule, help="Par rapport à la décision réellement prise (seuil " + f"{seuil0:.2f}).")
    st.dataframe(df.drop(columns=["id", "_valide", "_seuil"]), hide_index=True, width="stretch")
    contredit = df[df["Accord avec le précédent"] == False]  # noqa: E712
    if len(contredit):
        st.warning(f"{len(contredit)} ligne(s) où le modèle contredit le précédent le plus proche : à regarder en priorité.")

    st.markdown("**Pourquoi cette ligne ?**")
    choix = st.selectbox("Ligne", df["id"], format_func=lambda i: f"{df.loc[df['id'] == i, 'Description'].iloc[0]} — {df.loc[df['id'] == i, 'Décision'].iloc[0]}", key="rs_ligne")
    t = next(x for x in a3 if x["id"] == choix)
    prec = t["meta"].get("precedents", [])
    rep = _json(t["reponse"])
    g, d = st.columns(2)
    with g:
        st.markdown("**Preuves données au modèle (précédents les plus proches)**")
        if prec:
            st.dataframe(pd.DataFrame(prec).rename(columns={"score": "Similarité", "categorie": "Catégorie", "description": "Libellé précédent"}),
                         hide_index=True, width="stretch")
        else:
            st.write("Aucun précédent similaire dans le journal.")
    with d:
        st.markdown("**Ce que le modèle a répondu**")
        st.write(f"Catégorie : **{rep.get('categorie')}** · confiance **{rep.get('confiance')}**")
        st.write(_esc(rep.get("justification")))
        st.markdown(f"**Ce que l'agent en a fait** : {t.get('decision') or '—'} — {_esc(t.get('decision_detail'))}")
    _echange(t)


# --------------------------------------------------------------------------- #
# Un échange (prompt, réponse, réflexion, décision)
# --------------------------------------------------------------------------- #
def _echange(t: dict):
    p, r, pe, d = st.tabs(["Prompt envoyé", "Réponse brute", "Réflexion du modèle", "Décision de l'agent"])
    with p:
        st.code(t["prompt"] or "(vide)", language=None, wrap_lines=True)
    with r:
        st.code(t["reponse"] or "(aucune réponse)", language=None, wrap_lines=True)
        if t.get("erreur"):
            st.error(t["erreur"])
    with pe:
        if t.get("raisonnement"):
            st.code(t["raisonnement"], language=None, wrap_lines=True)
        else:
            st.caption("Ce modèle n'a pas émis de réflexion lisible. C'est normal : Claude en sortie structurée ne fournit que la réponse, "
                       "et les règles/gabarits n'ont pas de réflexion. Les modèles locaux « raisonnement » (deepseek-r1, qwen3) la fournissent. "
                       "Dans tous les cas, le prompt et les preuves ci-dessus sont ce sur quoi le modèle a travaillé.")
    with d:
        st.write(f"**{t.get('decision') or 'aucune décision consignée'}**")
        st.write(_esc(t.get("decision_detail")))
        st.caption(f"{t['fournisseur']} · {t['modele']} · {(t['duree_ms'] or 0):.0f} ms · {t['tok_in']} → {t['tok_out']} jetons")


# --------------------------------------------------------------------------- #
# Onglet 3 — tous les échanges + rejeu
# --------------------------------------------------------------------------- #
def _echanges(traces):
    if not traces:
        st.info("Aucun échange consigné pour ce passage (les passages antérieurs à cette fonction n'ont pas de traces).")
        return
    agents = sorted({t["agent"] for t in traces})
    filtre = st.multiselect("Agents", agents, default=[a for a in agents if a != "A3"] or agents, key="rs_filtre")
    visibles = [t for t in traces if t["agent"] in filtre]
    for t in visibles:
        icone = "🤖" if _reel(t) else "📏"
        with st.expander(f"{icone} {t['agent']} · {t['modele']} · {t.get('decision') or '—'}  (#{t['id']})"):
            _echange(t)
    st.divider()
    _rejeu(traces)


def _rejeu(traces):
    st.markdown("### 🔁 Rejouer une décision sur un autre modèle")
    st.caption("Reprend le prompt d'un échange et le soumet à un autre modèle pour voir s'il décide pareil. Rien n'est écrit dans la base ni dans les traces.")
    candidats = [t for t in traces if _reel(t) or t["agent"] == "A3"]
    if not candidats:
        st.info("Aucun échange rejouable.")
        return
    t = st.selectbox("Échange", candidats, key="rs_rej_t",
                     format_func=lambda x: f"#{x['id']} {x['agent']} · {x['modele']} · " + (x["meta"].get("description") or x["prompt"][:50]).replace("\n", " "))
    a, b = st.columns(2)
    prov = a.radio("Fournisseur", ("ollama", "claude"), horizontal=True, key="rs_rej_p")
    if prov == "ollama":
        noms = [m["nom"] for m in llm_f.lister_ollama()]
        modele = b.selectbox("Modèle", noms or [llm_f.OLLAMA_MODELE_DEFAUT], key="rs_rej_m_o")
    else:
        modele = b.selectbox("Modèle", llm_f.CLAUDE_MODELES, index=1, key="rs_rej_m_c")
        if not os.environ.get("ANTHROPIC_API_KEY"):
            st.warning("Clé API absente : saisissez-la dans la barre latérale (LLM des agents → Claude).")
    if not st.button("▶ Rejouer", key="rs_rej_go"):
        return
    schema, prompt = None, t["prompt"]
    if t["agent"] == "A3":
        schema = llm_outils.Classement
        if not _reel(t):                                            # la trace simulée ne contient pas le vrai prompt : on le reconstruit
            prompt = _prompt_a3_reconstruit(t)
    with st.spinner(f"{modele} réfléchit…"):
        try:
            nouveau = llm_f.rejouer(prov, modele, prompt, schema=schema, max_tokens=1500 if t["agent"] == "A8" else 800)
        except Exception as ex:                                     # noqa: BLE001
            st.error(f"{type(ex).__name__}: {ex}")
            return
    g, d = st.columns(2)
    g.markdown(f"**Original** — {t['fournisseur']} · {t['modele']}")
    g.code(t["reponse"], language=None, wrap_lines=True)
    d.markdown(f"**Rejoué** — {prov} · {modele} · {nouveau.duree_ms:.0f} ms")
    d.code(nouveau.texte, language=None, wrap_lines=True)
    if nouveau.raisonnement:
        with st.expander("Réflexion du modèle rejoué"):
            st.code(nouveau.raisonnement, language=None, wrap_lines=True)
    if schema is not None:
        ancien = _json(t["reponse"])
        mm = ancien.get("categorie") == nouveau.parse.categorie
        (st.success if mm else st.warning)(
            f"{'Même' if mm else 'Autre'} catégorie : {ancien.get('categorie')} ({ancien.get('confiance')}) → "
            f"{nouveau.parse.categorie} ({nouveau.parse.confiance})")


def _prompt_a3_reconstruit(t: dict) -> str:
    c = sqlite3.connect(M.BASE_DEMO)
    try:
        categories = dict(c.execute("SELECT categorie, nature FROM categories").fetchall())
    finally:
        c.close()
    meta = t["meta"]
    prec = [(p["score"], p["categorie"], p["description"]) for p in meta.get("precedents", [])]
    return llm_outils.prompt_classement({"description": meta.get("description", ""), "montant": meta.get("montant", 0.0)}, categories, prec)


# --------------------------------------------------------------------------- #
# Onglet 4 — garde-fous
# --------------------------------------------------------------------------- #
def _gardes(evts, traces, appels):
    st.markdown("### Vérificateur de nombres")
    st.caption("Principe central du système : un LLM ne calcule jamais. Tout nombre qu'il écrit doit exister dans le contexte qu'on lui a fourni, "
               "sinon sa réponse est rejetée et remplacée. Voici ce contrôle, nombre par nombre.")
    cibles = [t for t in traces if _reel(t) and t["agent"] in ("A5", "A7", "A8", "RAG") and t["reponse"]]
    if not cibles:
        st.info("Aucune rédaction par un modèle dans ce passage. Choisissez Claude ou Ollama (barre latérale) et relancez un passage.")
    else:
        t = st.selectbox("Réponse à vérifier", cibles, key="rs_garde_t", format_func=lambda x: f"#{x['id']} {x['agent']} · {x['modele']} · {x.get('decision') or '—'}")
        connus = _nombres(t["prompt"])
        lignes = [{"Nombre dans la réponse": n, "Présent dans le contexte": "✓" if _norm(n) in connus else "✕ INVENTÉ ?"} for n in NOMBRE.findall(t["reponse"])]
        if lignes:
            st.dataframe(pd.DataFrame(lignes).drop_duplicates(), hide_index=True, width="stretch")
        else:
            st.write("La réponse ne contient aucun nombre.")
        st.write(f"**Décision de l'agent** : {t.get('decision') or '—'} — {_esc(t.get('decision_detail'))}")
    st.markdown("### Contrôles consignés pendant le passage")
    g = appels[appels["type"] == "garde"] if not appels.empty else appels
    if g is None or g.empty:
        st.caption("Aucun contrôle de garde-fou consigné.")
    else:
        st.dataframe(pd.DataFrame([{"Agent": r["agent"], "Garde-fou": r["modele"], "Verdict": "✓ laissé passer" if r["statut"] == "ok" else "✕ rejeté",
                                    "Détail": _json(r["meta"])} for _, r in g.iterrows()]), hide_index=True, width="stretch")


def _norm(n: str) -> str:
    return re.sub(r"[   ]", "", n).replace(",", ".")


def _nombres(texte: str) -> set:
    return {_norm(n) for n in NOMBRE.findall(texte)}


# --------------------------------------------------------------------------- #
# Point d'entrée
# --------------------------------------------------------------------------- #
def afficher():
    runs = _runs()
    if not runs:
        st.info("Lancez un passage (« Démo en direct » ou « Mes documents ») : ses décisions s'expliqueront ici. En attendant, voici la structure du réseau d'agents.")
        reseau_ui.afficher_reseau([], [], [], "")
        return
    st.caption("Ici, rien n'est une boîte noire : on voit la règle de chaque agent, les preuves qu'il a utilisées, le prompt exact et la réponse exacte "
               "de chaque LLM, puis ce que l'agent en a fait — et pourquoi.")
    ids = [r["run_id"] for r in runs]
    if st.session_state.get("rs_run") not in ids:
        st.session_state["rs_run"] = st.session_state.get("run_vu") if st.session_state.get("run_vu") in ids else ids[0]
    rid = st.selectbox("Passage", ids, key="rs_run", label_visibility="collapsed",
                       format_func=lambda r: next(f"{x['titre']} — {x['statut']} — {x['mode']} — {str(x['debut'])[:19]}" for x in runs if x["run_id"] == r))
    evts, traces, appels = _evenements(rid), _traces(rid), _appels(rid)
    _bandeau(evts, traces, appels)
    t0, t1, t2, t3, t4 = st.tabs(["🕸 Réseau de neurones", "🧭 Parcours de décision", "🔍 Lignes classées (A3)", "💬 Échanges avec le LLM", "🛡 Garde-fous"])
    with t0:
        reseau_ui.afficher_reseau(evts, traces, appels, rid)
    with t1:
        _parcours(evts, traces)
    with t2:
        _lignes_a3(traces)
    with t3:
        _echanges(traces)
    with t4:
        _gardes(evts, traces, appels)
