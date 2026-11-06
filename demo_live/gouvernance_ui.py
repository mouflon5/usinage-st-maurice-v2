"""Vue « Gouvernance des données » du poste de démonstration : visuels du socle tresorerie_gouvernance, graphiques et interactifs.

  Vue d'ensemble DAMA               score par domaine du DAMA-DMBOK, plan d'action, rôles et intendance
  Métadonnées, référence, maîtres   dictionnaire, glossaire, traçabilité (graphe des flux), données de référence et données maîtres
  Qualité et couches                score et règles de qualité, quarantaine, restitution (mart) et couches stg / core / mart
  Sécurité et cycle de vie          classification et protection, profilage des tables, fraîcheur des données

Lecture seule sur la base de démo, sauf le bouton « Lancer le contrôle qualité ».
"""
from __future__ import annotations

import os
import sqlite3
import sys

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from demo_live import gouvernance_dama_ui, gouvernance_flux_ui

SECTIONS = ["Vue d'ensemble DAMA", "Métadonnées, référence, maîtres", "Qualité et couches", "Sécurité et cycle de vie", "Modèles de données"]
RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOSSIER_GOUV = os.path.join(RACINE, "tresorerie_gouvernance")
if DOSSIER_GOUV not in sys.path:
    sys.path.insert(0, DOSSIER_GOUV)

VERT, JAUNE, ROUGE, GRIS = "#0ca30c", "#fab219", "#d03b3b", "#8f9aa8"
SENS_COULEURS = {"public": "#1baf7a", "interne": "#2a78d6", "confidentiel": "#eda100", "restreint": "#d03b3b"}
COUCHES_COULEURS = {"stg": "#eda100", "core": "#1baf7a", "dim": "#8f9aa8", "mart": "#eb6834"}
TABLES_REF = ["ref_devise", "ref_banque", "ref_compte_type", "ref_categorie_flux", "ref_type_transaction",
              "ref_format_releve", "ref_statut_rapprochement", "ref_scenario", "ref_mapping_libelle"]
CONFIG = {"displaylogo": False, "modeBarButtonsToRemove": ["lasso2d", "select2d"]}


def _conn(db):
    return sqlite3.connect(db, timeout=10)


def _df(db, sql, params=()):
    c = _conn(db)
    try:
        return pd.read_sql_query(sql, c, params=params)
    except Exception:
        return pd.DataFrame()
    finally:
        c.close()


def _table(df, vide="Aucune donnée pour l'instant."):
    if df.empty:
        st.info(vide)
    else:
        st.dataframe(df, hide_index=True, width="stretch")


def _graphe(fig, hauteur=330, cle=None):
    fig.update_layout(height=hauteur, margin=dict(l=10, r=10, t=30, b=10), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    st.plotly_chart(fig, theme="streamlit", width="stretch", config=CONFIG, key=cle)


def _initialisee(db):
    c = _conn(db)
    try:
        return c.execute("SELECT 1 FROM sqlite_master WHERE name = 'meta_champ'").fetchone() is not None
    finally:
        c.close()


# ------------------------------------------------------------------ Métadonnées, référence, maîtres
def _dictionnaire(db):
    par_table = _df(db, "SELECT table_nom AS table_, COUNT(*) AS champs FROM meta_champ GROUP BY table_nom ORDER BY table_nom")
    if par_table.empty:
        st.info("Dictionnaire vide.")
        return
    detail = _df(db, "SELECT table_nom AS Table_, sensibilite AS Sensibilité, COUNT(*) AS Champs FROM meta_champ GROUP BY table_nom, sensibilite")
    c1, c2 = st.columns([3, 2])
    with c1, st.container(border=True):
        st.markdown("**Champs documentés par sensibilité et par table** (cliquez un bloc pour zoomer)")
        fig = px.treemap(detail, path=[px.Constant("Toutes les tables"), "Sensibilité", "Table_"], values="Champs", color="Sensibilité", color_discrete_map=SENS_COULEURS)
        fig.update_traces(hovertemplate="%{label}<br>%{value} champ(s)<extra></extra>", textinfo="label+value")
        _graphe(fig, 340, "g_dico_tree")
    with c2, st.container(border=True):
        st.markdown("**Répartition par sensibilité**")
        sens = detail.groupby("Sensibilité", as_index=False)["Champs"].sum()
        fig = go.Figure(go.Pie(labels=sens["Sensibilité"], values=sens["Champs"], hole=0.55, marker=dict(colors=[SENS_COULEURS.get(s, GRIS) for s in sens["Sensibilité"]]),
                               hovertemplate="%{label}<br>%{value} champ(s) (%{percent})<extra></extra>"))
        _graphe(fig, 340, "g_dico_pie")

    choix = st.selectbox("Table", ["(toutes)"] + par_table["table_"].tolist(), key="g_dico_table")
    sens = st.multiselect("Sensibilité", ["public", "interne", "confidentiel", "restreint"], key="g_dico_sens")
    q = st.text_input("Rechercher dans les définitions", key="g_dico_q")
    sql = ("SELECT table_nom AS \"Table\", champ_nom AS \"Champ\", type_donnee AS \"Type\", definition_metier AS \"Définition\", "
           "unite AS \"Unité\", regle_validation AS \"Règle de validation\", sensibilite AS \"Sensibilité\" FROM meta_champ WHERE 1=1")
    p = []
    if choix != "(toutes)":
        sql += " AND table_nom = ?"; p.append(choix)
    if sens:
        sql += f" AND sensibilite IN ({','.join('?' * len(sens))})"; p += sens
    if q:
        sql += " AND (definition_metier LIKE ? OR champ_nom LIKE ?)"; p += [f"%{q}%"] * 2
    res = _df(db, sql + " ORDER BY table_nom, champ_id", p)
    st.caption(f"{len(res)} champ(s) affiché(s).")
    _table(res)


def _glossaire(db):
    g = _df(db, "SELECT terme, definition, synonymes, reference FROM meta_glossaire ORDER BY terme")
    if g.empty:
        st.info("Glossaire vide.")
        return
    q = st.text_input("Rechercher un terme, une définition ou un synonyme", key="g_glo_q")
    if q:
        m = g.apply(lambda r: q.lower() in " ".join(str(v) for v in r.values).lower(), axis=1)
        g = g[m]
    st.caption(f"{len(g)} terme(s).")
    cols = st.columns(2)
    for i, r in enumerate(g.itertuples()):
        with cols[i % 2], st.container(border=True):
            st.markdown(f"**{r.terme}**")
            st.write(str(r.definition).replace("$", "\\$"))
            if r.synonymes:
                st.caption("Synonymes : " + str(r.synonymes))
            if r.reference:
                st.caption(f"Voir : `{r.reference}`")


def _tracabilite(db):
    gouvernance_flux_ui.afficher(db)
    st.markdown("##### Exécutions des agents")
    runs = _df(db, "SELECT run_id, agent, debut, fin, statut, parametres_json FROM meta_run ORDER BY debut DESC LIMIT 100")
    if not runs.empty:
        t = runs.dropna(subset=["debut"]).copy()
        t["fin"] = t["fin"].fillna(t["debut"])
        t["debut_dt"], t["fin_dt"] = pd.to_datetime(t["debut"]), pd.to_datetime(t["fin"])
        t["fin_dt"] = t.apply(lambda r: r["fin_dt"] + pd.Timedelta(seconds=20) if r["fin_dt"] <= r["debut_dt"] else r["fin_dt"], axis=1)
        fig = px.timeline(t, x_start="debut_dt", x_end="fin_dt", y="agent", color="statut", hover_name="run_id", hover_data={"debut_dt": False, "fin_dt": False},
                          color_discrete_map={"succes": "#1baf7a", "partiel": "#eda100", "echec": "#d03b3b", "en_cours": "#2a78d6"})
        fig.update_yaxes(title=None)
        _graphe(fig, 240, "g_runs_tl")
        st.caption("Chaque barre est un passage : de son début à sa fin. Survolez-la pour voir son identifiant.")
    _table(runs, "Aucune exécution tracée : lancez un scénario dans « Démo en direct ».")
    st.markdown("##### Fichiers sources (empreinte SHA-256)")
    fic = _df(db, "SELECT fichier_id, nom_fichier, format_code, taille_octets, recu_le, substr(hash_sha256,1,16) || '…' AS empreinte "
                  "FROM meta_fichier_source ORDER BY recu_le DESC LIMIT 100")
    if not fic.empty:
        fig = px.bar(fic.groupby("format_code", as_index=False).agg(fichiers=("fichier_id", "count"), octets=("taille_octets", "sum")), x="format_code", y="fichiers",
                     hover_data={"octets": True}, color_discrete_sequence=["#2a78d6"])
        fig.update_xaxes(title=None)
        _graphe(fig, 200, "g_fic_bar")
    _table(fic, "Aucun fichier enregistré.")


def _reference(db):
    def compte(t: str) -> int:
        d = _df(db, f"SELECT COUNT(*) AS n FROM {t}")
        return int(d["n"].iloc[0]) if not d.empty else 0

    tailles = pd.DataFrame({"Table": TABLES_REF, "Valeurs": [compte(t) for t in TABLES_REF]})
    c1, c2 = st.columns([2, 3])
    with c1, st.container(border=True):
        st.markdown("**Valeurs par table de référence**")
        fig = px.bar(tailles.sort_values("Valeurs"), x="Valeurs", y="Table", orientation="h", color_discrete_sequence=["#6250d6"])
        fig.update_yaxes(title=None)
        _graphe(fig, 320, "g_ref_bar")
    with c2:
        nom = st.selectbox("Table de référence", TABLES_REF, key="g_ref")
        d = _df(db, f"SELECT * FROM {nom}")
        q = st.text_input("Filtrer les valeurs", key="g_ref_q")
        if q and not d.empty:
            d = d[d.apply(lambda r: q.lower() in " ".join(str(v) for v in r.values).lower(), axis=1)]
        st.caption(f"{len(d)} valeur(s).")
        _table(d)
    st.caption("`ref_mapping_libelle` : à enrichir avec vos libellés bancaires pour réduire les mouvements « non classés ».")


def _maitres(db):
    cp = _df(db, "SELECT type_contrepartie AS Type, statut_validation AS Statut, COUNT(*) AS Contreparties FROM mdm_contrepartie WHERE fusionne_vers_id IS NULL "
                 "GROUP BY type_contrepartie, statut_validation")
    cmp_ = _df(db, "SELECT banque_code AS Banque, type_code AS Type, COUNT(*) AS Comptes FROM mdm_compte GROUP BY banque_code, type_code")
    c1, c2 = st.columns(2)
    with c1, st.container(border=True):
        st.markdown("**Contreparties par type et statut de validation** (cliquez pour zoomer)")
        if cp.empty:
            st.info("Aucune contrepartie : elles apparaissent au chargement des relevés.")
        else:
            fig = px.sunburst(cp, path=["Type", "Statut"], values="Contreparties", color="Statut",
                              color_discrete_map={"a_valider": "#eda100", "valide": "#1baf7a", "rejete": "#d03b3b"})
            fig.update_traces(hovertemplate="%{label}<br>%{value} contrepartie(s)<extra></extra>")
            _graphe(fig, 320, "g_mdm_sun")
    with c2, st.container(border=True):
        st.markdown("**Comptes par banque**")
        if cmp_.empty:
            st.info("Aucun compte.")
        else:
            fig = px.bar(cmp_, x="Banque", y="Comptes", color="Type", color_discrete_sequence=["#2a78d6", "#1baf7a", "#eb6834", "#6250d6"])
            _graphe(fig, 320, "g_mdm_bar")
    m1, m2 = st.columns(2)
    with m1:
        st.markdown("**Comptes** (numéro masqué, jamais en clair)")
        _table(_df(db, "SELECT compte_id, banque_code, type_code, devise_code, numero_masque, libelle, actif FROM mdm_compte"))
        st.markdown("**Entités juridiques**")
        _table(_df(db, "SELECT entite_id, nom_legal, devise_code, actif FROM mdm_entite_juridique"))
    with m2:
        st.markdown("**Contreparties**")
        _table(_df(db, "SELECT p.contrepartie_id AS id, p.nom_canonique, p.type_contrepartie, p.statut_validation, "
                       "(SELECT COUNT(*) FROM mdm_contrepartie_alias a WHERE a.contrepartie_id = p.contrepartie_id) AS alias "
                       "FROM mdm_contrepartie p WHERE p.fusionne_vers_id IS NULL ORDER BY p.statut_validation, p.nom_canonique LIMIT 300"),
               "Aucune contrepartie : elles apparaissent au chargement des relevés.")


def metadonnees(db):
    st.caption("Ce que veulent dire les données, d'où elles viennent et quelles valeurs sont permises.")
    n_champ = _df(db, "SELECT COUNT(*) n, SUM(sensibilite IN ('confidentiel','restreint')) s FROM meta_champ")
    n_tab = _df(db, "SELECT COUNT(DISTINCT table_nom) n FROM meta_champ")
    run = _df(db, "SELECT COUNT(*) n FROM meta_run")
    fic = _df(db, "SELECT COUNT(*) n FROM meta_fichier_source")
    a, b, c, d, e = st.columns(5)
    a.metric("Champs documentés", int(n_champ["n"][0]) if not n_champ.empty else 0, border=True)
    b.metric("Tables et vues", int(n_tab["n"][0]) if not n_tab.empty else 0, border=True)
    c.metric("Champs sensibles", int(n_champ["s"][0] or 0) if not n_champ.empty else 0, border=True)
    d.metric("Exécutions tracées", int(run["n"][0]) if not run.empty else 0, border=True)
    e.metric("Fichiers sources", int(fic["n"][0]) if not fic.empty else 0, border=True)

    t1, t2, t3, t4, t5 = st.tabs(["📖 Dictionnaire", "🗂 Glossaire", "🔗 Traçabilité", "🏷 Référence", "👥 Données maîtres"])
    with t1:
        _dictionnaire(db)
    with t2:
        _glossaire(db)
    with t3:
        _tracabilite(db)
    with t4:
        _reference(db)
    with t5:
        _maitres(db)


# ------------------------------------------------------------------ Qualité et couches
def _lancer_dq(db):
    import dq_runner
    c = _conn(db)
    try:
        c.execute("PRAGMA foreign_keys = ON")
        dq_runner.charger_regles(c)
        c.commit()
        return dq_runner.executer(c)
    finally:
        c.close()


def _jauge(score: float) -> go.Figure:
    return go.Figure(go.Indicator(mode="gauge+number", value=score, number=dict(suffix=" %", valueformat=".1f"),
                                  gauge=dict(axis=dict(range=[0, 100]), bar=dict(color="#2a78d6"),
                                             steps=[dict(range=[0, 80], color="rgba(208,59,59,0.35)"), dict(range=[80, 95], color="rgba(250,178,25,0.35)"),
                                                    dict(range=[95, 100], color="rgba(12,163,12,0.35)")],
                                             threshold=dict(line=dict(color="#d03b3b", width=3), value=95))))


def qualite(db):
    st.caption("Les données sont-elles fiables ? Règles de qualité, mouvements en quarantaine et vues de restitution.")
    if st.button("▶ Lancer le contrôle qualité maintenant", key="g_dq_go",
                 help="Exécute les 14 règles sur tous les mouvements. Les mouvements qui échouent une règle bloquante passent en quarantaine."):
        try:
            r = _lancer_dq(db)
            st.toast(f"Contrôle terminé : score {r['score_global']} %")
        except Exception as ex:
            st.error(f"Contrôle impossible : {ex}")

    ex = _df(db, "SELECT * FROM dq_execution ORDER BY rowid DESC LIMIT 1")
    nb_mouv = _df(db, "SELECT COUNT(*) n, SUM(statut_dq='quarantaine') q, SUM(statut_dq='avertissement') w FROM core_mouvement")
    g, rest = st.columns([2, 3])
    with g, st.container(border=True):
        st.markdown("**Score qualité global**")
        if ex.empty:
            st.info("Aucun contrôle n'a encore été exécuté : cliquez sur le bouton ci-dessus ou lancez un scénario.")
        else:
            _graphe(_jauge(float(ex["score_global"][0])), 210, "g_dq_jauge")
            st.caption("Rouge sous 80 %, jaune de 80 à 95 %, vert au-delà ; trait rouge : seuil de 95 %.")
    with rest:
        a, b = st.columns(2)
        c, d = st.columns(2)
        if not ex.empty:
            a.metric("Règles évaluées", int(ex["nb_regles"][0]), border=True)
            b.metric("Règles en échec", int(ex["nb_echecs"][0]), delta=f"{int(ex['nb_bloquants_echec'][0])} bloquante(s)", delta_color="inverse", border=True)
        c.metric("Mouvements", int(nb_mouv["n"][0] or 0) if not nb_mouv.empty else 0, border=True)
        d.metric("En quarantaine", int(nb_mouv["q"][0] or 0) if not nb_mouv.empty else 0,
                 delta=f"{int(nb_mouv['w'][0] or 0)} avertissement(s)" if not nb_mouv.empty else None, delta_color="off", border=True)

    t1, t2, t3, t4 = st.tabs(["✅ Règles", "🚫 Quarantaine", "📊 Restitution (mart)", "🧱 Couches"])
    with t1:
        _regles(db)
    with t2:
        _quarantaine(db)
    with t3:
        gouvernance_dama_ui.restitution(db)
    with t4:
        _couches(db)


def _regles(db):
    res = _df(db, "SELECT dimension AS \"Dimension\", regle_id AS \"Règle\", nom AS \"Description\", severite AS \"Sévérité\", "
                  "nb_evalue AS \"Évalués\", nb_violation AS \"Violations\", score_pct AS \"Score %\", statut AS \"Statut\" "
                  "FROM mart_dq_derniere_execution ORDER BY dimension, regle_id")
    if res.empty:
        _table(_df(db, "SELECT dimension AS \"Dimension\", regle_id AS \"Règle\", nom AS \"Description\", severite AS \"Sévérité\", seuil_pct AS \"Seuil %\" "
                       "FROM dq_regle WHERE actif = 1 ORDER BY dimension, regle_id"))
    else:
        c1, c2 = st.columns(2)
        with c1, st.container(border=True):
            st.markdown("**Score de chaque règle** (survolez pour le détail)")
            r = res.copy()
            r["Couleur"] = r["Statut"].map({"pass": "Réussie", "fail": "En échec"})
            fig = px.bar(r.sort_values("Score %"), x="Score %", y="Règle", orientation="h", color="Couleur", hover_data=["Description", "Évalués", "Violations", "Dimension"],
                         color_discrete_map={"Réussie": "#1baf7a", "En échec": "#d03b3b"})
            fig.update_xaxes(range=[0, 100])
            fig.update_yaxes(title=None)
            _graphe(fig, 380, "g_dq_regles")
        with c2, st.container(border=True):
            st.markdown("**Score moyen par dimension (DAMA)**")
            dim = _df(db, "SELECT dimension, ROUND(AVG(score_pct),1) AS score FROM mart_dq_derniere_execution WHERE severite <> 'info' GROUP BY dimension")
            if len(dim) >= 3:
                fig = go.Figure(go.Scatterpolar(r=dim["score"].tolist() + dim["score"].tolist()[:1], theta=dim["dimension"].tolist() + dim["dimension"].tolist()[:1], fill="toself",
                                                line=dict(color="#2a78d6"), hovertemplate="%{theta} : %{r} %<extra></extra>"))
                fig.update_layout(polar=dict(radialaxis=dict(range=[0, 100])))
            else:
                fig = px.bar(dim, x="score", y="dimension", orientation="h", color_discrete_sequence=["#2a78d6"])
            _graphe(fig, 380, "g_dq_dim")
        res["Statut"] = res["Statut"].map({"pass": "✅ réussi", "fail": "❌ échec"})
        _table(res)
    hist = _df(db, "SELECT execute_le, score_global FROM dq_execution ORDER BY rowid")
    if len(hist) > 1:
        with st.container(border=True):
            st.markdown("**Tendance du score**")
            fig = go.Figure(go.Scatter(x=hist["execute_le"], y=hist["score_global"], mode="lines+markers", line=dict(color="#2a78d6"),
                                       hovertemplate="%{x}<br>score %{y:.1f} %<extra></extra>"))
            fig.update_yaxes(range=[max(0, float(hist["score_global"].min()) - 5), 100], title="Score %")
            _graphe(fig, 240, "g_dq_hist")


def _quarantaine(db):
    st.caption("Éléments à examiner. Un mouvement en quarantaine est exclu des vues de rapport.")
    rej = _df(db, "SELECT rejet_id, regle_id, motif, table_source, cle_source, rejete_le, statut_traitement, payload_json FROM stg_rejet ORDER BY rejet_id DESC LIMIT 200")
    if not rej.empty:
        c1, c2 = st.columns(2)
        with c1, st.container(border=True):
            st.markdown("**Rejets par règle**")
            fig = px.bar(rej.groupby("regle_id", as_index=False).size().rename(columns={"size": "rejets"}), x="regle_id", y="rejets", color_discrete_sequence=["#d03b3b"])
            fig.update_xaxes(title=None)
            _graphe(fig, 250, "g_rej_regle")
        with c2, st.container(border=True):
            st.markdown("**Rejets par table et statut de traitement**")
            fig = px.sunburst(rej.assign(n=1), path=["table_source", "statut_traitement"], values="n", color_discrete_sequence=["#eda100", "#d03b3b", "#6250d6"])
            _graphe(fig, 250, "g_rej_sun")
    _table(rej, "Rien en quarantaine.")
    st.markdown("**Contreparties à valider**")
    _table(_df(db, "SELECT * FROM mart_contreparties_a_valider ORDER BY nb_mouvements DESC LIMIT 100"), "Aucune contrepartie en attente.")


def _couches(db):
    st.markdown("**Volumétrie par couche** : `stg` (texte brut) → `core` (normalisé) → `mart` (restitution)")
    vol = []
    for couche, tbl in [("stg", "stg_releve_ligne"), ("stg", "stg_rejet"), ("core", "core_mouvement"), ("core", "core_solde_releve"), ("core", "core_prevision"),
                        ("dim", "dim_date"), ("mart", "mart_flux_mensuel"), ("mart", "mart_mouvement_quotidien")]:
        n = _df(db, f"SELECT COUNT(*) AS n FROM {tbl}")
        vol.append({"Couche": couche, "Table": tbl, "Lignes": int(n["n"][0]) if not n.empty else None})
    v = pd.DataFrame(vol)
    c1, c2 = st.columns([3, 2])
    with c1, st.container(border=True):
        fig = px.bar(v.dropna().sort_values("Lignes"), x="Lignes", y="Table", orientation="h", color="Couche", color_discrete_map=COUCHES_COULEURS, log_x=True)
        fig.update_yaxes(title=None)
        fig.update_xaxes(title="Lignes (échelle logarithmique)")
        _graphe(fig, 320, "g_couches_bar")
    with c2, st.container(border=True):
        par_couche = v.groupby("Couche", as_index=False)["Lignes"].sum()
        fig = go.Figure(go.Pie(labels=par_couche["Couche"], values=par_couche["Lignes"], hole=0.5, marker=dict(colors=[COUCHES_COULEURS.get(c, GRIS) for c in par_couche["Couche"]]),
                               hovertemplate="%{label}<br>%{value} ligne(s) (%{percent})<extra></extra>"))
        _graphe(fig, 320, "g_couches_pie")
    st.caption("Le chemin détaillé d'une ligne, du fichier au rapport, est dans « Traçabilité ».")
    _table(v)
    st.markdown("**Derniers mouvements (`core_mouvement`)**")
    _table(_df(db, "SELECT mouvement_id, date_operation, libelle_normalise, montant_cents/100.0 AS montant, categorie_code, "
                   "statut_dq, run_id FROM core_mouvement ORDER BY mouvement_id DESC LIMIT 100"), "Aucun mouvement chargé.")


# ------------------------------------------------------------------ Entrée
def afficher(db):
    if not os.path.isfile(db) or not _initialisee(db):
        st.warning("Le socle de gouvernance n'est pas initialisé sur cette base. Lancez "
                   "`python tresorerie_gouvernance/init_db.py --db <base>` puis « Remettre à zéro ».")
        return
    v = st.radio("Section", SECTIONS, horizontal=True, key="g_vague", label_visibility="collapsed")
    if v == SECTIONS[0]:
        gouvernance_dama_ui.vue_ensemble(db)
    elif v == SECTIONS[1]:
        metadonnees(db)
    elif v == SECTIONS[2]:
        qualite(db)
    elif v == SECTIONS[4]:
        from demo_live import gouvernance_modeles_ui
        from demo_live import rag
        racine = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        gouvernance_modeles_ui.afficher(db, racine, (db, rag.INDEX))
    else:
        gouvernance_dama_ui.securite_cycle(db)
