"""Gouvernance des données selon le DAMA-DMBOK : tableau de bord par domaine, rôles et intendance, sécurité, profilage, fraîcheur, restitution.

Le DAMA-DMBOK découpe la gestion des données en domaines (gouvernance, métadonnées, qualité, données de référence et maîtres, sécurité,
architecture et intégration, entreposage et BI, cycle de vie). Cette page mesure chacun avec des indicateurs calculés dans la base, les compare à
une cible, signale les écarts et propose l'action à mener. Aucune donnée n'est inventée : un indicateur sans données reste vide.
"""
from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

PREFIXES = ("meta_", "ref_", "mdm_", "dq_", "stg_", "core_", "dim_", "mart_")
DOMAINES = ["Gouvernance", "Métadonnées", "Qualité", "Référence et maîtres", "Sécurité", "Architecture et intégration", "Entreposage et BI", "Cycle de vie"]
VERT, JAUNE, ROUGE, GRIS, BLEU = "#1baf7a", "#eda100", "#d03b3b", "#8f9aa8", "#2a78d6"
CONFIG = {"displaylogo": False, "modeBarButtonsToRemove": ["lasso2d", "select2d"]}


# --------------------------------------------------------------------------- #
# Lecture de la base
# --------------------------------------------------------------------------- #
def _df(db: str, sql: str, params=()) -> pd.DataFrame:
    c = sqlite3.connect(db, timeout=10)
    try:
        return pd.read_sql_query(sql, c, params=params)
    except Exception:                                                       # noqa: BLE001
        return pd.DataFrame()
    finally:
        c.close()


def _v(db: str, sql: str, params=()) -> float | None:
    d = _df(db, sql, params)
    if d.empty:
        return None
    x = d.iloc[0, 0]
    return None if x is None or pd.isna(x) else float(x)


def _age_jours(db: str, sql: str) -> float | None:
    """Jours écoulés depuis la date renvoyée par `sql` (UTC)."""
    d = _df(db, sql)
    if d.empty or d.iloc[0, 0] is None:
        return None
    t = pd.to_datetime(d.iloc[0, 0], errors="coerce")
    if pd.isna(t):
        return None
    return max((datetime.now(timezone.utc).replace(tzinfo=None) - t.to_pydatetime()).total_seconds() / 86400, 0.0)


def _graphe(fig: go.Figure, hauteur: int = 320, cle: str | None = None, **kw):
    fig.update_layout(height=hauteur, margin=dict(l=10, r=10, t=30, b=10), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    return st.plotly_chart(fig, theme="streamlit", width="stretch", config=CONFIG, key=cle, **kw)


# --------------------------------------------------------------------------- #
# Indicateurs par domaine
# --------------------------------------------------------------------------- #
def indicateurs(db: str) -> pd.DataFrame:
    """Un indicateur par ligne : domaine, valeur, cible, score 0-100 (100 = cible atteinte), détail et recommandation."""
    lignes: list[dict] = []

    def ajouter(domaine, nom, valeur, cible, unite, detail, reco, sens="max"):
        if valeur is None or not cible:
            score = None
        elif sens == "max":
            score = min(valeur / cible, 1.0) * 100
        else:                                                               # « moins c'est mieux » (jours, retards)
            score = 100.0 if valeur <= cible else max(0.0, cible / valeur * 100)
        lignes.append({"Domaine": domaine, "Indicateur": nom, "Valeur": valeur, "Cible": cible, "Unité": unite, "Score": score, "Détail": detail, "Recommandation": reco, "Sens": sens})

    pct = lambda sql: _v(db, sql)
    # Gouvernance : qui répond de quoi
    ajouter("Gouvernance", "Champs avec propriétaire désigné", pct("SELECT 100.0*SUM(proprietaire IS NOT NULL AND proprietaire <> '')/COUNT(*) FROM meta_champ"), 100, "%",
            "Chaque champ du dictionnaire a un rôle responsable de sa qualité et de ses changements.", "Désigner un propriétaire pour chaque champ sans responsable.")
    roles = _v(db, "SELECT COUNT(DISTINCT proprietaire) FROM meta_champ WHERE proprietaire IS NOT NULL")
    ajouter("Gouvernance", "Rôles distincts (propriétaire et intendant)", None if roles is None else min(roles / 2, 1) * 100, 100, "%",
            f"{int(roles or 0)} rôle(s) distincts : le DAMA recommande de séparer le propriétaire (décide) de l'intendant (applique).",
            "Distinguer le rôle de propriétaire de celui d'intendant des données.")
    # Métadonnées
    ajouter("Métadonnées", "Champs documentés", pct("SELECT 100.0*SUM(definition_metier NOT LIKE 'À DOCUMENTER%')/COUNT(*) FROM meta_champ"), 100, "%",
            "Part des champs avec une définition métier.", "Compléter descriptions_champs.py pour chaque colonne marquée « À DOCUMENTER ».")
    ajouter("Métadonnées", "Champs avec règle de validation", pct("SELECT 100.0*SUM(regle_validation IS NOT NULL AND regle_validation <> '')/COUNT(*) FROM meta_champ"), 40, "%",
            "Une règle écrite (domaine de valeurs, format, unicité) rend le champ contrôlable.", "Écrire la règle de validation des champs clés (montants, dates, codes).")
    ajouter("Métadonnées", "Champs avec exemple", pct("SELECT 100.0*SUM(exemple IS NOT NULL AND exemple <> '')/COUNT(*) FROM meta_champ"), 40, "%",
            "Un exemple de valeur aide les utilisateurs métier à lire le dictionnaire.", "Ajouter un exemple aux champs les plus consultés.")
    objets = _v(db, "SELECT COUNT(*) FROM sqlite_master WHERE type IN ('table','view') AND (" + " OR ".join(f"name LIKE '{p}%'" for p in PREFIXES) + ")")
    docs = _v(db, "SELECT COUNT(DISTINCT table_nom) FROM meta_champ")
    ajouter("Métadonnées", "Tables et vues décrites", None if not objets or docs is None else min(docs / objets, 1) * 100, 100, "%",
            f"{int(docs or 0)} objet(s) décrits sur {int(objets or 0)} dans le schéma.", "Décrire les tables et vues non couvertes par le dictionnaire.")
    # Qualité
    sc = _v(db, "SELECT score_global FROM dq_execution ORDER BY rowid DESC LIMIT 1")
    ajouter("Qualité", "Score du dernier contrôle", sc, 95, "%", "Score global pondéré des règles évaluées sur tous les mouvements.", "Corriger les règles bloquantes en échec (onglet Qualité > Règles).")
    ajouter("Qualité", "Règles actives évaluées",
            pct("SELECT 100.0*COUNT(DISTINCT r.regle_id)/NULLIF((SELECT COUNT(*) FROM dq_regle WHERE actif = 1), 0) FROM dq_resultat r "
                "WHERE r.execution_id = (SELECT execution_id FROM dq_execution ORDER BY rowid DESC LIMIT 1)"), 100, "%",
            "Chaque règle active doit avoir été évaluée au dernier contrôle.", "Relancer le contrôle qualité : des règles actives n'ont pas de résultat.")
    ajouter("Qualité", "Mouvements hors quarantaine", pct("SELECT 100.0*SUM(statut_dq <> 'quarantaine')/COUNT(*) FROM core_mouvement"), 90, "%",
            "Part des mouvements acceptés par les règles bloquantes.", "Traiter la quarantaine : corriger la source ou documenter l'exception.")
    rej = _v(db, "SELECT COUNT(*) FROM stg_rejet")
    ajouter("Qualité", "Rejets traités", None if not rej else pct("SELECT 100.0*SUM(statut_traitement NOT IN ('a_revoir','a_traiter'))/COUNT(*) FROM stg_rejet"), 80, "%",
            f"{int(rej or 0)} rejet(s) au journal des problèmes ; ceux qui restent « à revoir » attendent une décision.",
            "Traiter les rejets : corriger, accepter avec justification ou rejeter définitivement.")
    # Référence et maîtres
    ajouter("Référence et maîtres", "Contreparties validées",
            pct("SELECT 100.0*SUM(statut_validation = 'valide')/NULLIF(COUNT(*), 0) FROM mdm_contrepartie WHERE actif = 1 AND fusionne_vers_id IS NULL"), 80, "%",
            "Une contrepartie créée automatiquement est « à valider » tant qu'un intendant ne l'a pas confirmée.", "Valider les contreparties à forte activité (file d'intendance).")
    ajouter("Référence et maîtres", "Mouvements classés au plan de trésorerie", pct("SELECT 100.0*SUM(categorie_code <> 'NON_CLASSE')/COUNT(*) FROM core_mouvement"), 85, "%",
            "Part des mouvements rattachés à une catégorie du plan (ref_categorie_flux).", "Enrichir ref_mapping_libelle avec les libellés bancaires récurrents.")
    ajouter("Référence et maîtres", "Contreparties avec alias",
            pct("SELECT 100.0*SUM(EXISTS(SELECT 1 FROM mdm_contrepartie_alias a WHERE a.contrepartie_id = p.contrepartie_id))/NULLIF(COUNT(*), 0) FROM mdm_contrepartie p WHERE actif = 1"),
            100, "%", "Les alias rattachent les libellés bruts à la contrepartie maître.", "Rattacher chaque contrepartie à au moins un libellé source.")
    # Sécurité
    ajouter("Sécurité", "Champs classifiés", pct("SELECT 100.0*SUM(sensibilite IS NOT NULL AND sensibilite <> '')/COUNT(*) FROM meta_champ"), 100, "%",
            "Chaque champ porte un niveau : public, interne, confidentiel ou restreint.", "Classifier les champs sans niveau de sensibilité.")
    ajouter("Sécurité", "Champs sensibles avec propriétaire",
            pct("SELECT 100.0*SUM(proprietaire IS NOT NULL AND proprietaire <> '')/NULLIF(COUNT(*), 0) FROM meta_champ WHERE sensibilite IN ('confidentiel','restreint')"), 100, "%",
            "Les champs confidentiels et restreints doivent avoir un responsable de leur protection.", "Désigner un propriétaire pour chaque champ sensible.")
    ajouter("Sécurité", "Numéros de compte masqués et hachés",
            pct("SELECT 100.0*SUM(numero_masque LIKE '****%' AND numero_hash IS NOT NULL AND numero_hash <> '')/NULLIF(COUNT(*), 0) FROM mdm_compte"), 100, "%",
            "Le numéro complet n'est jamais stocké : seuls les quatre derniers chiffres et une empreinte salée le sont.", "Masquer et hacher les numéros de compte non protégés.")
    # Architecture et intégration (traçabilité)
    ajouter("Architecture et intégration", "Mouvements traçables jusqu'au fichier",
            pct("SELECT 100.0*SUM(run_id IS NOT NULL AND fichier_id IS NOT NULL AND stg_id IS NOT NULL)/COUNT(*) FROM core_mouvement"), 100, "%",
            "Chaque mouvement garde le passage, le fichier source et la ligne d'arrivée dont il vient.", "Reporter run_id, fichier_id et stg_id à chaque chargement.")
    ajouter("Architecture et intégration", "Lignes d'arrivée liées à un fichier", pct("SELECT 100.0*SUM(fichier_id IS NOT NULL)/COUNT(*) FROM stg_releve_ligne"), 100, "%",
            "La zone d'arrivée conserve la provenance brute de chaque ligne.", "Enregistrer le fichier source avant d'écrire dans la zone d'arrivée.")
    ajouter("Architecture et intégration", "Passages clôturés", pct("SELECT 100.0*SUM(fin IS NOT NULL)/COUNT(*) FROM meta_run"), 100, "%",
            "Un passage sans fin est un traitement interrompu ou non tracé.", "Clôturer ou purger les passages restés ouverts.")
    # Entreposage et BI
    attendu = _v(db, "SELECT COUNT(*) FROM core_mouvement WHERE statut_dq <> 'quarantaine'")
    obs = _v(db, "SELECT SUM(nb_mouvements) FROM mart_mouvement_quotidien")
    ajouter("Entreposage et BI", "Réconciliation noyau → restitution", None if not attendu or obs is None else min(obs, attendu) / max(obs, attendu) * 100, 100, "%",
            f"{int(obs or 0)} mouvement(s) dans la restitution pour {int(attendu or 0)} attendus (hors quarantaine).", "Rechercher les mouvements perdus entre le noyau et les vues de restitution.")
    marts = _df(db, "SELECT name FROM sqlite_master WHERE type='view' AND name LIKE 'mart_%'")
    ok_marts = sum(1 for n in marts["name"] if _v(db, f"SELECT COUNT(*) FROM {n}") is not None) if not marts.empty else 0
    ajouter("Entreposage et BI", "Vues de restitution lisibles", None if marts.empty else ok_marts / len(marts) * 100, 100, "%",
            f"{ok_marts} vue(s) lisible(s) sur {len(marts)}.", "Corriger les vues de restitution en erreur.")
    # Cycle de vie
    ajouter("Cycle de vie", "Jours depuis le dernier chargement", _age_jours(db, "SELECT MAX(cree_le) FROM core_mouvement"), 7, "jours",
            "Un chargement ancien rend la restitution périmée.", "Charger les relevés récents.", sens="min")
    ajouter("Cycle de vie", "Jours depuis les derniers prix de marché", _age_jours(db, "SELECT MAX(date_obs) FROM core_prix_marche WHERE serie_code = 'PALUMUSDM'"), 62, "jours",
            "Les séries de marché (mensuelles) alimentent la projection du prix des métaux.", "Mettre à jour depuis FRED (Prix des métaux > Historique et données).", sens="min")
    ajouter("Cycle de vie", "Versions de schéma suivies", None if _v(db, "SELECT COUNT(*) FROM meta_version_schema") is None else min(_v(db, "SELECT COUNT(*) FROM meta_version_schema"), 1) * 100, 100, "%",
            "Chaque évolution du schéma est datée et décrite.", "Inscrire la version du schéma dans meta_version_schema.")
    return pd.DataFrame(lignes)


def _rag(score) -> str:
    if score is None or pd.isna(score):
        return "⚪"
    return "🟢" if score >= 90 else ("🟡" if score >= 60 else "🔴")


def _selection_radar() -> str | None:
    etat = st.session_state.get("g_dama_radar") or {}
    pts = (etat.get("selection") or {}).get("points") if isinstance(etat, dict) else None
    for p in pts or []:
        if p.get("curve_number") == 1 and p.get("point_index") is not None:
            return DOMAINES[p["point_index"] % len(DOMAINES)]
    return None


# --------------------------------------------------------------------------- #
# Vue d'ensemble
# --------------------------------------------------------------------------- #
def vue_ensemble(db: str) -> None:
    ind = indicateurs(db)
    st.caption("Tableau de bord de la gouvernance par domaine du DAMA-DMBOK. Chaque score compare un indicateur calculé dans la base à sa cible : "
               "100 = cible atteinte. Cliquez un sommet du radar ou choisissez un domaine pour voir ses indicateurs.")
    par_dom = ind.groupby("Domaine", sort=False)["Score"].mean().reindex(DOMAINES)
    global_ = float(par_dom.dropna().mean()) if par_dom.notna().any() else None
    a, b, c, d = st.columns(4)
    a.metric("Score global", f"{global_:.0f} / 100" if global_ is not None else "—", border=True, help="Moyenne des scores des huit domaines.")
    d_bas = ind[ind["Score"] < 60]
    b.metric("Indicateurs sous 60", len(d_bas), border=True, help="Écarts importants à la cible.")
    c.metric("Indicateurs à la cible", int((ind["Score"] >= 99.5).sum()), delta=f"sur {int(ind['Score'].notna().sum())}", delta_color="off", border=True)
    faible = par_dom.dropna().idxmin() if par_dom.notna().any() else None
    d.metric("Domaine le plus faible", faible or "—", delta=f"{par_dom[faible]:.0f} / 100" if faible else None, delta_color="off", border=True)

    sel_radar = _selection_radar()
    if sel_radar and sel_radar != st.session_state.get("g_dama_vu"):
        st.session_state["g_dama_vu"] = sel_radar
        st.session_state["g_dama_dom"] = sel_radar
    c1, c2 = st.columns([2, 3])
    with c1, st.container(border=True):
        st.markdown("**Roue du DAMA** (100 = cible atteinte)")
        vals = [0 if pd.isna(x) else float(x) for x in par_dom]
        fig = go.Figure()
        fig.add_trace(go.Scatterpolar(r=[100] * (len(DOMAINES) + 1), theta=DOMAINES + DOMAINES[:1], mode="lines", line=dict(color=GRIS, dash="dot"), hoverinfo="skip", name="Cible"))
        fig.add_trace(go.Scatterpolar(r=vals + vals[:1], theta=DOMAINES + DOMAINES[:1], fill="toself", mode="lines+markers", name="Score", line=dict(color=BLEU),
                                      marker=dict(size=9), fillcolor="rgba(42,120,214,0.25)", hovertemplate="%{theta}<br>score %{r:.0f} / 100<extra></extra>"))
        fig.update_layout(polar=dict(radialaxis=dict(range=[0, 100], tickvals=[25, 50, 75, 100])), showlegend=False, clickmode="event+select")
        _graphe(fig, 400, "g_dama_radar", on_select="rerun", selection_mode="points")
    with c2, st.container(border=True):
        st.markdown("**Score par domaine**")
        tab = pd.DataFrame({"Domaine": DOMAINES, "Score": [None if pd.isna(x) else float(x) for x in par_dom]}).dropna()
        tab["Statut"] = tab["Score"].map(lambda s: "À la cible" if s >= 90 else ("À améliorer" if s >= 60 else "Écart important"))
        fig = px.bar(tab.sort_values("Score"), x="Score", y="Domaine", orientation="h", color="Statut",
                     color_discrete_map={"À la cible": VERT, "À améliorer": JAUNE, "Écart important": ROUGE}, range_x=[0, 100])
        fig.update_yaxes(title=None)
        _graphe(fig, 400, "g_dama_bar")

    choix = st.selectbox("Domaine", ["(tous)"] + DOMAINES, key="g_dama_dom")
    vue = ind if choix == "(tous)" else ind[ind["Domaine"] == choix]
    aff = vue.assign(Statut=vue["Score"].map(_rag), Valeur_=vue.apply(lambda r: "—" if pd.isna(r["Valeur"]) else (f"{r['Valeur']:.1f} {r['Unité']}"), axis=1),
                     Cible_=vue.apply(lambda r: f"{'≤' if r['Sens'] == 'min' else '≥'} {r['Cible']:.0f} {r['Unité']}", axis=1))
    st.dataframe(aff[["Statut", "Domaine", "Indicateur", "Valeur_", "Cible_", "Score", "Détail", "Recommandation"]].rename(columns={"Valeur_": "Valeur", "Cible_": "Cible"}),
                 hide_index=True, width="stretch",
                 column_config={"Score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100, format="%.0f"), "Statut": st.column_config.TextColumn(width="small")})

    with st.container(border=True):
        st.markdown("**Plan d'action prioritaire** : les cinq plus grands écarts à la cible")
        pri = ind.dropna(subset=["Score"]).sort_values("Score").head(5)
        for r in pri.itertuples():
            if r.Score >= 99.5:
                continue
            st.markdown(f"- {_rag(r.Score)} **{r.Domaine} · {r.Indicateur}** ({r.Score:.0f} / 100) : {r.Recommandation}".replace("$", "\\$"))
        if (pri["Score"] >= 99.5).all():
            st.success("Tous les indicateurs sont à la cible.")
    roles_intendance(db)


# --------------------------------------------------------------------------- #
# Rôles et intendance
# --------------------------------------------------------------------------- #
def roles_intendance(db: str) -> None:
    st.subheader("Rôles et intendance")
    st.caption("Qui répond de quelles données, et ce qui attend une décision d'un intendant.")
    meta = _df(db, "SELECT table_nom, proprietaire, definition_metier FROM meta_champ")
    if not meta.empty:
        meta["Couche"] = meta["table_nom"].map(lambda t: next((p.rstrip("_") for p in PREFIXES if t.startswith(p)), "autre"))
        c1, c2 = st.columns([3, 2])
        with c1, st.container(border=True):
            st.markdown("**Champs par propriétaire, par couche et par table** (cliquez pour zoomer)")
            groupes = meta.fillna({"proprietaire": "(non désigné)"}).groupby(["proprietaire", "Couche", "table_nom"], as_index=False).size().rename(columns={"size": "champs"})
            fig = px.sunburst(groupes, path=["proprietaire", "Couche", "table_nom"], values="champs", color="proprietaire", color_discrete_sequence=[BLEU, "#6250d6", JAUNE])
            fig.update_traces(hovertemplate="%{label}<br>%{value} champ(s)<extra></extra>")
            _graphe(fig, 380, "g_roles_sun")
        with c2, st.container(border=True):
            st.markdown("**Charge d'intendance** (décisions en attente)")
            file_ = pd.DataFrame({
                "File": ["Contreparties à valider", "Rejets à revoir", "Mouvements non classés"],
                "Éléments": [_v(db, "SELECT COUNT(*) FROM mart_contreparties_a_valider") or 0, _v(db, "SELECT COUNT(*) FROM stg_rejet WHERE statut_traitement IN ('a_revoir','a_traiter')") or 0,
                             _v(db, "SELECT COUNT(*) FROM core_mouvement WHERE categorie_code = 'NON_CLASSE'") or 0]})
            fig = px.bar(file_, x="Éléments", y="File", orientation="h", color_discrete_sequence=[JAUNE])
            fig.update_yaxes(title=None)
            _graphe(fig, 200, "g_roles_bar")
            st.caption("Les contreparties se valident dans « Métadonnées, référence, maîtres > Données maîtres », les rejets dans « Qualité et couches > Quarantaine ».")
    try:
        import dictionnaire
        cadre = pd.DataFrame([{"Couche": p.rstrip("_"), "Propriétaire": dictionnaire.PROPRIETAIRES.get(p, ""), "Alimentée par": dictionnaire.SOURCES.get(p, ""),
                               "Champs": int((meta["Couche"] == p.rstrip("_")).sum()) if not meta.empty else 0} for p in PREFIXES])
        st.markdown("**Cadre de responsabilités par couche**")
        st.dataframe(cadre, hide_index=True, width="stretch")
    except Exception:                                                       # noqa: BLE001
        pass


# --------------------------------------------------------------------------- #
# Sécurité et cycle de vie
# --------------------------------------------------------------------------- #
def securite_cycle(db: str) -> None:
    st.caption("Protéger les données (classification, masquage), savoir ce qu'elles contiennent (profilage) et vérifier qu'elles sont à jour (fraîcheur).")
    t1, t2, t3 = st.tabs(["🔒 Sécurité et confidentialité", "🔍 Profilage", "⏱ Fraîcheur"])
    with t1:
        _securite(db)
    with t2:
        _profilage(db)
    with t3:
        _fraicheur(db)


def _securite(db: str) -> None:
    cls = _df(db, "SELECT table_nom AS Table_, sensibilite AS Sensibilité, COUNT(*) AS Champs FROM meta_champ GROUP BY table_nom, sensibilite")
    sensibles = _df(db, "SELECT table_nom AS \"Table\", champ_nom AS \"Champ\", sensibilite AS \"Sensibilité\", definition_metier AS \"Définition\", regle_validation AS \"Règle de validation\", "
                        "proprietaire AS \"Propriétaire\" FROM meta_champ WHERE sensibilite IN ('confidentiel','restreint') ORDER BY sensibilite DESC, table_nom, champ_id")
    n_tot = int(cls["Champs"].sum()) if not cls.empty else 0
    a, b, c, d = st.columns(4)
    for col, niveau in zip((a, b, c, d), ("public", "interne", "confidentiel", "restreint")):
        n = int(cls.loc[cls["Sensibilité"] == niveau, "Champs"].sum()) if not cls.empty else 0
        col.metric(niveau.capitalize(), n, delta=f"{n / n_tot * 100:.0f} % des champs" if n_tot else None, delta_color="off", border=True)
    c1, c2 = st.columns([3, 2])
    with c1, st.container(border=True):
        st.markdown("**Où se trouvent les champs sensibles** (survolez une case)")
        if cls.empty:
            st.info("Dictionnaire vide.")
        else:
            piv = cls.pivot_table(index="Table_", columns="Sensibilité", values="Champs", aggfunc="sum").fillna(0)
            for niveau in ("public", "interne", "confidentiel", "restreint"):
                if niveau not in piv:
                    piv[niveau] = 0
            piv = piv[["public", "interne", "confidentiel", "restreint"]]
            piv["sens"] = piv["confidentiel"] + piv["restreint"]
            piv = piv.sort_values(["sens", "interne"], ascending=False).head(18).drop(columns="sens")
            fig = go.Figure(go.Heatmap(z=piv.to_numpy(), x=piv.columns.tolist(), y=piv.index.tolist(), colorscale=[[0, "rgba(137,135,129,0.08)"], [1, "#d03b3b"]],
                                       hovertemplate="%{y}<br>%{x} : %{z} champ(s)<extra></extra>", showscale=False, text=piv.to_numpy(), texttemplate="%{text}"))
            fig.update_yaxes(autorange="reversed", title=None)
            _graphe(fig, 480, "g_sec_heat")
    with c2, st.container(border=True):
        st.markdown("**Contrôles de protection**")
        nb_compte = _v(db, "SELECT COUNT(*) FROM mdm_compte") or 0
        libre = _v(db, "SELECT COUNT(*) FROM mdm_compte WHERE libelle GLOB '*[0-9][0-9][0-9][0-9][0-9][0-9]*'") or 0
        controles = [
            ("Numéros de compte masqués (****NNNN)", nb_compte and (_v(db, "SELECT COUNT(*) FROM mdm_compte WHERE numero_masque LIKE '****%'") or 0) == nb_compte, f"{int(nb_compte)} compte(s)"),
            ("Empreinte salée du numéro présente", nb_compte and (_v(db, "SELECT COUNT(*) FROM mdm_compte WHERE numero_hash IS NOT NULL AND numero_hash <> ''") or 0) == nb_compte, "numero_hash"),
            ("Aucun numéro de compte en clair dans le libellé du compte", libre == 0, f"{int(libre)} libellé(s) contiennent six chiffres ou plus : vérifiez qu'il ne s'agit pas du numéro complet" if libre else "libellés sans numéro complet"),
            ("Tous les champs sont classifiés", (_v(db, "SELECT COUNT(*) FROM meta_champ WHERE sensibilite IS NULL OR sensibilite = ''") or 0) == 0, "meta_champ.sensibilite"),
            ("Champs sensibles avec propriétaire", (_v(db, "SELECT COUNT(*) FROM meta_champ WHERE sensibilite IN ('confidentiel','restreint') AND (proprietaire IS NULL OR proprietaire = '')") or 0) == 0, "meta_champ.proprietaire"),
        ]
        for libelle, ok, detail in controles:
            (st.success if ok else st.warning)(f"{libelle}  \n{detail}", icon=":material/check_circle:" if ok else ":material/warning:")
    with st.container(border=True):
        st.markdown("**Champs confidentiels et restreints**")
        q = st.text_input("Filtrer", key="g_sec_q", placeholder="table, champ ou mot de la définition")
        s = sensibles if not q else sensibles[sensibles.apply(lambda r: q.lower() in " ".join(str(v) for v in r.values).lower(), axis=1)]
        st.caption(f"{len(s)} champ(s).")
        st.dataframe(s, hide_index=True, width="stretch")


@st.cache_data(show_spinner=False, ttl=30)
def _profil(db: str, table: str) -> tuple[pd.DataFrame, int]:
    """Profil d'une table : (une ligne par colonne, nombre de lignes)."""
    c = sqlite3.connect(db, timeout=10)
    try:
        cols = [r[1] for r in c.execute(f'PRAGMA table_info("{table}")')]
        if not cols:
            return pd.DataFrame(), 0
        sel = ", ".join(f'COUNT("{k}"), COUNT(DISTINCT "{k}")' for k in cols)
        ligne = c.execute(f'SELECT COUNT(*), {sel} FROM "{table}"').fetchone()
    finally:
        c.close()
    n = ligne[0]
    out = [{"Colonne": k, "Renseignées": ligne[1 + 2 * i], "Distinctes": ligne[2 + 2 * i], "Complétude (%)": 100.0 * ligne[1 + 2 * i] / n if n else None,
            "Unicité (%)": 100.0 * ligne[2 + 2 * i] / ligne[1 + 2 * i] if ligne[1 + 2 * i] else None} for i, k in enumerate(cols)]
    return pd.DataFrame(out), n


def _profilage(db: str) -> None:
    tables = _df(db, "SELECT name FROM sqlite_master WHERE type='table' AND (" + " OR ".join(f"name LIKE '{p}%'" for p in PREFIXES) + ") ORDER BY name")["name"].tolist()
    if not tables:
        st.info("Aucune table à profiler.")
        return
    st.caption("Le profilage mesure, colonne par colonne, ce qui est réellement renseigné et la variété des valeurs : c'est la base des règles de qualité.")
    t = st.selectbox("Table", tables, index=tables.index("core_mouvement") if "core_mouvement" in tables else 0, key="g_prof_table")
    p, n = _profil(db, t)
    if p.empty:
        st.info("Table vide ou illisible.")
        return
    vides = p[p["Complétude (%)"] < 50]
    a, b, c = st.columns(3)
    a.metric("Lignes", f"{n:,}".replace(",", " "), border=True)
    b.metric("Colonnes", len(p), border=True)
    c.metric("Colonnes à moins de 50 % renseignées", len(vides), border=True)
    with st.container(border=True):
        st.markdown("**Complétude par colonne** (survolez pour le détail)")
        fig = px.bar(p, x="Complétude (%)", y="Colonne", orientation="h", color="Complétude (%)", color_continuous_scale=["#d03b3b", "#eda100", "#1baf7a"], range_color=[0, 100],
                     hover_data={"Renseignées": True, "Distinctes": True, "Unicité (%)": ":.0f"})
        fig.update_yaxes(autorange="reversed", title=None)
        fig.update_xaxes(range=[0, 100])
        fig.update_coloraxes(showscale=False)
        _graphe(fig, max(240, 22 * len(p) + 60), "g_prof_bar")
    st.dataframe(p, hide_index=True, width="stretch", column_config={
        "Complétude (%)": st.column_config.ProgressColumn("Complétude (%)", min_value=0, max_value=100, format="%.0f"),
        "Unicité (%)": st.column_config.ProgressColumn("Unicité (%)", min_value=0, max_value=100, format="%.0f")})


def _fraicheur(db: str) -> None:
    sources = [("stg_releve_ligne", "Zone d'arrivée (lignes lues)", "SELECT MAX(cree_le) FROM stg_releve_ligne", 7),
               ("core_mouvement", "Noyau (mouvements)", "SELECT MAX(cree_le) FROM core_mouvement", 7),
               ("meta_run", "Dernier passage d'un agent", "SELECT MAX(debut) FROM meta_run", 7),
               ("dq_execution", "Dernier contrôle qualité", "SELECT MAX(execute_le) FROM dq_execution", 7),
               ("mdm_contrepartie", "Données maîtres (contreparties)", "SELECT MAX(cree_le) FROM mdm_contrepartie", 30),
               ("core_prix_marche", "Prix de marché (aluminium)", "SELECT MAX(date_obs) FROM core_prix_marche WHERE serie_code = 'PALUMUSDM'", 62),
               ("meta_champ", "Dictionnaire de données", "SELECT MAX(maj_le) FROM meta_champ", 30)]
    lignes = []
    for table, libelle, sql, seuil in sources:
        age = _age_jours(db, sql)
        lignes.append({"Jeu de données": libelle, "Table": table, "Âge (jours)": age, "Seuil (jours)": seuil,
                       "Statut": "—" if age is None else ("À jour" if age <= seuil else ("À rafraîchir" if age <= 3 * seuil else "Périmé"))})
    df = pd.DataFrame(lignes)
    st.caption("Fraîcheur = temps écoulé depuis la dernière écriture. Les seuils sont ceux de la qualité « actualité » du DAMA : 7 jours pour les données de l'exploitation, 30 jours pour les référentiels.")
    with st.container(border=True):
        d = df.dropna(subset=["Âge (jours)"])
        fig = px.bar(d.sort_values("Âge (jours)"), x="Âge (jours)", y="Jeu de données", orientation="h", color="Statut",
                     color_discrete_map={"À jour": VERT, "À rafraîchir": JAUNE, "Périmé": ROUGE}, hover_data=["Table", "Seuil (jours)"])
        for i, (_, r) in enumerate(d.sort_values("Âge (jours)").iterrows()):
            fig.add_shape(type="line", x0=r["Seuil (jours)"], x1=r["Seuil (jours)"], y0=i - 0.4, y1=i + 0.4, line=dict(color=GRIS, dash="dot"))
        fig.update_yaxes(title=None)
        _graphe(fig, 320, "g_fraich_bar")
        st.caption("Trait pointillé : seuil de chaque jeu de données.")
    st.dataframe(df, hide_index=True, width="stretch", column_config={"Âge (jours)": st.column_config.NumberColumn(format="%.1f")})


# --------------------------------------------------------------------------- #
# Restitution (mart)
# --------------------------------------------------------------------------- #
def restitution(db: str) -> None:
    st.caption("La restitution (couche « mart ») sert les écrans et les rapports. Ce qui compte pour la gouvernance : d'où viennent ces vues, ce qu'elles filtrent, "
               "si elles réconcilient avec le noyau et si elles sont fiables. Les montants et les flux de trésorerie sont dans « Trésorerie » et « États financiers ».")
    vues = _df(db, "SELECT name, sql FROM sqlite_master WHERE type='view' AND name LIKE 'mart_%' ORDER BY name")
    if vues.empty:
        st.info("Aucune vue de restitution.")
        return
    lignes = []
    for r in vues.itertuples():
        sql = " ".join(str(r.sql).split())
        sources = sorted(set(re.findall(r"(?:FROM|JOIN)\s+([a-z_]+)", sql)) - {r.name})
        n = _v(db, f"SELECT COUNT(*) FROM {r.name}")
        ncol = len(_df(db, f"PRAGMA table_info({r.name})"))
        doc = _v(db, "SELECT 100.0*SUM(definition_metier NOT LIKE 'À DOCUMENTER%')/COUNT(*) FROM meta_champ WHERE table_nom = ?", (r.name,))
        lignes.append({"Vue": r.name, "Lignes": n, "Colonnes": ncol, "Alimentée par": ", ".join(sources), "Exclut la quarantaine": "oui" if "statut_dq <> 'quarantaine'" in sql else "—",
                       "Exclut les transferts internes": "oui" if "TRF_INTERNE" in sql else "—", "Documentée (%)": doc})
    cat = pd.DataFrame(lignes)
    with st.container(border=True):
        st.markdown("**Catalogue des vues de restitution**")
        st.dataframe(cat, hide_index=True, width="stretch", column_config={"Documentée (%)": st.column_config.ProgressColumn("Documentée (%)", min_value=0, max_value=100, format="%.0f"),
                                                                           "Lignes": st.column_config.NumberColumn(format="%d")})

    total = _v(db, "SELECT COUNT(*) FROM core_mouvement") or 0
    hors_q = _v(db, "SELECT COUNT(*) FROM core_mouvement WHERE statut_dq <> 'quarantaine'") or 0
    dans_mart = _v(db, "SELECT SUM(nb_mouvements) FROM mart_mouvement_quotidien") or 0
    classes = _v(db, "SELECT COUNT(*) FROM core_mouvement WHERE statut_dq <> 'quarantaine' AND categorie_code <> 'NON_CLASSE'") or 0
    fiables = _v(db, "SELECT COUNT(*) FROM core_mouvement m JOIN mdm_contrepartie p ON p.contrepartie_id = m.contrepartie_id WHERE m.statut_dq <> 'quarantaine' "
                     "AND m.categorie_code <> 'NON_CLASSE' AND p.statut_validation = 'valide'") or 0
    c1, c2 = st.columns(2)
    with c1, st.container(border=True):
        st.markdown("**Réconciliation noyau → restitution**")
        ok = int(dans_mart) == int(hors_q)
        (st.success if ok else st.error)(f"{int(dans_mart)} mouvement(s) dans la restitution quotidienne pour {int(hors_q)} attendus (hors quarantaine) : "
                                          + ("la restitution est complète." if ok else "des mouvements manquent ou sont en trop."))
        st.caption(f"{int(total - hors_q)} mouvement(s) en quarantaine sont volontairement exclus.")
    with c2, st.container(border=True):
        st.markdown("**Entonnoir de fiabilité des mouvements** (survolez une étape)")
        fig = go.Figure(go.Funnel(y=["Mouvements du noyau", "Hors quarantaine", "Classés au plan", "Contrepartie validée"], x=[total, hors_q, classes, fiables],
                                  marker=dict(color=[BLEU, VERT, JAUNE, "#6250d6"]), textinfo="value+percent initial",
                                  hovertemplate="%{y}<br>%{x} mouvement(s)<extra></extra>"))
        _graphe(fig, 260, "g_rest_fun")
    par_mois = _df(db, "SELECT substr(date_operation, 1, 7) AS mois, statut_dq AS statut, COUNT(*) AS mouvements FROM core_mouvement GROUP BY 1, 2 ORDER BY 1")
    if not par_mois.empty:
        with st.container(border=True):
            st.markdown("**Couverture de la restitution par mois** : mouvements retenus et exclus (cliquez la légende pour filtrer)")
            fig = px.bar(par_mois, x="mois", y="mouvements", color="statut", color_discrete_map={"ok": VERT, "avertissement": JAUNE, "quarantaine": ROUGE})
            fig.update_xaxes(title=None, type="category")
            _graphe(fig, 280, "g_rest_mois")
    cp = _df(db, "SELECT nom_canonique AS contrepartie, nb_mouvements, nb_alias FROM mart_contreparties_a_valider ORDER BY nb_mouvements DESC LIMIT 15")
    if not cp.empty:
        with st.container(border=True):
            st.markdown("**File d'intendance : contreparties à valider par activité** (les premières ont le plus d'effet sur la restitution)")
            fig = px.bar(cp.sort_values("nb_mouvements"), x="nb_mouvements", y="contrepartie", orientation="h", color_discrete_sequence=[JAUNE], hover_data=["nb_alias"])
            fig.update_yaxes(title=None)
            _graphe(fig, 380, "g_rest_cp")
