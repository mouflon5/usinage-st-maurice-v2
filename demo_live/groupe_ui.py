"""Vue « Consolidation du groupe » : le cas intégrateur du Groupe Saint-Maurice (société mère, filiales à 100 %, Soudure Bécancour à 80 %, filiale américaine en USD).

Neuf onglets, comme les neuf étapes du chiffrier du cours : le groupe, les hypothèses, les balances et la conversion USD, l'acquisition et la répartition du prix,
les dix-neuf écritures, le chiffrier, la participation ne donnant pas le contrôle (PNDC), les états consolidés et les huit contrôles. Tout se recalcule quand on change
une hypothèse. Le moteur est consolidation_groupe.py (testé par test_consolidation_groupe.py).
"""
from __future__ import annotations

import re

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import consolidation_groupe as G
from consolidation_groupe_textes import NOTES
from demo_live import etats_ui

CONFIG = {"displaylogo": False, "modeBarButtonsToRemove": ["lasso2d", "select2d"]}
FAMILLES = ["Opérations réciproques", "Profits non réalisés", "Soldes réciproques", "Dividendes", "Placements", "Suivi de l'acquisition", "Attribution"]
COULEUR_FAMILLE = {"Opérations réciproques": "#2a78d6", "Profits non réalisés": "#d9930a", "Soldes réciproques": "#6250d6", "Dividendes": "#1baf7a", "Placements": "#8f9aa8",
                   "Suivi de l'acquisition": "#d03b3b", "Attribution": "#1f5f8b"}
DEFAUTS = G.Hypotheses()


def _md(texte):
    return re.sub(r"(?<!\\)\$", r"\\$", texte) if isinstance(texte, str) else texte


def _n(v) -> str:
    return etats_ui.nombre(v)


def _graphique(fig, cle: str, hauteur: int = 340) -> None:
    fig.update_layout(height=hauteur, margin=dict(l=10, r=10, t=30, b=10), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", legend_title_text="")
    st.plotly_chart(fig, theme="streamlit", width="stretch", config=CONFIG, key=cle)


def _tableau(lignes: list[tuple], entetes: list[str]) -> None:
    """lignes : (style, libellé, [valeurs])."""
    corps = "".join(f'<tr class="{s}"><td>{lib}</td>' + "".join(f'<td class="n">{_n(v) if isinstance(v, (int, float)) or v is None else v}</td>' for v in vals) + "</tr>"
                    for s, lib, vals in lignes)
    tete = "".join(f"<th>{e}</th>" for e in entetes)
    st.html(f'{etats_ui.CSS}<table class="ef"><thead><tr><th>En dollars canadiens</th>{tete}</tr></thead><tbody>{corps}</tbody></table>')


# --- Hypothèses -------------------------------------------------------------------------------------------------------------------------------
def _hypotheses() -> G.Hypotheses:
    s = st.session_state
    D = DEFAUTS
    with st.expander("⚙ Hypothèses — tout se recalcule à chaque changement", expanded=False):
        a, b, c = st.columns(3)
        with a:
            st.markdown("**Détention, impôt et change**")
            st.slider("Détention de Soudure Bécancour (%)", 51, 100, int(D.detention_sbe * 100), 1, key="gc_det", help="Le solde constitue la participation ne donnant pas le contrôle.")
            st.slider("Taux d'impôt combiné (%)", 0.0, 40.0, D.taux_impot * 100, 0.5, key="gc_imp", help="Impôts différés sur les écarts de juste valeur et sur le profit non réalisé.")
            st.number_input("Cours de clôture USD → CAD", 0.8, 2.0, D.cours_cloture, 0.005, format="%.4f", key="gc_cc", help="Actifs et passifs de la filiale américaine.")
            st.number_input("Cours moyen de l'exercice", 0.8, 2.0, D.cours_moyen, 0.005, format="%.4f", key="gc_cm", help="Produits, charges et amortissement.")
            st.number_input("Cours historique du capital", 0.8, 2.0, D.cours_historique, 0.005, format="%.4f", key="gc_ch",
                            help="Doit rester celui du placement inscrit à la mère (1,32) : sinon l'écriture E15 ne balance plus.")
        with b:
            st.markdown("**Acquisition de Soudure Bécancour**")
            st.number_input("Juste valeur de la PNDC ($)", 0.0, 5_000_000.0, D.jv_pndc, 10_000.0, key="gc_jvp", help="Le chapitre 1582 impose la juste valeur de la participation ne donnant pas le contrôle.")
            st.number_input("Écart de JV — immeuble et équipements ($)", 0.0, 3_000_000.0, D.jv_immobilisations, 10_000.0, key="gc_jv1")
            st.number_input("Écart de JV — relations clients ($)", 0.0, 3_000_000.0, D.jv_relations, 10_000.0, key="gc_jv2")
            st.number_input("Écart de JV — carnet de commandes ($)", 0.0, 2_000_000.0, D.jv_carnet, 10_000.0, key="gc_jv3")
            st.number_input("Passif repris — provision environnementale ($)", -1_000_000.0, 0.0, D.passif_repris, 10_000.0, key="gc_pass")
            st.slider("Mois d'amortissement dans l'exercice", 1, 12, int(D.mois_exercice), 1, key="gc_mois", help="Du 1er avril au 31 décembre : 9 mois.")
        with c:
            st.markdown("**Intragroupe et profit non réalisé**")
            st.number_input("Ventes de Soudure Bécancour à Usinage — amont ($)", 0.0, 5_000_000.0, D.ventes_amont, 10_000.0, key="gc_vam")
            st.number_input("Stocks de Soudure Bécancour encore détenus ($)", 0.0, 3_000_000.0, D.stocks_sbe, 10_000.0, key="gc_ssbe")
            st.slider("Marge brute du vendeur sur ces stocks (%)", 0.0, 60.0, D.marge_sbe * 100, 1.0, key="gc_msbe", help="La marge de Soudure Bécancour sur ces produits, pas la marge moyenne du groupe.")
            st.number_input("Stocks de Usinage chez USM Precision — aval ($)", 0.0, 3_000_000.0, D.stocks_usinage_chez_usp, 10_000.0, key="gc_susp",
                            help="Une vente descendante génère une élimination imputée à 100 % à la société mère.")
            st.number_input("Soldes intersociétés à éliminer ($)", 0.0, 3_000_000.0, D.soldes_interco, 10_000.0, key="gc_sol",
                            help="Modifiez-le pour provoquer un décalage de coupure : le contrôle de réciprocité le détecte.")
        st.button("↺ Revenir aux hypothèses de départ", key="gc_reset", on_click=lambda: [s.pop(k, None) for k in list(s) if k.startswith("gc_") and k != "gc_reset"])
    g = lambda k, d: s.get(k, d)
    return G.Hypotheses(
        detention_sbe=g("gc_det", D.detention_sbe * 100) / 100, taux_impot=g("gc_imp", D.taux_impot * 100) / 100, cours_cloture=g("gc_cc", D.cours_cloture),
        cours_moyen=g("gc_cm", D.cours_moyen), cours_historique=g("gc_ch", D.cours_historique), jv_pndc=g("gc_jvp", D.jv_pndc), jv_immobilisations=g("gc_jv1", D.jv_immobilisations),
        jv_relations=g("gc_jv2", D.jv_relations), jv_carnet=g("gc_jv3", D.jv_carnet), passif_repris=g("gc_pass", D.passif_repris), mois_exercice=float(g("gc_mois", D.mois_exercice)),
        ventes_amont=g("gc_vam", D.ventes_amont), stocks_sbe=g("gc_ssbe", D.stocks_sbe), marge_sbe=g("gc_msbe", D.marge_sbe * 100) / 100,
        stocks_usinage_chez_usp=g("gc_susp", D.stocks_usinage_chez_usp), soldes_interco=g("gc_sol", D.soldes_interco))


# --- Onglets ----------------------------------------------------------------------------------------------------------------------------------
def onglet_groupe(res: dict) -> None:
    h = res["hypotheses"]
    dot = f"""digraph G {{ rankdir=TB; bgcolor="transparent"; node [shape=box, style="rounded,filled", fontname="Helvetica", fontsize=11, color="#1f5f8b", fillcolor="#eaf1f7", fontcolor="#1b2430"];
      edge [color="#6b7785", fontname="Helvetica", fontsize=10, fontcolor="#6b7785"];
      GSM [label="Gestion Saint-Maurice inc.\\nsociété mère"]; USM [label="Usinage Saint-Maurice inc.\\nopérante"]; ISM [label="Immeubles Saint-Maurice inc.\\nusine louée à l'opérante"];
      SBE [label="Soudure Bécancour inc.\\nacquise le 1er avril 2025", fillcolor="#fdf1d6"]; USP [label="USM Precision Inc.\\nfiliale américaine (USD)", fillcolor="#e6f4ec"];
      GSM -> USM [label=" 100 %"]; GSM -> ISM [label=" 100 %"]; USM -> SBE [label=" {h.detention_sbe:.0%}"]; USM -> USP [label=" 100 %"]; }}"""
    c1, c2 = st.columns([3, 2])
    with c1:
        st.markdown("**Structure du groupe**")
        st.graphviz_chart(dot, width="stretch")
    with c2:
        st.markdown("**Le cas**")
        st.markdown(_md(f"Exercice clos le **31 décembre 2025**, référentiel **NCECF (Partie II)**, montants en dollars canadiens. Soudure Bécancour est détenue à **{h.detention_sbe:.0%}** depuis le "
                        f"1er avril 2025 : neuf mois de résultats seulement, et une participation ne donnant pas le contrôle (PNDC) de {1 - h.detention_sbe:.0%}. USM Precision tient ses livres en dollars US : "
                        "établissement autonome, méthode du cours de clôture."))
        st.caption("Hors du périmètre : Métallika s.e.n.c. (50 %, contrôle conjoint, valeur de consolidation, chapitre 3056) et Atelier Robotique Mauricie (35 %, influence notable, valeur de consolidation, "
                   "chapitre 3051) — une seule ligne au bilan, hors chiffrier.")
    st.dataframe(pd.DataFrame([{"Entité": G.NOMS[e], "Rôle": G.ROLES[e]} for e in G.ENTITES]), hide_index=True, width="stretch")
    k = res["chiffres_cles"]
    m = st.columns(4)
    m[0].metric("Produits consolidés", _n(k["Produits consolidés"]) + " $")
    m[1].metric("Résultat net consolidé", _n(k["Résultat net consolidé"]) + " $", f"minoritaires {_n(k['dont attribuable aux minoritaires'])} $", delta_color="off")
    m[2].metric("Total de l'actif", _n(k["Total de l'actif consolidé"]) + " $")
    ok = all(c["ok"] for c in res["controles"])
    m[3].metric("Contrôles", f"{sum(c['ok'] for c in res['controles'])} / {len(res['controles'])}", "chiffrier signable" if ok else "à corriger", delta_color="normal" if ok else "inverse")
    st.info(_md("**Chaîne de calcul.** Les balances (étape 02) alimentent le journal des dix-neuf écritures (étape 05), qui remplit les colonnes d'élimination du chiffrier (étape 06), d'où les états consolidés "
                "(étape 08) sont dérivés sans aucune saisie. Les écritures n'existent pas dans les livres des sociétés : elles vivent dans le chiffrier et doivent être recréées à chaque exercice."))


def onglet_balances(res: dict) -> None:
    bv = res["balances"]
    st.markdown("**Étape 02 — Les cinq balances de vérification** (débit positif, crédit négatif ; chaque colonne totalise zéro)")
    lignes, section = [], None
    for compte, sec in G.COMPTES:
        if sec != section:
            section = sec
            lignes.append(("titre", sec, [None] * 6))
        lignes.append(("ligne", compte, [bv.loc[compte, c] for c in (*G.ENTITES, "Total agrégé")]))
    lignes.append(("total", "CONTRÔLE — chaque colonne doit totaliser zéro", [bv[c].sum() for c in (*G.ENTITES, "Total agrégé")]))
    _tableau(lignes, [G.NOMS[e].replace("Saint-Maurice", "SM") if e != "USP" else "USM Precision (CAD)" for e in G.ENTITES] + ["Total agrégé"])
    st.markdown("**Étape 03 — Conversion de USM Precision Inc.**")
    st.caption("Établissement autonome → méthode du cours de clôture (chapitre 1651) : actifs et passifs au cours de clôture, produits et charges au cours moyen, capital-actions au cours historique, "
               "bénéfices non répartis d'ouverture reportés. L'écart de conversion est un résidu de bouclage, jamais au résultat.")
    conv = res["conversion"]
    st.dataframe(conv.style.format({"Solde (USD)": "{:,.0f}", "Taux": "{:.4f}", "Solde (CAD)": "{:,.0f}"}, na_rep="—"), hide_index=True, width="stretch")
    for k in ("conversion_1", "conversion_2", "conversion_3"):
        st.markdown(_md("- " + NOTES[k]))


def onglet_acquisition(res: dict) -> None:
    a, h = res["acquisition"], res["hypotheses"]
    st.markdown("**A · Répartition du prix d'acquisition (1er avril 2025)**")
    _tableau([("ligne", "Actif net comptable à la date d'acquisition (capital 500 000 $ et BNR 2 600 000 $)", [a["actif_net_comptable"]]),
              ("ligne", "Total des écarts de juste valeur, avant impôts (immeuble, relations clients, carnet, passif repris)", [a["ecarts_jv"]]),
              ("ligne", "Impôts différés sur les écarts de juste valeur", [-a["impots_differes"]]),
              ("total", "Juste valeur de l'actif net identifiable", [a["jv_actif_net"]])], ["Montant"])
    st.caption(NOTES["juste_valeur_impot"])
    st.markdown("**B · L'écart d'acquisition**")
    _tableau([("ligne", "Contrepartie transférée pour 80 % (placement chez l'opérante)", [a["contrepartie"]]), ("ligne", "Juste valeur de la PNDC", [a["jv_pndc"]]),
              ("sous", "Total à répartir", [a["a_repartir"]]), ("ligne", "Moins : juste valeur de l'actif net identifiable", [-a["jv_actif_net"]]),
              ("total", "ÉCART D'ACQUISITION", [a["goodwill"]])], ["Montant"])
    st.caption(NOTES["ecart_acquisition"])
    st.markdown("**Pour comparaison — option IFRS de la quote-part**")
    c1, c2, c3 = st.columns(3)
    c1.metric("PNDC à la quote-part", _n(a["pndc_quote_part"]) + " $")
    c2.metric("Écart d'acquisition en quote-part", _n(a["goodwill_quote_part"]) + " $")
    c3.metric("Écart attribuable à la PNDC", _n(a["diff_goodwill"]) + " $")
    st.caption(NOTES["ifrs"])
    st.markdown(f"**C · Amortissement des écarts de juste valeur — {h.mois_exercice:.0f} mois**")
    am = pd.DataFrame(a["amortissements"])
    st.dataframe(am.style.format({"Montant": "{:,.0f}", "Durée (ans)": "{:.1f}", "Charge annuelle": "{:,.0f}", "Charge de l'exercice": "{:,.0f}"}), hide_index=True, width="stretch")
    m = st.columns(3)
    m[0].metric("Amortissement additionnel", _n(a["amort_total"]) + " $")
    m[1].metric("Reprise d'impôts différés", _n(a["reprise_impots"]) + " $")
    m[2].metric("Réduction nette du résultat consolidé", _n(a["reduction_nette"]) + " $")
    st.info(_md(NOTES["amortissement_ppa"]))


def onglet_ecritures(res: dict) -> None:
    jr = res["journal"]
    deb = sum(l["debit"] for e in jr for l in e["lignes"])
    st.markdown("**Étape 05 — Les dix-neuf écritures de consolidation.** Aucune n'existe dans les livres des sociétés : elles vivent dans le chiffrier.")
    fam = st.multiselect("Familles affichées", FAMILLES, default=FAMILLES, key="gc_fam")
    resume = pd.DataFrame([{"Famille": f, "Écritures": sum(1 for e in jr if e["famille"] == f), "Total des débits ($)": sum(l["debit"] for e in jr if e["famille"] == f for l in e["lignes"])} for f in FAMILLES])
    fig = go.Figure(go.Bar(x=resume["Total des débits ($)"], y=resume["Famille"], orientation="h", marker_color=[COULEUR_FAMILLE[f] for f in resume["Famille"]],
                           text=[f"{n} écr." for n in resume["Écritures"]], textposition="outside"))
    fig.update_yaxes(autorange="reversed")
    _graphique(fig, "gc_fam_g", 260)
    for e in jr:
        if e["famille"] not in fam:
            continue
        total = sum(l["debit"] for l in e["lignes"])
        with st.expander(f"{e['no']} · {e['famille']} · {e['operation']} — {_n(total)} $", expanded=e["no"] in ("E16",)):
            t = pd.DataFrame([{"Compte touché": l["compte"], "Débit": l["debit"] or None, "Crédit": l["credit"] or None} for l in e["lignes"]])
            st.dataframe(t.style.format({"Débit": "{:,.2f}", "Crédit": "{:,.2f}"}, na_rep=""), hide_index=True, width="stretch")
            st.markdown(f"**Pourquoi.** {_md(e['pourquoi'])}")
    st.success(_md(f"Total des écritures : débits {_n(deb)} $ = crédits {_n(sum(l['credit'] for e in jr for l in e['lignes']))} $.")) if res["controles"][0]["ok"] else st.error("Les débits ne sont pas égaux aux crédits.")


def onglet_chiffrier(res: dict) -> None:
    ch = res["chiffrier"]
    st.markdown("**Étape 06 — Le chiffrier de consolidation.** Un compte par ligne, une entité par colonne ; les colonnes d'élimination se remplissent seules à partir du journal.")
    lignes, section = [], None
    for compte, sec in G.COMPTES:
        if sec != section:
            section = sec
            lignes.append(("titre", sec, [None] * 9))
        r = ch.loc[compte]
        lignes.append(("ligne", compte, [r[c] for c in (*G.ENTITES, "Agrégé", "Élim. débit", "Élim. crédit", "Consolidé")]))
    lignes.append(("total", "TOTAL — la colonne consolidée doit être nulle", [ch[c].sum() for c in (*G.ENTITES, "Agrégé", "Élim. débit", "Élim. crédit", "Consolidé")]))
    _tableau(lignes, ["GSM", "USM", "ISM", "SBE", "USP", "Agrégé", "Élim. Dr", "Élim. Cr", "Consolidé"])
    st.caption("Consolidé = somme des cinq entités + débits − crédits des écritures. Les placements, les soldes et les billets intersociétés, les dividendes et les honoraires tombent à zéro.")


def onglet_pndc(res: dict) -> None:
    p, h = res["pndc"], res["hypotheses"]
    st.markdown(f"**Étape 07 — La participation ne donnant pas le contrôle.** Les {1 - h.detention_sbe:.0%} de Soudure Bécancour conservés par l'ancien propriétaire : ni une dette, ni un actif — des capitaux propres qui ne vous appartiennent pas.")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**A · Le résultat attribuable aux minoritaires**")
        _tableau([("ligne", "Résultat net de Soudure Bécancour — 9 mois", [p["resultat_sbe"]]), ("ligne", "Amortissement des écarts de JV, net d'impôts", [p["amort_net"]]),
                  ("ligne", "Profit non réalisé en stocks, net d'impôts — vente amont", [p["nr_net"]]), ("sous", "Résultat ajusté de la filiale", [p["resultat_ajuste"]]),
                  ("ligne", f"Quote-part des minoritaires ({1 - h.detention_sbe:.0%})", [p["quote_part_pndc"]]), ("ligne", "Quote-part de la société mère", [p["quote_part_mere"]])], ["Montant"])
    with c2:
        st.markdown("**B · Continuité du solde au bilan**")
        _tableau([("ligne", "Solde à l'acquisition — 1er avril 2025", [p["solde_acquisition"]]), ("ligne", "Quote-part du résultat de l'exercice", [p["quote_part_pndc"]]),
                  ("ligne", "Dividendes versés aux minoritaires", [p["dividendes_min"]]), ("total", "Solde au 31 décembre 2025", [p["solde_cloture"]])], ["Montant"])
    fig = go.Figure(go.Bar(x=["Résultat de la filiale", "Écarts de JV (net)", "Profit non réalisé (net)", "Résultat ajusté", "Société mère", "Minoritaires"],
                           y=[p["resultat_sbe"], p["amort_net"], p["nr_net"], p["resultat_ajuste"], p["quote_part_mere"], p["quote_part_pndc"]],
                           marker_color=["#8f9aa8", "#d03b3b", "#d03b3b", "#1f5f8b", "#1baf7a", "#d9930a"]))
    _graphique(fig, "gc_pndc", 300)
    st.markdown(_md(f"**Le point de jugement.** {NOTES['pndc_jugement']}"))
    for k in ("pndc_ecarts", "pndc_amont", "pndc_quote_part"):
        st.caption("• " + NOTES[k])


def _effet_resultat(res: dict) -> dict[str, float]:
    """Effet de chaque famille d'écritures sur le résultat net (hors attribution), en dollars."""
    sections = dict(G.COMPTES)
    out = {}
    for e in res["journal"]:
        if e["famille"] == "Attribution":
            continue
        eff = sum((l["credit"] - l["debit"]) for l in e["lignes"] if sections[l["compte"]] in ("PRODUITS", "CHARGES"))
        out[e["famille"]] = out.get(e["famille"], 0.0) + eff
    return out


def onglet_etats(res: dict) -> None:
    et, k = res["etats"], res["chiffres_cles"]
    r, bn = et["resultats"], et["bnr"]
    st.markdown("**Étape 08 — Les états financiers consolidés** — entièrement dérivés du chiffrier, aucune saisie.")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Bilan consolidé au 31 décembre 2025**")
        lignes = [("titre", "Actif", [None])] + [("ligne", n, [v]) for n, v in et["actif"].items()] + [("ligne", f"⚠ {n} (non éliminé)", [v]) for n, v in et["residuels_actif"].items()] + [
            ("total", "TOTAL DE L'ACTIF", [et["total_actif"]]), ("titre", "Passif", [None])] + [("ligne", n, [v]) for n, v in et["passif"].items()] + [
            ("ligne", f"⚠ {n} (non éliminé)", [v]) for n, v in et["residuels_passif"].items()] + [("sous", "TOTAL DU PASSIF", [et["total_passif"]]), ("titre", "Capitaux propres", [None])] + [
            ("ligne", n, [v]) for n, v in et["cp"].items()] + [("sous", "TOTAL DES CAPITAUX PROPRES", [et["total_cp"]]), ("total", "TOTAL DU PASSIF ET DES CAPITAUX PROPRES", [et["total_passif"] + et["total_cp"]])]
        _tableau(lignes, ["31 déc. 2025"])
    with c2:
        st.markdown("**État des résultats consolidé — exercice 2025**")
        lignes = [("ligne", "Ventes", [r["ventes"]])] + ([("ligne", "⚠ Autres produits (non éliminés)", [r["autres_produits"]])] if abs(r["autres_produits"]) > 0.5 else []) + [
            ("sous", "TOTAL DES PRODUITS", [r["total_produits"]])] + [("ligne", n, [v]) for n, v in r["charges"] if abs(v) > 0.5 or n in ("Coût des ventes", "Charges d'intérêts")] + [
            ("sous", "TOTAL DES CHARGES", [r["total_charges"]]), ("sous", "RÉSULTAT AVANT IMPÔTS", [r["avant_impots"]]), ("ligne", "Impôts sur les bénéfices", [r["impots"]]),
            ("total", "RÉSULTAT NET", [r["net"]]), ("ligne", "Attribuable aux actionnaires minoritaires", [r["min"]]), ("ligne", "Attribuable aux actionnaires de la société mère", [r["mere"]])]
        _tableau(lignes, ["2025"])
        st.markdown("**Bénéfices non répartis consolidés**")
        _tableau([("ligne", "Solde au début, après élimination du pré-acquisition", [bn["debut"]]), ("ligne", "Résultat attribuable à la société mère", [bn["resultat_mere"]]),
                  ("ligne", "Dividendes déclarés par la société mère", [bn["dividendes"]]), ("total", "SOLDE À LA FIN", [bn["fin"]])], ["2025"])
    st.markdown("**Du résultat des cinq entités au résultat consolidé**")
    eff = _effet_resultat(res)
    agrege = r["net"] - sum(eff.values())
    etapes = [(f, v) for f, v in eff.items() if abs(v) > 0.5]
    fig = go.Figure(go.Waterfall(x=["Somme des résultats des entités", *[f for f, _ in etapes], "Résultat net consolidé"], measure=["absolute", *["relative"] * len(etapes), "total"],
                                 y=[agrege, *[v for _, v in etapes], None], increasing=dict(marker=dict(color="#1baf7a")), decreasing=dict(marker=dict(color="#d03b3b")),
                                 totals=dict(marker=dict(color="#1f5f8b")), connector=dict(line=dict(color="#8f9aa8"))))
    _graphique(fig, "gc_cascade", 330)
    st.caption("Les dividendes intragroupe (revenus de la mère comptés deux fois), le profit non réalisé et l'amortissement des écarts de juste valeur sont les trois écritures qui changent vraiment le résultat consolidé ; "
               "les autres éliminations déplacent des produits et des charges de même montant.")


def onglet_controles(res: dict) -> None:
    st.markdown("**Étape 09 — Les huit contrôles avant de signer.** Toutes les lignes doivent afficher CONFORME.")
    t = pd.DataFrame([{"Contrôle": c["controle"], "Écart calculé": c["ecart"], "Résultat": "CONFORME" if c["ok"] else "À CORRIGER", "Ce qu'il signifie": c["signification"]} for c in res["controles"]])
    st.dataframe(t.style.format({"Écart calculé": "{:,.2f}"}).map(lambda v: "color:#1baf7a;font-weight:600" if v == "CONFORME" else ("color:#d03b3b;font-weight:600" if v == "À CORRIGER" else ""), subset=["Résultat"]),
                 hide_index=True, width="stretch")
    if all(c["ok"] for c in res["controles"]):
        st.success("Le chiffrier est signable : les huit contrôles sont conformes.")
    else:
        st.error("Au moins un contrôle échoue : le chiffrier n'est pas signable. Un résidu intersociétés signale un décalage de coupure ou une refacturation traitée d'un seul côté.")
    st.markdown("**Chiffres clés du consolidé**")
    k = res["chiffres_cles"]
    st.dataframe(pd.DataFrame({"Indicateur": list(k), "Montant ($)": list(k.values())}).style.format({"Montant ($)": "{:,.2f}"}), hide_index=True, width="stretch")
    st.download_button("⬇ Télécharger le chiffrier, les écritures et les contrôles (Excel)", G.classeur_excel(res), file_name="Consolidation_Groupe_Saint-Maurice_2025.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


def afficher() -> None:
    st.caption(_md("Cas intégrateur du **Groupe Saint-Maurice** (cours de consolidation) : société mère, filiales à 100 %, Soudure Bécancour à 80 % et filiale américaine en USD. "
                   "Neuf étapes, du périmètre aux contrôles ; modifiez une hypothèse et tout se recalcule. Ces données sont indépendantes de la base de trésorerie."))
    h = _hypotheses()
    res = G.consolider(h)
    onglets = st.tabs(["🏛 Le groupe", "🧾 Balances et conversion", "🏷 Acquisition et PPA", "📝 Les 19 écritures", "📊 Chiffrier", "👥 PNDC", "📒 États consolidés", "✅ Contrôles"])
    for onglet, f in zip(onglets, (onglet_groupe, onglet_balances, onglet_acquisition, onglet_ecritures, onglet_chiffrier, onglet_pndc, onglet_etats, onglet_controles)):
        with onglet:
            f(res)
