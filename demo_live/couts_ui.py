"""Vue « Coûts de revient » : les méthodes de comptabilité de management appliquées à Groupe Usinage Saint-Maurice, vues par un CPA en gestion.

Dix onglets, dans l'ordre où un contrôleur de manufacture raisonne : voir, comprendre le coût, fixer le prix, vérifier le devis, décider, contrôler, planifier la capacité, améliorer, rendre compte.

  Tableau de bord     où le groupe gagne vraiment de l'argent : indicateurs à seuils, constats, matrice de positionnement, cadre des méthodes retenues et écartées
  Du compte au produit  diagramme de flux du poste comptable au produit, coût complet par composante
  Rentabilité (ABC)   centres d'analyse contre ABC, carte de chaleur des charges indirectes, distorsion
  Prix prix et planchers : cascade du prix à la marge, planchers (variable, spécifique, complet), prix cible
  Devis contre réel   coût par commande : précision des soumissions, dérive par élément de coût et par ligne
  Décisions à la marge  marge sur coûts variables, point mort, levier, tornado, abandon d'une ligne, commande spéciale
  Standards et écarts   écarts de matière, main-d'œuvre, frais variables et frais fixes (budget, volume), investigation, limites de contrôle, marché contre achat
  Capacité et contraintes  sous-activité par centre (imputation rationnelle) et mix par heure-machine (théorie des contraintes)
  Coût cible et qualité  coût admissible, feature costing, activités selon leur valeur (ABM), coût de la qualité
  Rapports            rapports stratégique, tactique et opérationnel, exportables (PDF, HTML, Markdown)

Les calculs sont dans couts_revient.py et couts_rapports.py (testés). Les montants sont fictifs et modifiables : tout se recalcule.
"""
from __future__ import annotations

import html
import re

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import couts_rapports as R
import couts_revient as C

CONFIG = {"displaylogo": False, "modeBarButtonsToRemove": ["lasso2d", "select2d"]}
MARQUE = "#1f5f8b"
COULEURS = {"Usinage sur mesure": "#1f5f8b", "Contrats aéro et rail": "#2a78d6", "Pièces de rechange": "#d9930a", "Prototypage": "#8f9aa8"}
COULEUR_CLASSE = {"Valeur ajoutée": "#1baf7a", "Nécessaire sans valeur ajoutée": "#eda100", "Sans valeur": "#d03b3b"}
FEU = {"ok": "#1baf7a", "att": "#d9930a", "crit": "#d03b3b", "info": "#5b6573"}
GRILLE = "rgba(128,128,128,.18)"

CSS = """<style>
.cr-hero{background:linear-gradient(135deg,#1f5f8b 0%,#2a78d6 100%);color:#fff;border-radius:14px;padding:18px 22px;margin:2px 0 14px}
.cr-hero h3{margin:0 0 4px;font-size:1.25rem;color:#fff}.cr-hero p{margin:0;opacity:.92;font-size:.95rem}
.cr-kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:10px;margin:.4rem 0 1rem}
.cr-k{border:1px solid rgba(128,128,128,.25);border-left:5px solid var(--c);border-radius:10px;padding:10px 12px;background:rgba(128,128,128,.06)}
.cr-k .l{font-size:.72rem;opacity:.75;text-transform:uppercase;letter-spacing:.04em}.cr-k .v{font-size:1.45rem;font-weight:700;line-height:1.25}
.cr-k .s{font-size:.8rem;opacity:.85}.cr-k .p{display:inline-block;font-size:.7rem;font-weight:700;color:#fff;background:var(--c);border-radius:999px;padding:1px 8px;margin-bottom:3px}
.cr-msg{border-left:4px solid #1f5f8b;background:rgba(31,95,139,.09);padding:9px 14px;border-radius:6px;margin:.45rem 0;line-height:1.45}
.cr-msg.alerte{border-left-color:#d03b3b;background:rgba(208,59,59,.09)}
.cr-meta{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:6px 18px;font-size:.86rem;margin-top:8px}.cr-meta b{opacity:.85}
.cr-lecture{border:1px dashed rgba(128,128,128,.45);border-radius:8px;padding:8px 12px;font-size:.88rem;margin:.4rem 0 .8rem}
.cr-entete{border:1px solid rgba(128,128,128,.28);border-left:5px solid #1f5f8b;border-radius:10px;padding:10px 14px;margin:0 0 .9rem}
.cr-entete .q{font-weight:700;font-size:1.02rem;line-height:1.35}.cr-entete .chips{display:flex;flex-wrap:wrap;gap:6px;margin-top:7px}
.cr-entete .chip{font-size:.78rem;background:rgba(31,95,139,.10);border-radius:999px;padding:2px 11px}
.cr-entete .chip b{opacity:.7;margin-right:5px;font-weight:600;text-transform:uppercase;font-size:.66rem;letter-spacing:.03em}
.cr-meth{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:9px;margin:.3rem 0 .8rem}
.cr-m{border:1px solid rgba(128,128,128,.25);border-top:4px solid var(--c);border-radius:10px;padding:9px 12px;background:rgba(128,128,128,.05)}
.cr-m .t{font-weight:700;font-size:.95rem}.cr-m .b{display:inline-block;font-size:.66rem;font-weight:700;color:#fff;background:var(--c);border-radius:999px;padding:1px 8px;margin-bottom:4px;text-transform:uppercase}
.cr-m .d{font-size:.8rem;opacity:.85;margin-top:3px}.cr-m.ecartee{opacity:.72}
.cr-section{font-size:1.15rem;font-weight:700;margin:1.4rem 0 .2rem;padding-top:.8rem;border-top:2px solid rgba(31,95,139,.35)}
</style>"""

COULEUR_STATUT_METHODE = {"Pilier": "#1f5f8b", "Complément": "#2a9d8f", "Écartée": "#8f9aa8"}


def _md(texte):
    """Échappe le signe $ : Streamlit le prendrait pour le début d'une formule et mangerait le texte entre deux montants."""
    return re.sub(r"(?<!\\)\$", r"\\$", texte) if isinstance(texte, str) else texte


def _k(v: float) -> str:
    return f"{v:,.0f} k$".replace(",", " ")


def _d(v: float, dec: int = 0) -> str:
    return f"{v:,.{dec}f} $".replace(",", " ")


def _fav(v: float) -> str:
    return "défavorable" if v > 0 else ("favorable" if v < 0 else "nul")


def _style(fig: go.Figure, hauteur: int = 340) -> go.Figure:
    fig.update_layout(height=hauteur, margin=dict(l=10, r=10, t=36, b=10), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=dict(size=13),
                      legend=dict(orientation="h", y=1.14, title_text=""), hoverlabel=dict(font_size=13))
    fig.update_xaxes(gridcolor=GRILLE, zeroline=False)
    fig.update_yaxes(gridcolor=GRILLE, zeroline=False)
    return fig


def _graphique(fig, cle: str, hauteur: int = 340) -> None:
    st.plotly_chart(_style(fig, hauteur), theme="streamlit", width="stretch", config=CONFIG, key=cle)


def _cartes(items: list[tuple]) -> None:
    """Cartes d'indicateurs : (libellé, valeur, précision, statut)."""
    corps = "".join(f'<div class="cr-k" style="--c:{FEU[s]}"><div class="l">{html.escape(l)}</div><div class="v">{html.escape(v)}</div>'
                    f'<div class="s">{html.escape(n)}</div></div>' for l, v, n, s in items)
    st.html(f'<div class="cr-kpis">{corps}</div>')


def _cartes_kpi(kpis: list) -> None:
    corps = "".join(f'<div class="cr-k" style="--c:{FEU[k.statut]}"><span class="p">{R.STATUTS[k.statut]}</span><div class="l">{html.escape(k.libelle)}</div>'
                    f'<div class="v">{html.escape(k.valeur)}</div><div class="s">{html.escape(k.note or ("Cible : " + k.cible if k.cible and k.cible != "—" else ""))}'
                    f'{(" · cible " + html.escape(k.cible)) if k.note and k.cible and k.cible != "—" else ""}</div></div>' for k in kpis)
    st.html(f'<div class="cr-kpis">{corps}</div>')


def _lecture(texte: str) -> None:
    st.info(_md(texte), icon=":material/lightbulb:")


def _entete(question: str, methode: str, decision: str, public: str) -> None:
    """Bandeau d'ouverture de chaque onglet : la question posée, la méthode qui y répond, la décision éclairée et à qui elle sert."""
    st.html(f'<div class="cr-entete"><div class="q">{html.escape(question)}</div><div class="chips"><span class="chip"><b>Méthode</b>{html.escape(methode)}</span>'
            f'<span class="chip"><b>Décision</b>{html.escape(decision)}</span><span class="chip"><b>Pour</b>{html.escape(public)}</span></div></div>')


def _section(titre: str) -> None:
    st.html(f'<div class="cr-section">{html.escape(titre)}</div>')


# --- Synthèse ---------------------------------------------------------------------------------------------------------------------------------
def onglet_synthese() -> None:
    rep = R.rapport_strategique()
    rent = C.rentabilite_produits()
    ventes = float(rent["Ventes (k$)"].sum())
    st.html(f'<div class="cr-hero"><h3>Où le groupe gagne vraiment de l\'argent</h3><p>{html.escape(f"Ventes de {_k(ventes)} · marge complète ABC de {_k(rent['Marge complète ABC (k$)'].sum())} · " f"{int((rent['Marge complète ABC (k$)'] < 0).sum())} ligne(s) sur {len(rent)} sous le coût complet")}.</p></div>')
    _cartes_kpi(rep.kpis)
    st.markdown("#### Constats clés")
    for i, m in enumerate(rep.messages):
        st.html(f'<div class="cr-msg{" alerte" if i == 1 else ""}">{R._gras_html(m)}</div>')

    c1, c2 = st.columns([3, 2])
    with c1:
        st.markdown("###### Matrice de positionnement des lignes")
        d = rent.reset_index(names="Ligne")
        fig = go.Figure()
        for _, r in d.iterrows():
            fig.add_scatter(x=[r["Taux de MCV"] * 100], y=[r["Marge complète ABC (%)"] * 100], mode="markers+text", name=r["Ligne"], text=[r["Ligne"]], textposition="top center",
                            marker=dict(size=max(18, r["Ventes (k$)"] ** 0.5 * 0.9), color=COULEURS[r["Ligne"]], line=dict(width=2, color="white"), opacity=.9),
                            hovertemplate=f"<b>{r['Ligne']}</b><br>Taux de MCV %{{x:.1f}} %<br>Marge complète ABC %{{y:.1f}} %<br>Ventes {_k(r['Ventes (k$)'])}<extra></extra>")
        moy = rent["MCV (k$)"].sum() / ventes * 100
        fig.add_hline(y=0, line_color="#d03b3b", line_width=1.5)
        fig.add_vline(x=moy, line_dash="dot", line_color="#8f9aa8")
        fig.add_annotation(x=0.99, y=0.99, xref="paper", yref="paper", text="Rentable au coût complet", showarrow=False, xanchor="right", yanchor="top", font=dict(size=11, color="#1baf7a"))
        fig.add_annotation(x=0.99, y=0.02, xref="paper", yref="paper", text="À réparer : sous le coût complet", showarrow=False, xanchor="right", yanchor="bottom", font=dict(size=11, color="#d03b3b"))
        fig.update_yaxes(range=[min(-45, d["Marge complète ABC (%)"].min() * 100 - 8), max(35, d["Marge complète ABC (%)"].max() * 100 + 12)])
        fig.update_xaxes(title="Taux de marge sur coûts variables (%)")
        fig.update_yaxes(title="Marge complète ABC (% des ventes)")
        fig.update_layout(showlegend=False)
        _graphique(fig, "cr_matrice", 400)
        st.caption("Taille de la bulle = ventes. Ligne pointillée verticale : taux de marge moyen du groupe. Sous la ligne rouge, la ligne perd de l'argent quand on lui impute sa part de tous les frais.")
    with c2:
        st.markdown("###### Distorsion du coût (ABC − centres d'analyse)")
        dist = rent["Distorsion (k$)"].sort_values()
        fig = go.Figure(go.Bar(x=dist.values, y=dist.index, orientation="h", marker_color=["#1f5f8b" if v < 0 else "#d03b3b" for v in dist.values],
                               text=[f"{v:+,.0f}".replace(",", " ") + " k$" for v in dist.values], textposition="outside"))
        fig.update_traces(cliponaxis=False)
        fig.update_xaxes(title="k$ (positif : la ligne est subventionnée)", range=[min(dist.min() * 1.5, -200), max(dist.max() * 1.5, 200)])
        fig.update_yaxes(automargin=True)
        _graphique(fig, "cr_dist", 400)
        st.caption("Une subvention croisée se compense toujours : ce que certaines lignes reçoivent, d'autres le paient.")
    _lecture(f"**Lecture du CPA.** Fixer les prix sur les centres d'analyse ferait croire que {int((rent['Marge selon centres (k$)'] > 0).sum())} lignes sur {len(rent)} sont rentables. "
             f"Avec l'ABC, la marge complète du groupe tombe de {_k(rent['Marge selon centres (k$)'].sum())} à {_k(rent['Marge complète ABC (k$)'].sum())} sur la même base de charges : "
             "ce n'est pas le résultat qui change, c'est sa répartition — et donc les prix à réviser en premier.")
    _section("Cadre de gestion : les méthodes retenues pour une manufacture sur commande, et celles qu'on écarte")
    _cadre_methodes()


# --- Cadre des méthodes -----------------------------------------------------------------------------------------------------------------------
def _cadre_methodes() -> None:
    """Les méthodes retenues pour une manufacture sur commande, et celles qu'un contrôleur écarte, avec la raison."""
    m = C.METHODES
    for statut, titre in (("Pilier", "Piliers : le socle du coût de revient"), ("Complément", "Compléments : pour une question précise"), ("Écartée", "Écartées : et pourquoi")):
        sous = m[m["Statut"] == statut]
        cartes = "".join(f'<div class="cr-m{" ecartee" if statut == "Écartée" else ""}" style="--c:{COULEUR_STATUT_METHODE[statut]}"><span class="b">{statut}</span>'
                         f'<div class="t">{html.escape(r["Méthode"])}</div>'
                         f'<div class="d">{html.escape(r["Question à laquelle elle répond"] if statut != "Écartée" else r["Pourquoi"])}</div>'
                         f'{"" if statut == "Écartée" else "<div class=d style=opacity:.65>" + html.escape(r["Décision éclairée"]) + "</div>"}</div>' for _, r in sous.iterrows())
        st.markdown(f"**{titre}**")
        st.html(f'<div class="cr-meth">{cartes}</div>')
    st.info("**Le réflexe du contrôleur.** On choisit — et on combine — les méthodes selon la décision à éclairer, jamais l'inverse : l'ABC pour la rentabilité, le standard pour le contrôle, "
            "le coût par commande pour la soumission, la marge sur coûts variables pour la décision à court terme, la marge par heure du goulot quand la capacité manque.", icon=":material/lightbulb:")


# --- Coût complet -----------------------------------------------------------------------------------------------------------------------------
def onglet_complet() -> None:
    _entete("Combien coûte vraiment une pièce de chaque ligne de produits ?", "Centres d'analyse (taux par centre) contre ABC (inducteurs réels)", "Prix, portefeuille et soumissions", "Direction et contrôleur")
    rep = C.repartition_secondaire()
    with st.expander("1 · Centres d'analyse : répartition primaire puis secondaire", expanded=False):
        c1, c2 = st.columns([3, 2])
        with c1:
            t = rep.copy()
            t["Unité d'œuvre"] = t["Centre"].map(C.UNITE_OEUVRE)
            st.dataframe(t.style.format({"Primaire": "{:,.0f}", "Reçu des auxiliaires": "{:,.0f}", "Total": "{:,.0f}"}), hide_index=True, width="stretch")
            st.caption(_md("Montants en k$. L'administration (900) et l'entretien des machines (600) sont des centres auxiliaires : ils sont reportés sur les centres "
                           "principaux avec des clés de répartition. Les centres d'analyse classiques divisent ensuite chaque centre par une seule unité d'œuvre : "
                           "les heures-machine pour l'usinage CNC, le coût de la main-d'œuvre directe pour les autres."))
        with c2:
            fig = go.Figure(go.Bar(x=rep["Centre"], y=rep["Primaire"], name="Primaire", marker_color="#8f9aa8"))
            fig.add_bar(x=rep["Centre"], y=rep["Reçu des auxiliaires"], name="Reçu des auxiliaires", marker_color=MARQUE)
            fig.update_layout(barmode="stack")
            _graphique(fig, "cr_rep", 260)

    d = C.cout_complet()
    methodes = ("Centres d'analyse", "ABC")
    couleurs = ["#8f9aa8", MARQUE]
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("###### Coût de revient ($ par pièce ou projet)")
        revient = pd.DataFrame({m: d[f"{m} : revient ($/unité)"] for m in methodes})
        fig = px.bar(revient.reset_index().melt(id_vars="index", var_name="Méthode", value_name="$/unité"), x="index", y="$/unité", color="Méthode", barmode="group",
                     labels={"index": ""}, color_discrete_sequence=couleurs, log_y=True)
        _graphique(fig, "cr_revient")
        st.caption("Échelle logarithmique : un projet de prototypage vaut des milliers de dollars, une pièce de contrat récurrent quelques dizaines.")
    with c2:
        st.markdown("###### Marge par unité ($)")
        marge = pd.DataFrame({m: d[f"{m} : marge ($/unité)"] for m in methodes})
        fig = px.bar(marge.reset_index().melt(id_vars="index", var_name="Méthode", value_name="$/unité"), x="index", y="$/unité", color="Méthode", barmode="group",
                     labels={"index": ""}, color_discrete_sequence=couleurs)
        fig.add_hline(y=0, line_color="#d03b3b")
        _graphique(fig, "cr_marge")

    st.markdown("###### Où se loge le coût indirect : charges ABC par unité, centre par produit")
    pools = C.repartition_secondaire().set_index("Centre")["Total"]
    vol = pd.Series({p: x["volume"] for p, x in C.PRODUITS.items()})
    carte = pd.DataFrame({c: (pools[c] * pd.Series(C.INDUCTEURS[c], dtype=float) / sum(C.INDUCTEURS[c].values())) / vol for c in pools.index}).T
    fig = go.Figure(go.Heatmap(z=carte.values, x=carte.columns, y=carte.index, colorscale=[[0, "#eaf1f7"], [1, MARQUE]], text=[[f"{v:,.0f} $".replace(",", " ") for v in r] for r in carte.values],
                               texttemplate="%{text}", hovertemplate="%{y} → %{x}<br>%{z:,.0f} $ par unité<extra></extra>", showscale=False))
    fig.update_yaxes(autorange="reversed")
    _graphique(fig, "cr_chaleur", 280)
    res = pd.DataFrame({"Produit": d.index, "Prix": d["Prix ($/unité)"], "Direct": d["Direct ($/unité)"]})
    for m in methodes:
        res[f"Revient {m}"] = d[f"{m} : revient ($/unité)"].values
    res["Écart ABC - centres"] = (d["ABC : revient ($/unité)"] - d["Centres d'analyse : revient ($/unité)"]).values
    st.dataframe(res.style.format({c: "{:,.2f}" for c in res.columns if c != "Produit"}), hide_index=True, width="stretch")
    ecart_rel = (d["ABC : revient ($/unité)"] - d["Centres d'analyse : revient ($/unité)"]) / d["Centres d'analyse : revient ($/unité)"]
    sous, sur = ecart_rel.idxmax(), ecart_rel.idxmin()
    _lecture(f"**Lecture.** Les centres d'analyse répartissent le gros des frais indirects selon la main-d'œuvre directe : ils sous-évaluent le coût de **{sous}** "
             f"({ecart_rel.max():+.0%} selon l'ABC) et sur-évaluent celui de **{sur}** ({ecart_rel.min():+.0%}). "
             "Le contrôle dimensionnel à 100 % et le suivi de configuration des contrats aéro et rail, l'ingénierie du prototypage, ne se voient pas dans les heures de machiniste. "
             "Un prix plancher fixé sur la main-d'œuvre serait donc trop bas là où l'on contrôle et programme le plus.")


# --- Prix et rentabilité ----------------------------------------------------------------------------------------------------------------------
def onglet_prix() -> None:
    _entete("À quel prix peut-on vendre, et jusqu'où peut-on négocier ?", "Planchers de prix (variable, spécifique, complet) et prix cible", "Politique de prix et soumissions", "Ventes et direction")
    marge = st.slider("Marge visée sur le coût complet ABC", 0, 40, 15, 1, format="%d %%", key="cr_marge_visee") / 100
    plan = C.planchers_prix(marge)
    p = st.selectbox("Ligne examinée", list(C.PRODUITS), key="cr_prix_ligne")
    d = C.cout_complet().loc[p]
    r = plan.set_index("Produit").loc[p]
    prod = C.PRODUITS[p]
    _cartes([("Prix actuel", _d(r["Prix actuel ($)"], 2), "par " + prod["unite"], "info"),
             ("Plancher complet ABC", _d(r["Plancher complet ABC ($)"], 2), "le prix couvre le coût complet" if r["Prix actuel ($)"] >= r["Plancher complet ABC ($)"] else "le prix est sous le coût complet",
              "ok" if r["Prix actuel ($)"] >= r["Plancher complet ABC ($)"] else "crit"),
             (f"Prix cible ({marge:.0%})", _d(r["Prix cible ($)"], 2), f"{r['Prix cible ($)'] / r['Prix actuel ($)'] - 1:+.1%} par rapport au prix actuel".replace(".", ","), "ok" if r["Prix actuel ($)"] >= r["Prix cible ($)"] else "att"),
             ("Position", r["Position"], "selon les trois planchers", "ok" if r["Position"] == "Au-dessus du prix cible" else ("att" if r["Position"] == "Sous le prix cible" else "crit"))])
    c1, c2 = st.columns(2)
    with c1:
        st.markdown(f"###### Du prix à la marge — {p} ($ par {prod['unite']})")
        abc = d["ABC : indirect ($/unité)"]
        mcv = prod["prix"] - C.direct_unitaire(p)
        fig = go.Figure(go.Waterfall(x=["Prix", "Matière", "Main-d'œuvre directe", "Frais variables", "Marge sur coûts variables", "Charges indirectes (ABC)", "Marge complète ABC"],
                                     measure=["absolute", "relative", "relative", "relative", "total", "relative", "total"],
                                     y=[prod["prix"], -prod["achat"], -prod["mod"], -prod["variable"], None, -abc, None], decreasing=dict(marker=dict(color="#d03b3b")),
                                     increasing=dict(marker=dict(color="#1baf7a")), totals=dict(marker=dict(color=MARQUE)), connector=dict(line=dict(color="#8f9aa8")),
                                     text=[f"{v:,.0f}".replace(",", " ") for v in [prod["prix"], -prod["achat"], -prod["mod"], -prod["variable"], mcv, -abc, mcv - abc]], textposition="outside"))
        _graphique(fig, "cr_cascade", 380)
    with c2:
        st.markdown("###### Position du prix par rapport aux planchers (en % du prix actuel)")
        fig = go.Figure()
        for _, x in plan.iterrows():
            pr = x["Prix actuel ($)"]
            fig.add_scatter(x=[x["Plancher variable ($)"] / pr * 100, x["Plancher spécifique ($)"] / pr * 100, x["Plancher complet ABC ($)"] / pr * 100, x["Prix cible ($)"] / pr * 100],
                            y=[x["Produit"]] * 4, mode="markers", showlegend=False, marker=dict(size=13, color=["#1baf7a", "#d9930a", "#d03b3b", MARQUE], line=dict(width=1, color="white")),
                            hovertemplate="%{x:.0f} % du prix actuel<extra></extra>")
        for nom, couleur in (("Plancher variable", "#1baf7a"), ("Plancher spécifique", "#d9930a"), ("Plancher complet ABC", "#d03b3b"), ("Prix cible", MARQUE)):
            fig.add_scatter(x=[None], y=[None], mode="markers", name=nom, marker=dict(size=11, color=couleur))
        fig.add_vline(x=100, line_dash="dash", line_color="#8f9aa8", annotation_text="prix actuel", annotation_position="top")
        fig.update_xaxes(title="% du prix actuel")
        _graphique(fig, "cr_planchers", 380)
        st.caption("Tout point à droite de la ligne pointillée est un seuil que le prix actuel ne franchit pas : le prix est alors sous ce plancher.")
    st.markdown("###### Couloir de prix par ligne")
    st.dataframe(plan.style.format({"Prix actuel ($)": "{:,.2f}", "Plancher variable ($)": "{:,.2f}", "Plancher spécifique ($)": "{:,.2f}", "Plancher complet ABC ($)": "{:,.2f}", "Prix cible ($)": "{:,.2f}",
                                    "Écart prix / cible (%)": "{:+.1%}"}), hide_index=True, width="stretch")
    sous = plan[plan["Prix actuel ($)"] < plan["Plancher complet ABC ($)"]]
    _lecture(f"**Lecture.** {len(sous)} ligne(s) se vendent sous leur coût complet ABC : **{', '.join(sous['Produit']) if len(sous) else 'aucune'}**. "
             "Sous le plancher variable, chaque pièce vendue aggrave le résultat ; entre le plancher variable et le plancher spécifique, la vente contribue mais la ligne ne couvre pas ses fixes ; "
             "entre le spécifique et le complet, elle couvre ses fixes mais pas sa part des frais communs. Un prix cible de " + f"{marge:.0%}" + " sur le coût ABC fixe la hausse à viser aux renouvellements.")


# --- Devis contre réel (coût par commande) ----------------------------------------------------------------------------------------------------
def onglet_commandes() -> None:
    _entete("Le prix soumis était-il le bon ? Que révèle le coût réel de chaque commande sur la qualité de nos estimations ?",
            "Coût par commande : devis contre réel, écart par élément de coût", "Soumissions, gabarits d'estimation et marges", "Ventes, estimation et production")
    seuil = st.slider("Seuil d'alerte : dépassement du devis", 1, 20, 5, 1, format="%d %%", key="cr_devis_seuil") / 100
    c, d, prec = C.commandes(), C.commandes_detail(), C.precision_soumissions(seuil)
    ecart = c["Écart ($)"].sum() / c["Coût estimé ($)"].sum()
    mp, mr = 1 - c["Coût estimé ($)"].sum() / c["Prix soumis ($)"].sum(), 1 - c["Coût réel ($)"].sum() / c["Prix soumis ($)"].sum()
    n_rev = int((c["Écart (%)"] > seuil).sum())
    pire = prec.sort_values("Écart moyen pondéré", ascending=False).iloc[0]
    _cartes([("Dépassement moyen du devis", f"{ecart:+.1%}".replace(".", ","), f"{_d(c['Écart ($)'].sum())} sur {len(c)} commandes", "ok" if ecart <= seuil else ("att" if ecart <= 2 * seuil else "crit")),
             ("Marge : soumise → réelle", f"{mp:.1%} → {mr:.1%}".replace(".", ","), f"{(mp - mr) * 100:.1f} points perdus".replace(".", ","), "ok" if mp - mr < .02 else ("att" if mp - mr < .06 else "crit")),
             ("Commandes à revoir", f"{n_rev} sur {len(c)}", f"dépassement de plus de {seuil:.0%}", "ok" if n_rev == 0 else ("att" if n_rev <= 2 else "crit")),
             ("Ligne la moins bien estimée", pire["Ligne"], f"{pire['Écart moyen pondéré']:+.0%} · dérive surtout : {pire['Poste qui dérive'].lower()}".replace(".", ","), "crit" if pire["Écart moyen pondéré"] > .1 else "att")])
    c = c.assign(Code=c["Commande"].str.split(" ").str[0])
    d = d.assign(Code=d["Commande"].str.split(" ").str[0])
    g1, g2 = st.columns(2)
    with g1:
        st.markdown("###### Marge soumise contre marge réelle")
        fig = go.Figure()
        fig.add_bar(x=c["Code"], y=c["Marge prévue (%)"] * 100, name="Marge soumise", marker_color="#8f9aa8", customdata=c["Commande"], hovertemplate="%{customdata}<br>soumise %{y:.1f} %<extra></extra>")
        fig.add_bar(x=c["Code"], y=c["Marge réelle (%)"] * 100, name="Marge réelle", marker_color=[FEU["ok"] if (a - b) * 100 < 2 else (FEU["att"] if (a - b) * 100 < 6 else FEU["crit"]) for a, b in zip(c["Marge prévue (%)"], c["Marge réelle (%)"])],
                    customdata=c["Commande"], hovertemplate="%{customdata}<br>réelle %{y:.1f} %<extra></extra>")
        fig.add_hline(y=0, line_color="#d03b3b")
        fig.update_layout(barmode="group")
        fig.update_yaxes(title="% du prix soumis")
        _graphique(fig, "cr_marges_cmd", 360)
    with g2:
        st.markdown("###### D'où vient le dépassement ? Écart par élément ($)")
        fig = px.bar(d, x="Code", y="Écart ($)", color="Élément", color_discrete_sequence=["#1f5f8b", "#2a78d6", "#d9930a", "#8f9aa8", "#d03b3b"], hover_name="Commande")
        fig.add_hline(y=0, line_color="#8f9aa8")
        fig.update_layout(barmode="relative")
        _graphique(fig, "cr_ecart_elements", 360)
    st.markdown("###### Précision des soumissions par ligne")
    st.dataframe(prec.style.format({"Écart moyen pondéré": "{:+.1%}", "Marge prévue (%)": "{:.1%}", "Marge réelle (%)": "{:.1%}", "Dérive du poste ($)": "{:,.0f}"}).background_gradient(
        subset=["Écart moyen pondéré"], cmap="RdYlGn_r", vmin=0, vmax=.5), hide_index=True, width="stretch")
    st.markdown("###### Une commande, du devis au réel")
    choix = st.selectbox("Commande", list(c["Commande"]), index=int(c["Écart (%)"].idxmax()), key="cr_cmd_choix")
    r = c.set_index("Commande").loc[choix]
    dd = d[d["Commande"] == choix].set_index("Élément")
    fig = go.Figure(go.Waterfall(x=["Coût estimé (devis)", *C.ELEMENTS_COMMANDE, "Coût réel"], measure=["absolute", *["relative"] * len(C.ELEMENTS_COMMANDE), "total"],
                                 y=[r["Coût estimé ($)"], *[dd.loc[e, "Écart ($)"] for e in C.ELEMENTS_COMMANDE], None], increasing=dict(marker=dict(color="#d03b3b")), decreasing=dict(marker=dict(color="#1baf7a")),
                                 totals=dict(marker=dict(color="#8f9aa8")), connector=dict(line=dict(color="#8f9aa8"))))
    fig.update_yaxes(range=[min(r["Coût estimé ($)"], r["Coût réel ($)"]) * .85, max(r["Coût estimé ($)"], r["Coût réel ($)"]) * 1.08])
    _graphique(fig, "cr_cmd_cascade", 330)
    st.caption(_md(f"Prix soumis {_d(r['Prix soumis ($)'])} · marge soumise {r['Marge prévue (%)']:.1%} · marge réelle {r['Marge réelle (%)']:.1%}. Taux machine standard {_d(C.taux_machine(), 2)}/h, "
                   f"main-d'œuvre {_d(C.STANDARD['taux'], 2)}/h : l'écart mesure le volume de travail (heures, reprises, sous-traitance), pas son prix.".replace(".", ",")))
    aero = prec.set_index("Ligne").loc["Contrats aéro et rail"]
    _lecture(f"**Lecture.** Les contrats aéro et rail se soumissionnent à {aero['Marge prévue (%)']:.0%} de marge et se réalisent à {aero['Marge réelle (%)']:.0%} : leurs gammes sont stables, l'estimation est fiable. "
             f"À l'inverse, **{pire['Ligne']}** dérive de {pire['Écart moyen pondéré']:+.0%} : les heures-machine et les réglages sont sous-estimés, et la marge soumise s'évapore. "
             "Un taux d'estimation qui ne s'améliore pas est un prix qui ne se défend pas : on recalibre les gabarits sur les commandes terminées, on garde une réserve pour les nouveautés, "
             "et on sort les prototypes du forfait pour les facturer au temps passé.")


# --- Imputation directs et indirects ----------------------------------------------------------------------------------------------------------
COULEUR_FLUX = {"direct": "rgba(27,175,122,.45)", "indirect": "rgba(217,147,10,.45)", "secondaire": "rgba(143,154,168,.45)"}


def _sankey(flux: pd.DataFrame) -> go.Figure:
    noeuds = list(dict.fromkeys([*flux["Source"], *flux["Cible"]]))
    idx = {n: i for i, n in enumerate(noeuds)}

    def couleur(n: str) -> str:
        if n in C.PRODUITS:
            return COULEURS[n]
        if n == "Charges directes":
            return "#1baf7a"
        if n == "Charges indirectes":
            return "#d9930a"
        if n in C.CENTRES_AUXILIAIRES or n in C.CENTRES_PRINCIPAUX:
            return "#6250d6" if n in C.CENTRES_AUXILIAIRES else "#2a78d6"
        return "#8f9aa8"
    return go.Figure(go.Sankey(
        arrangement="snap", node=dict(label=noeuds, color=[couleur(n) for n in noeuds], pad=12, thickness=16, line=dict(width=0)),
        link=dict(source=[idx[s] for s in flux["Source"]], target=[idx[t] for t in flux["Cible"]], value=flux["Montant (k$)"].round(1).tolist(),
                  color=[COULEUR_FLUX[f] for f in flux["Famille"]], hovertemplate="%{source.label} → %{target.label}<br>%{value:,.0f} k$<extra></extra>")))


def onglet_imputation() -> None:
    _entete("Par quel chemin chaque dollar de charge arrive-t-il jusqu'au produit ?", "Imputation : charges directes, centres d'analyse, puis inducteurs", "Traçabilité comptable et valorisation", "Comptabilité et contrôleur")
    famille = st.radio("Charges affichées", ["Tout", "Charges directes", "Charges indirectes"], index=2, horizontal=True, key="cr_imp_fam",
                       help="En vue « Tout », les charges directes occupent plus de la moitié du diagramme et rapetissent la chaîne des charges indirectes.")
    flux = C.imputation_flux(famille)
    postes = C.postes_comptables()
    direct, indirect = postes.query("Nature == 'Direct'")["Montant (k$)"].sum(), postes.query("Nature == 'Indirect'")["Montant (k$)"].sum()
    _cartes([("Charges directes", _k(direct), f"{direct / (direct + indirect):.1%} du total".replace(".", ","), "info"), ("Charges indirectes", _k(indirect), f"{indirect / (direct + indirect):.1%} du total".replace(".", ","), "att"),
             ("Coût complet absorbé", _k(direct + indirect), "comptes 5010, 5210, 6xxx, 7xxx, 8010", "info")])
    st.markdown("###### Du poste comptable au produit")
    _graphique(_sankey(flux), "cr_sankey", 680)
    st.caption(_md("Lecture de gauche à droite : poste comptable → nature (directe ou indirecte) → centres d'analyse (les centres auxiliaires, en violet, se déversent sur les "
                   "centres principaux, en bleu) → produit. Vert : affectation directe ; ambre : charges indirectes ; gris : répartition secondaire. Montants en k$."))
    st.markdown("###### Coût de revient complet par unité, par composante")
    comp = C.cout_complet_par_composante()
    long = comp.reset_index(names="Produit").melt(id_vars="Produit", var_name="Composante", value_name="$/unité")
    fig = px.bar(long, x="$/unité", y="Produit", color="Composante", orientation="h", barmode="stack",
                 color_discrete_sequence=["#1f5f8b", "#2a78d6", "#7bb3e6", "#d9930a", "#eda100", "#f2c46a", "#8f9aa8", "#c3c9d1"])
    fig.update_yaxes(categoryorder="array", categoryarray=list(C.PRODUITS)[::-1])
    _graphique(fig, "cr_composantes", 320)
    prix = pd.Series({p: d["prix"] for p, d in C.PRODUITS.items()})
    total = comp.sum(axis=1)
    n_dir = len(C.COMPTES_DIRECTS)
    resume = pd.DataFrame({"Charges directes ($/unité)": comp.iloc[:, :n_dir].sum(axis=1), "Charges indirectes ($/unité)": comp.iloc[:, n_dir:].sum(axis=1),
                           "Revient complet ($/unité)": total, "Prix ($/unité)": prix, "Marge ($/unité)": prix - total}).reset_index(names="Produit")
    st.dataframe(resume.style.format({c: "{:,.2f}" for c in resume.columns if c != "Produit"}), hide_index=True, width="stretch")
    st.markdown("###### Postes comptables et mode d'imputation")
    f_nature = st.segmented_control("Nature", ["Direct", "Indirect"], default=["Direct", "Indirect"], selection_mode="multi", key="cr_imp_nat")
    t = postes[postes["Nature"].isin(f_nature or [])]
    t = t.groupby(["Compte", "Poste", "Nature", "Mode", "Imputé à"], as_index=False)["Montant (k$)"].sum().sort_values(["Compte", "Imputé à"])
    st.dataframe(t.style.format({"Montant (k$)": "{:,.0f}"}), hide_index=True, width="stretch")
    _lecture("**Lecture.** Les comptes 5010 (matières), 6030 (main-d'œuvre directe) et 5210 (outillage et énergie machine imputables) se rattachent directement au produit : aucune clé de "
             "répartition n'est nécessaire. Les autres postes (6xxx, 7xxx, 8010) sont communs à plusieurs produits : ils sont d'abord regroupés par centre, puis répartis par l'inducteur de "
             "l'activité. Le compte 6030 se retrouve des deux côtés (la part directe suit les heures du produit, la part indirecte — réglages, surveillance, inspection — passe par les centres), "
             "et le compte 8010 (amortissement) alimente trois centres.")


# --- Coûts partiels ---------------------------------------------------------------------------------------------------------------------------
def onglet_marge() -> None:
    _entete("Que gagne-t-on, ou perd-on, si le volume, le prix ou l'offre changent ?", "Coûts variables, point mort, levier et coûts pertinents", "Décisions à court terme : volumes, prix, abandon, commande spéciale", "Direction et ventes")
    c1, c2 = st.columns(2)
    vol = c1.slider("Variation des volumes", -30, 30, 0, 1, format="%d %%", key="cr_vol") / 100
    prix = c2.slider("Variation des prix de vente", -5.0, 5.0, 0.0, 0.5, format="%.1f %%", key="cr_prix") / 100
    df = C.contribution(vol, prix)
    r = C.resultat_et_point_mort(df)
    lev = C.levier_exploitation()
    _cartes([("Marge sur coûts variables", _k(r["mcv"]), f"taux {r['taux_mcv']:.1%}".replace(".", ","), "info"), ("Charges fixes", _k(r["fixes"]), "spécifiques + communes", "info"),
             ("Résultat d'exploitation", _k(r["resultat"]), f"{r['resultat'] / r['ventes']:.1%} des ventes".replace(".", ","), "ok" if r["resultat"] > 0 else "crit"),
             ("Point mort (ventes)", _k(r["point_mort"]), f"marge de sécurité {r['marge_securite']:.1%}".replace(".", ","), "ok" if r["marge_securite"] >= .2 else "att"),
             ("Levier d'exploitation", f"{lev['degre_levier']:.1f} ×".replace(".", ","), "1 % de volume = " + f"{lev['degre_levier']:.1f} % de résultat".replace(".", ","), "att" if lev["degre_levier"] > 3 else "ok")])
    t = df.set_index("Produit")
    fig = go.Figure()
    fig.add_bar(x=t.index, y=t["MCV (k$)"], name="Marge sur coûts variables", marker_color=MARQUE)
    fig.add_bar(x=t.index, y=-t["Fixes spécifiques (k$)"], name="Fixes spécifiques", marker_color="#d03b3b")
    fig.add_scatter(x=t.index, y=t["Marge spécifique (k$)"], name="Marge sur coûts spécifiques", mode="markers+text", marker=dict(size=13, color="#1b2430", line=dict(width=2, color="white")),
                    text=[f"{v:,.0f}".replace(",", " ") for v in t["Marge spécifique (k$)"]], textposition="top center")
    fig.update_layout(barmode="relative")
    _graphique(fig, "cr_contrib", 360)
    st.dataframe(df.style.format({"Ventes (k$)": "{:,.0f}", "Coûts variables (k$)": "{:,.0f}", "MCV (k$)": "{:,.0f}", "Taux de MCV": "{:.1%}",
                                  "Fixes spécifiques (k$)": "{:,.0f}", "Marge spécifique (k$)": "{:,.0f}"}), hide_index=True, width="stretch")
    st.caption("Les coûts variables comprennent la matière, la main-d'œuvre directe (payée aux heures travaillées) et l'outillage imputable ; les fixes spécifiques sont les équipements, "
               "les outillages dédiés et les équipes que la disparition de la ligne ferait disparaître.")

    c1, c2 = st.columns([3, 2])
    with c1:
        st.markdown("###### Sensibilité du résultat à ±10 % de chaque facteur (tornado)")
        s = C.sensibilite_resultat(0.10).iloc[::-1]
        fig = go.Figure()
        fig.add_bar(y=s["Facteur"], x=s["Défavorable (k$)"], orientation="h", name="Défavorable", marker_color="#d03b3b", text=[f"{v:,.0f}".replace(",", " ") for v in s["Défavorable (k$)"]], textposition="outside")
        fig.add_bar(y=s["Facteur"], x=s["Favorable (k$)"], orientation="h", name="Favorable", marker_color="#1baf7a", text=[f"+{v:,.0f}".replace(",", " ") for v in s["Favorable (k$)"]], textposition="outside")
        fig.update_layout(barmode="relative")
        fig.update_xaxes(title="Effet sur le résultat d'exploitation (k$)")
        _graphique(fig, "cr_tornado", 330)
    with c2:
        st.markdown("###### Point mort de chaque ligne")
        pm = C.point_mort_produits()
        fig = go.Figure(go.Bar(x=pm["Produit"], y=pm["Point mort / volume"] * 100, marker_color=["#d03b3b" if v > 100 else MARQUE for v in pm["Point mort / volume"] * 100],
                               text=[f"{v:.0f} %" for v in pm["Point mort / volume"] * 100], textposition="outside"))
        fig.add_hline(y=100, line_dash="dash", line_color="#8f9aa8", annotation_text="volume actuel")
        fig.update_yaxes(title="Point mort en % du volume actuel")
        _graphique(fig, "cr_pm", 330)
    levier = f"{lev['degre_levier']:.1f}".replace(".", ",")
    _lecture(f"**Lecture.** Avec un levier de {levier} ×, le résultat varie {levier} fois plus vite que les volumes : une baisse de 10 % des volumes retire {_k(-s.set_index('Facteur').loc['Volumes', 'Défavorable (k$)'])}. "
             "Le prix est de loin le facteur le plus puissant : 10 % de prix valent plus que 10 % de volume. Le prototypage ne couvrirait ses fixes spécifiques qu'en plus que triplant son volume.")

    st.markdown("###### Faut-il abandonner une ligne ?")
    p = st.selectbox("Ligne examinée", list(C.PRODUITS), index=3, key="cr_abandon")
    delta = C.abandon(p, df)
    ligne = t.loc[p]
    if delta > 0:
        st.warning(_md(f"Abandonner **{p}** améliorerait le résultat de **{_k(delta)}** : sa marge ({_k(ligne['MCV (k$)'])}) ne couvre pas ses fixes "
                       f"spécifiques évitables ({_k(ligne['Fixes spécifiques (k$)'])}). À confirmer par les effets indirects : les prototypes préparent les séries d'usinage sur mesure et les contrats "
                       "récurrents, l'équipe d'ingénierie sert aussi les soumissions, et des clients pourraient partir."))
    else:
        st.success(_md(f"Garder **{p}** : elle contribue pour **{_k(-delta)}** aux fixes communs ({_k(C.FIXES_COMMUNES)}) ; l'abandonner dégraderait le résultat d'autant."))
    st.caption(_md("Les fixes communs ne sont pas évitables en abandonnant une ligne : les répartir sur elle (coût complet) la ferait paraître déficitaire à tort."))

    _section("Faut-il accepter une commande spéciale à prix réduit ?")
    a, b, c, d = st.columns([2, 1.3, 1.3, 1.4])
    lig = a.selectbox("Ligne", list(C.PRODUITS), index=2, key="cr_cs_ligne")
    base = C.PRODUITS[lig]
    qte = b.number_input(f"Quantité ({base['unite']}s)", 1.0, 1_000_000.0, 5000.0, 100.0, key="cr_cs_q")
    prix_cs = c.number_input("Prix offert ($ l'unité)", 0.01, 100_000.0, round(base["prix"] * 0.65, 2), 1.0, key="cr_cs_p")
    libre = d.toggle("Capacité disponible", True, key="cr_cs_libre", help="Désactivé : la commande prend la place de ventes régulières aux heures-machine contraintes.")
    cs = C.commande_speciale(lig, qte, prix_cs, libre)
    _cartes([("Marge unitaire sur coûts variables", _d(cs["marge_unitaire"], 2), f"prix {_d(prix_cs, 2)} − variable {_d(C.direct_unitaire(lig), 2)}", "ok" if cs["marge_unitaire"] > 0 else "crit"),
             ("Contribution de la commande", _d(cs["contribution"]), f"{cs['heures']:,.0f} heures-machine".replace(",", " "), "info"),
             ("Coût d'opportunité", _d(cs["cout_opportunite"]), "aucune vente régulière déplacée" if libre else "marge régulière sacrifiée sur les heures prises", "ok" if libre else "att"),
             ("Contribution nette", _d(cs["contribution_nette"]), "ACCEPTER" if cs["accepter"] else "REFUSER", "ok" if cs["accepter"] else "crit")])
    _lecture(f"**Lecture.** Seuls les coûts qui diffèrent comptent : le coût variable de {_d(C.direct_unitaire(lig), 2)} l'unité, et rien des charges fixes, qui existent avec ou sans la commande. "
             f"{'La capacité dort : toute marge positive améliore le résultat' if libre else 'La capacité est pleine : la commande doit rapporter plus que les ventes régulières qu\'elle déplace, soit un plancher de ' + _d(cs['plancher'], 2) + ' l\'unité'}. "
             "Garde-fous : que la commande ne crée pas de précédent de prix chez les clients réguliers, et qu'elle ne mobilise pas une capacité qu'on aurait pu vendre au prix courant.")


# --- Standards et écarts ----------------------------------------------------------------------------------------------------------------------
def onglet_ecarts() -> None:
    _entete("Pourquoi le coût réel n'est-il pas celui qui était prévu, et quels écarts méritent qu'on s'y arrête ?", "Coûts standards : matière, main-d'œuvre, frais variables et fixes, limites de contrôle", "Contrôle et responsabilisation", "Production, achats et finances")
    S = C.STANDARD
    st.caption(_md(f"Standards par pièce : {S['kg_par_piece']} kg de barre d'aluminium 6061 (copeaux et chutes compris) à {S['prix']:.2f} $/kg ; {S['heures_par_piece']} h de main-d'œuvre à "
                   f"{S['taux']:.0f} $/h ; frais variables de {S['variable_par_piece']:.2f} $. Exemple : la production d'un mois."))
    a, b, c = st.columns(3)
    pieces = a.number_input("Pièces produites", 100.0, 20000.0, 2000.0, 50.0, key="cr_e_pieces")
    kg = b.number_input("Barre achetée (kg)", 100.0, 100000.0, 5010.0, 10.0, key="cr_e_kg")
    prix = c.number_input("Prix d'achat réel ($/kg)", 3.0, 15.0, 8.05, 0.05, format="%.2f", key="cr_e_prix")
    d1, d2, d3 = st.columns(3)
    h = d1.number_input("Heures de main-d'œuvre réelles", 100.0, 20000.0, 1830.0, 10.0, key="cr_e_h")
    tx = d2.number_input("Taux horaire réel ($/h)", 20.0, 120.0, 60.5, 0.5, key="cr_e_tx")
    fv = d3.number_input("Frais variables réels ($)", 0.0, 100000.0, 6900.0, 100.0, key="cr_e_fv")
    e = C.ecarts(pieces, kg, prix, h, tx, fv)
    ecarts = {k: v for k, v in e.items() if not k.startswith("_")}
    _cartes([("Coût standard de la production réelle", _d(e["_cout_standard"]), f"{_d(e['_cout_standard'] / pieces, 2)} par pièce", "info"), ("Coût réel", _d(e["_cout_reel"]), f"{_d(e['_cout_reel'] / pieces, 2)} par pièce", "info"),
             ("Écart total", _d(e["_total"]), f"{_fav(e['_total'])} · {e['_total'] / e['_cout_standard']:+.1%}".replace(".", ","),
              "ok" if abs(e["_total"]) / e["_cout_standard"] <= 0.03 else ("att" if abs(e["_total"]) / e["_cout_standard"] <= 0.07 else "crit"))])
    fig = go.Figure(go.Waterfall(x=["Coût standard", *ecarts, "Coût réel"], measure=["absolute", *["relative"] * len(ecarts), "total"],
                                 y=[e["_cout_standard"], *ecarts.values(), None], increasing=dict(marker=dict(color="#d03b3b")),
                                 decreasing=dict(marker=dict(color="#1baf7a")), totals=dict(marker=dict(color="#8f9aa8")), connector=dict(line=dict(color="#8f9aa8"))))
    fig.update_yaxes(range=[min(e["_cout_standard"], e["_cout_reel"]) * .9, max(e["_cout_standard"], e["_cout_reel"]) * 1.05])
    _graphique(fig, "cr_waterfall", 360)

    st.markdown("###### Frais généraux fixes : écart de budget et écart de volume")
    fixes = st.number_input("Frais fixes de fabrication dépensés dans le mois ($)", 10000.0, 80000.0, 31900.0, 100.0, key="cr_e_ff",
                            help=f"Budget : {C.FIXES_STANDARD['budget_mensuel']:,.0f} $ pour une production normale de {C.FIXES_STANDARD['volume_normal']:,.0f} pièces.".replace(",", " "))
    ff = C.ecarts_frais_fixes(pieces, fixes)
    _cartes([("Taux d'imputation prédéterminé", f"{_d(ff['taux'], 2)} par pièce", f"budget {_d(ff['budget'])} ÷ {C.FIXES_STANDARD['volume_normal']:,.0f} pièces".replace(",", " "), "info"),
             ("Écart de budget", _d(ff["ecart_budget"]), f"dépensé {_d(ff['reel'])} contre budgété · {_fav(ff['ecart_budget'])}", "ok" if ff["ecart_budget"] <= 0 else "att"),
             ("Écart de volume", _d(ff["ecart_volume"]), f"production à {ff['utilisation']:.0%} de la normale · {_fav(ff['ecart_volume'])}".replace(".", ","), "ok" if ff["ecart_volume"] <= 0 else "att"),
             ("Sous-imputation totale", _d(ff["sous_imputation"]), "charge de la période, hors du coût des pièces" if ff["sous_imputation"] > 0 else "sur-imputation : boni de la période",
              "ok" if abs(ff["sous_imputation"]) <= .02 * ff["budget"] else "att")])
    fig = go.Figure(go.Waterfall(x=["Imputés aux pièces", "Écart de volume", "Écart de budget", "Dépensés"], measure=["absolute", "relative", "relative", "total"],
                                 y=[ff["imputes"], ff["ecart_volume"], ff["ecart_budget"], None], increasing=dict(marker=dict(color="#d03b3b")), decreasing=dict(marker=dict(color="#1baf7a")),
                                 totals=dict(marker=dict(color="#8f9aa8")), connector=dict(line=dict(color="#8f9aa8")),
                                 text=[_d(ff["imputes"]), _d(ff["ecart_volume"]), _d(ff["ecart_budget"]), _d(ff["reel"])], textposition="outside"))
    fig.update_yaxes(range=[min(ff["imputes"], ff["reel"]) * .9, max(ff["imputes"], ff["reel"]) * 1.06])
    _graphique(fig, "cr_ff", 300)
    st.caption(_md("Les frais fixes sont imputés aux pièces au taux prédéterminé. L'écart de budget (dépensé moins budgété) relève des responsables de dépenses ; l'écart de volume "
                   "(budgété moins imputé) vient d'une production inférieure à la normale : c'est de la capacité non remplie, pas une dépense de trop."))

    st.markdown("###### Règle d'investigation et limites de contrôle")
    r1, r2 = st.columns(2)
    sp = r1.slider("Seuil en % du coût standard", 1, 15, 5, 1, format="%d %%", key="cr_seuil_p") / 100
    sd = r2.number_input("Seuil en dollars", 0.0, 50000.0, 2500.0, 250.0, key="cr_seuil_d")
    hist = C.historique_ecarts(courant=ecarts)
    lim = C.limites_controle(hist)
    t = pd.DataFrame({"Cause": list(ecarts), "Écart ($)": list(ecarts.values())})
    t["Nature"] = t["Écart ($)"].map(_fav)
    t["Moyenne 11 mois ($)"] = [lim.loc[k, "Moyenne"] for k in ecarts]
    t["Limite haute ($)"] = [lim.loc[k, "Limite haute"] for k in ecarts]
    t["À investiguer"] = ["Oui" if C.investigation(v, e["_cout_standard"], sp, sd) else "Non" for v in ecarts.values()]
    t["Hors limites"] = ["Oui" if lim.loc[k, "Hors limites"] else "Non" for k in ecarts]
    t["Responsable probable"] = ["Approvisionnement", "Production (programmation, outils de coupe)", "Ressources humaines et paie", "Planification et réglages", "Production"]
    st.dataframe(t.style.format({"Écart ($)": "{:,.0f}", "Moyenne 11 mois ($)": "{:,.0f}", "Limite haute ($)": "{:,.0f}"}).map(
        lambda v: "color:#d03b3b;font-weight:700" if v == "Oui" else "", subset=["À investiguer", "Hors limites"]), hide_index=True, width="stretch")
    cause = st.selectbox("Carte de contrôle de la cause", list(ecarts), index=3, key="cr_carte_cause")
    serie = hist[cause]
    mu, sig = lim.loc[cause, "Moyenne"], lim.loc[cause, "Écart-type"]
    fig = go.Figure()
    fig.add_scatter(x=serie.index, y=serie.values, mode="lines+markers", name="Écart mensuel", line=dict(color=MARQUE, width=2),
                    marker=dict(size=[7] * (len(serie) - 1) + [14], color=[MARQUE] * (len(serie) - 1) + ["#d03b3b" if lim.loc[cause, "Hors limites"] else "#1baf7a"], line=dict(width=1, color="white")))
    fig.add_hline(y=mu, line_color="#8f9aa8", annotation_text="moyenne")
    fig.add_hline(y=lim.loc[cause, "Limite haute"], line_dash="dash", line_color="#d03b3b", annotation_text="limite haute (+2σ)")
    fig.add_hline(y=max(lim.loc[cause, "Limite basse"], 0), line_dash="dash", line_color="#1baf7a", annotation_text="limite basse (−2σ)")
    fig.update_yaxes(title="Écart ($)")
    _graphique(fig, "cr_carte", 320)
    st.caption("Les 11 premiers mois fixent la moyenne et les limites (± 2 écarts-types) ; le dernier point est le mois saisi ci-dessus. Un point hors limites n'est pas du hasard : c'est un signal.")

    st.markdown("###### L'écart de prix de la matière : marché ou achat ?")
    m1, m2 = st.columns(2)
    vm = m1.slider("Variation du prix du métal depuis la fixation du standard", -20.0, 20.0, 3.0, 0.5, format="%.1f %%", key="cr_var_marche") / 100
    pm_ = m2.slider("Part du prix d'achat qui suit le marché", 10, 100, 55, 5, format="%d %%", key="cr_part_marche") / 100
    dec = C.decomposer_ecart_prix(ecarts["Prix de la matière"], vm, pm_, S["prix"], kg)
    _cartes([("Écart de prix de la matière", _d(dec["ecart_total"]), _fav(dec["ecart_total"]), "info"), ("Expliqué par le marché", _d(dec["effet_marche"]), "hors du contrôle de l'acheteur", "att"),
             ("Relève de l'achat", _d(dec["effet_achat"]), "surcharges, quantités, délais : négociable", "ok" if dec["effet_achat"] <= 0 else "crit")])
    pire = max(ecarts, key=ecarts.get)
    _lecture(f"**Lecture.** Le plus gros écart défavorable est « {pire} » ({_d(ecarts[pire])}). Un écart sert à désigner qui questionner, pas à conclure : "
             f"sur les {_d(dec['ecart_total'])} d'écart de prix, {_d(dec['effet_marche'])} suivent le marché des métaux (vue « Prix des métaux ») et ne se négocient pas ; le reste est l'affaire de l'acheteur.")


# --- Capacité et mix --------------------------------------------------------------------------------------------------------------------------
def onglet_capacite() -> None:
    _entete("Les machines sont-elles assez occupées, et que faire passer en premier quand elles manquent ?", "Imputation rationnelle et théorie des contraintes", "Capacité, investissement, mix et ordonnancement", "Opérations et direction")
    st.markdown("###### Utilisation et sous-activité par centre")
    cn = st.slider("Capacité normale du centre d'usinage CNC (heures-machine par année)", 30000, 60000, 40000, 500, key="cr_cap_cnc")
    cap = C.capacite_centres({**C.CAPACITE_NORMALE, "Usinage CNC": float(cn)})
    sous = float(cap["Coût de sous-activité (k$)"].clip(lower=0).sum())
    _cartes([("Sous-activité totale", _k(sous), "charge de la période", "att" if sous > 0 else "ok"), ("Utilisation du centre CNC", f"{cap.set_index('Centre').loc['Usinage CNC', 'Utilisation']:.0%}", "cible 80 % à 95 %",
              "ok" if 0.8 <= cap.set_index("Centre").loc["Usinage CNC", "Utilisation"] <= 0.95 else "att"),
             ("Fixes par heure-machine : complet / IRCF", f"{cap.set_index('Centre').loc['Usinage CNC', 'Taux fixe réel ($/unité)']:.1f} / {cap.set_index('Centre').loc['Usinage CNC', 'Taux fixe normal ($/unité)']:.1f} $".replace(".", ","),
              "le coût complet gonfle le prix d'une heure quand la machine est vide", "info")])
    c1, c2 = st.columns(2)
    with c1:
        fig = go.Figure(go.Bar(y=cap["Centre"], x=cap["Utilisation"] * 100, orientation="h", marker_color=[FEU["ok"] if 80 <= u * 100 <= 95 else FEU["att"] for u in cap["Utilisation"]],
                               text=[f"{u:.0%}" for u in cap["Utilisation"]], textposition="outside"))
        fig.add_vrect(x0=80, x1=95, fillcolor="rgba(27,175,122,.12)", line_width=0, annotation_text="zone cible", annotation_position="top left")
        fig.update_xaxes(title="Utilisation (%)", range=[0, 110])
        fig.update_yaxes(autorange="reversed")
        _graphique(fig, "cr_util", 300)
    with c2:
        fig = go.Figure(go.Bar(y=cap["Centre"], x=cap["Coût de sous-activité (k$)"], orientation="h", marker_color="#d9930a", text=[f"{v:,.0f} k$".replace(",", " ") for v in cap["Coût de sous-activité (k$)"]], textposition="outside"))
        fig.update_xaxes(title="Coût de sous-activité (k$)")
        fig.update_yaxes(autorange="reversed")
        _graphique(fig, "cr_sousact", 300)
    st.dataframe(cap.style.format({"Activité réelle": "{:,.0f}", "Capacité normale": "{:,.0f}", "Utilisation": "{:.1%}", "Charges du centre (k$)": "{:,.0f}", "Charges fixes (k$)": "{:,.0f}",
                                   "Taux fixe normal ($/unité)": "{:,.2f}", "Taux fixe réel ($/unité)": "{:,.2f}", "Coût de sous-activité (k$)": "{:,.0f}"}), hide_index=True, width="stretch")
    st.caption("Charges fixes = 85 % des charges du centre (après répartition secondaire). Sous-activité = charges fixes × (1 − utilisation). Le taux « normal » reste le même quel que soit le volume ; "
               "le taux « réel » grimpe quand les machines se vident.")

    st.markdown("###### Mix qui maximise la marge quand les heures-machine sont rares")
    m1, m2 = st.columns(2)
    capm = m1.slider("Capacité disponible (heures-machine)", 20000, 60000, 40000, 500, key="cr_mix_cap")
    cro = m2.slider("Croissance maximale de la demande par ligne", 0, 50, 20, 5, format="%d %%", key="cr_mix_cro") / 100
    mix = C.mix_capacite(float(capm), cro)
    _cartes([("Contrainte de capacité", "Active" if mix.attrs["contrainte_active"] else "Inactive", "toute heure supplémentaire a une valeur" if mix.attrs["contrainte_active"] else f"{mix.attrs['heures_inutilisees']:,.0f} h inutilisées".replace(",", " "),
              "att" if mix.attrs["contrainte_active"] else "ok"),
             ("Valeur d'une heure-machine de plus", _d(mix.attrs["prix_ombre"]), "prix implicite de la capacité", "info"),
             ("Marge sur coûts variables : mix optimal", _k(mix.attrs["mcv_optimale"]), f"{mix.attrs['mcv_optimale'] - mix.attrs['mcv_actuelle']:+,.0f} k$ contre le mix actuel".replace(",", " "),
              "ok" if mix.attrs["mcv_optimale"] >= mix.attrs["mcv_actuelle"] else "crit")])
    fig = go.Figure()
    fig.add_bar(x=mix["Produit"], y=mix["Heures actuelles"], name="Heures actuelles", marker_color="#8f9aa8")
    fig.add_bar(x=mix["Produit"], y=mix["Heures allouées"], name="Heures allouées (mix optimal)", marker_color=MARQUE)
    fig.add_scatter(x=mix["Produit"], y=mix["MCV par heure-machine ($)"], name="MCV par heure-machine ($, axe de droite)", yaxis="y2", mode="markers+text", marker=dict(size=14, color="#d9930a", line=dict(width=2, color="white")),
                    text=[f"{v:,.0f} $".replace(",", " ") for v in mix["MCV par heure-machine ($)"]], textposition="top center")
    fig.update_layout(barmode="group", yaxis2=dict(overlaying="y", side="right", title="MCV par heure ($)", showgrid=False), yaxis=dict(title="Heures-machine"))
    _graphique(fig, "cr_mix", 360)
    st.dataframe(mix.style.format({"Heures par unité": "{:.2f}", "MCV par unité ($)": "{:,.0f}", "MCV par heure-machine ($)": "{:,.0f}", "Heures actuelles": "{:,.0f}", "Demande max (heures)": "{:,.0f}",
                                   "Heures allouées": "{:,.0f}", "Volume optimal (milliers)": "{:,.1f}", "Variation vs actuel": "{:+.0%}", "MCV optimale (k$)": "{:,.0f}", "MCV actuelle (k$)": "{:,.0f}"}),
                 hide_index=True, width="stretch")
    st.warning("Ce mix ne tient pas compte des charges fixes spécifiques ni des engagements contractuels : il guide l'ordonnancement et les soumissions quand la charge dépasse la capacité, "
               "il ne justifie pas à lui seul d'abandonner une ligne.")
    _lecture(f"**Lecture.** Quand les heures-machine sont rares, on classe les lignes par marge sur coûts variables **par heure-machine**, pas par marge unitaire ni par marge totale : "
             f"{mix.iloc[0]['Produit']} rapporte {_d(mix.iloc[0]['MCV par heure-machine ($)'])} l'heure, {mix.iloc[-1]['Produit']} seulement {_d(mix.iloc[-1]['MCV par heure-machine ($)'])}. "
             "Sous la capacité actuelle, la ligne la moins rentable à l'heure est la première à sacrifier ; au-dessus, elle est la dernière à servir.")


# --- Coûts cibles et feature costing ----------------------------------------------------------------------------------------------------------
def onglet_cible() -> None:
    _entete("Combien peut-on dépenser pour une offre, étant donné ce que le marché accepte de payer ?", "Coût cible, feature costing, ABM et coût de la qualité", "Conception, nouveaux contrats et amélioration continue", "Ingénierie, ventes et qualité")
    st.caption("Exemple : un contrat de pièces d'aéronautique certifié, en série (prix par pièce).")
    a, b, c = st.columns(3)
    prix = a.number_input("Prix de marché de la pièce ($)", 20.0, 2000.0, 185.0, 5.0, key="cr_c_prix")
    marge = b.slider("Marge visée", 5, 40, 20, 1, format="%d %%", key="cr_c_marge") / 100
    produit = c.number_input("Coût de la matière ($/pièce)", 0.0, 1000.0, 48.0, 1.0, key="cr_c_prod")
    st.markdown("###### Caractéristiques de l'offre (modifiables)")
    carac = st.data_editor(C.CARACTERISTIQUES, hide_index=True, width="stretch", key="cr_c_edit", num_rows="fixed",
                           column_config={"Caractéristique": st.column_config.TextColumn(disabled=True),
                                          "Coût estimé ($/pièce)": st.column_config.NumberColumn(min_value=0.0, step=1.0),
                                          "Importance pour le client (%)": st.column_config.NumberColumn(min_value=0.0, step=1.0)})
    if carac["Importance pour le client (%)"].sum() <= 0:
        st.warning("Au moins une caractéristique doit avoir une importance supérieure à zéro.")
        return
    cadre, t = C.cout_cible(prix, marge, produit, carac)
    _cartes([("Coût admissible", _d(cadre["admissible"]), f"prix {_d(prix)} moins marge {marge:.0%}", "info"), ("Enveloppe pour les caractéristiques", _d(cadre["enveloppe"]), "après le coût de la matière", "info"),
             ("Coût estimé actuel", _d(cadre["estime"]), "somme des caractéristiques", "info"),
             ("Écart à réduire", _d(cadre["ecart"]), _fav(cadre["ecart"]), "ok" if cadre["ecart"] <= 0 else "crit")])
    fig = go.Figure()
    fig.add_bar(x=t["Caractéristique"], y=t["Part du coût"] * 100, name="Part du coût", marker_color="#d9930a")
    fig.add_bar(x=t["Caractéristique"], y=t["Part de la valeur"] * 100, name="Part de la valeur perçue", marker_color=MARQUE)
    fig.update_layout(barmode="group", yaxis_title="%")
    fig.update_xaxes(tickangle=-12)
    _graphique(fig, "cr_feature", 360)
    aff = t[["Caractéristique", "Coût estimé ($/pièce)", "Coût cible ($/pièce)", "Écart à réduire ($)", "Ratio coût / valeur"]]
    st.dataframe(aff.style.format({"Coût estimé ($/pièce)": "{:,.2f}", "Coût cible ($/pièce)": "{:,.2f}", "Écart à réduire ($)": "{:+,.2f}", "Ratio coût / valeur": "{:.2f}"})
                 .background_gradient(subset=["Ratio coût / valeur"], cmap="RdYlGn_r", vmin=.5, vmax=1.8), hide_index=True, width="stretch")
    pire, mieux = t.loc[t["Ratio coût / valeur"].idxmax()], t.loc[t["Ratio coût / valeur"].idxmin()]
    _lecture(f"**Lecture (feature costing).** « {pire['Caractéristique']} » coûte {pire['Ratio coût / valeur']:.1f} fois sa valeur perçue : c'est la première à "
             f"simplifier ou à re-concevoir (plan de contrôle par échantillonnage, par exemple). « {mieux['Caractéristique']} » est sous-investie par rapport à ce que le client en attend "
             f"({mieux['Ratio coût / valeur']:.1f} fois).")


# --- ABM / PBM / qualité ----------------------------------------------------------------------------------------------------------------------
def onglet_abm() -> None:
    _section("Activités et qualité : où le coût se crée-t-il, et qu'apporte-t-il au client ?")
    st.markdown("###### Scénario d'amélioration")
    cibles = st.multiselect("Activités à réduire", C.ACTIVITES.loc[C.ACTIVITES["Classe"] != "Valeur ajoutée", "Activité"].tolist(),
                            default=["Attente entre opérations (encours)", "Reprises, retouches et rebuts", "Corrections de factures"], key="cr_a_cibles")
    taux = st.slider("Réduction visée sur ces activités", 0, 100, 50, 5, format="%d %%", key="cr_a_taux") / 100
    t = C.scenario_abm({a: taux for a in cibles})
    total, apres = t["Coût (k$)"].sum(), t["Coût après (k$)"].sum()
    par_classe = t.groupby("Classe")["Coût (k$)"].sum().reindex(C.CLASSES)
    _cartes([("Coût du processus", _k(total), "toutes activités", "info"), ("Part à valeur ajoutée", f"{par_classe['Valeur ajoutée'] / total:.0%}", "cible : plus de 50 %", "ok" if par_classe["Valeur ajoutée"] / total >= .5 else "att"),
             ("Part sans valeur", f"{par_classe['Sans valeur'] / total:.0%}", "à réduire", "att"), ("Économie du scénario", _k(total - apres), f"{(total - apres) / total:.1%}".replace(".", ","), "ok")])
    c1, c2 = st.columns(2)
    with c1:
        fig = px.treemap(t, path=[px.Constant("Groupe Usinage Saint-Maurice"), "Processus", "Activité"], values="Coût (k$)", color="Classe", color_discrete_map=COULEUR_CLASSE)
        _graphique(fig, "cr_treemap", 380)
    with c2:
        proc = t.groupby("Processus")[["Coût (k$)", "Coût après (k$)"]].sum().reset_index()
        fig = go.Figure()
        fig.add_bar(y=proc["Processus"], x=proc["Coût (k$)"], name="Avant", orientation="h", marker_color="#8f9aa8")
        fig.add_bar(y=proc["Processus"], x=proc["Coût après (k$)"], name="Après", orientation="h", marker_color=MARQUE)
        fig.update_layout(barmode="group", xaxis_title="k$")
        _graphique(fig, "cr_processus", 380)
    st.dataframe(t.style.format({"Coût (k$)": "{:,.0f}", "Coût après (k$)": "{:,.0f}"}), hide_index=True, width="stretch")
    st.caption("Les montants sont fictifs. Les activités à valeur ajoutée (temps de coupe, finition) ne sont pas dans les options : on les protège, on ne les réduit pas.")

    st.markdown("###### Coût de la qualité")
    q = C.cout_qualite()
    _cartes([("Coût de la qualité", _k(q["total"]), f"{q['pct_ventes']:.1%} des ventes".replace(".", ","), "ok" if q["pct_ventes"] <= .05 else ("att" if q["pct_ventes"] <= .10 else "crit")),
             ("Conformité (prévention + évaluation)", _k(q["conformite"]), "dépense choisie", "info"), ("Non-conformité (défaillances)", _k(q["non_conformite"]), f"{q['ratio_non_conformite']:.0%} du total".replace(".", ","),
              "ok" if q["ratio_non_conformite"] <= .3 else "att")])
    c1, c2 = st.columns([2, 3])
    with c1:
        fig = go.Figure(go.Pie(labels=q["par_categorie"].index, values=q["par_categorie"].values, hole=.55, marker_colors=["#1baf7a", "#2a78d6", "#d9930a", "#d03b3b"], textinfo="label+percent"))
        fig.update_layout(showlegend=False)
        _graphique(fig, "cr_coq", 320)
    with c2:
        d = q["detail"].sort_values("Montant (k$)")
        fig = go.Figure(go.Bar(y=d["Poste"], x=d["Montant (k$)"], orientation="h", marker_color=[{"Prévention": "#1baf7a", "Évaluation": "#2a78d6", "Défaillance interne": "#d9930a", "Défaillance externe": "#d03b3b"}[c] for c in d["Catégorie"]],
                               text=[f"{v:,.0f}".replace(",", " ") for v in d["Montant (k$)"]], textposition="outside"))
        fig.update_xaxes(title="k$")
        _graphique(fig, "cr_coq_detail", 320)
    _lecture(f"**Lecture.** Le groupe dépense {_k(q['conformite'])} pour éviter ou détecter les défauts et {_k(q['non_conformite'])} pour les corriger. "
             "Un dollar de prévention (plans de contrôle, formation, certification) évite en général plusieurs dollars de reprises, de rebuts et de réclamations ; "
             "viser une part de défaillances sous 30 % du coût total est un objectif raisonnable pour un atelier certifié AS9100.")


def onglet_cible_qualite() -> None:
    onglet_cible()
    onglet_abm()


# --- Rapports par niveau ----------------------------------------------------------------------------------------------------------------------
NIVEAUX = {"Stratégique": ("🏛", "Conseil et direction", "annuel"), "Tactique": ("🧭", "Directeurs", "mensuel"), "Opérationnel": ("🔧", "Atelier", "hebdomadaire")}


def onglet_rapports() -> None:
    st.markdown("**Un même chiffre, trois lectures.** Le conseil veut savoir où créer de la valeur, les directeurs ce qu'ils doivent corriger ce mois-ci, l'atelier ce qu'il doit vérifier cette semaine. "
                "Chaque rapport est généré à partir des calculs de cette section et change quand les hypothèses changent.")
    niveau = st.segmented_control("Niveau du rapport", list(NIVEAUX), default="Stratégique", format_func=lambda n: f"{NIVEAUX[n][0]} {n}", key="cr_niveau") or "Stratégique"
    with st.expander("⚙ Hypothèses du rapport"):
        a, b, c = st.columns(3)
        with a:
            marge = st.slider("Marge visée sur le coût ABC", 0, 40, 15, 1, format="%d %%", key="rp_marge") / 100
            cap = st.number_input("Capacité normale du centre CNC (h)", 20000.0, 60000.0, 40000.0, 500.0, key="rp_cap")
            cro = st.slider("Croissance maximale de la demande", 0, 50, 20, 5, format="%d %%", key="rp_cro") / 100
        with b:
            sp = st.slider("Seuil d'investigation (% du standard)", 1, 15, 5, 1, format="%d %%", key="rp_sp") / 100
            sd = st.number_input("Seuil d'investigation ($)", 0.0, 50000.0, 2500.0, 250.0, key="rp_sd")
            vm = st.slider("Variation du métal depuis le standard", -20.0, 20.0, 3.0, 0.5, format="%.1f %%", key="rp_vm") / 100
        with c:
            red = st.slider("Réduction visée des activités sans valeur", 0, 100, 50, 5, format="%d %%", key="rp_red") / 100
            hr = st.number_input("Heures de main-d'œuvre réelles du mois", 500.0, 5000.0, 1830.0, 10.0, key="rp_hr")
            kg = st.number_input("Barre achetée dans le mois (kg)", 1000.0, 20000.0, 5010.0, 10.0, key="rp_kg")
            fx = st.number_input("Frais fixes de fabrication dépensés ($)", 10000.0, 80000.0, 31900.0, 100.0, key="rp_fx")
            sdv = st.slider("Seuil de dépassement du devis", 1, 20, 5, 1, format="%d %%", key="rp_sdv") / 100
    params = R.Parametres(marge_visee=marge, capacite_cnc=cap, croissance_max=cro, seuil_pct=sp, seuil_dollars=sd, var_marche=vm, reduction_abm=red, heures_reelles=hr, kg_achetes=kg, fixes_reels=fx, seuil_devis=sdv)
    rap = R.construire(niveau, params)
    icone = NIVEAUX[niveau][0]
    st.html(f'<div class="cr-hero"><h3>{icone} {html.escape(rap.titre)}</h3><p>{html.escape(rap.objectif)}</p><div class="cr-meta"><div><b>Niveau</b><br>{html.escape(rap.niveau)}</div>'
            f'<div><b>Destinataires</b><br>{html.escape(rap.destinataires)}</div><div><b>Fréquence</b><br>{html.escape(rap.frequence)}</div><div><b>Période</b><br>{html.escape(rap.periode)}</div></div></div>')
    c1, c2, c3 = st.columns(3)
    nom = f"Rapport_{niveau.lower().replace('é', 'e')}_couts_de_revient"
    c1.download_button("⬇ PDF", R.en_pdf(rap), file_name=f"{nom}.pdf", mime="application/pdf", key="rp_pdf", width="stretch")
    c2.download_button("⬇ HTML (imprimable)", R.en_html(rap), file_name=f"{nom}.html", mime="text/html", key="rp_html", width="stretch")
    c3.download_button("⬇ Markdown", R.en_markdown(rap), file_name=f"{nom}.md", mime="text/markdown", key="rp_md", width="stretch")
    st.markdown("#### Indicateurs")
    _cartes_kpi(rap.kpis)
    st.markdown("#### À retenir")
    for i, m in enumerate(rap.messages):
        st.html(f'<div class="cr-msg{" alerte" if "Alerte" in m or "déficitaire" in m else ""}">{R._gras_html(m)}</div>')
    for s in rap.sections:
        st.markdown(f"#### {s.titre}")
        for x in s.paragraphes:
            st.markdown(_md(x))
        if s.tableau is not None:
            st.dataframe(s.tableau, hide_index=True, width="stretch")
        if s.legende:
            st.caption(_md(s.legende))
    st.markdown("#### Plan d'action")
    plan = pd.DataFrame([{"Priorité": a.priorite, "Action": a.action, "Responsable": a.responsable, "Échéance": a.echeance, "Impact": a.impact} for a in rap.actions])
    st.dataframe(plan.style.map(lambda v: {"Haute": "color:#d03b3b;font-weight:700", "Moyenne": "color:#d9930a;font-weight:700"}.get(v, ""), subset=["Priorité"]), hide_index=True, width="stretch")
    if rap.methode:
        with st.expander("Méthode"):
            st.markdown(_md(rap.methode))


# --- Vue ---------------------------------------------------------------------------------------------------------------------------------------
def afficher() -> None:
    st.html(CSS)
    st.caption(_md("Le coût de revient d'une manufacture sur commande, tel qu'un contrôleur le gère : chaque onglet pose une question, nomme la méthode qui y répond et la décision qu'elle éclaire. "
                   "Chiffres fictifs modifiables ; tout se recalcule. Les méthodes retenues et écartées sont au bas du tableau de bord."))
    noms = ["📌 Tableau de bord", "🧱 Du compte au produit", "🧮 Rentabilité (ABC)", "💲 Prix", "📦 Devis contre réel", "⚖ Décisions à la marge", "🎯 Standards et écarts",
            "🏭 Capacité et contraintes", "💡 Coût cible et qualité", "📑 Rapports"]
    fonctions = (onglet_synthese, onglet_imputation, onglet_complet, onglet_prix, onglet_commandes, onglet_marge, onglet_ecarts, onglet_capacite, onglet_cible_qualite, onglet_rapports)
    for onglet, f in zip(st.tabs(noms), fonctions):
        with onglet:
            f()
