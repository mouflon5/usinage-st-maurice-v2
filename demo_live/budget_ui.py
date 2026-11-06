"""Vue « Planification budgétaire » : trois approches du budget (top-down, bottom-up, base zéro), leur réconciliation et le process mining qui les nourrit.

Six onglets, dans l'ordre du cycle budgétaire :

  Processus         le cycle en couloirs (qui fait quoi, avec les chiffres de chaque étape), le calendrier et le rôle de chaque approche
  Top-down          la direction fixe la cible ; cascade de l'enveloppe vers les lignes et les centres
  Bottom-up         les gestionnaires bâtissent leur budget ; pont du résultat de base au résultat demandé, capacité, frais indirects
  Base zéro         paquets de décision classés par valeur, ligne de coupure selon l'enveloppe
  Réconciliation    leviers qui rejoignent la cible, tours de négociation, budget maître et phasage mensuel
  Process mining    journal d'événements : carte du processus, variantes, goulots, conformité, chronologie, lien avec le budget

Les calculs sont dans budget_planification.py et process_mining.py (testés). Les chiffres sont fictifs et modifiables : tout se recalcule.
"""
from __future__ import annotations

import html
from datetime import date, datetime

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import budget_planification as B
import couts_revient as C
import process_mining as P
from demo_live import couts_ui as U

COULEUR_APPROCHE = {"Top-down": "#1f5f8b", "Bottom-up": "#2a9d8f", "Base zéro": "#d9930a", "Réconciliation": "#8e5ec7", "Approbation": "#5b6573", "Suivi": "#5b6573"}
COULEUR_DECISION = {"Obligatoire": "#5b6573", "Financé": "#1baf7a", "Non financé": "#d03b3b"}
CSS = """<style>
.bp-ou{display:inline-block;font-size:.72rem;font-weight:700;background:#d03b3b;color:#fff;border-radius:999px;padding:1px 9px;margin-left:6px}
.bp-trace{display:flex;flex-wrap:wrap;align-items:center;gap:3px;margin:3px 0 0}
.bp-puce{font-size:.7rem;color:#fff;border-radius:5px;padding:2px 6px;white-space:nowrap}
.bp-fleche{font-size:.7rem;opacity:.5}
.bp-var{border:1px solid rgba(128,128,128,.25);border-radius:9px;padding:7px 11px;margin:5px 0;background:rgba(128,128,128,.05)}
.bp-var .tete{display:flex;justify-content:space-between;font-size:.82rem;margin-bottom:2px}
.bp-barre{height:6px;border-radius:3px;background:rgba(128,128,128,.2);margin:3px 0 4px}.bp-barre i{display:block;height:6px;border-radius:3px}
</style>"""


def _p(cle: str, defaut: float) -> float:
    return float(st.session_state.get(cle, defaut))


def _etat() -> dict:
    """Lit les hypothèses des widgets (valeurs par défaut au premier passage) et calcule les trois approches et leur réconciliation."""
    td = B.top_down(_p("bp_g", B.CIBLES_DEFAUT["croissance_ventes"]), _p("bp_m", B.CIBLES_DEFAUT["marge_cible"]), _p("bp_pd", B.CIBLES_DEFAUT["productivite_directe"]))
    hyp = B.HYP_LIGNES.copy()
    for i, l in enumerate(B.LIGNES):
        hyp.loc[l, "Volume (%)"] = _p(f"bp_v{i}", hyp.loc[l, "Volume (%)"])
        hyp.loc[l, "Prix (%)"] = _p(f"bp_x{i}", hyp.loc[l, "Prix (%)"])
        hyp.loc[l, "Productivité (%)"] = _p(f"bp_r{i}", hyp.loc[l, "Productivité (%)"])
    gen = {"inflation_matiere": _p("bp_im", B.HYP_GENERALES["inflation_matiere"]), "inflation_salaires": _p("bp_is", B.HYP_GENERALES["inflation_salaires"]),
           "inflation_generale": _p("bp_ig", B.HYP_GENERALES["inflation_generale"]), "prudence": _p("bp_pr", B.HYP_GENERALES["prudence"])}
    bu = B.bottom_up(hyp, gen)
    poids = {k: _p(f"bp_w{i}", v) for i, (k, v) in enumerate(B.CRITERES.items())}
    enveloppe = td["enveloppe"] if st.session_state.get("bp_env_auto", True) else _p("bp_env", float(round(td["enveloppe"])))
    eco_pm = None
    if st.session_state.get("bp_pm_paquet", True):
        eco_pm = P.cout_reprises(_journal(P.ACHATS.nom), P.ACHATS.nom)["evitable_k"]
    bz = B.zbb(enveloppe, poids, bu["indexation_indirect"], eco_pm)
    rec = B.reconciliation(td, bu, bz, _p("bp_pd2", 0.5), _p("bp_px2", 0.1))
    return {"td": td, "bu": bu, "bz": bz, "rec": rec, "hyp": hyp, "eco_pm": eco_pm}


@st.cache_data(show_spinner=False)
def _journal(nom: str) -> pd.DataFrame:
    return P.journal(nom)


def _signe(v: float, dec: int = 0) -> str:
    return f"{v:+,.{dec}f}".replace(",", " ")


# --- Onglet 1 : le processus ------------------------------------------------------------------------------------------------------------------------
LANES = ["Direction", "Gestionnaires d'unités", "Responsables de centres", "Contrôle de gestion", "Comité de budget", "Conseil d'administration"]
CAL_VERS_FLUX = [1, 2, 3, 4, 5, 5, 6, 7, 8, 9]       # étape du calendrier -> étape du diagramme


def _etape_courante() -> int | None:
    auj = date.today()
    for i, r in B.ETAPES.iterrows():
        if auj <= r["Fin"]:
            return CAL_VERS_FLUX[i]
    return None


def _fig_processus(e: dict) -> go.Figure:
    td, bu, bz, rec = e["td"], e["bu"], e["bz"], e["rec"]
    nb_coupes = int((~bz["paquets"]["Financé"]).sum())
    pas = 2.0
    etapes = {  # numéro: (couloir, colonne, titre, valeur, approche)
        1: (0, 0, "Orientations<br>stratégiques", f"Croissance {td['croissance']:+.0f} %", "Top-down"),
        2: (0, 1, "Cibles et<br>enveloppes", f"Résultat {U._k(td['resultat'])}", "Top-down"),
        3: (1, 2, "Budgets des<br>unités", f"Demandé {U._k(bu['resultat'])}", "Bottom-up"),
        4: (2, 2, "Paquets de<br>décision", f"{nb_coupes} paquets coupés", "Base zéro"),
        5: (3, 3, "Consolidation<br>et capacité", f"CNC à {bu['heures']['utilisation']:.0%}", "Bottom-up"),
        6: (3, 4, "Écart cible c.<br>ascendant", f"Écart {U._k(rec['ecart_initial'])}", "Réconciliation"),
        7: (4, 5, "Arbitrage<br>(tours)", f"Reste {U._k(rec['ecart_residuel'])}", "Réconciliation"),
        8: (5, 6, "Approbation du<br>budget maître", f"Retenu {U._k(rec['resultat_retenu'])}", "Approbation"),
        9: (3, 7, "Suivi mensuel et<br>reprévisions", "Écarts mensuels", "Suivi"),
    }
    flux = [(1, 2), (2, 3), (2, 4), (3, 5), (4, 5), (5, 6), (6, 7), (7, 8), (8, 9)]
    courant = _etape_courante()
    larg, haut = 1.76, 0.78
    fig = go.Figure()
    shapes, annots = [], []
    n_col = 8
    for i, nom in enumerate(LANES):
        shapes.append(dict(type="rect", x0=-1.0, x1=n_col * pas - 0.2, y0=-i - 0.5, y1=-i + 0.5, fillcolor="rgba(128,128,128,.07)" if i % 2 == 0 else "rgba(128,128,128,.0)",
                           line=dict(width=0), layer="below"))
        annots.append(dict(xref="paper", x=-0.004, xanchor="right", y=-i, yref="y", text=f"<b>{nom}</b>", showarrow=False, font=dict(size=12), align="right"))

    def bord(n: int, cote: str) -> tuple[float, float]:
        c, k, *_ = etapes[n]
        x, y = k * pas, -c
        return (x + larg / 2, y) if cote == "d" else (x - larg / 2, y)

    for a, b in flux:
        (x0, y0), (x1, y1) = bord(a, "d"), bord(b, "g")
        xm = (x0 + x1) / 2
        chemin = f"M {x0},{y0} L {xm},{y0} L {xm},{y1} L {x1},{y1}" if abs(y0 - y1) > 1e-9 else f"M {x0},{y0} L {x1},{y1}"
        shapes.append(dict(type="path", path=chemin, line=dict(color="#7b8794", width=2)))
        annots.append(dict(x=x1, y=y1, ax=x1 - 0.22, ay=y1, xref="x", yref="y", axref="x", ayref="y", showarrow=True, arrowhead=2, arrowsize=1.3, arrowwidth=2, arrowcolor="#7b8794", text=""))
    # boucle de négociation : de l'arbitrage vers les budgets des unités et des centres
    (xs, ys) = (etapes[7][1] * pas, -etapes[7][0] + haut / 2)
    for cible in (3, 4):
        x1, y1 = bord(cible, "d")
        shapes.append(dict(type="path", path=f"M {xs},{ys} L {xs},{y1} L {x1},{y1}", line=dict(color="#8e5ec7", width=2, dash="dash")))
        annots.append(dict(x=x1, y=y1, ax=x1 + 0.22, ay=y1, xref="x", yref="y", axref="x", ayref="y", showarrow=True, arrowhead=2, arrowsize=1.3, arrowwidth=2, arrowcolor="#8e5ec7", text=""))
    annots.append(dict(x=xs + 0.08, y=-2.0, xref="x", yref="y", text="<i>tours de<br>négociation</i>", showarrow=False, xanchor="left", font=dict(size=11, color="#8e5ec7")))
    for n, (c, k, titre, valeur, appr) in etapes.items():
        x, y = k * pas, -c
        couleur = COULEUR_APPROCHE[appr]
        shapes.append(dict(type="rect", x0=x - larg / 2, x1=x + larg / 2, y0=y - haut / 2, y1=y + haut / 2, fillcolor=couleur, opacity=1,
                           line=dict(color="#ffd23f" if n == courant else couleur, width=4 if n == courant else 1), layer="above"))
        annots.append(dict(x=x, y=y, xref="x", yref="y", showarrow=False, align="center", font=dict(color="#fff", size=11),
                           text=f"<b>{n}. {titre}</b><br><span style='font-size:10px'>{valeur}</span>"))
        if n == courant:
            annots.append(dict(x=x - larg / 2, y=y - haut / 2 - 0.12, xref="x", yref="y", text="<b>▶ en cours</b>", showarrow=False, xanchor="left", font=dict(size=11, color="#b8860b")))
    for appr in ("Top-down", "Bottom-up", "Base zéro", "Réconciliation", "Approbation"):
        fig.add_scatter(x=[None], y=[None], mode="markers", marker=dict(size=11, color=COULEUR_APPROCHE[appr], symbol="square"), name=appr)
    fig.update_layout(shapes=shapes, annotations=annots, xaxis=dict(visible=False, range=[-1.0, n_col * pas - 0.2], fixedrange=True),
                      yaxis=dict(visible=False, range=[-len(LANES) + 0.5, 0.62], fixedrange=True), showlegend=True)
    fig.update_layout(margin=dict(l=170, r=10, t=30, b=10), legend=dict(orientation="h", y=1.08, x=0), height=640)
    return fig


def _fig_calendrier() -> go.Figure:
    d = B.ETAPES.copy()
    d["Début"], d["Fin"] = pd.to_datetime(d["Début"]), pd.to_datetime(d["Fin"]) + pd.Timedelta(days=1)
    fig = px.timeline(d, x_start="Début", x_end="Fin", y="Étape", color="Approche", color_discrete_map=COULEUR_APPROCHE, hover_data={"Acteur": True})
    fig.update_yaxes(autorange="reversed", title="")
    fig.update_xaxes(title="")
    auj = pd.Timestamp(date.today())
    if d["Début"].min() <= auj <= d["Fin"].max():
        fig.add_shape(type="line", x0=auj, x1=auj, y0=0, y1=1, yref="paper", line=dict(color="#d03b3b", width=2, dash="dot"))
        fig.add_annotation(x=auj, y=1, yref="paper", text="aujourd'hui", showarrow=False, yshift=10, font=dict(color="#d03b3b", size=11))
    return fig


def onglet_processus(e: dict) -> None:
    td, bu, rec = e["td"], e["bu"], e["rec"]
    U._entete("Comment passe-t-on d'une ambition à un budget que tout le monde peut défendre ?", "Top-down + bottom-up + base zéro, réconciliés",
              "Quel résultat et quelles enveloppes pour l'exercice " + str(B.EXERCICE), "Direction, comité de budget, conseil d'administration")
    U._cartes([("Cible de résultat (top-down)", U._k(td["resultat"]), f"marge de {td['marge']:.0f} % sur {U._k(td['ventes'])}", "info"),
               ("Résultat demandé (bottom-up)", U._k(bu["resultat"]), f"écart de {U._k(rec['ecart_initial'])} avec la cible", "att" if rec["ecart_initial"] > 0 else "ok"),
               ("Budget retenu (réconcilié)", U._k(rec["resultat_retenu"]), f"marge de {rec['marge_retenue']:.1f} %", "ok" if rec["ecart_residuel"] <= 0 else "att"),
               ("Écart restant à arbitrer", U._k(rec["ecart_residuel"]), "négatif = la cible est dépassée" if rec["ecart_residuel"] <= 0 else "à trancher par le comité", "ok" if rec["ecart_residuel"] <= 0 else "crit")])
    U._section("Le cycle budgétaire, couloir par couloir")
    st.caption("Chaque boîte porte le chiffre de son étape, recalculé quand vous changez une hypothèse. Les flèches pointillées sont les tours de négociation.")
    st.plotly_chart(_fig_processus(e), theme="streamlit", width="stretch", config=U.CONFIG, key="bp_flux")
    U._section("Calendrier")
    U._graphique(_fig_calendrier(), "bp_gantt", 360)
    U._section("Trois approches, un seul budget")
    cartes = "".join(f'<div class="cr-m" style="--c:{COULEUR_APPROCHE[r["Approche"]]}"><span class="b">{html.escape(r["Approche"])}</span><div class="t">{html.escape(r["Principe"])}</div>'
                     f'<div class="d"><b>+</b> {html.escape(r["Avantages"])}</div><div class="d"><b>−</b> {html.escape(r["Risques"])}</div>'
                     f'<div class="d" style="opacity:.65">À utiliser pour : {html.escape(r["Quand l\'utiliser"])}</div></div>' for _, r in B.METHODES_BUDGET.iterrows())
    st.html(f'<div class="cr-meth">{cartes}</div>')
    st.info("**Le réflexe du contrôleur : une approche hybride.** Le top-down donne le cap et les enveloppes, le bottom-up engage ceux qui livreront les chiffres et valide la capacité, "
            "la base zéro nettoie les frais indirects là où l'inertie s'accumule. On ne l'applique pas partout chaque année : un centre sur trois par an, et toujours après une hausse de coûts "
            "non expliquée. Le process mining, lui, dit où les processus du budget et des achats perdent du temps et de l'argent.", icon=":material/lightbulb:")


# --- Onglet 2 : top-down ----------------------------------------------------------------------------------------------------------------------------
def _fig_sankey_td(td: dict) -> go.Figure:
    noeuds = ["Ventes cibles", "Résultat cible", "Coûts directs", "Frais indirects"] + list(B.LIGNES) + list(B.CENTRES)
    idx = {n: i for i, n in enumerate(noeuds)}
    src, dst, val = [], [], []

    def lien(a, b, v):
        src.append(idx[a]), dst.append(idx[b]), val.append(max(float(v), 0.0))
    lien("Ventes cibles", "Résultat cible", td["resultat"])
    lien("Ventes cibles", "Coûts directs", td["directs"])
    lien("Ventes cibles", "Frais indirects", td["enveloppe"])
    for l in B.LIGNES:
        lien("Coûts directs", l, td["par_ligne"].loc[l, "Coûts directs cibles"])
    for c in B.CENTRES:
        lien("Frais indirects", c, td["par_centre"].loc[c, "Enveloppe cible"])
    couleurs = ["#1f5f8b", "#1baf7a", "#2a78d6", "#d9930a"] + [U.COULEURS[l] for l in B.LIGNES] + ["#c9a24a"] * len(B.CENTRES)
    fig = go.Figure(go.Sankey(arrangement="snap", node=dict(label=[f"{n}" for n in noeuds], color=couleurs, pad=14, thickness=16),
                              link=dict(source=src, target=dst, value=val, color="rgba(128,128,128,.28)")))
    return fig


def onglet_top_down(e: dict) -> None:
    td = e["td"]
    U._entete("Quel résultat la direction exige-t-elle, et combien chaque ligne et chaque centre peuvent-ils dépenser ?", "Budget descendant (top-down) : cible, enveloppe, répartition",
              "Fixer le cap et les plafonds de dépenses", "Direction générale, conseil d'administration")
    c1, c2, c3 = st.columns(3)
    c1.slider("Croissance cible des ventes (%)", 0.0, 15.0, B.CIBLES_DEFAUT["croissance_ventes"], 0.5, key="bp_g")
    c2.slider("Marge d'exploitation cible (%)", 5.0, 20.0, B.CIBLES_DEFAUT["marge_cible"], 0.5, key="bp_m")
    c3.slider("Gain de productivité demandé sur les coûts directs (%)", 0.0, 5.0, B.CIBLES_DEFAUT["productivite_directe"], 0.25, key="bp_pd")
    td = _etat()["td"]
    b = B.resultat_base()
    U._cartes([("Ventes cibles", U._k(td["ventes"]), f"{td['croissance']:+.1f} % sur {U._k(b['ventes'])}", "info"),
               ("Résultat cible", U._k(td["resultat"]), f"{td['marge']:.1f} % des ventes (base : {b['resultat'] / b['ventes'] * 100:.1f} %)", "info"),
               ("Coûts directs cibles", U._k(td["directs"]), f"{td['directs'] / td['ventes'] * 100:.1f} % des ventes", "info"),
               ("Enveloppe de frais indirects", U._k(td["enveloppe"]), f"{(td['enveloppe'] / b['indirects'] - 1) * 100:+.1f} % contre la base de {U._k(b['indirects'])}", "att" if td["enveloppe"] < b["indirects"] else "ok")])
    U._section("De la cible aux plafonds de dépenses")
    st.caption("L'enveloppe des frais indirects est un résidu : ventes cibles moins résultat cible moins coûts directs cibles. Elle est ensuite répartie au prorata de la base.")
    st.plotly_chart(_fig_sankey_td(td).update_layout(height=420, margin=dict(l=10, r=10, t=10, b=10), paper_bgcolor="rgba(0,0,0,0)", font=dict(size=13)),
                    theme="streamlit", width="stretch", config=U.CONFIG, key="bp_sankey")
    g1, g2 = st.columns(2)
    with g1:
        st.markdown("###### Cibles par ligne (k$)")
        t = td["par_ligne"]
        st.dataframe(t.style.format({"Ventes base": "{:,.0f}", "Ventes cibles": "{:,.0f}", "Croissance (%)": "{:+.1f}", "Coûts directs cibles": "{:,.0f}", "Contribution cible": "{:,.0f}"}), width="stretch")
    with g2:
        st.markdown("###### Enveloppes par centre (k$)")
        t = td["par_centre"]
        st.dataframe(t.style.format({"Base": "{:,.0f}", "Enveloppe cible": "{:,.0f}", "Variation (%)": "{:+.1f}"}), width="stretch")
    U._lecture(f"La cible exige {U._k(td['resultat'])}, soit {U._k(td['resultat'] - b['resultat'])} de plus que l'exercice courant. Avec {td['croissance']:.1f} % de croissance et {td['marge']:.0f} % de marge, "
               f"les frais indirects doivent tenir dans {U._k(td['enveloppe'])} ({(td['enveloppe'] / b['indirects'] - 1) * 100:+.1f} %). C'est la limite du top-down : il ne sait pas si cette enveloppe est réaliste, "
               "d'où le bottom-up et la base zéro.")


# --- Onglet 3 : bottom-up ---------------------------------------------------------------------------------------------------------------------------
def onglet_bottom_up(e: dict) -> None:
    U._entete("Que peuvent réellement livrer les gestionnaires, avec leurs volumes, leurs prix et leurs coûts ?", "Budget ascendant (bottom-up) : volume x prix, coûts unitaires, capacité",
              "Engager les responsables et valider la capacité de l'atelier", "Gestionnaires d'unités, responsables de centres, contrôle de gestion")
    st.markdown("###### Hypothèses des gestionnaires par ligne")
    en_tete = st.columns([2.2, 1, 1, 1])
    for c, t in zip(en_tete, ("Ligne", "Volume (%)", "Prix (%)", "Productivité (%)")):
        c.caption(t)
    for i, l in enumerate(B.LIGNES):
        a, v, x, r = st.columns([2.2, 1, 1, 1])
        a.markdown(f"**{l}**")
        v.number_input("Volume", -20.0, 40.0, float(B.HYP_LIGNES.loc[l, "Volume (%)"]), 0.5, key=f"bp_v{i}", label_visibility="collapsed")
        x.number_input("Prix", -10.0, 15.0, float(B.HYP_LIGNES.loc[l, "Prix (%)"]), 0.5, key=f"bp_x{i}", label_visibility="collapsed")
        r.number_input("Productivité", 0.0, 10.0, float(B.HYP_LIGNES.loc[l, "Productivité (%)"]), 0.25, key=f"bp_r{i}", label_visibility="collapsed")
    g = st.columns(4)
    g[0].number_input("Inflation matière (%)", 0.0, 15.0, B.HYP_GENERALES["inflation_matiere"], 0.1, key="bp_im")
    g[1].number_input("Inflation salariale (%)", 0.0, 15.0, B.HYP_GENERALES["inflation_salaires"], 0.1, key="bp_is")
    g[2].number_input("Inflation générale (%)", 0.0, 15.0, B.HYP_GENERALES["inflation_generale"], 0.1, key="bp_ig")
    g[3].number_input("Marge de prudence sur les frais indirects (%)", 0.0, 15.0, B.HYP_GENERALES["prudence"], 0.5, key="bp_pr")
    e = _etat()
    bu, td = e["bu"], e["td"]
    h = bu["heures"]
    U._cartes([("Ventes demandées", U._k(bu["ventes"]), f"{(bu['ventes'] / B.resultat_base()['ventes'] - 1) * 100:+.1f} % sur la base", "info"),
               ("Coûts directs", U._k(bu["directs"]), f"{bu['directs'] / bu['ventes'] * 100:.1f} % des ventes", "info"),
               ("Frais indirects demandés", U._k(bu["indirects"]), f"dont prudence de {U._k(bu['prudence'])}", "att" if bu["prudence"] > 0 else "ok"),
               ("Résultat ascendant", U._k(bu["resultat"]), f"cible : {U._k(td['resultat'])}", "ok" if bu["resultat"] >= td["resultat"] else "crit"),
               ("Utilisation du centre CNC", f"{h['utilisation']:.0%}", f"{h['requises']:,.0f} h sur {h['capacite']:,.0f} h".replace(",", " "),
                "crit" if h["utilisation"] > 1 else ("att" if h["utilisation"] > 0.92 else "ok"))])
    c1, c2 = st.columns([3, 2])
    with c1:
        U._section("Du résultat de base au résultat demandé")
        pont = B.pont_ascendant(bu)
        base_res = B.resultat_base()["resultat"]
        fig = go.Figure(go.Waterfall(x=["Résultat de base"] + [p for p, _ in pont] + ["Résultat ascendant"], measure=["absolute"] + ["relative"] * len(pont) + ["total"],
                                     y=[base_res] + [v for _, v in pont] + [None], text=[U._k(base_res)] + [_signe(v) for _, v in pont] + [U._k(bu["resultat"])], textposition="outside",
                                     increasing=dict(marker_color="#1baf7a"), decreasing=dict(marker_color="#d03b3b"), totals=dict(marker_color="#2a9d8f"), connector=dict(line=dict(color="#8f9aa8"))))
        fig.add_hline(y=td["resultat"], line=dict(color="#1f5f8b", dash="dash"), annotation_text="cible top-down", annotation_position="top left")
        fig.update_layout(showlegend=False)
        U._graphique(fig, "bp_pont", 380)
    with c2:
        U._section("Capacité du centre d'usinage")
        fig = go.Figure(go.Indicator(mode="gauge+number", value=h["requises"], number=dict(suffix=" h", valueformat=",.0f"),
                                     gauge=dict(axis=dict(range=[0, h["capacite"] * 1.2]), bar=dict(color="#2a9d8f"),
                                                steps=[dict(range=[0, h["capacite"] * 0.92], color="rgba(27,175,122,.25)"), dict(range=[h["capacite"] * 0.92, h["capacite"]], color="rgba(217,147,10,.3)"),
                                                       dict(range=[h["capacite"], h["capacite"] * 1.2], color="rgba(208,59,59,.3)")],
                                                threshold=dict(line=dict(color="#d03b3b", width=4), value=h["capacite"]))))
        U._graphique(fig, "bp_cap", 330)
        st.caption("Heures-machine requises par le programme des gestionnaires. Au-delà de la capacité normale : quart supplémentaire ou sous-traitance, donc des coûts que le budget doit prévoir.")
    c3, c4 = st.columns(2)
    with c3:
        U._section("Ventes et contribution par ligne")
        d = bu["par_ligne"].reset_index()
        b0 = B.base()
        fig = go.Figure()
        fig.add_bar(name="Ventes de base", x=d["Ligne"], y=[b0.loc[l, "Ventes"] for l in d["Ligne"]], marker_color="#c5ccd6")
        fig.add_bar(name="Ventes demandées", x=d["Ligne"], y=d["Ventes"], marker_color=U.MARQUE)
        fig.add_bar(name="Contribution demandée", x=d["Ligne"], y=d["Contribution"], marker_color="#1baf7a")
        fig.update_layout(barmode="group")
        U._graphique(fig, "bp_lignes", 340)
    with c4:
        U._section("Frais indirects demandés par centre")
        ic = bu["par_centre"].reset_index()
        fig = go.Figure()
        fig.add_bar(name="Base", x=ic["Centre"], y=ic["Base"], marker_color="#c5ccd6")
        fig.add_bar(name="Indexation et activité", x=ic["Centre"], y=ic["Budget sans prudence"] - ic["Base"], marker_color=U.MARQUE)
        fig.add_bar(name="Prudence", x=ic["Centre"], y=ic["Prudence"], marker_color="#d9930a")
        fig.update_layout(barmode="stack")
        U._graphique(fig, "bp_centres", 340)
    U._lecture(f"Les gestionnaires demandent {U._k(bu['resultat'])}, soit {U._k(td['resultat'] - bu['resultat'])} sous la cible. Ils ont aussi glissé {U._k(bu['prudence'])} de prudence dans les frais indirects : "
               "c'est le biais classique du bottom-up (budget qui reproduit le passé, avec une marge de sécurité). Le centre CNC tourne à "
               f"{h['utilisation']:.0%} de sa capacité normale : {'il reste peu de marge de manœuvre pour la croissance de l’aéro et du prototypage' if h['utilisation'] > 0.92 else 'la croissance est absorbable'}.")


# --- Onglet 4 : base zéro ---------------------------------------------------------------------------------------------------------------------------
def _fig_coupure(bz: dict) -> go.Figure:
    d = bz["paquets"]
    fig = go.Figure()
    for dec, couleur in COULEUR_DECISION.items():
        s = d[d["Décision"] == dec]
        if s.empty:
            continue
        fig.add_bar(name=dec, x=s["Cumul (k$)"] - s["Coût net (k$)"] / 2, y=s["Efficience"], width=s["Coût net (k$)"] * 0.96, marker_color=couleur,
                    customdata=s[["Paquet", "Centre", "Coût net (k$)", "Valeur"]].values,
                    hovertemplate="<b>%{customdata[0]}</b><br>%{customdata[1]}<br>Coût : %{customdata[2]:,.0f} k$<br>Valeur : %{customdata[3]:.2f} / 5<extra></extra>")
    fig.add_vline(x=bz["enveloppe"], line=dict(color="#d03b3b", width=3, dash="dash"), annotation_text=f"enveloppe {bz['enveloppe']:,.0f} k$".replace(",", " "), annotation_position="top right")
    fig.update_xaxes(title="Coût cumulé des paquets classés (k$) ; la largeur d'une barre est le coût du paquet")
    fig.update_yaxes(title="Efficience (valeur par k$)")
    return fig


def onglet_base_zero(e: dict) -> None:
    U._entete("Quelles dépenses indirectes méritent d'exister, si on repart de zéro ?", "Budget base zéro (ZBB) : paquets de décision à trois niveaux, classés par valeur",
              "Où placer la ligne de coupure des frais indirects", "Responsables de centres, comité de budget")
    st.markdown("###### Critères de valeur (pondération)")
    cols = st.columns(4)
    for i, (k, v) in enumerate(B.CRITERES.items()):
        cols[i].slider(k, 0, 50, v, 5, key=f"bp_w{i}")
    o1, o2, o3 = st.columns([1.3, 1.3, 2])
    o1.checkbox("Enveloppe = celle du top-down", True, key="bp_env_auto")
    if not st.session_state.get("bp_env_auto", True):
        o2.number_input("Enveloppe (k$)", 3000.0, 12000.0, float(round(e["td"]["enveloppe"])), 50.0, key="bp_env")
    o3.checkbox("Inclure le paquet issu du process mining", True, key="bp_pm_paquet", help="Appariement automatisé des factures : son coût est compensé par l'économie des reprises mesurées dans le journal.")
    e = _etat()
    bz, bu = e["bz"], e["bu"]
    d = bz["paquets"]
    U._cartes([("Paquets examinés", f"{len(d)}", f"{int(d['Obligatoire'].sum())} obligatoires, {int((d['Niveau'] == 'Amélioré').sum())} améliorations", "info"),
               ("Plancher obligatoire", U._k(bz["obligatoire"]), "conformité, sécurité, capacité de base", "crit" if bz["obligatoire_depasse"] else "info"),
               ("Budget base zéro", U._k(bz["total"]), f"enveloppe : {U._k(bz['enveloppe'])}", "ok" if bz["total"] <= bz["enveloppe"] + 1e-6 else "crit"),
               ("Coupé (paquets actuels)", U._k(bz["coupe"]), f"{int(((d['Niveau'] == 'Actuel') & ~d['Financé']).sum())} paquets sous la ligne", "att"),
               ("Ajouté (améliorations)", U._k(bz["ajoute"]), f"{int(((d['Niveau'] == 'Amélioré') & d['Financé']).sum())} initiatives financées", "ok"),
               ("Contre le bottom-up", U._k(bu["indirects"] - bz["total"]), "économie sur les frais indirects demandés", "ok" if bu["indirects"] >= bz["total"] else "att")])
    U._section("Classement des paquets et ligne de coupure")
    st.caption("On finance d'abord le plancher obligatoire, puis les paquets les plus efficients, jusqu'à ce que l'enveloppe soit épuisée. Les barres rouges sont celles que l'enveloppe ne permet pas de financer.")
    U._graphique(_fig_coupure(bz), "bp_coupure", 400)
    c1, c2 = st.columns([3, 2])
    with c1:
        U._section("Résultat par centre")
        pc = bz["par_centre"].reset_index()
        fig = go.Figure()
        fig.add_bar(name="Base indexée", x=pc["Centre"], y=pc["Base indexée"], marker_color="#c5ccd6")
        fig.add_bar(name="Budget base zéro", x=pc["Centre"], y=pc["Budget base zéro"], marker_color="#d9930a")
        fig.add_bar(name="Demandé (bottom-up)", x=pc["Centre"], y=bu["par_centre"].loc[pc["Centre"], "Budget demandé"].values, marker_color=U.MARQUE)
        fig.update_layout(barmode="group")
        U._graphique(fig, "bp_zbb_centres", 360)
    with c2:
        U._section("Ce que la ligne tranche")
        t = pc.set_index("Centre")[["Coupé (paquets actuels)", "Ajouté (améliorations)"]]
        st.dataframe(t.style.format("{:,.0f}"), width="stretch")
        st.caption("Coupé : paquets du niveau actuel que l'enveloppe ne finance pas. Ajouté : améliorations qui passent la ligne.")
    U._section("Les paquets de décision")
    centre = st.selectbox("Centre", ["Tous"] + B.CENTRES, key="bp_zbb_centre")
    t = d if centre == "Tous" else d[d["Centre"] == centre]
    t = t[["Rang", "Centre", "Paquet", "Niveau", "Coût net (k$)", "Valeur", "Efficience", "Décision"]]
    st.dataframe(t.style.format({"Coût net (k$)": "{:,.0f}", "Valeur": "{:.2f}", "Efficience": "{:.2f}"}).map(
        lambda v: f"color:{COULEUR_DECISION.get(v, 'inherit')};font-weight:700" if v in COULEUR_DECISION else "", subset=["Décision"]), hide_index=True, width="stretch")
    with st.expander("Comment lire un paquet de décision"):
        st.markdown("Un paquet est une activité avec son niveau de service et son coût. Chaque centre en décrit trois niveaux : **minimum** (ce qui est obligatoire), **actuel** (ce que l'on fait aujourd'hui) "
                    "et **amélioré** (ce que l'on aimerait ajouter). Chaque paquet est noté de 0 à 5 selon quatre critères ; la **valeur** est la moyenne pondérée, l'**efficience** la valeur par k$ dépensé. "
                    "Le classement force la comparaison entre centres, ce que ni le top-down ni le bottom-up ne font.")
    U._lecture(f"Avec une enveloppe de {U._k(bz['enveloppe'])}, la base zéro retient {U._k(bz['total'])} : elle coupe {U._k(bz['coupe'])} de paquets actuels peu efficients et finance {U._k(bz['ajoute'])} d'améliorations. "
               "Ce n'est pas une coupe uniforme : les centres qui offrent le plus de valeur par dollar gardent leur budget, les paquets de confort passent sous la ligne.")


# --- Onglet 5 : réconciliation ----------------------------------------------------------------------------------------------------------------------
def onglet_reconciliation(e: dict) -> None:
    U._entete("Comment rejoindre la cible sans fausser le budget, et que décide-t-on pour l'écart restant ?", "Leviers chiffrés, tours de négociation, budget maître",
              "Le budget que le conseil approuve", "Comité de budget, conseil d'administration")
    c1, c2, c3 = st.columns(3)
    c1.slider("Productivité supplémentaire de la main-d'œuvre directe (%)", 0.0, 3.0, 0.5, 0.25, key="bp_pd2")
    c2.slider("Hausse de prix additionnelle (%)", 0.0, 2.0, 0.1, 0.1, key="bp_px2")
    c3.slider("Part de l'effort demandée à la direction (%)", 0, 100, 40, 10, key="bp_part")
    e = _etat()
    rec, td, bu = e["rec"], e["td"], e["bu"]
    U._cartes([("Cible (top-down)", U._k(rec["cible"]), f"marge de {rec['marge_cible']:.1f} %", "info"), ("Ascendant (bottom-up)", U._k(rec["resultat_bu"]), "avant leviers", "att"),
               ("Budget retenu", U._k(rec["resultat_retenu"]), f"marge de {rec['marge_retenue']:.1f} %", "ok" if rec["ecart_residuel"] <= 0 else "att"),
               ("Écart restant", U._k(rec["ecart_residuel"]), "la cible est atteinte" if rec["ecart_residuel"] <= 0 else "à arbitrer", "ok" if rec["ecart_residuel"] <= 0 else "crit")])
    a, b = st.columns([3, 2])
    with a:
        U._section("Du résultat ascendant au budget retenu")
        lev = rec["leviers"]
        fig = go.Figure(go.Waterfall(x=["Ascendant"] + [n for n, _ in lev] + ["Budget retenu"], measure=["absolute"] + ["relative"] * len(lev) + ["total"],
                                     y=[rec["resultat_bu"]] + [v for _, v in lev] + [None], text=[U._k(rec["resultat_bu"])] + [_signe(v) for _, v in lev] + [U._k(rec["resultat_retenu"])],
                                     textposition="outside", increasing=dict(marker_color="#1baf7a"), decreasing=dict(marker_color="#d03b3b"), totals=dict(marker_color="#8e5ec7"),
                                     connector=dict(line=dict(color="#8f9aa8"))))
        fig.add_hline(y=rec["cible"], line=dict(color="#1f5f8b", dash="dash"), annotation_text="cible top-down", annotation_position="top left")
        fig.update_layout(showlegend=False)
        fig.update_xaxes(tickangle=-12)
        U._graphique(fig, "bp_leviers", 400)
    with b:
        U._section("Tours de négociation")
        it = B.iterations(rec["ecart_initial"], _p("bp_part", 40) / 100)
        fig = go.Figure()
        fig.add_bar(name="Concession de la direction", x=it["Tour"][1:], y=it["Concession direction"][1:], marker_color="#1f5f8b")
        fig.add_bar(name="Effort des gestionnaires", x=it["Tour"][1:], y=it["Effort gestionnaires"][1:], marker_color="#2a9d8f")
        fig.add_scatter(name="Écart restant", x=it["Tour"], y=it["Écart restant"], mode="lines+markers", line=dict(color="#d03b3b", width=3), yaxis="y")
        fig.update_layout(barmode="stack")
        fig.update_xaxes(title="Tour", dtick=1)
        U._graphique(fig, "bp_tours", 400)
        st.caption("Modèle simple : à chaque tour, chaque partie ferme la moitié de sa part de l'écart restant. Il illustre la convergence, pas une prévision.")
    U._section("Budget maître")
    b0 = B.resultat_base()
    base_df = B.base()
    lignes = [("Ventes", b0["ventes"], td["ventes"], bu["ventes"], rec["ventes"]), ("Coûts directs", b0["directs"], td["directs"], bu["directs"], rec["directs"]),
              ("Contribution", b0["ventes"] - b0["directs"], td["ventes"] - td["directs"], bu["ventes"] - bu["directs"], rec["ventes"] - rec["directs"]),
              ("Frais indirects", b0["indirects"], td["enveloppe"], bu["indirects"], rec["indirects"]),
              ("Résultat d'exploitation", b0["resultat"], td["resultat"], bu["resultat"], rec["resultat_retenu"])]
    mt = pd.DataFrame(lignes, columns=["k$", f"Base {B.BASE_ANNEE}", "Top-down", "Bottom-up", "Budget retenu"]).set_index("k$")
    mt.loc["Marge d'exploitation (%)"] = [b0["resultat"] / b0["ventes"] * 100, td["marge"], bu["resultat"] / bu["ventes"] * 100, rec["marge_retenue"]]
    st.dataframe(mt.style.format("{:,.0f}").format("{:.1f}", subset=pd.IndexSlice[["Marge d'exploitation (%)"], :]), width="stretch")
    U._section(f"Phasage mensuel du budget retenu ({B.EXERCICE})")
    ph = B.phasage(rec)
    fig = go.Figure()
    fig.add_bar(name="Ventes", x=ph.index, y=ph["Ventes"], marker_color="#c5ccd6")
    fig.add_bar(name="Résultat du mois", x=ph.index, y=ph["Résultat"], marker_color=U.MARQUE)
    fig.add_scatter(name="Résultat cumulé", x=ph.index, y=ph["Résultat cumulé"], mode="lines+markers", line=dict(color="#1baf7a", width=3), yaxis="y2")
    fig.update_layout(barmode="group", yaxis2=dict(overlaying="y", side="right", showgrid=False, title="cumulé (k$)"))
    U._graphique(fig, "bp_phasage", 340)
    U._lecture(f"Les trois approches se rejoignent ainsi : les gestionnaires retirent leur prudence, la base zéro resserre les frais indirects et deux leviers modestes (productivité, prix) complètent. "
               f"Le budget retenu est de {U._k(rec['resultat_retenu'])}, " + ("la cible est atteinte sans exiger plus que des hypothèses défendables." if rec["ecart_residuel"] <= 0 else
               f"il reste {U._k(rec['ecart_residuel'])} à arbitrer : soit la direction assouplit sa cible, soit elle choisit un levier de plus."))


# --- Onglet 6 : process mining ----------------------------------------------------------------------------------------------------------------------
def _mix(c1: str, c2: str, t: float) -> str:
    t = min(max(t, 0.0), 1.0)
    a, b = [int(c1[i:i + 2], 16) for i in (1, 3, 5)], [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(a, b))


def _courbe(p0, p1, courbure: float, r: float = 0.25) -> tuple[list[float], list[float]]:
    (x0, y0), (x1, y1) = p0, p1
    d = max(((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5, 1e-6)
    nx, ny = -(y1 - y0) / d, (x1 - x0) / d
    cx, cy = (x0 + x1) / 2 + nx * courbure * d, (y0 + y1) / 2 + ny * courbure * d
    t0, t1 = min(r / d, 0.45), 1 - min(r / d, 0.45)
    ts = [t0 + (t1 - t0) * i / 24 for i in range(25)]
    xs = [(1 - t) ** 2 * x0 + 2 * (1 - t) * t * cx + t ** 2 * x1 for t in ts]
    ys = [(1 - t) ** 2 * y0 + 2 * (1 - t) * t * cy + t ** 2 * y1 for t in ts]
    return xs, ys


def _fig_carte(nom: str, log: pd.DataFrame, seuil_pct: float, frequences: bool) -> go.Figure:
    p = P.PROCESSUS[nom]
    arcs = P.suivis_directs(log)
    n_cas = log["Cas"].nunique()
    arcs = arcs[arcs["Fréquence"] >= max(1, seuil_pct / 100 * n_cas)]
    acts = P.activites(log)
    fmax = float(arcs["Fréquence"].max())
    amax = float(arcs["Attente moyenne (h)"].max())
    fig = go.Figure()
    annots = []
    for _, a in arcs.iterrows():
        pa, pb = p.positions[a["De"]], p.positions[a["Vers"]]
        dx = pb[0] - pa[0]
        courbure = 0.28 if pa[1] == pb[1] and (dx < 0 or dx > 1.01) else 0.0      # saut en avant : arc au-dessus ; retour en arrière : arc au-dessous
        xs, ys = _courbe(pa, pb, courbure)
        couleur = _mix("#9bc6e8", "#d03b3b", a["Attente moyenne (h)"] / amax)
        largeur = 1.5 + 8 * (a["Fréquence"] / fmax) ** 0.6
        fig.add_scatter(x=xs, y=ys, mode="lines", line=dict(color=couleur, width=largeur), hoverinfo="skip", showlegend=False)
        annots.append(dict(x=xs[-1], y=ys[-1], ax=xs[-3], ay=ys[-3], xref="x", yref="y", axref="x", ayref="y", showarrow=True, arrowhead=2, arrowsize=1.1, arrowwidth=1.5, arrowcolor=couleur, text=""))
        mx, my = xs[12], ys[12]
        fig.add_scatter(x=[mx], y=[my], mode="markers+text" if frequences else "markers", marker=dict(size=14, opacity=0), text=[f"{int(a['Fréquence'])}"] if frequences else None,
                        textposition="top center", textfont=dict(size=10), showlegend=False,
                        hovertemplate=f"<b>{a['De']} → {a['Vers']}</b><br>{int(a['Fréquence'])} cas<br>Attente moyenne : {a['Attente moyenne (h)']:.0f} h<br>Médiane : {a['Attente médiane (h)']:.0f} h<extra></extra>")
    noms = list(p.positions)
    fig.add_scatter(x=[p.positions[a][0] for a in noms], y=[p.positions[a][1] for a in noms], mode="markers+text",
                    marker=dict(size=46, color=[int(acts["Cas"].get(a, 0)) for a in noms], colorscale=[[0, "#c5d6e6"], [1, "#1f5f8b"]], line=dict(color="#fff", width=2), cmin=0, cmax=n_cas),
                    text=[f"<b>{int(acts['Cas'].get(a, 0))}</b>" for a in noms], textfont=dict(color="#fff", size=11), textposition="middle center", showlegend=False,
                    hovertemplate="<b>%{customdata[0]}</b><br>%{customdata[1]} cas<extra></extra>", customdata=[[a, int(acts["Cas"].get(a, 0))] for a in noms])
    etiquettes = dict(zip(p.chemin, p.courts)) | {a: a.replace(" ", "<br>", 1) for a in p.extras}
    fig.add_scatter(x=[p.positions[a][0] for a in noms], y=[p.positions[a][1] - 0.38 for a in noms], mode="text", text=[etiquettes.get(a, a) for a in noms], textfont=dict(size=11),
                    textposition="bottom center", hoverinfo="skip", showlegend=False)
    fig.add_scatter(x=[-5], y=[-5], mode="markers", marker=dict(size=0.1, color=[0], cmin=0, cmax=amax, colorscale=[[0, "#9bc6e8"], [1, "#d03b3b"]], showscale=True,
                                                                    colorbar=dict(title="Attente<br>moyenne (h)", thickness=12, len=0.7, x=1.01)), showlegend=False, hoverinfo="skip")
    fig.update_layout(annotations=annots, xaxis=dict(visible=False, range=[-0.7, 8.7]), yaxis=dict(visible=False, range=[-2.0, 1.4], scaleanchor=None))
    return fig


def _puces(trace: tuple, p) -> str:
    code = dict(zip(p.chemin, p.courts))
    palette = px.colors.qualitative.Safe + px.colors.qualitative.Set2
    couleur = {a: palette[i % len(palette)] for i, a in enumerate(list(p.chemin) + list(p.extras))}
    return '<div class="bp-trace">' + '<span class="bp-fleche">›</span>'.join(
        f'<span class="bp-puce" style="background:{couleur[a]}">{html.escape(code.get(a, a))}</span>' for a in trace) + "</div>"


def onglet_process_mining(e: dict) -> None:
    U._entete("Comment les processus se déroulent-ils réellement, et où perdent-ils du temps et de l'argent ?", "Process mining : journal d'événements, carte des suivis directs, conformité par alignement",
              "Corriger le processus avant de budgéter ses coûts", "Contrôle de gestion, achats, production, audit interne")
    st.caption("Le journal est synthétique et reproductible (une ligne par événement : cas, activité, horodatage, ressource). Un vrai journal viendrait de l'ERP avec exactement les mêmes colonnes.")
    nom = st.radio("Processus analysé", list(P.PROCESSUS), horizontal=True, key="bp_pm_proc")
    p = P.PROCESSUS[nom]
    log = _journal(nom)
    s = P.statistiques(log, nom)
    U._cartes([("Cas analysés", f"{s['cas']:,}".replace(",", " "), f"{s['evenements']:,} événements, {s['activites']} activités".replace(",", " "), "info"),
               ("Variantes", f"{s['variantes']}", f"les 3 premières couvrent {s['top3']:.0f} % des cas", "att" if s["variantes"] > 20 else "info"),
               ("Durée médiane", f"{s['duree_mediane']:.1f} j", f"90 % des cas sous {s['duree_p90']:.1f} j", "info"),
               ("Cas conformes", f"{s['conformes']:.0f} %", f"aptitude moyenne au modèle : {s['aptitude']:.2f}", "ok" if s["conformes"] >= 85 else ("att" if s["conformes"] >= 65 else "crit"))])
    arcs = P.suivis_directs(log)
    conf = P.conformite(log, nom)
    t1, t2, t3, t4, t5, t6 = st.tabs(["🗺 Carte du processus", "🧬 Variantes", "⏱ Goulots et délais", "✅ Conformité et contrôles", "📅 Chronologie", "💰 Lien avec le budget"])
    with t1:
        c1, c2 = st.columns([2, 1])
        seuil = c1.slider("Seuil de complexité : masquer les chemins empruntés par moins de … % des cas", 0.0, 30.0, 1.0, 0.5, key=f"bp_seuil_{nom}")
        freq = c2.checkbox("Afficher les fréquences", True, key=f"bp_freq_{nom}")
        st.plotly_chart(U._style(_fig_carte(nom, log, seuil, freq), 470), theme="streamlit", width="stretch", config=U.CONFIG, key=f"bp_carte_{nom}")
        st.caption("Les cercles portent le nombre de cas qui passent par l'activité. L'épaisseur d'une flèche est sa fréquence ; sa couleur, l'attente moyenne avant l'activité suivante (du bleu pâle au rouge). "
                   "Les arcs au-dessus sautent des étapes, ceux du bas bouclent sur une reprise.")
    with t2:
        v = P.variantes(log, nom)
        a, b = st.columns([2, 3])
        with a:
            top = v.head(12)
            fig = go.Figure()
            fig.add_bar(x=top["Variante"], y=top["Part (%)"], marker_color=["#1baf7a" if c else "#d9930a" for c in top["Conforme"]], name="Part des cas (%)")
            fig.add_scatter(x=top["Variante"], y=top["Cumul (%)"], mode="lines+markers", line=dict(color="#d03b3b"), name="Cumul (%)")
            fig.update_layout(title="Pareto des variantes (vert : conforme)")
            U._graphique(fig, f"bp_pareto_{nom}", 330)
        with b:
            for _, r in v.head(6).iterrows():
                st.html(f'<div class="bp-var"><div class="tete"><span><b>{r["Variante"]}</b>{" " if r["Conforme"] else "<span class=bp-ou>hors modèle</span>"}</span>'
                        f'<span>{int(r["Cas"])} cas · {r["Part (%)"]:.1f} % · médiane {r["Durée médiane (j)"]:.1f} j</span></div>'
                        f'<div class="bp-barre"><i style="width:{r["Part (%)"]:.1f}%;background:{"#1baf7a" if r["Conforme"] else "#d9930a"}"></i></div>{_puces(r["Trace"], p)}</div>')
        U._lecture(f"{s['variantes']} façons différentes d'exécuter le même processus, dont {int((~v['Conforme']).sum())} s'écartent du modèle. Les trois premières couvrent {s['top3']:.0f} % des cas : "
                   "le reste est une longue queue de cas particuliers, où se cachent les contournements.")
    with t3:
        g = P.goulots(arcs, 6)
        a, b = st.columns(2)
        with a:
            fig = go.Figure(go.Bar(y=[f"{r['De']} → {r['Vers']}" for _, r in g.iterrows()][::-1], x=g["Attente totale (h)"][::-1] / 24, orientation="h", marker_color="#d03b3b",
                                   text=[f"{x:.0f} % de l'attente" for x in g["Part de l'attente (%)"][::-1]], textposition="inside"))
            fig.update_layout(title="Où s'accumule l'attente (jours cumulés)")
            U._graphique(fig, f"bp_goulots_{nom}", 360)
        with b:
            d = P.durees_cas(log)
            fig = px.histogram(d, x="Durée (j)", nbins=30, color_discrete_sequence=[U.MARQUE])
            fig.add_vline(x=s["duree_mediane"], line=dict(color="#1baf7a", dash="dash"), annotation_text="médiane")
            fig.add_vline(x=s["duree_p90"], line=dict(color="#d03b3b", dash="dash"), annotation_text="90e centile")
            fig.update_layout(title="Durée de bout en bout des cas")
            U._graphique(fig, f"bp_duree_{nom}", 360)
        st.dataframe(g[["De", "Vers", "Fréquence", "Attente moyenne (h)", "Attente médiane (h)", "Part de l'attente (%)"]].style.format(
            {"Attente moyenne (h)": "{:,.0f}", "Attente médiane (h)": "{:,.0f}", "Part de l'attente (%)": "{:.1f}"}), hide_index=True, width="stretch")
        pire = g.iloc[0]
        U._lecture(f"Le principal goulot est « {pire['De']} → {pire['Vers']} » : {pire['Attente moyenne (h)']:.0f} h d'attente moyenne et {pire['Part de l\'attente (%)']:.0f} % de toute l'attente du processus. "
                   "C'est là qu'un gain de délai vaut le plus (escomptes manqués pour les achats, délais de livraison pour la fabrication).")
    with t4:
        r = P.resume_ecarts(conf)
        a, b = st.columns(2)
        with a:
            fig = go.Figure(go.Bar(x=r["Écart"], y=r["Cas"], marker_color=["#d03b3b", "#d9930a", "#8e5ec7"], text=r["Cas"], textposition="outside"))
            fig.update_layout(title="Cas par type d'écart (un cas peut cumuler)")
            U._graphique(fig, f"bp_ecarts_{nom}", 330)
        with b:
            fig = px.histogram(conf, x="Aptitude", nbins=20, color_discrete_sequence=["#2a9d8f"])
            fig.update_layout(title="Aptitude des cas au modèle de référence (1 = conforme)")
            U._graphique(fig, f"bp_apt_{nom}", 330)
        sautees = P.detail_sautees(conf)
        if len(sautees):
            st.markdown("###### Étapes de contrôle sautées")
            st.dataframe(sautees.rename("Cas").to_frame().rename_axis("Étape sautée"), width="stretch")
        sod = P.separation_taches(log, nom)
        if p.sod:
            st.markdown("###### Séparation des tâches")
            if len(sod):
                st.error(U._md(f"{len(sod)} facture(s) ont été enregistrées **et** approuvées par la même personne ({p.sod[0]} puis {p.sod[1]}), pour {sod['Montant ($)'].sum():,.0f} $.".replace(",", " ")), icon=":material/warning:")
                st.dataframe(sod.head(15).style.format({"Montant ($)": "{:,.0f}"}), hide_index=True, width="stretch")
            else:
                st.success("Aucune violation de la séparation des tâches.", icon=":material/check_circle:")
        U._lecture("L'alignement compare chaque cas à la séquence du modèle : une étape obligatoire absente, une activité répétée (reprise) ou un ordre inversé sont des écarts. "
                   "Pour un contrôleur, un écart sur une étape d'approbation est un risque de contrôle interne, pas seulement une inefficacité.")
    with t5:
        d = log[log["Cas"].isin(log["Cas"].drop_duplicates().head(250))].copy()
        ordre = {c: i for i, c in enumerate(d.groupby("Cas")["Horodatage"].min().sort_values().index)}
        d["Rang"] = d["Cas"].map(ordre)
        fig = px.scatter(d, x="Horodatage", y="Rang", color="Activité", hover_data=["Cas", "Ressource"], color_discrete_sequence=px.colors.qualitative.Safe + px.colors.qualitative.Set2, render_mode="webgl")
        fig.update_traces(marker=dict(size=5))
        fig.update_yaxes(title="Cas (du plus ancien au plus récent)", autorange="reversed")
        U._graphique(fig, f"bp_points_{nom}", 480)
        st.caption("Diagramme à points : chaque ligne est un cas, chaque point un événement. Les bandes inclinées sont le rythme normal ; les points isolés à droite d'une ligne sont les cas qui traînent.")
        hebdo = log.groupby(pd.Grouper(key="Horodatage", freq="W"))["Cas"].nunique()
        fig = go.Figure(go.Scatter(x=hebdo.index, y=hebdo.values, mode="lines", fill="tozeroy", line=dict(color=U.MARQUE)))
        fig.update_layout(title="Cas actifs par semaine")
        U._graphique(fig, f"bp_hebdo_{nom}", 260)
    with t6:
        cr = P.cout_reprises(log, nom)
        U._cartes([("Coût annuel des reprises", U._k(cr["annuel_k"]), f"{p.cas_annuels:,} cas par an".replace(",", " "), "att"),
                   ("Économie visée", U._k(cr["evitable_k"]), "la moitié des reprises évitée", "ok"),
                   ("Paquet de base zéro", "45 k$" if nom == P.ACHATS.nom else "—", "appariement automatisé des factures" if nom == P.ACHATS.nom else "non lié au budget des frais indirects", "info")])
        st.dataframe(cr["detail"].style.format({"Coût unitaire ($)": "{:,.0f}", "Coût ($)": "{:,.0f}"}), hide_index=True, width="stretch")
        if nom == P.ACHATS.nom:
            pq = e["bz"]["paquets"]
            ligne = pq[pq["Paquet"] == B.PAQUET_PM]
            if len(ligne):
                r0 = ligne.iloc[0]
                st.success(U._md(f"Le paquet « {B.PAQUET_PM} » coûte {r0['Coût (k$)']:.0f} k$ et fait économiser {e['eco_pm']:.0f} k$ par an en reprises évitées : son coût net est de {r0['Coût net (k$)']:.0f} k$ "
                                 f"(décision de la base zéro : {r0['Décision'].lower()})."), icon=":material/link:")
            else:
                st.info("Le paquet issu du process mining est désactivé dans l'onglet Base zéro.", icon=":material/link_off:")
        U._lecture("Le process mining boucle le cycle : il mesure le coût des reprises dans le journal, ce coût alimente un paquet de décision de la base zéro, et le budget retenu finance la correction. "
                   "Les reprises de fabrication sont aussi celles du poste « Reprises » du coût par commande.")


def afficher() -> None:
    st.html(U.CSS)
    st.html(CSS)
    st.caption(U._md("Planification budgétaire de l'exercice " + str(B.EXERCICE) + " : trois approches (top-down, bottom-up, base zéro), leur réconciliation et le process mining qui mesure où les processus coûtent le plus. "
                     "Chiffres fictifs modifiables ; tout se recalcule."))
    e = _etat()
    noms = ["🧭 Processus", "⬇ Top-down", "⬆ Bottom-up", "0️⃣ Base zéro", "⚖ Réconciliation", "⛏ Process mining"]
    fonctions = (onglet_processus, onglet_top_down, onglet_bottom_up, onglet_base_zero, onglet_reconciliation, onglet_process_mining)
    for onglet, f in zip(st.tabs(noms), fonctions):
        with onglet:
            f(e)
