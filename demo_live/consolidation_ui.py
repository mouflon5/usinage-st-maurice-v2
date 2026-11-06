"""Consolidation des trois divisions : onglets « Consolidé » et « Écritures de consolidation » de la vue « États financiers ».

  Consolidé                 hypothèses intercompagnies, états consolidés (résultats, bilan, flux, capitaux propres), chiffrier par division
  Écritures de consolidation  périmètre et méthode, opérations internes, écritures des divisions, étapes de la consolidation, journal des éliminations,
                              cascades agrégé → consolidé et contrôles

Le moteur est consolidation.py (testé par test_consolidation.py) ; les états consolidés retrouvent exactement les états existants de l'entreprise.
"""
from __future__ import annotations

import re

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import consolidation as K
import etats_financiers as ef

CONFIG = {"displaylogo": False, "modeBarButtonsToRemove": ["lasso2d", "select2d"]}
COULEURS = {"USI": "#1f5f8b", "PIE": "#d9930a", "PRO": "#2a78d6"}
DEFAUTS = K.ParametresConso()

TRAITEMENTS = {
    "EC-1": "Les pièces usinées que l'Usinage de précision cède aux Pièces de rechange et au Prototypage sont un revenu pour le vendeur et un achat pour l'acheteur, mais ni l'un ni l'autre pour "
            "l'entreprise : on retire le même montant des deux côtés. Aucun effet sur le résultat.",
    "EC-2": "Le temps-machine et la finition que l'atelier de l'Usinage de précision fournit aux Pièces de rechange et lui refacture sont un service interne : produit chez l'un, charge chez l'autre, nul pour l'entreprise.",
    "EC-3": "Le siège (logé dans l'Usinage de précision) facture des frais de gestion aux deux autres divisions : même élimination, des deux côtés.",
    "EC-4": "Les intérêts du prêt de l'Usinage de précision au Prototypage (équipements d'impression 3D et de métrologie) sont un produit financier d'un côté, une charge de l'autre : on retire les deux.",
    "EC-5": "Ce que l'Usinage de précision a facturé et qu'il n'a pas encore encaissé est une créance sur les Pièces de rechange et le Prototypage, qui l'inscrivent en dette : l'entreprise ne se doit rien à elle-même.",
    "EC-6": "Même logique pour le capital du prêt : à recevoir chez l'Usinage de précision, à rembourser chez le Prototypage. Aucun des deux n'a de sens dans le bilan consolidé.",
    "EC-7": "Les pièces achetées à l'Usinage de précision et encore en stock sont inscrites au prix de cession : leur valeur contient la marge de l'Usinage de précision. Pour l'entreprise, un stock "
            "vaut son coût : on retire la marge du stock et du résultat (profit non réalisé).",
    "EC-8": "La marge contenue dans les stocks de début a été retirée l'an dernier ; ces pièces se sont vendues cette année : la marge est maintenant réalisée. On l'ajoute au "
            "résultat (crédit au coût des produits vendus) en la retirant des bénéfices non répartis d'ouverture, pour ne la compter qu'une fois.",
}


def _md(texte):
    return re.sub(r"(?<!\\)\$", r"\\$", texte) if isinstance(texte, str) else texte


def _n(v) -> str:
    from demo_live import etats_ui
    return etats_ui.nombre(v)


def tableau_colonnes(lignes, entetes: list[str]) -> str:
    """Tableau HTML à plusieurs colonnes, dans le style des états financiers."""
    from demo_live import etats_ui
    corps = []
    for style, libelle, vals in lignes:
        cells = "".join(f'<td class="n">{etats_ui.nombre(v)}</td>' for v in vals)
        corps.append(f'<tr class="{style}"><td>{libelle}</td>{cells}</tr>')
    tete = "".join(f"<th>{e}</th>" for e in entetes)
    return f'{etats_ui.CSS}<table class="ef"><thead><tr><th>En dollars canadiens</th>{tete}</tr></thead><tbody>{"".join(corps)}</tbody></table>'


def parametres() -> K.ParametresConso:
    s = st.session_state
    return K.ParametresConso(
        achats_pie_chez_usi=s.get("co_q_pie", DEFAUTS.achats_pie_chez_usi * 100) / 100, achats_pro_chez_usi=s.get("co_q_pro", DEFAUTS.achats_pro_chez_usi * 100) / 100,
        majoration=s.get("co_maj", DEFAUTS.majoration * 100) / 100, temps_machine_pct=s.get("co_tm", DEFAUTS.temps_machine_pct * 100) / 100,
        gestion_pct=s.get("co_ges", DEFAUTS.gestion_pct * 100) / 100, pret=s.get("co_pret", DEFAUTS.pret), taux_pret=s.get("co_taux", DEFAUTS.taux_pret * 100) / 100,
        jours_ic=s.get("co_jours", DEFAUTS.jours_ic))


def _hypotheses() -> None:
    with st.expander("⚙ Hypothèses des opérations entre divisions — tout se recalcule", expanded=False):
        a, b, c = st.columns(3)
        with a:
            st.markdown("**Produits**")
            st.slider("Part des pièces de rechange fabriquée par l'Usinage de précision (%)", 0, 100, int(DEFAUTS.achats_pie_chez_usi * 100), 5, key="co_q_pie")
            st.slider("Part des composants de prototypes usinés par l'Usinage de précision (%)", 0, 100, int(DEFAUTS.achats_pro_chez_usi * 100), 5, key="co_q_pro")
            st.slider("Majoration du prix de cession (% du coût)", 0.0, 30.0, DEFAUTS.majoration * 100, 0.5, key="co_maj",
                      help="Le prix de cession interne = coût × (1 + majoration). Plus il est élevé, plus l'Usinage de précision gagne et plus la marge interne des stocks est grande.")
        with b:
            st.markdown("**Services**")
            st.slider("Temps-machine refacturé aux Pièces de rechange (% de leurs ventes)", 0.0, 12.0, DEFAUTS.temps_machine_pct * 100, 0.5, key="co_tm")
            st.slider("Frais de gestion facturés aux Pièces de rechange et au Prototypage (% de leurs ventes)", 0.0, 5.0, DEFAUTS.gestion_pct * 100, 0.1, key="co_ges")
        with c:
            st.markdown("**Financement et règlement**")
            st.number_input("Prêt de l'Usinage de précision au Prototypage ($)", 0.0, 2_000_000.0, DEFAUTS.pret, 50_000.0, key="co_pret")
            st.slider("Taux d'intérêt du prêt (%)", 0.0, 12.0, DEFAUTS.taux_pret * 100, 0.25, key="co_taux")
            st.slider("Délai de règlement des factures internes (jours)", 0, 90, int(DEFAUTS.jours_ic), 5, key="co_jours")
        st.caption("Les montants varient, mais le consolidé reste égal aux états existants : les éliminations annulent exactement ce qui est interne.")


def afficher_consolide(res: dict, j: ef.Journal, annee: int, pres: dict, titre_bilan: tuple[str, str]) -> None:
    from demo_live import etats_ui
    st.caption(_md("États consolidés des trois divisions de Groupe Usinage Saint-Maurice — **Usinage de précision**, **Pièces de rechange et service**, **Prototypage et ingénierie**. "
                   "Chaque division présente ses états, avec les opérations qu'elle fait avec les autres ; les éliminations (onglet « Écritures de consolidation ») retirent "
                   "tout ce qui est interne. Les montants des divisions sont des répartitions pro forma des états existants : l'entreprise ne tient pas de livres par division."))
    _hypotheses()
    c = K.consolider(res, annee, parametres())
    ctr = K.controles(c)
    ar, cr, er = c["agrege_r"], c["consolide_r"], c["elim_r"]
    k = st.columns(4)
    k[0].metric("Produits — somme des divisions", _n(ar["total_produits"]) + " $")
    k[1].metric("Éliminations (opérations internes)", _n(er["total_produits"]) + " $", help="Ventes de produits, services et frais de gestion entre divisions.")
    k[2].metric("Produits consolidés", _n(cr["total_produits"]) + " $")
    ok = all(x["ok"] for x in ctr)
    k[3].metric("Contrôles de consolidation", f"{sum(x['ok'] for x in ctr)} / {len(ctr)}", "égal aux états existants" if ok else "écart à examiner", delta_color="normal" if ok else "inverse")
    if not ok:
        st.error("Un contrôle de consolidation échoue : voir l'onglet « Écritures de consolidation ».")

    vue = st.radio("Présentation", ["États consolidés", "Chiffrier par division"], horizontal=True, key="co_vue",
                   help="« États consolidés » : les états de l'entreprise, ligne par ligne. « Chiffrier » : chaque division, leur somme, les éliminations, le consolidé.")
    entetes = [*K.DIVISIONS.values(), "Somme", "Éliminations", "Consolidé"]
    t1, t2, t3, t4, t5 = st.tabs(["📈 Résultats", "🏦 Bilan", "💧 Flux de trésorerie", "🧾 Capitaux propres", "🧩 Poids des divisions"])
    chiffrier = K.presenter(c)
    with t1:
        st.html(etats_ui.tableau_html(pres["resultats"], annee, (f"FY{annee} consolidé", f"FY{annee - 1}")) if vue == "États consolidés"
                else tableau_colonnes(chiffrier["resultats"], entetes))
    with t2:
        st.html(etats_ui.tableau_html(pres["bilan"], annee, titre_bilan) if vue == "États consolidés" else tableau_colonnes(chiffrier["bilan"], entetes))
    with t3:
        st.html(etats_ui.tableau_html(pres["flux"], annee))
        st.caption("Le tableau des flux se prépare à l'échelle consolidée : les opérations internes n'ont aucun effet sur la trésorerie de l'entreprise (un décaissement d'une "
                   "division est l'encaissement d'une autre). Les variations de créances, de stocks et de fournisseurs sont celles des soldes consolidés, déjà nets des éliminations.")
    with t4:
        st.html(etats_ui.tableau_html(pres["capitaux"], annee))
        st.caption("Les divisions ne détiennent pas de titres les unes des autres : le capital-actions consolidé est celui de l'entreprise et aucune élimination de participation "
                   "n'est nécessaire. La seule écriture qui touche les bénéfices non répartis est celle de la marge interne des stocks de début (EC-8).")
    with t5:
        _poids(c)
    st.download_button("⬇ Télécharger le chiffrier et les écritures de consolidation (Excel)", K.classeur_excel(c), file_name=f"Consolidation_FY{annee}.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


def _poids(c: dict) -> None:
    r = c["divisions"]
    noms = list(K.DIVISIONS.values())
    fig = go.Figure()
    fig.add_bar(x=noms, y=r["total_produits"], name="Produits (avant éliminations)", marker_color="#8f9aa8")
    fig.add_bar(x=noms, y=r["baiia"], name="BAIIA", marker_color="#1f5f8b")
    fig.add_bar(x=noms, y=r["net"], name="Résultat net", marker_color="#d9930a")
    fig.update_layout(barmode="group", height=340, margin=dict(l=10, r=10, t=30, b=10), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", legend_title_text="")
    st.plotly_chart(fig, theme="streamlit", width="stretch", config=CONFIG, key="co_poids")
    tab = pd.DataFrame({"Division": noms, "Produits": r["total_produits"], "dont ventes à d'autres divisions": [r["ventes_ic"][i] + r["services_ic"][i] + r["gestion_ic"][i] for i in range(3)],
                        "Marge brute": r["marge_brute"], "BAIIA": r["baiia"], "Résultat net": r["net"], "Actif": c["bilans"]["total_actif"]})
    tab["Marge nette"] = tab["Résultat net"] / tab["Produits"]
    st.dataframe(tab.style.format({col: "{:,.0f}" for col in tab.columns if col not in ("Division", "Marge nette")} | {"Marge nette": "{:.1%}"}), hide_index=True, width="stretch")
    st.caption("Répartition pro forma : les divisions sont rentables à des degrés différents parce que les marges internes (prix de cession, temps-machine, frais de gestion) déplacent du "
               "résultat vers l'Usinage de précision. Ces déplacements s'annulent à la consolidation : le résultat de l'entreprise n'en est pas changé.")


# --- Écritures et traitements ----------------------------------------------------------------------------------------------------------------
def _cascade(titre: str, depart: tuple[str, float], etapes: list[tuple[str, float]], arrivee: str, cle: str) -> None:
    y = [depart[1], *[v for _, v in etapes], None]
    fig = go.Figure(go.Waterfall(x=[depart[0], *[n for n, _ in etapes], arrivee], measure=["absolute", *["relative"] * len(etapes), "total"], y=y,
                                 decreasing=dict(marker=dict(color="#d03b3b")), increasing=dict(marker=dict(color="#1baf7a")), totals=dict(marker=dict(color="#1f5f8b")),
                                 connector=dict(line=dict(color="#8f9aa8"))))
    fig.update_layout(title=titre, height=320, margin=dict(l=10, r=10, t=40, b=10), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", showlegend=False)
    fin = depart[1] + sum(v for _, v in etapes)
    fig.update_yaxes(range=[min(fin, depart[1]) * 0.9, depart[1] * 1.03])
    st.plotly_chart(fig, theme="streamlit", width="stretch", config=CONFIG, key=cle)


def afficher_ecritures(res: dict, annee: int) -> None:
    pc = parametres()
    c = K.consolider(res, annee, pc)
    ic, er, eb = c["interco"], c["elim_r"], c["elim_b"]
    d = lambda v: _n(v) + " $"
    st.caption(_md("Tout ce que la consolidation demande de comptabiliser, de la répartition des états jusqu'au contrôle final. Les montants suivent les hypothèses de l'onglet « Consolidé »."))

    st.markdown("###### 1 · Périmètre et méthode")
    a, b, cc = st.columns(3)
    with a, st.container(border=True):
        st.markdown("**Périmètre**")
        st.markdown("Trois divisions d'une même société : **Usinage de précision** (usine, machines CNC, soudure, siège), **Pièces de rechange et service**, "
                    "**Prototypage et ingénierie**. Aucune ne détient de titres d'une autre.")
    with b, st.container(border=True):
        st.markdown("**Méthode**")
        st.markdown("Regroupement ligne par ligne, puis **élimination des opérations internes** : produits et charges, soldes à recevoir et à payer, prêt, marge interne des stocks.")
    with cc, st.container(border=True):
        st.markdown("**Ce qui n'a pas lieu d'être**")
        st.markdown("Élimination de titres de participation, écart d'acquisition, part des actionnaires sans contrôle, conversion de devises : sans objet pour des divisions "
                    "détenues à 100 % dans une société unique.")

    st.markdown("###### 2 · Opérations entre divisions de l'exercice")
    ops = pd.DataFrame([
        ("Vente de pièces", "Usinage → Pièces de rechange", ic["ventes_produits"][1], "Prix de cession : coût × (1 + majoration)"),
        ("Vente de pièces", "Usinage → Prototypage", ic["ventes_produits"][2], "Idem"),
        ("Temps-machine refacturé", "Usinage → Pièces de rechange", ic["services"], f"{pc.temps_machine_pct:.1%} des ventes des Pièces de rechange".replace(".", ",")),
        ("Frais de gestion", "Usinage → Pièces de rechange", ic["gestion"][1], f"{pc.gestion_pct:.1%} des ventes".replace(".", ",")),
        ("Frais de gestion", "Usinage → Prototypage", ic["gestion"][2], "Idem"),
        ("Prêt (solde de clôture)", "Usinage → Prototypage", ic["pret"], "Remboursable : non courant"),
        ("Intérêts du prêt", "Prototypage → Usinage", ic["interet"], f"{pc.taux_pret:.2%} du prêt".replace(".", ",")),
        ("Marge interne dans les stocks de fin", "Pièces de rechange et Prototypage", ic["nr_fin"], "Majoration × stocks internes à la clôture"),
        ("Marge interne dans les stocks de début", "Pièces de rechange et Prototypage", ic["nr_deb"], "Même calcul, stocks de l'exercice précédent"),
    ], columns=["Opération", "Entre", "Montant ($)", "Base"])
    st.dataframe(ops.style.format({"Montant ($)": "{:,.0f}"}), hide_index=True, width="stretch")

    st.markdown("###### 3 · Écritures passées dans les divisions (avant consolidation)")
    st.caption("Chaque division enregistre ses opérations internes dans ses propres livres, comme avec un tiers. C'est ce qui gonfle les produits, les charges, les créances et les dettes de la somme des divisions.")
    ed = pd.DataFrame(K.ecritures_divisions(c))
    ops_liste = list(dict.fromkeys(ed["operation"]))
    choix = st.multiselect("Opérations affichées", ops_liste, default=ops_liste[:2], key="co_ops")
    sel = ed[ed["operation"].isin(choix)].rename(columns={"operation": "Opération", "division": "Division", "compte": "Compte", "libelle": "Libellé", "debit": "Débit", "credit": "Crédit"})
    st.dataframe(sel.style.format({"Débit": lambda v: "" if not v else f"{v:,.0f}", "Crédit": lambda v: "" if not v else f"{v:,.0f}"}), hide_index=True, width="stretch")

    st.markdown("###### 4 · Étapes de la consolidation")
    with st.expander("Étape 1 — Répartir les états entre les divisions"):
        st.markdown("Les produits, charges, actifs et passifs des états existants sont répartis par des clés (ventes par catégorie, charges par nature, immobilisations, dettes). "
                    "Chaque clé totalise 100 % : la somme des divisions retrouve l'entreprise **avant** toute opération interne "
                    f"(résultat avant impôts : {d(sum(ic['avant_impot_ext']))}).")
    with st.expander("Étape 2 — Enregistrer les opérations internes dans chaque division"):
        st.markdown(_md(f"Les divisions facturent et achètent entre elles : la somme des divisions affiche {d(c['agrege_r']['total_produits'])} de produits, dont "
                        f"{d(-er['total_produits'])} sont internes. Les soldes à recevoir et à payer (délai de {pc.jours_ic:.0f} jours) créent {d(ic['creance'])} de créances et autant de dettes."))
    with st.expander("Étape 3 — Éliminer les produits et les charges internes (EC-1 à EC-4)"):
        st.markdown(_md(f"On débite le produit interne du vendeur et on crédite la charge interne de l'acheteur, pour le même montant : ventes de pièces {d(sum(ic['ventes_produits']))}, "
                        f"temps-machine {d(ic['services'])}, frais de gestion {d(sum(ic['gestion']))}, intérêts {d(ic['interet'])}. Le résultat ne bouge pas : "
                        "les deux côtés s'annulent."))
    with st.expander("Étape 4 — Éliminer les soldes internes (EC-5 et EC-6)"):
        st.markdown(_md(f"Créances de l'Usinage de précision ({d(ic['creance'])}) contre dettes des Pièces de rechange et du Prototypage ({d(sum(ic['dettes']))}), et prêt ({d(ic['pret'])}) contre emprunt : "
                        "ils s'annulent. Le total de l'actif consolidé diminue de "
                        f"{d(-eb['total_actif'])}."))
    with st.expander("Étape 5 — Éliminer la marge interne des stocks (EC-7 et EC-8)", expanded=True):
        m = pc.majoration
        st.markdown(_md(f"Les Pièces de rechange et le Prototypage détiennent à la clôture {d(sum(ic['stock_ic_fin']))} de pièces (au coût) achetées à l'Usinage de précision. Inscrits au prix de cession, ils valent "
                        f"{m:.0%} de plus : la marge de l'Usinage de précision ({d(ic['nr_fin'])}) n'est pas réalisée tant que les pièces ne sont pas vendues à un client.".replace(".", ",")))
        st.latex(r"\text{Marge non réalisée} = \text{majoration} \times \text{stocks internes (au coût)}")
        st.markdown(_md(f"À la clôture : {m:.0%} × {d(sum(ic['stock_ic_fin']))} = **{d(ic['nr_fin'])}** (EC-7). Au début : {m:.0%} × {d(sum(ic['stock_ic_deb']))} = **{d(ic['nr_deb'])}**, "
                        f"maintenant réalisée (EC-8). L'effet net sur le résultat est de {d(ic['nr_fin'] - ic['nr_deb'])}.".replace(".", ",")))
    with st.expander("Étape 6 — Impôts"):
        st.markdown("Les divisions appartiennent à une seule société qui produit **une** déclaration : l'impôt se calcule sur le résultat consolidé, puis se répartit sur les divisions selon leur "
                    "résultat avant impôts hors marge de cession. La marge interne des stocks n'est donc imposée nulle part, et **aucun impôt différé** n'est à comptabiliser. "
                    "Si les divisions étaient des sociétés distinctes, chacune paierait l'impôt sur sa marge interne : on constaterait alors un actif d'impôt différé "
                    "(taux × marge non réalisée), à comptabiliser dans une écriture de plus.")
    with st.expander("Étape 7 — Contrôler"):
        st.markdown("Chaque écriture s'équilibre ; chaque compte interne s'annule ; et le consolidé retrouve les états existants ligne par ligne (voir le tableau en bas de page).")

    st.markdown("###### 5 · Journal des écritures de consolidation")
    jr = pd.DataFrame(c["journal"])
    for no in dict.fromkeys(jr["no"]):
        lignes = jr[jr["no"] == no]
        with st.expander(f"{no} — {lignes.iloc[0]['titre']} — {d(lignes['debit'].sum())}"):
            st.dataframe(lignes[["compte", "libelle", "debit", "credit"]].rename(columns={"compte": "Compte", "libelle": "Libellé", "debit": "Débit", "credit": "Crédit"})
                         .style.format({"Débit": lambda v: "" if not v else f"{v:,.0f}", "Crédit": lambda v: "" if not v else f"{v:,.0f}"}), hide_index=True, width="stretch")
            st.markdown(f"**Traitement.** {TRAITEMENTS[no]}")
    st.markdown(f"**Total des écritures : débits {d(jr['debit'].sum())} = crédits {d(jr['credit'].sum())}.**")

    st.markdown("###### 6 · De la somme des divisions au consolidé")
    g, h = st.columns(2)
    with g:
        _cascade("Total des produits", ("Somme des divisions", c["agrege_r"]["total_produits"]),
                 [("Ventes de pièces", er["ventes_ic"]), ("Temps-machine", er["services_ic"]), ("Frais de gestion", er["gestion_ic"])], "Consolidé", "co_cas_r")
    with h:
        _cascade("Total de l'actif", ("Somme des divisions", c["agrege_b"]["total_actif"]),
                 [("Créances internes", eb["creances_ic"]), ("Prêt interne", eb["pret_ic"]), ("Marge interne des stocks", eb["stocks"])], "Consolidé", "co_cas_b")

    st.markdown("###### 7 · Comptes intercompagnies utilisés")
    st.dataframe(pd.DataFrame(K.COMPTES_IC, columns=["Compte", "Libellé", "État", "Nature"]), hide_index=True, width="stretch")

    st.markdown("###### 8 · Contrôles")
    ctr = pd.DataFrame(K.controles(c))
    ctr["Résultat"] = ctr["ok"].map({True: "✓", False: "✕"})
    st.dataframe(ctr.rename(columns={"controle": "Contrôle", "ecart": "Écart ($)"})[["Contrôle", "Résultat", "Écart ($)"]].style.format({"Écart ($)": "{:,.2f}"}), hide_index=True, width="stretch")
    if all(ctr["ok"]):
        st.success("Tous les contrôles passent : le consolidé égale les états existants et les écritures s'équilibrent.")
    else:
        st.error("Au moins un contrôle échoue.")
