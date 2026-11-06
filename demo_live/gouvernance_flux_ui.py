"""Traçabilité : graphe interactif des flux de données, du relevé bancaire jusqu'aux écrans qui les consomment.

Deux vues de la même chaîne :
  Graphe des flux   chaque élément (fichiers, agents, tables, écrans) est un nœud ; cliquer un nœud met en évidence tout ce qui l'alimente
                    (amont) et tout ce qu'il alimente (aval), puis affiche son détail : volumétrie, voisins, colonnes, aperçu des lignes,
                    règles de qualité qui le visent. Les boutons « amont » et « aval » permettent de naviguer de proche en proche.
  Volumes (Sankey)  combien de lignes passent de l'étape à l'autre : fichiers → zone d'arrivée → noyau → quarantaine ou restitution.
Un passage (run) peut être choisi pour ne voir que ce qu'il a produit ; les volumes sont lus dans la base de démonstration.
"""
from __future__ import annotations

import sqlite3
import textwrap

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

COUCHES = {
    "source": ("Sources", "#8f9aa8"), "traitement": ("Traitements (agents et moteurs)", "#2a78d6"), "stg": ("Zone d'arrivée (stg)", "#eda100"),
    "core": ("Noyau (core et journal)", "#1baf7a"), "ref": ("Références et données maîtres", "#6250d6"),
    "mart": ("Restitution (mart)", "#eb6834"), "usage": ("Écrans et rapports", "#e87ba4"),
}
# tables filtrables par passage (colonne run_id)
RUN_TABLES = {"stg_releve_ligne", "core_mouvement", "stg_rejet", "meta_fichier_source", "core_solde_releve", "core_prevision"}

# id: (libellé, couche, x, y, table ou None, description)
NOEUDS = {
    "fich": ("Relevés bancaires", "source", 0, 4.0, "meta_fichier_source", "PDF, CSV ou Excel déposés par l'utilisateur. Chaque fichier est enregistré avec son empreinte SHA-256 (un fichier déjà vu est reconnu)."),
    "fred": ("Séries de marché (FRED)", "source", 0, 0.5, "core_prix_marche", "Aluminium, nickel, cuivre, acier, minerai de fer, zinc et change : importés dans la base, une ligne par série et par date."),
    "a1": ("A1 Acquisition", "traitement", 1, 4.0, None, "Trouve les relevés du compte, détecte les mois manquants et trace chaque fichier (meta_fichier_source)."),
    "a2": ("A2 Extraction", "traitement", 2, 4.0, None, "Lit les documents, extrait les opérations et rejoue la continuité des soldes."),
    "stg": ("stg_releve_ligne", "stg", 3, 4.0, "stg_releve_ligne", "Zone d'arrivée : les lignes des relevés, en texte brut, telles que lues."),
    "sol": ("core_solde_releve", "core", 3, 6.2, "core_solde_releve", "Soldes de début et de fin lus sur les relevés, pour les contrôles de continuité."),
    "ref": ("ref_* (références)", "ref", 3, 1.6, "ref_categorie_flux", "Valeurs permises : banques, devises, catégories de flux, formats, statuts, règles de libellés."),
    "a3": ("A3 Classement et chargement", "traitement", 4, 4.0, None, "Écarte les doublons, classe chaque ligne (règles, puis LLM pour le résidu) et charge le noyau et le journal."),
    "mdm": ("mdm_* (données maîtres)", "ref", 4, 1.6, "mdm_contrepartie", "Comptes, entités et contreparties dédoublonnées (golden records)."),
    "core": ("core_mouvement", "core", 5, 4.9, "core_mouvement", "Mouvements normalisés : un par opération, avec catégorie, contrepartie et statut de qualité."),
    "jg": ("journal_general", "core", 5, 3.0, "journal_general", "Journal des écritures classées : la base des prévisions, des écarts, des états financiers et du tableau de trésorerie."),
    "prix": ("core_prix_marche", "core", 5, 0.5, "core_prix_marche", "Historique des prix de marché (métaux, change)."),
    "dq": ("Moteur qualité (14 règles)", "traitement", 5, 6.4, None, "Évalue les règles de qualité sur les mouvements : score, échecs, quarantaine."),
    "rej": ("stg_rejet (quarantaine)", "stg", 6, 6.4, "stg_rejet", "Éléments qui échouent une règle bloquante : exclus des rapports jusqu'à examen."),
    "a4": ("A4 Prévision", "traitement", 6, 3.3, None, "Prévoit encaissements et décaissements (SARIMAX) à partir du journal."),
    "a5": ("A5 Écarts", "traitement", 6, 2.2, None, "Compare réel, budget et prévision et explique les écarts."),
    "a6": ("A6 Contrôle", "traitement", 6, 4.4, None, "Onze contrôles indépendants : approuve, approuve avec réserves ou bloque."),
    "mart": ("mart_* (restitution)", "mart", 7, 5.6, "mart_flux_mensuel", "Vues de restitution : flux mensuels, mouvements quotidiens, contreparties à valider, dernière exécution qualité."),
    "a7": ("A7 Rapports", "traitement", 7, 3.0, None, "Produit le classeur Excel et le brouillon du rapport mensuel R0."),
    "tab": ("Tableau de trésorerie", "usage", 8, 4.2, None, "Le tableau de bord HTML (R0 à R8), recalculé depuis le journal."),
    "rap": ("Rapports des agents et R0", "usage", 8, 3.0, None, "Rapports par agent, rapport mensuel et classeur Excel."),
    "eta": ("États financiers", "usage", 8, 1.9, None, "Résultats, bilan et flux de trésorerie pro forma construits depuis le journal."),
    "ess": ("Prix des métaux", "usage", 8, 0.5, None, "Projection du prix de l'acier et de l'aluminium, du prix d'achat et de l'effet sur la trésorerie."),
    "gouv": ("Écrans de gouvernance", "usage", 8, 5.9, None, "Dictionnaire, qualité, quarantaine et restitution affichés dans cette page."),
}
ARETES = [
    ("fich", "a1"), ("a1", "a2"), ("a2", "stg"), ("a2", "sol"), ("stg", "a3"), ("ref", "a3"), ("a3", "core"), ("a3", "jg"), ("a3", "mdm"), ("mdm", "core"),
    ("core", "dq"), ("dq", "rej"), ("core", "mart"), ("mdm", "mart"), ("dq", "mart"), ("fred", "prix"),
    ("jg", "a4"), ("jg", "a5"), ("jg", "a6"), ("sol", "a6"), ("a4", "a7"), ("a5", "a7"), ("a6", "a7"), ("jg", "tab"), ("jg", "eta"), ("a7", "rap"),
    ("prix", "ess"), ("jg", "ess"), ("mart", "gouv"), ("rej", "gouv"),
]
LIENS = {"fich": "Une ligne par fichier", "stg": "Une ligne par opération lue"}


# --------------------------------------------------------------------------- #
# Lecture de la base
# --------------------------------------------------------------------------- #
def _df(db: str, sql: str, params=()) -> pd.DataFrame:
    c = sqlite3.connect(db, timeout=10)
    try:
        return pd.read_sql_query(sql, c, params=params)
    except Exception:                                                     # noqa: BLE001
        return pd.DataFrame()
    finally:
        c.close()


def _n(db: str, sql: str, params=()) -> int:
    d = _df(db, sql, params)
    return int(d.iloc[0, 0] or 0) if not d.empty else 0


def compter(db: str, noeud: str, run: str | None) -> int | None:
    """Nombre de lignes d'un nœud de données (None pour un agent ou un écran)."""
    table = NOEUDS[noeud][4]
    if not table:
        return None
    if noeud == "mart":
        return sum(_n(db, f"SELECT COUNT(*) FROM {t}") for t in ("mart_flux_mensuel", "mart_mouvement_quotidien", "mart_contreparties_a_valider"))
    if noeud == "ref":
        return sum(_n(db, f"SELECT COUNT(*) FROM {t}") for t in ("ref_devise", "ref_banque", "ref_compte_type", "ref_categorie_flux", "ref_type_transaction",
                                                                  "ref_format_releve", "ref_statut_rapprochement", "ref_scenario", "ref_mapping_libelle"))
    if noeud == "mdm":
        return sum(_n(db, f"SELECT COUNT(*) FROM {t}") for t in ("mdm_contrepartie", "mdm_compte", "mdm_entite_juridique"))
    if run and table in RUN_TABLES:
        return _n(db, f"SELECT COUNT(*) FROM {table} WHERE run_id = ?", (run,))
    return _n(db, f"SELECT COUNT(*) FROM {table}")


@st.cache_data(show_spinner=False, ttl=15)
def volumes(db: str, run: str | None) -> dict:
    """Volumes lus dans la base : lignes par nœud et ventilations utilisées par le Sankey."""
    f = " WHERE run_id = ?" if run else ""
    p = (run,) if run else ()
    d = {k: compter(db, k, run) for k, v in NOEUDS.items() if v[4]}
    d["stg_promues"] = _n(db, "SELECT COUNT(*) FROM core_mouvement m JOIN stg_releve_ligne s ON s.stg_id = m.stg_id" + (" WHERE m.run_id = ?" if run else ""), p)
    d["statuts"] = {r.statut_dq: int(r.n) for r in _df(db, "SELECT statut_dq, COUNT(*) AS n FROM core_mouvement" + f + " GROUP BY statut_dq", p).itertuples()}
    d["rejets_core"] = _n(db, "SELECT COUNT(*) FROM stg_rejet WHERE table_source = 'core_mouvement'" + (" AND run_id = ?" if run else ""), p)
    d["runs"] = _n(db, "SELECT COUNT(*) FROM meta_run" + (" WHERE run_id = ?" if run else ""), p)
    return d


def passages(db: str) -> pd.DataFrame:
    """Un passage par ligne, avec ses volumes (fichiers, lignes lues, mouvements, rejets)."""
    return _df(db, "SELECT r.run_id AS passage, r.statut, substr(r.debut, 1, 16) AS début, "
                   "(SELECT COUNT(*) FROM meta_fichier_source x WHERE x.run_id = r.run_id) AS fichiers, "
                   "(SELECT COUNT(*) FROM stg_releve_ligne x WHERE x.run_id = r.run_id) AS lignes_lues, "
                   "(SELECT COUNT(*) FROM core_mouvement x WHERE x.run_id = r.run_id) AS mouvements, "
                   "(SELECT COUNT(*) FROM stg_rejet x WHERE x.run_id = r.run_id) AS rejets "
                   "FROM meta_run r ORDER BY r.debut DESC LIMIT 50")


# --------------------------------------------------------------------------- #
# Graphe des flux
# --------------------------------------------------------------------------- #
def amont_aval(noeud: str | None) -> tuple[set[str], set[str]]:
    """Tout ce qui alimente un nœud (amont) et tout ce qu'il alimente (aval), de proche en proche."""
    if not noeud:
        return set(), set()

    def parcourir(depart: str, vers_amont: bool) -> set[str]:
        vus, pile = set(), [depart]
        while pile:
            courant = pile.pop()
            for a, b in ARETES:
                src, dst = (b, a) if vers_amont else (a, b)
                if src == courant and dst not in vus:
                    vus.add(dst)
                    pile.append(dst)
        return vus

    return parcourir(noeud, True), parcourir(noeud, False)


def _rgba(hexa: str, alpha: float) -> str:
    return f"rgba({int(hexa[1:3], 16)},{int(hexa[3:5], 16)},{int(hexa[5:7], 16)},{alpha})"


def _figure_graphe(vol: dict, sel: str | None) -> go.Figure:
    amont, aval = amont_aval(sel)
    actifs = ({sel} | amont | aval) if sel else set(NOEUDS)
    ids = list(NOEUDS)

    def fort(a: str, b: str) -> bool:
        """Arête du chemin amont ou aval du nœud choisi."""
        return bool(sel) and (a in amont | {sel} and b in amont | {sel} or a in aval | {sel} and b in aval | {sel})

    fig = go.Figure()
    for hi in (False, True):                                    # courbes 0 (arêtes atténuées) et 1 (arêtes en évidence)
        xs, ys = [], []
        for a, b in ARETES:
            if fort(a, b) == hi:
                xs += [NOEUDS[a][2], NOEUDS[b][2], None]
                ys += [NOEUDS[a][3], NOEUDS[b][3], None]
        fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines", hoverinfo="skip", showlegend=False,
                                 line=dict(width=3 if hi else 1.4, color="#e87ba4" if hi else "rgba(137,135,129,0.55)")))
    for a, b in ARETES:
        xa, ya, xb, yb = NOEUDS[a][2], NOEUDS[a][3], NOEUDS[b][2], NOEUDS[b][3]
        fig.add_annotation(x=xa + (xb - xa) * 0.82, y=ya + (yb - ya) * 0.82, ax=xa + (xb - xa) * 0.62, ay=ya + (yb - ya) * 0.62, xref="x", yref="y", axref="x", ayref="y",
                           showarrow=True, arrowhead=3, arrowsize=1.1, arrowwidth=2.2 if fort(a, b) else 1.2,
                           arrowcolor="#e87ba4" if fort(a, b) else "rgba(137,135,129,0.7)")
    textes, tailles, couleurs, survol, positions = [], [], [], [], []
    for i in ids:
        lib, couche, x, y, table, desc = NOEUDS[i]
        n = vol.get(i)
        nb = f"{n:,}".replace(",", " ") if n is not None else None
        textes.append("<br>".join(textwrap.wrap(lib, 14)) + (f"<br><b>{nb}</b>" if nb else ""))
        positions.append("top center" if int(x) % 2 == 0 else "bottom center")           # les colonnes voisines alternent pour que les libellés ne se chevauchent pas
        tailles.append(30 if table else 24)
        couleurs.append(_rgba(COUCHES[couche][1], 1.0 if i in actifs else 0.2))     # l'atténuation passe par la couleur : la sélection ne la défait pas
        survol.append(f"<b>{lib}</b><br>{COUCHES[couche][0]}" + (f"<br>{nb} ligne(s)" if nb else "") + "<br>" + (desc[:110] + "…" if len(desc) > 110 else desc))
    fig.add_trace(go.Scatter(                                   # courbe 2 : les nœuds (lue par _selection_plotly)
        x=[NOEUDS[i][2] for i in ids], y=[NOEUDS[i][3] for i in ids], mode="markers+text", text=textes, textposition=positions, textfont=dict(size=10),
        marker=dict(size=tailles, color=couleurs, opacity=1, symbol=["square" if NOEUDS[i][4] else "circle" for i in ids],
                    line=dict(width=[4 if i == sel else 1 for i in ids], color=["#e87ba4" if i == sel else "rgba(255,255,255,0.6)" for i in ids])),
        hovertext=survol, hoverinfo="text", showlegend=False, selected=dict(marker=dict(opacity=1)), unselected=dict(marker=dict(opacity=1))))
    for code, (nom, col) in COUCHES.items():                                  # légende des couches
        fig.add_trace(go.Scatter(x=[None], y=[None], mode="markers", marker=dict(size=10, color=col), name=nom, hoverinfo="skip"))
    fig.update_layout(height=700, margin=dict(l=10, r=10, t=30, b=10), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", dragmode="pan",
                      legend=dict(orientation="h", y=1.06, x=0), xaxis=dict(visible=False, range=[-0.6, 8.7]), yaxis=dict(visible=False, range=[7.4, -0.9]),
                      clickmode="event+select")
    return fig


def _selection_plotly() -> str | None:
    """Nœud cliqué dans le graphe (état du composant lu avant de le redessiner)."""
    etat = st.session_state.get("g_flux_graphe") or {}
    pts = (etat.get("selection") or {}).get("points") if isinstance(etat, dict) else None
    ids = list(NOEUDS)
    for p in pts or []:
        if p.get("curve_number") == 2 and 0 <= p.get("point_index", -1) < len(ids):
            return ids[p["point_index"]]
    return None


def _aller(noeud: str) -> None:
    st.session_state["g_flux_sel"] = noeud


def _detail(db: str, noeud: str, vol: dict, run: str | None) -> None:
    lib, couche, _, _, table, desc = NOEUDS[noeud]
    amont, aval = amont_aval(noeud)
    directs_amont = [a for a, b in ARETES if b == noeud]
    directs_aval = [b for a, b in ARETES if a == noeud]
    with st.container(border=True):
        st.markdown(f"#### {lib}")
        st.caption(f"{COUCHES[couche][0]} · {desc}".replace("$", "\\$"))
        a, b, c = st.columns(3)
        n = vol.get(noeud)
        a.metric("Lignes", f"{n:,}".replace(",", " ") if n is not None else "—", border=True)
        b.metric("Éléments en amont", len(amont), border=True)
        c.metric("Éléments en aval", len(aval), border=True)
        x, y = st.columns(2)
        with x:
            st.markdown("**Alimenté par**")
            for i in directs_amont or [None]:
                if i:
                    st.button(f"← {NOEUDS[i][0]}", key=f"g_amont_{noeud}_{i}", on_click=_aller, args=(i,), width="stretch")
                else:
                    st.caption("Source de données : rien en amont.")
        with y:
            st.markdown("**Alimente**")
            for i in directs_aval or [None]:
                if i:
                    st.button(f"{NOEUDS[i][0]} →", key=f"g_aval_{noeud}_{i}", on_click=_aller, args=(i,), width="stretch")
                else:
                    st.caption("Fin de chaîne : rien en aval.")
        if table and noeud not in ("mart", "ref", "mdm"):
            cols = _df(db, "SELECT champ_nom AS Champ, definition_metier AS Définition, sensibilite AS Sensibilité FROM meta_champ WHERE table_nom = ? ORDER BY champ_id", (table,))
            apercu = _df(db, f"SELECT * FROM {table}" + (" WHERE run_id = ?" if run and table in RUN_TABLES else "") + " LIMIT 8", (run,) if run and table in RUN_TABLES else ())
            t1, t2, t3 = st.tabs(["Aperçu des lignes", "Colonnes documentées", "Règles de qualité"])
            with t1:
                st.dataframe(apercu, hide_index=True, width="stretch") if not apercu.empty else st.caption("Aucune ligne.")
            with t2:
                st.dataframe(cols, hide_index=True, width="stretch") if not cols.empty else st.caption("Table non documentée dans le dictionnaire.")
            with t3:
                regles = _df(db, "SELECT regle_id AS Règle, nom AS Description, dimension AS Dimension, severite AS Sévérité FROM dq_regle WHERE cible_table = ? AND actif = 1", (table,))
                st.dataframe(regles, hide_index=True, width="stretch") if not regles.empty else st.caption("Aucune règle de qualité ne vise directement cette table.")
        elif noeud in ("mart", "ref", "mdm"):
            groupes = {"mart": ["mart_flux_mensuel", "mart_mouvement_quotidien", "mart_contreparties_a_valider", "mart_dq_derniere_execution"],
                       "ref": ["ref_devise", "ref_banque", "ref_compte_type", "ref_categorie_flux", "ref_type_transaction", "ref_format_releve", "ref_statut_rapprochement", "ref_scenario", "ref_mapping_libelle"],
                       "mdm": ["mdm_entite_juridique", "mdm_compte", "mdm_contrepartie", "mdm_contrepartie_alias"]}[noeud]
            st.dataframe(pd.DataFrame({"Table": groupes, "Lignes": [_n(db, f"SELECT COUNT(*) FROM {t}") for t in groupes]}), hide_index=True, width="stretch")
        elif noeud in ("a1", "a2", "a3", "a4", "a5", "a6", "a7", "dq"):
            r = _df(db, "SELECT run_id AS Passage, statut AS Statut, substr(debut,1,19) AS Début, substr(fin,1,19) AS Fin FROM meta_run ORDER BY debut DESC LIMIT 6")
            st.caption("Derniers passages tracés (chaque agent reçoit le run_id du passage et le reporte sur ses écritures) :")
            st.dataframe(r, hide_index=True, width="stretch") if not r.empty else st.caption("Aucun passage tracé.")


# --------------------------------------------------------------------------- #
# Sankey
# --------------------------------------------------------------------------- #
def _figure_sankey(vol: dict) -> go.Figure | None:
    st_ = vol["statuts"]
    n_core, n_stg, n_fich = vol.get("core", 0) or 0, vol.get("stg", 0) or 0, vol.get("fich", 0) or 0
    prom = min(vol["stg_promues"], n_stg)
    ok, av, qu = st_.get("ok", 0), st_.get("avertissement", 0), st_.get("quarantaine", 0)
    noeuds = ["Fichiers reçus", "stg_releve_ligne (lignes lues)", "core_mouvement (promus)", "Non promus (doublons, hors période)", "Statut qualité : ok",
              "Statut qualité : avertissement", "Statut qualité : quarantaine", "Vues de restitution (mart)", "stg_rejet (quarantaine)"]
    liens = [(0, 1, n_stg, "lignes lues dans les fichiers"), (1, 2, prom, "lignes promues au noyau"), (1, 3, max(n_stg - prom, 0), "lignes non promues"),
             (2, 4, ok, "conformes"), (2, 5, av, "avec avertissement"), (2, 6, qu, "en quarantaine"), (4, 7, ok, "vers la restitution"),
             (5, 7, av, "vers la restitution"), (6, 8, qu, "mis de côté")]
    liens = [l for l in liens if l[2] > 0]
    if not liens:
        return None
    total = max(n_stg, 1)
    couleurs = ["#8f9aa8", "#eda100", "#1baf7a", "#b3a794", "#1baf7a", "#eda100", "#d03b3b", "#eb6834", "#d03b3b"]
    fig = go.Figure(go.Sankey(
        arrangement="snap", node=dict(label=[f"{n}" for n in noeuds], color=couleurs, pad=34, thickness=18, line=dict(color="rgba(0,0,0,0.2)", width=0.5)),
        link=dict(source=[l[0] for l in liens], target=[l[1] for l in liens], value=[l[2] for l in liens], label=[l[3] for l in liens],
                  color=[f"rgba({int(couleurs[l[1]][1:3], 16)},{int(couleurs[l[1]][3:5], 16)},{int(couleurs[l[1]][5:7], 16)},0.35)" for l in liens],
                  customdata=[f"{l[2] / total * 100:.0f} % des lignes lues" for l in liens],
                  hovertemplate="%{label}<br>%{value} ligne(s)<br>%{customdata}<extra></extra>")))
    fig.update_layout(height=520, margin=dict(l=10, r=10, t=10, b=10), paper_bgcolor="rgba(0,0,0,0)", font=dict(size=12))
    return fig


# --------------------------------------------------------------------------- #
# Entrée
# --------------------------------------------------------------------------- #
def afficher(db: str) -> None:
    passes = passages(db)
    st.markdown("##### Flux des données")
    st.caption("Du relevé bancaire aux écrans : cliquez un nœud du graphe pour voir ce qui l'alimente et ce qu'il alimente, ou choisissez un passage "
               "pour ne voir que ce qu'il a produit.")
    a, b = st.columns([3, 2])
    vue = a.segmented_control("Vue", ["Graphe des flux", "Volumes (Sankey)"], default="Graphe des flux", key="g_flux_vue", label_visibility="collapsed") or "Graphe des flux"
    options = ["Tous les passages"] + (passes["passage"].tolist() if not passes.empty else [])
    choix = b.selectbox("Passage", options, key="g_flux_run", label_visibility="collapsed", help="Limite les volumes aux fichiers et aux lignes créés par ce passage.")
    run = None if choix == "Tous les passages" else choix
    vol = volumes(db, run)

    if vue == "Graphe des flux":
        plotly_sel = _selection_plotly()
        if plotly_sel != st.session_state.get("g_flux_vu"):                   # un nouveau clic dans le graphe prend le dessus
            st.session_state["g_flux_vu"] = plotly_sel
            if plotly_sel:
                st.session_state["g_flux_sel"] = plotly_sel
        sel = st.session_state.get("g_flux_sel")
        c1, c2 = st.columns([4, 1])
        c1.selectbox("Élément affiché", [None] + list(NOEUDS), format_func=lambda i: "(cliquez le graphe ou choisissez ici)" if i is None else NOEUDS[i][0],
                     key="g_flux_sel", label_visibility="collapsed")
        c2.button("Tout afficher", on_click=lambda: st.session_state.update(g_flux_sel=None, g_flux_vu=None), width="stretch", key="g_flux_reset")
        st.plotly_chart(_figure_graphe(vol, sel), key="g_flux_graphe", on_select="rerun", selection_mode="points", theme="streamlit", width="stretch",
                        config={"displaylogo": False, "scrollZoom": True})
        if sel:
            _detail(db, sel, vol, run)
        else:
            st.info("Cliquez un nœud pour mettre en évidence son amont et son aval, voir sa volumétrie, un aperçu de ses lignes et les règles de qualité qui le visent.")
    else:
        fig = _figure_sankey(vol)
        if fig is None:
            st.info("Aucun volume à montrer : lancez un scénario dans « Démo en direct » ou déposez des relevés.")
        else:
            st.plotly_chart(fig, theme="streamlit", width="stretch", config={"displaylogo": False})
            q = vol["statuts"].get("quarantaine", 0)
            st.caption(f"Largeur des bandes = nombre de lignes. {q} mouvement(s) en quarantaine sont exclus de la restitution ; les lignes « non promues » "
                       "sont des doublons ou des lignes hors période écartés par A3.")

    st.markdown("##### Passages")
    if passes.empty:
        st.info("Aucun passage tracé : lancez un scénario dans « Démo en direct ».")
    else:
        ev = st.dataframe(passes, hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row", key="g_flux_tab",
                          column_config={"fichiers": st.column_config.NumberColumn("Fichiers", format="%d"), "lignes_lues": st.column_config.ProgressColumn("Lignes lues", format="%d", min_value=0, max_value=int(max(passes["lignes_lues"].max(), 1))),
                                         "mouvements": st.column_config.ProgressColumn("Mouvements", format="%d", min_value=0, max_value=int(max(passes["mouvements"].max(), 1))),
                                         "rejets": st.column_config.NumberColumn("Rejets", format="%d")})
        lignes = list(ev.selection.rows) if ev is not None and getattr(ev, "selection", None) is not None else []
        if lignes:
            st.caption(f"Passage sélectionné : `{passes.iloc[lignes[0]]['passage']}`. Choisissez-le dans la liste ci-dessus pour filtrer le graphe.")
