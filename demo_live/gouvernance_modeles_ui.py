"""Gouvernance des données : modèles de données, liens entre les tables et bases vectorielles, de façon dynamique et interactive.

  Modèle relationnel   graphe des tables et de leurs relations (clés étrangères déclarées et liens déduits des noms de colonnes) ; cliquer une
                       table met en évidence ses voisines et ouvre sa fiche (colonnes, relations navigables, aperçu, définition SQL)
  Matrice des liens    qui référence qui, tables les plus connectées, intégrité référentielle mesurée (lignes orphelines)
  Bases vectorielles   détection des bases vectorielles du projet, fiche de gouvernance de l'index de recherche (RAG), carte des passages
                       et comparaison entre la recherche BM25 actuelle et une recherche vectorielle (TF-IDF)

Lecture seule sur les bases : rien n'est écrit.
"""
from __future__ import annotations

import math
import os
import re
import sqlite3
from collections import defaultdict

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

COUCHES = [("legacy", "Orchestrateur d'origine", "#8f9aa8"), ("meta", "Métadonnées (meta)", "#6250d6"), ("ref", "Référence (ref)", "#1baf7a"),
           ("mdm", "Données maîtres (mdm)", "#2a78d6"), ("stg", "Zone d'arrivée (stg)", "#eda100"), ("core", "Noyau (core)", "#1f5f8b"),
           ("dq", "Qualité (dq)", "#d03b3b"), ("dim", "Dimensions (dim)", "#e87ba4"), ("mart", "Restitution (mart)", "#eb6834")]
NOM_COUCHE = {c: n for c, n, _ in COUCHES}
COULEUR_COUCHE = {c: col for c, _, col in COUCHES}
ORDRE_COUCHE = {c: i for i, (c, _, _) in enumerate(COUCHES)}
PREFIXES = ("meta_", "ref_", "mdm_", "stg_", "core_", "dq_", "dim_", "mart_")
ROSE = "#e87ba4"
CONFIG = {"displaylogo": False, "scrollZoom": True, "modeBarButtonsToRemove": ["lasso2d", "select2d"]}


def couche(nom: str) -> str:
    return next((p.rstrip("_") for p in PREFIXES if nom.startswith(p)), "legacy")


# --------------------------------------------------------------------------- #
# Lecture du schéma
# --------------------------------------------------------------------------- #
@st.cache_data(show_spinner=False, ttl=30)
def schema(db: str, avec_vues: bool = True) -> dict:
    """{table: {genre, colonnes: [(nom, type, notnull, pk)], fk: [(colonne, table_cible, colonne_cible)], ddl, lignes}}."""
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=10)
    try:
        objets = c.execute("SELECT name, type, sql FROM sqlite_master WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall()
        out = {}
        for nom, genre, ddl in objets:
            if genre == "view" and not avec_vues:
                continue
            cols = [(r[1], r[2] or "", bool(r[3]), int(r[5])) for r in c.execute(f'PRAGMA table_info("{nom}")')]
            fk = []
            if genre == "table":
                fk = [(r[3], r[2], r[4] or "") for r in c.execute(f'PRAGMA foreign_key_list("{nom}")')]
            try:
                n = c.execute(f'SELECT COUNT(*) FROM "{nom}"').fetchone()[0]
            except sqlite3.Error:
                n = None
            out[nom] = {"genre": genre, "colonnes": cols, "fk": fk, "ddl": ddl or "", "lignes": n}
        # une clé étrangère sans colonne cible vise la clé primaire de la table cible
        for nom, t in out.items():
            t["fk"] = [(col, dst, dcol or next((k[0] for k in out.get(dst, {"colonnes": []})["colonnes"] if k[3] == 1), "")) for col, dst, dcol in t["fk"]]
        return out
    finally:
        c.close()


def liens(sch: dict) -> list[dict]:
    """Relations entre tables : clés étrangères déclarées, puis liens déduits (colonne qui porte le nom de la clé primaire d'une autre table,
    ou colonne « x_code » qui vise la table de référence ref_x). Un lien : {src, col, dst, dst_col, type}."""
    pk1 = defaultdict(list)                                              # nom de colonne -> tables dont c'est la clé primaire (simple)
    for t, d in sch.items():
        if d["genre"] != "table":
            continue
        pks = [k for k in d["colonnes"] if k[3] > 0]
        if len(pks) == 1:
            pk1[pks[0][0]].append(t)
    refs = {t[4:]: t for t, d in sch.items() if t.startswith("ref_") and d["genre"] == "table"}
    vus, out = set(), []

    def ajouter(src, col, dst, dcol, genre):
        cle = (src, col, dst)
        if cle not in vus:
            vus.add(cle)
            out.append({"src": src, "col": col, "dst": dst, "dst_col": dcol, "type": genre})

    for t, d in sch.items():
        for col, dst, dcol in d["fk"]:
            if dst in sch:
                ajouter(t, col, dst, dcol, "déclaré")
    for t, d in sch.items():
        for col, _, _, pk in d["colonnes"]:
            for u in pk1.get(col, []):
                if u != t and not (pk > 0 and d["genre"] == "table"):         # la clé primaire d'une table n'est pas un renvoi vers une autre
                    ajouter(t, col, u, col, "déduit")
            if col.endswith("_code") and col != "code":
                stem = col[:-5]
                for rs, rt in refs.items():
                    if rt != t and (rs == stem or rs.startswith(stem + "_") or rs.endswith("_" + stem)):
                        ajouter(t, col, rt, "code", "déduit")
    return out


# --------------------------------------------------------------------------- #
# Dispositions
# --------------------------------------------------------------------------- #
def disposition_couches(ids: list[str]) -> dict[str, tuple[float, float]]:
    par = defaultdict(list)
    for i in sorted(ids):
        par[couche(i)].append(i)
    pos = {}
    hauteur = max((len(v) for v in par.values()), default=1)
    for c, noms in par.items():
        for k, nom in enumerate(noms):
            pos[nom] = (ORDRE_COUCHE[c], (hauteur - len(noms)) / 2 + k)
    return pos


@st.cache_data(show_spinner=False)
def disposition_forces(ids: tuple, aretes: tuple, graine: int = 7, iterations: int = 260) -> dict[str, tuple[float, float]]:
    """Disposition « ressorts » (Fruchterman-Reingold) : les tables liées se rapprochent, les autres se repoussent."""
    n = len(ids)
    if n == 0:
        return {}
    rng = np.random.default_rng(graine)
    pos = rng.random((n, 2))
    idx = {i: k for k, i in enumerate(ids)}
    E = [(idx[a], idx[b]) for a, b in aretes if a in idx and b in idx and a != b]
    k = math.sqrt(1.0 / n)
    t = 0.12
    for _ in range(iterations):
        delta = pos[:, None, :] - pos[None, :, :]
        dist = np.linalg.norm(delta, axis=2) + 1e-9
        disp = ((k * k / dist ** 2)[:, :, None] * delta).sum(axis=1)
        for a, b in E:
            d = pos[a] - pos[b]
            f = d * (np.linalg.norm(d) + 1e-9) / k
            disp[a] -= f
            disp[b] += f
        longueur = np.linalg.norm(disp, axis=1) + 1e-9
        pos += disp / longueur[:, None] * np.minimum(longueur, t)[:, None]
        t *= 0.985
    pos -= pos.min(axis=0)
    pos /= np.maximum(pos.max(axis=0), 1e-9)
    return {i: (float(pos[idx[i], 0]), float(pos[idx[i], 1])) for i in ids}


# --------------------------------------------------------------------------- #
# Modèle relationnel
# --------------------------------------------------------------------------- #
def _selection(cle: str, courbe: int, ids: list[str]) -> str | None:
    etat = st.session_state.get(cle) or {}
    pts = (etat.get("selection") or {}).get("points") if isinstance(etat, dict) else None
    for p in pts or []:
        if p.get("curve_number") == courbe and 0 <= p.get("point_index", -1) < len(ids):
            return ids[p["point_index"]]
    return None


def _aller(nom: str) -> None:
    st.session_state["g_mod_sel"] = nom


def _rgba(hexa: str, alpha: float) -> str:
    return f"rgba({int(hexa[1:3], 16)},{int(hexa[3:5], 16)},{int(hexa[5:7], 16)},{alpha})"


def _figure_modele(sch: dict, aretes: list[dict], pos: dict, sel: str | None, taille: str, noms: bool, recherche: str, forces: bool) -> tuple[go.Figure, list[str]]:
    ids = [i for i in sch if i in pos]
    voisins = {sel} if sel else set(ids)
    if sel:
        for a in aretes:
            if a["src"] == sel:
                voisins.add(a["dst"])
            if a["dst"] == sel:
                voisins.add(a["src"])
    trouves = {i for i in ids if recherche and (recherche.lower() in i.lower() or any(recherche.lower() in c[0].lower() for c in sch[i]["colonnes"]))}
    fig = go.Figure()
    # courbes 0 à 3 : arêtes (déclarées / déduites) x (atténuées / en évidence)
    for genre in ("déclaré", "déduit"):
        for fort in (False, True):
            xs, ys = [], []
            for a in aretes:
                if a["type"] != genre or a["src"] == a["dst"] or a["src"] not in pos or a["dst"] not in pos:
                    continue
                en = bool(sel) and (a["src"] == sel or a["dst"] == sel)
                if en == fort:
                    xs += [pos[a["src"]][0], pos[a["dst"]][0], None]
                    ys += [pos[a["src"]][1], pos[a["dst"]][1], None]
            fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines", hoverinfo="skip", showlegend=False,
                                     line=dict(width=3 if fort else 1.2, color=ROSE if fort else "rgba(137,135,129,0.5)", dash="solid" if genre == "déclaré" else "dot")))
    for a in aretes:                                                      # flèches : de la table qui référence vers la table référencée
        if a["src"] == a["dst"] or a["src"] not in pos or a["dst"] not in pos:
            continue
        (xa, ya), (xb, yb) = pos[a["src"]], pos[a["dst"]]
        en = bool(sel) and (a["src"] == sel or a["dst"] == sel)
        fig.add_annotation(x=xa + (xb - xa) * 0.86, y=ya + (yb - ya) * 0.86, ax=xa + (xb - xa) * 0.7, ay=ya + (yb - ya) * 0.7, xref="x", yref="y", axref="x", ayref="y",
                           showarrow=True, arrowhead=3, arrowsize=1, arrowwidth=2 if en else 1, arrowcolor=ROSE if en else "rgba(137,135,129,0.6)")
    degre = defaultdict(int)
    for a in aretes:
        degre[a["src"]] += 1
        degre[a["dst"]] += 1
    tailles, couleurs, survol, bord = [], [], [], []
    for i in ids:
        d = sch[i]
        if taille == "Lignes":
            t = 12 + 5 * math.log10(max(d["lignes"] or 1, 1) + 1)
        elif taille == "Colonnes":
            t = 10 + 1.4 * len(d["colonnes"])
        else:
            t = 18
        tailles.append(min(t, 44))
        alpha = 1.0 if i in voisins else 0.2
        couleurs.append(_rgba(COULEUR_COUCHE[couche(i)], alpha))
        bord.append(ROSE if i == sel else ("#2a78d6" if i in trouves else "rgba(255,255,255,0.6)"))
        n = d["lignes"]
        survol.append(f"<b>{i}</b><br>{NOM_COUCHE[couche(i)]} · {'vue' if d['genre'] == 'view' else 'table'}<br>{len(d['colonnes'])} colonne(s)"
                      + (f" · {n:,} ligne(s)".replace(",", " ") if n is not None else "") + f"<br>{degre[i]} lien(s)")
    fig.add_trace(go.Scatter(                                            # courbe 4 : les tables (lue par _selection)
        x=[pos[i][0] for i in ids], y=[pos[i][1] for i in ids], mode="markers+text" if noms else "markers", text=[i for i in ids] if noms else None,
        textposition="top center", textfont=dict(size=9),
        marker=dict(size=tailles, color=couleurs, symbol=["diamond" if sch[i]["genre"] == "view" else "circle" for i in ids], opacity=1,
                    line=dict(width=[4 if i == sel or i in trouves else 1 for i in ids], color=bord)),
        hovertext=survol, hoverinfo="text", showlegend=False, selected=dict(marker=dict(opacity=1)), unselected=dict(marker=dict(opacity=1))))
    for c, nom, col in COUCHES:
        if any(couche(i) == c for i in ids):
            fig.add_trace(go.Scatter(x=[None], y=[None], mode="markers", marker=dict(size=10, color=col), name=nom, hoverinfo="skip"))
    for nom, dash in (("Clé étrangère déclarée", "solid"), ("Lien déduit du nom de colonne", "dot")):
        fig.add_trace(go.Scatter(x=[None], y=[None], mode="lines", line=dict(color="rgba(137,135,129,0.9)", dash=dash), name=nom, hoverinfo="skip"))
    xr = [-0.08, 1.08] if forces else [-0.6, len(COUCHES) - 0.4]
    yr = [1.08, -0.08] if forces else [max(y for _, y in pos.values()) + 1 if pos else 1, -1]
    fig.update_layout(height=820, margin=dict(l=10, r=10, t=10, b=10), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", dragmode="pan",
                      legend=dict(orientation="h", y=-0.01, yanchor="top", x=0, font=dict(size=11)), xaxis=dict(visible=False, range=xr), yaxis=dict(visible=False, range=yr), clickmode="event+select")
    return fig, ids


def _fiche(db: str, sch: dict, aretes: list[dict], nom: str) -> None:
    d = sch[nom]
    sortants = [a for a in aretes if a["src"] == nom]
    entrants = [a for a in aretes if a["dst"] == nom]
    with st.container(border=True):
        st.markdown(f"#### {nom}")
        st.caption(f"{NOM_COUCHE[couche(nom)]} · {'vue' if d['genre'] == 'view' else 'table'}")
        a, b, c, e = st.columns(4)
        a.metric("Colonnes", len(d["colonnes"]), border=True)
        b.metric("Lignes", f"{d['lignes']:,}".replace(",", " ") if d["lignes"] is not None else "—", border=True)
        c.metric("Références (sortantes)", len(sortants), border=True)
        e.metric("Référencée par", len(entrants), border=True)
        t1, t2, t3, t4 = st.tabs(["Colonnes", "Relations", "Aperçu des lignes", "Définition SQL"])
        with t1:
            fk = {a["col"]: f"→ {a['dst']}.{a['dst_col']}" for a in sortants}
            doc = _lire(db, "SELECT champ_nom, definition_metier, sensibilite FROM meta_champ WHERE table_nom = ?", (nom,))
            dmap = {r.champ_nom: (r.definition_metier, r.sensibilite) for r in doc.itertuples()} if not doc.empty else {}
            st.dataframe(pd.DataFrame([{"Colonne": n, "Type": t, "Clé": "PK" if pk else ("FK" if n in fk else ""), "Obligatoire": "oui" if nn or pk else "", "Référence": fk.get(n, ""),
                                        "Sensibilité": dmap.get(n, ("", ""))[1], "Définition": dmap.get(n, ("", ""))[0]} for n, t, nn, pk in d["colonnes"]]), hide_index=True, width="stretch")
        with t2:
            x, y = st.columns(2)
            with x:
                st.markdown("**Références** (cette table pointe vers…)")
                for a in sortants or [None]:
                    if a is None:
                        st.caption("Aucune.")
                    else:
                        st.button(f"{a['col']} → {a['dst']}.{a['dst_col']}  ({a['type']})", key=f"g_mod_s_{nom}_{a['col']}_{a['dst']}", on_click=_aller, args=(a["dst"],), width="stretch")
            with y:
                st.markdown("**Référencée par** (ces tables pointent vers elle)")
                for a in entrants or [None]:
                    if a is None:
                        st.caption("Aucune.")
                    else:
                        st.button(f"{a['src']}.{a['col']}  ({a['type']})", key=f"g_mod_e_{nom}_{a['src']}_{a['col']}", on_click=_aller, args=(a["src"],), width="stretch")
            if sortants:
                st.markdown("**Intégrité référentielle** des références sortantes")
                st.dataframe(pd.DataFrame([{"Lien": f"{a['col']} → {a['dst']}.{a['dst_col']}", "Type": a["type"], "Lignes orphelines": orphelins(db, a)} for a in sortants]),
                             hide_index=True, width="stretch")
        with t3:
            ap = _lire(db, f'SELECT * FROM "{nom}" LIMIT 10')
            st.dataframe(ap, hide_index=True, width="stretch") if not ap.empty else st.caption("Aucune ligne.")
        with t4:
            st.code(d["ddl"] or "(définition indisponible)", language="sql")


def _lire(db: str, sql: str, params=()) -> pd.DataFrame:
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=10)
    try:
        return pd.read_sql_query(sql, c, params=params)
    except Exception:                                                     # noqa: BLE001
        return pd.DataFrame()
    finally:
        c.close()


@st.cache_data(show_spinner=False, ttl=30)
def orphelins(db: str, a: dict) -> int | None:
    """Lignes dont la valeur de la colonne n'existe pas dans la colonne cible (None si la requête est impossible)."""
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=10)
    try:
        return c.execute(f'SELECT COUNT(*) FROM "{a["src"]}" WHERE "{a["col"]}" IS NOT NULL AND "{a["col"]}" NOT IN (SELECT "{a["dst_col"]}" FROM "{a["dst"]}" WHERE "{a["dst_col"]}" IS NOT NULL)').fetchone()[0]
    except sqlite3.Error:
        return None
    finally:
        c.close()


def modele_relationnel(db: str) -> None:
    st.caption("Chaque point est une table (losange : une vue). Un trait plein est une clé étrangère déclarée, un pointillé un lien déduit du nom de la colonne ; "
               "la flèche va de la table qui référence vers la table référencée. Cliquez une table : ses voisines restent en couleur et sa fiche s'ouvre.")
    c1, c2, c3, c4 = st.columns([2, 2, 2, 2])
    disp = c1.segmented_control("Disposition", ["Par couche", "Réseau (forces)"], default="Par couche", key="g_mod_disp") or "Par couche"
    taille = c2.segmented_control("Taille des points", ["Uniforme", "Colonnes", "Lignes"], default="Colonnes", key="g_mod_taille") or "Colonnes"
    genres = c3.multiselect("Liens affichés", ["déclaré", "déduit"], default=["déclaré", "déduit"], key="g_mod_genres")
    recherche = c4.text_input("Chercher une table ou une colonne", key="g_mod_q", placeholder="ex. compte_id")
    d1, d2, d3 = st.columns([4, 1, 1])
    couches_ = d1.multiselect("Couches", [c for c, _, _ in COUCHES], default=[c for c, _, _ in COUCHES], key="g_mod_couches", format_func=lambda c: NOM_COUCHE[c])
    vues = d2.toggle("Vues", value=True, key="g_mod_vues")
    noms = d3.toggle("Noms", value=True, key="g_mod_noms")

    sch_tout = schema(db, vues)
    sch = {t: d for t, d in sch_tout.items() if couche(t) in couches_}
    aretes = [a for a in liens(sch_tout) if a["type"] in genres and a["src"] in sch and a["dst"] in sch]
    if not sch:
        st.info("Aucune table dans les couches choisies.")
        return
    forces = disp == "Réseau (forces)"
    pos = disposition_forces(tuple(sorted(sch)), tuple(sorted((a["src"], a["dst"]) for a in aretes))) if forces else disposition_couches(list(sch))

    ids = [i for i in sch if i in pos]
    cliquee = _selection("g_mod_graphe", 4, ids)
    if cliquee != st.session_state.get("g_mod_vu"):
        st.session_state["g_mod_vu"] = cliquee
        if cliquee:
            st.session_state["g_mod_sel"] = cliquee
    if st.session_state.get("g_mod_sel") not in sch:
        st.session_state["g_mod_sel"] = None
    sel = st.session_state.get("g_mod_sel")
    e1, e2 = st.columns([4, 1])
    e1.selectbox("Table affichée", [None] + sorted(sch), format_func=lambda t: "(cliquez le graphe ou choisissez ici)" if t is None else t, key="g_mod_sel", label_visibility="collapsed")
    e2.button("Tout afficher", on_click=lambda: st.session_state.update(g_mod_sel=None, g_mod_vu=None), width="stretch", key="g_mod_reset")
    a, b, c, d = st.columns(4)
    a.metric("Tables et vues", len(sch), border=True)
    b.metric("Liens", len(aretes), delta=f"{sum(1 for x in aretes if x['type'] == 'déclaré')} déclaré(s)", delta_color="off", border=True)
    isolees = [i for i in sch if not any(x["src"] == i or x["dst"] == i for x in aretes)]
    c.metric("Tables sans lien", len(isolees), border=True, help=", ".join(sorted(isolees)[:12]) or "aucune")
    d.metric("Couches", len({couche(i) for i in sch}), border=True)

    fig, ids = _figure_modele(sch, aretes, pos, sel, taille, noms, recherche, forces)
    st.plotly_chart(fig, key="g_mod_graphe", on_select="rerun", selection_mode="points", theme="streamlit", width="stretch", config=CONFIG)
    if sel:
        _fiche(db, sch_tout, liens(sch_tout), sel)
    else:
        st.info("Cliquez une table pour voir ses colonnes, ses relations navigables, un aperçu de ses lignes et sa définition SQL.")


# --------------------------------------------------------------------------- #
# Matrice des liens et intégrité
# --------------------------------------------------------------------------- #
def matrice_liens(db: str) -> None:
    sch = schema(db, True)
    aretes = liens(sch)
    st.caption("Qui référence qui. Une case colorée est un lien de la table en ligne (qui référence) vers la table en colonne (référencée) ; survolez-la pour voir les colonnes.")
    c1, c2 = st.columns([3, 2])
    choix = c1.multiselect("Couches", [c for c, _, _ in COUCHES], default=[c for c, _, _ in COUCHES], key="g_mat_couches", format_func=lambda c: NOM_COUCHE[c])
    seul = c2.segmented_control("Liens", ["Tous", "Déclarés", "Déduits"], default="Tous", key="g_mat_genre") or "Tous"
    A = [a for a in aretes if (seul == "Tous" or a["type"] == seul[:-1].lower() + "é") and couche(a["src"]) in choix and couche(a["dst"]) in choix and a["src"] != a["dst"]]
    noms = sorted({a["src"] for a in A} | {a["dst"] for a in A}, key=lambda t: (ORDRE_COUCHE[couche(t)], t))
    if not A:
        st.info("Aucun lien pour ce filtre.")
    else:
        i = {n: k for k, n in enumerate(noms)}
        z = np.zeros((len(noms), len(noms)))
        txt = [["" for _ in noms] for _ in noms]
        for a in A:
            z[i[a["src"]], i[a["dst"]]] += 1
            txt[i[a["src"]]][i[a["dst"]]] += f"{a['col']} → {a['dst_col']} ({a['type']})<br>"
        with st.container(border=True):
            fig = go.Figure(go.Heatmap(z=np.where(z == 0, np.nan, z), x=noms, y=noms, text=txt, hovertemplate="%{y} → %{x}<br>%{text}<extra></extra>",
                                       colorscale=[[0, "#9fc6f3"], [1, "#184f95"]], showscale=False, xgap=1, ygap=1))
            fig.update_yaxes(autorange="reversed", title="référence …", tickfont=dict(size=9))
            fig.update_xaxes(title="… la table référencée", tickangle=-60, tickfont=dict(size=9))
            fig.update_layout(height=max(520, 14 * len(noms) + 160), margin=dict(l=10, r=10, t=30, b=10), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
            st.plotly_chart(fig, theme="streamlit", width="stretch", config={"displaylogo": False}, key="g_mat_heat")
    deg = defaultdict(lambda: [0, 0])
    for a in aretes:
        deg[a["src"]][0] += 1
        deg[a["dst"]][1] += 1
    g1, g2 = st.columns(2)
    with g1, st.container(border=True):
        st.markdown("**Tables les plus connectées** (références émises et reçues)")
        d = pd.DataFrame([{"Table": t, "Références émises": v[0], "Références reçues": v[1]} for t, v in deg.items()])
        if not d.empty:
            d["Total"] = d["Références émises"] + d["Références reçues"]
            d = d.sort_values("Total", ascending=False).head(15).sort_values("Total")
            fig = px.bar(d, x=["Références émises", "Références reçues"], y="Table", orientation="h", color_discrete_sequence=["#2a78d6", "#eb6834"])
            fig.update_layout(height=420, margin=dict(l=10, r=10, t=10, b=10), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", legend_title_text="", xaxis_title=None, yaxis_title=None,
                              legend=dict(orientation="h", y=1.08))
            st.plotly_chart(fig, theme="streamlit", width="stretch", config={"displaylogo": False}, key="g_mat_deg")
    with g2, st.container(border=True):
        st.markdown("**Tables sans aucun lien**")
        iso = sorted(t for t, d in sch.items() if t not in deg)
        st.caption(f"{len(iso)} table(s) ou vue(s) isolées : à relier, ou à documenter comme autonomes.")
        st.dataframe(pd.DataFrame({"Table": iso, "Couche": [NOM_COUCHE[couche(t)] for t in iso], "Lignes": [sch[t]["lignes"] for t in iso]}), hide_index=True, width="stretch", height=380)

    st.markdown("##### Intégrité référentielle")
    st.caption("Pour chaque lien, nombre de lignes dont la valeur n'existe pas dans la table référencée (lignes orphelines). Zéro est attendu.")
    mesures = [{"Lien": f"{a['src']}.{a['col']} → {a['dst']}.{a['dst_col']}", "Type": a["type"], "Lignes": sch[a["src"]]["lignes"], "Orphelines": orphelins(db, a)}
               for a in aretes if a["src"] != a["dst"] and sch[a["src"]]["genre"] == "table"]
    m = pd.DataFrame(mesures)
    if m.empty:
        st.info("Aucun lien à contrôler.")
        return
    m["Statut"] = m["Orphelines"].map(lambda v: "—" if v is None else ("✅ intègre" if v == 0 else "⚠ orphelines"))
    k1, k2, k3 = st.columns(3)
    k1.metric("Liens contrôlés", len(m), border=True)
    k2.metric("Intègres", int((m["Orphelines"] == 0).sum()), border=True)
    k3.metric("Avec lignes orphelines", int((m["Orphelines"].fillna(0) > 0).sum()), border=True)
    filtre = st.segmented_control("Afficher", ["Tous", "Orphelines seulement"], default="Tous", key="g_mat_integr") or "Tous"
    st.dataframe(m if filtre == "Tous" else m[m["Orphelines"].fillna(0) > 0], hide_index=True, width="stretch")


# --------------------------------------------------------------------------- #
# Bases vectorielles
# --------------------------------------------------------------------------- #
MOTIFS_VECTORIELS = {
    "ChromaDB": r"chromadb|langchain_chroma", "FAISS": r"\bfaiss\b", "Qdrant": r"qdrant", "pgvector": r"pgvector", "LanceDB": r"lancedb", "Pinecone": r"pinecone",
    "Weaviate": r"weaviate", "Milvus": r"milvus|pymilvus", "sqlite-vec": r"sqlite_vec|sqlite-vec|vec0",
    "Modèle d'embeddings": r"sentence_transformers|SentenceTransformer|OpenAIEmbeddings|HuggingFaceEmbeddings|OllamaEmbeddings|\.embed_(query|documents)\(|embeddings\.create",
}
FICHIERS_VECTORIELS = ("chroma.sqlite3", ".faiss", ".lance", ".annoy", ".hnsw", "index.faiss")


@st.cache_data(show_spinner=False, ttl=120)
def detecter_vectoriel(racine: str, bases: tuple) -> pd.DataFrame:
    """Cherche des bases vectorielles : fichiers d'index, bibliothèques dans le code, colonnes d'embeddings dans les bases SQLite."""
    lignes = []
    trouves = defaultdict(list)
    fichiers_vect = []
    for dossier, sous, fichiers in os.walk(racine):
        sous[:] = [d for d in sous if d not in {"__pycache__", ".git", ".idea", "scenarios", ".venv", "node_modules", "donnees_externes"}]
        for f in fichiers:
            if f.lower().endswith(FICHIERS_VECTORIELS):
                fichiers_vect.append(os.path.relpath(os.path.join(dossier, f), racine))
            if f.endswith((".py", ".txt", ".toml", ".json")) and "gouvernance_modeles_ui" not in f:
                try:
                    texte = open(os.path.join(dossier, f), encoding="utf-8", errors="ignore").read()
                except OSError:
                    continue
                for nom, motif in MOTIFS_VECTORIELS.items():
                    if re.search(motif, texte, re.I):
                        trouves[nom].append(os.path.relpath(os.path.join(dossier, f), racine))
    lignes.append({"Vérification": "Fichiers d'index vectoriel (Chroma, FAISS, LanceDB…)", "Résultat": "aucun" if not fichiers_vect else f"{len(fichiers_vect)} trouvé(s)",
                   "Détail": ", ".join(fichiers_vect[:5])})
    for nom, motif in MOTIFS_VECTORIELS.items():
        lignes.append({"Vérification": f"Bibliothèque ou appel : {nom}", "Résultat": "aucun" if not trouves[nom] else f"{len(trouves[nom])} fichier(s)", "Détail": ", ".join(trouves[nom][:4])})
    for chemin in bases:
        if not os.path.isfile(chemin):
            continue
        c = sqlite3.connect(f"file:{chemin}?mode=ro", uri=True, timeout=10)
        try:
            colonnes = []
            for (t,) in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
                for r in c.execute(f'PRAGMA table_info("{t}")'):
                    if re.search(r"embedding|vecteur|vector|vec$", r[1], re.I):
                        colonnes.append(f"{t}.{r[1]}")
            virtuelles = [(n, re.search(r"USING\s+(\w+)", s or "", re.I).group(1)) for n, s in c.execute("SELECT name, sql FROM sqlite_master WHERE sql LIKE 'CREATE VIRTUAL%'") if re.search(r"USING\s+(\w+)", s or "", re.I)]
        finally:
            c.close()
        lignes.append({"Vérification": f"Colonnes d'embeddings dans {os.path.basename(chemin)}", "Résultat": "aucune" if not colonnes else f"{len(colonnes)} colonne(s)", "Détail": ", ".join(colonnes[:5])})
        for n, module in virtuelles:
            lignes.append({"Vérification": f"Table virtuelle dans {os.path.basename(chemin)}", "Résultat": f"{n} ({module})", "Détail": "index plein texte, pas de vecteurs" if module.lower().startswith("fts") else module})
    return pd.DataFrame(lignes)


@st.cache_data(show_spinner=False, ttl=60)
def corpus_lexical(index: str, signature: float) -> dict | None:
    """Représente chaque passage du RAG par un vecteur TF-IDF, puis le projette en 2 dimensions (SVD)."""
    from demo_live import rag
    c = sqlite3.connect(f"file:{index}?mode=ro", uri=True, timeout=10)
    try:
        docs = c.execute("SELECT id, type, source, titre, texte FROM docs ORDER BY id").fetchall()
    finally:
        c.close()
    if len(docs) < 5:
        return None
    jetons = [rag.jetons(f"{d[3]} {d[4]}") for d in docs]
    df = defaultdict(int)
    for j in jetons:
        for t in set(j):
            df[t] += 1
    n = len(docs)
    vocab = {t: k for k, t in enumerate(sorted(t for t, v in df.items() if 2 <= v <= 0.6 * n))}
    if len(vocab) < 5:
        return None
    idf = np.array([math.log((1 + n) / (1 + df[t])) + 1 for t in sorted(vocab, key=vocab.get)])
    M = np.zeros((n, len(vocab)), dtype=np.float32)
    for i, j in enumerate(jetons):
        for t in j:
            if t in vocab:
                M[i, vocab[t]] += 1
    M = np.log1p(M) * idf
    M /= np.maximum(np.linalg.norm(M, axis=1, keepdims=True), 1e-9)
    U, S, Vt = np.linalg.svd(M, full_matrices=False)
    coords = U[:, :2] * S[:2]
    return {"docs": docs, "vocab": vocab, "idf": idf, "M": M, "Vt": Vt[:2], "coords": coords, "variance": float((S[:2] ** 2).sum() / (S ** 2).sum()), "dim": len(vocab), "n": n}


def vecteur_requete(corpus: dict, question: str) -> np.ndarray | None:
    from demo_live import rag
    v = np.zeros(corpus["dim"], dtype=np.float32)
    for t in rag.jetons(question):
        if t in corpus["vocab"]:
            v[corpus["vocab"][t]] += 1
    if not v.any():
        return None
    v = np.log1p(v) * corpus["idf"]
    return v / max(np.linalg.norm(v), 1e-9)


def _selection_carte() -> int | None:
    etat = st.session_state.get("g_vec_carte") or {}
    pts = (etat.get("selection") or {}).get("points") if isinstance(etat, dict) else None
    for p in pts or []:
        if p.get("curve_number") == 0 and p.get("point_index") is not None:
            return int(p["point_index"])
    return None


def bases_vectorielles(db: str, racine: str, bases: tuple) -> None:
    from demo_live import rag
    st.caption("Une base vectorielle range des textes sous forme de vecteurs (embeddings) pour retrouver ceux qui « ressemblent » à une question. "
               "Cette page cherche s'il y en a dans le projet, décrit l'index de recherche réel et le compare à une recherche vectorielle.")
    det = detecter_vectoriel(racine, bases)
    vect = det[det["Vérification"].str.contains("Colonnes d'embeddings|Fichiers d'index|Bibliothèque ou appel") & ~det["Résultat"].isin(["aucun", "aucune"])]
    if vect.empty:
        st.info("**Aucune base vectorielle (embeddings) n'est utilisée dans ce projet.** La recherche du RAG repose sur un index plein texte SQLite FTS5 (BM25, lexical). "
                "Les vérifications ci-dessous le montrent ; la suite décrit cet index et simule ce que donnerait une recherche vectorielle.", icon=":material/search:")
    else:
        st.success("Des éléments vectoriels ont été trouvés : voir le détail ci-dessous.")
    with st.expander("Vérifications effectuées", expanded=not vect.empty):
        st.dataframe(det, hide_index=True, width="stretch")

    if not os.path.isfile(rag.INDEX):
        st.warning("L'index de recherche n'existe pas encore : ouvrez « Système RAG » ou « Assistant » pour le construire.")
        return
    et = rag.etat_index()
    taille = os.path.getsize(rag.INDEX) / 1024
    c = sqlite3.connect(f"file:{rag.INDEX}?mode=ro", uri=True, timeout=10)
    try:
        textes = c.execute("SELECT titre, texte FROM docs").fetchall()
        termes = len({t for titre, texte in textes for t in rag.jetons(f"{titre} {texte}")})
        longueurs = [len(r[1] or "") for r in textes]
        sources = c.execute("SELECT type, source, COUNT(*) FROM docs GROUP BY type, source").fetchall()
    finally:
        c.close()
    with st.container(border=True):
        st.markdown("##### Fiche de gouvernance de l'index de recherche")
        a, b, d, e = st.columns(4)
        a.metric("Passages indexés", et.get("passages", 0), border=True)
        b.metric("Termes distincts (FTS5)", int(termes or 0), border=True)
        d.metric("Taille du fichier", f"{taille:,.0f} Ko".replace(",", " "), border=True)
        e.metric("Construit le", str(et.get("construit", "—"))[:16], border=True)
        st.dataframe(pd.DataFrame({"Attribut": ["Nom", "Type", "Méthode de recherche", "Représentation des textes", "Modèle d'embeddings", "Dimension", "Distance", "Index approximatif (HNSW…)", "Mise à jour",
                                                "Propriétaire", "Sensibilité"],
                                   "Valeur": ["rag.db", "Index plein texte SQLite FTS5", "BM25 (poids 3 sur le titre, 1 sur le texte)", "Jetons (mots sans accents) : lexical, sans vecteurs", "Aucun", "—", "—", "Non",
                                              "Reconstruit à la demande (rag.construire)", "Intendant des données", "Interne : contient des rapports R0 et des traces d'agents"]}), hide_index=True, width="stretch")
    g1, g2 = st.columns(2)
    with g1, st.container(border=True):
        st.markdown("**Passages par type et par source** (cliquez pour zoomer)")
        s = pd.DataFrame(sources, columns=["Type", "Source", "Passages"])
        fig = px.treemap(s, path=[px.Constant("Index"), "Type", "Source"], values="Passages", color="Type", color_discrete_sequence=px.colors.qualitative.Set2)
        fig.update_traces(hovertemplate="%{label}<br>%{value} passage(s)<extra></extra>")
        fig.update_layout(height=340, margin=dict(l=10, r=10, t=10, b=10), paper_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig, theme="streamlit", width="stretch", config={"displaylogo": False}, key="g_vec_tree")
    with g2, st.container(border=True):
        st.markdown("**Longueur des passages** (caractères)")
        fig = px.histogram(pd.DataFrame({"Longueur": longueurs}), x="Longueur", nbins=30, color_discrete_sequence=["#2a78d6"])
        fig.update_layout(height=340, margin=dict(l=10, r=10, t=10, b=10), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", yaxis_title="Passages", bargap=0.05)
        st.plotly_chart(fig, theme="streamlit", width="stretch", config={"displaylogo": False}, key="g_vec_hist")

    corpus = corpus_lexical(rag.INDEX, os.path.getmtime(rag.INDEX))
    if corpus is None:
        st.info("Pas assez de passages pour dessiner la carte.")
        return
    st.markdown("##### Carte des passages et comparaison des recherches")
    st.caption(f"Chaque passage est représenté par un vecteur TF-IDF de {corpus['dim']} dimensions (un poids par mot), projeté en 2 dimensions "
               f"({corpus['variance'] * 100:.0f} % de la variance conservée). Deux passages proches sur la carte parlent des mêmes mots. "
               "Posez une question : elle est placée sur la carte et la recherche vectorielle (similarité cosinus) est comparée à la recherche actuelle (BM25).")
    q = st.text_input("Question à tester", key="g_vec_q", placeholder="ex. pourquoi A6 a bloqué le passage ?")
    k = st.slider("Résultats comparés", 3, 10, 5, key="g_vec_k")
    top_vec, top_bm25, qv = [], [], None
    if q.strip():
        qv = vecteur_requete(corpus, q)
        if qv is not None:
            sims = corpus["M"] @ qv
            top_vec = [(int(i), float(sims[i])) for i in np.argsort(-sims)[:k] if sims[i] > 0]
        top_bm25 = rag.chercher(q, k=k)
    sel_carte = _selection_carte()
    docs = corpus["docs"]
    types = [d[1] for d in docs]
    palette = dict(zip(sorted(set(types)), px.colors.qualitative.Set2 * 3))
    vec_ids = {i for i, _ in top_vec}
    bm_ids = {r["id"] for r in top_bm25}
    ids_doc = [d[0] for d in docs]
    tailles = [16 if (i in vec_ids or ids_doc[i] in bm_ids) else (13 if i == sel_carte else 7) for i in range(len(docs))]
    bords = ["#e87ba4" if i in vec_ids and ids_doc[i] in bm_ids else ("#2a78d6" if i in vec_ids else ("#eb6834" if ids_doc[i] in bm_ids else "rgba(255,255,255,0.4)")) for i in range(len(docs))]
    fig = go.Figure(go.Scatter(x=corpus["coords"][:, 0], y=corpus["coords"][:, 1], mode="markers",
                               marker=dict(size=tailles, color=[palette[t] for t in types], line=dict(width=[2.5 if b != "rgba(255,255,255,0.4)" else 0.5 for b in bords], color=bords), opacity=0.9),
                               hovertext=[f"<b>{d[3][:70]}</b><br>{d[1]} · {d[2][:50]}<br>{(d[4] or '')[:140].replace(chr(10), ' ')}…" for d in docs], hoverinfo="text", showlegend=False,
                               selected=dict(marker=dict(opacity=1)), unselected=dict(marker=dict(opacity=0.9))))
    if qv is not None:
        qxy = corpus["Vt"] @ qv                                          # même projection que les passages (U·S = M·Vtᵀ)
        fig.add_trace(go.Scatter(x=[float(qxy[0])], y=[float(qxy[1])], mode="markers+text", text=["Question"], textposition="top center",
                                 marker=dict(symbol="star", size=20, color="#d03b3b", line=dict(width=1, color="white")), hoverinfo="skip", showlegend=False))
    for t, col in palette.items():
        fig.add_trace(go.Scatter(x=[None], y=[None], mode="markers", marker=dict(size=9, color=col), name=t, hoverinfo="skip"))
    fig.update_layout(height=560, margin=dict(l=10, r=10, t=10, b=10), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", dragmode="pan", clickmode="event+select",
                      xaxis=dict(visible=False), yaxis=dict(visible=False), legend=dict(orientation="h", y=-0.01, yanchor="top", font=dict(size=11)))
    st.plotly_chart(fig, key="g_vec_carte", on_select="rerun", selection_mode="points", theme="streamlit", width="stretch", config=CONFIG)
    if q.strip():
        cvec, cbm = st.columns(2)
        with cvec:
            st.markdown("**Recherche vectorielle (TF-IDF, cosinus)**")
            st.dataframe(pd.DataFrame([{"Passage": docs[i][3][:70], "Type": docs[i][1], "Similarité": s} for i, s in top_vec]), hide_index=True, width="stretch",
                         column_config={"Similarité": st.column_config.ProgressColumn("Similarité", min_value=0, max_value=1, format="%.2f")}) if top_vec else st.caption("Aucun passage ne partage de mot avec la question.")
        with cbm:
            st.markdown("**Recherche actuelle (BM25)**")
            st.dataframe(pd.DataFrame([{"Passage": r["titre"][:70], "Type": r["type"], "Couverture des mots": r["couverture"]} for r in top_bm25]), hide_index=True, width="stretch",
                         column_config={"Couverture des mots": st.column_config.ProgressColumn("Couverture des mots", min_value=0, max_value=1, format="%.2f")}) if top_bm25 else st.caption("Aucun résultat.")
        communs = len({docs[i][0] for i, _ in top_vec} & {r["id"] for r in top_bm25})
        st.caption(f"{communs} passage(s) sur {k} sont retrouvés par les deux méthodes (liseré rose sur la carte ; bleu : vectoriel seul ; orange : BM25 seul). "
                   "Cette recherche vectorielle reste lexicale (elle compte les mots) : de vrais embeddings sémantiques retrouveraient aussi les synonymes.")
    if sel_carte is not None:
        d = docs[sel_carte]
        with st.container(border=True):
            st.markdown(f"**{d[3]}**")
            st.caption(f"{d[1]} · {d[2]}")
            st.text(rag.neutraliser(d[4] or "")[:1200])
    with st.expander("Gouverner une base vectorielle : ce qu'il faudrait suivre"):
        st.markdown("""
Si le RAG passait à de vrais embeddings, ces éléments deviendraient des métadonnées à gouverner, comme les tables du dictionnaire :
- **Le modèle d'embeddings** (nom et version) : changer de modèle change tous les vecteurs, il faut alors tout reconstruire.
- **La dimension et la distance** (cosinus, produit scalaire) : elles doivent être les mêmes à l'écriture et à la lecture.
- **La provenance** de chaque passage (fichier, rapport, passage du pipeline) : sans elle, impossible de citer ou de supprimer une source.
- **La classification** des textes indexés : un index copie les données, il hérite de leur sensibilité.
- **Le cycle de vie** : date de construction, mise à jour, suppression d'un document et de ses vecteurs.
- **La qualité de la recherche** : un jeu de questions de référence (le banc d'essai du RAG) mesuré à chaque changement.
""")


# --------------------------------------------------------------------------- #
# Entrée
# --------------------------------------------------------------------------- #
def afficher(db: str, racine: str, bases: tuple) -> None:
    st.caption("Comment les données sont organisées : les tables et leurs relations, leur intégrité, et les index de recherche (vectoriels ou non).")
    t1, t2, t3 = st.tabs(["🗺 Modèle relationnel", "🔗 Matrice des liens et intégrité", "🧬 Bases vectorielles"])
    with t1:
        modele_relationnel(db)
    with t2:
        matrice_liens(db)
    with t3:
        bases_vectorielles(db, racine, bases)
