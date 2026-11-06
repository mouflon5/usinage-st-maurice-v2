"""Vue « États financiers » : résultats, bilan, flux de trésorerie et variation des capitaux propres — dynamiques.

Tout se recalcule à chaque changement d'hypothèse (jours de créances, investissements, impôts, scénario…) à partir du journal général de
la base de démonstration : un passage d'agents qui ajoute des écritures modifie donc aussi les états. Le moteur (etats_financiers.py)
est un modèle à trois états liés, contrôlé par des identités comptables affichées dans l'onglet « Analyse ».

Deux onglets présentent la consolidation des trois divisions (consolidation_ui.py, moteur consolidation.py) : « Consolidé » (états consolidés et
chiffrier par division) et « Écritures de consolidation » (opérations internes, éliminations, contrôles).
"""
from __future__ import annotations

import math
import os

import pandas as pd
import streamlit as st

import etats_financiers as ef
from demo_live import consolidation_ui, moteur as M, navigation_ui as NAV

# clé → (défaut, libellé) ; les pourcentages sont saisis en % et convertis en fractions
DEFAUTS = {
    "ef_var_ventes": 0.0, "ef_var_produits": 0.0, "ef_var_charges": 0.0, "ef_var_taux": 0.0,
    "ef_dso": None, "ef_dio": 12.0, "ef_dpo": 30.0,
    "ef_capex": 450_000.0, "ef_amort": 12.0, "ef_impot": 26.5, "ef_impaye": 25.0, "ef_div": 50.0, "ef_emission": 0.0,
    "ef_tirages": 100.0, "ef_int_bdc": 15.0,
    "ef_cash0": 400_000.0, "ef_immo0": 3_500_000.0, "ef_bdc0": 1_000_000.0, "ef_marge0": None, "ef_capital": 500_000.0,
}

CSS = """<style>
.ef{width:100%;border-collapse:collapse;font-size:.92rem;font-variant-numeric:tabular-nums}
.ef th{text-align:right;font-weight:600;padding:6px 10px;border-bottom:2px solid rgba(128,128,128,.55)}
.ef th:first-child{text-align:left}
.ef td{padding:4px 10px;border-bottom:1px solid rgba(128,128,128,.18)}
.ef td.n{text-align:right;white-space:nowrap}
.ef td.nb{color:#c0392b}
.ef tr.titre td{font-weight:700;padding-top:12px;border-bottom:1px solid rgba(128,128,128,.4);letter-spacing:.02em}
.ef tr.ligne td:first-child{padding-left:22px}
.ef tr.sous td{font-weight:600;border-top:1px solid rgba(128,128,128,.55)}
.ef tr.total td{font-weight:700;border-top:2px solid rgba(128,128,128,.7);border-bottom:3px double rgba(128,128,128,.7);background:rgba(31,95,139,.09)}
.ef tr.info td{font-size:.82rem;opacity:.75;font-style:italic}
</style>"""


def nombre(v) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return ""
    if abs(v) < 0.5:
        return "—"
    s = f"{abs(v):,.0f}".replace(",", " ")
    return f"({s})" if v < 0 else s


def tableau_html(lignes, annee: int, titre_col: tuple[str, str] | None = None) -> str:
    entetes = titre_col or (f"FY{annee}", f"FY{annee - 1}")
    corps = []
    for style, libelle, vals in lignes:
        cells = "".join(f'<td class="n{" nb" if (v is not None and v < -0.5 and style == "total") else ""}">{nombre(v)}</td>' for v in vals)
        corps.append(f'<tr class="{style}"><td>{libelle}</td>{cells}</tr>')
    return (f'{CSS}<table class="ef"><thead><tr><th>En dollars canadiens</th><th>{entetes[0]}</th><th>{entetes[1]}</th></tr></thead>'
            f'<tbody>{"".join(corps)}</tbody></table>')


@st.cache_data(show_spinner=False)
def _journal(chemin: str, mtime: float) -> ef.Journal:
    return ef.lire_journal(chemin)


def _initialiser(j: ef.Journal):
    base = ef.parametres_par_defaut(j)
    for k, v in DEFAUTS.items():
        if k not in st.session_state:
            st.session_state[k] = {"ef_dso": base.dso, "ef_marge0": base.marge_ouverture or 0.0}.get(k, v)
    st.session_state.setdefault("ef_scen", "Base")
    st.session_state.setdefault("ef_depuis", j.annees[-1])


def _reinitialiser(j: ef.Journal):
    for k in list(DEFAUTS) + ["ef_scen", "ef_depuis", "ef_origine"]:
        st.session_state.pop(k, None)
    _initialiser(j)


def _appliquer_envoi(j: ef.Journal):
    """Applique un scénario envoyé par une autre vue (ex. « Prix des métaux »). Les clés des curseurs ne survivent pas à une vue où
    ils ne sont pas dessinés : l'autre vue dépose donc le scénario dans `ef_envoi`, et on le copie ici avant de dessiner les curseurs."""
    e = st.session_state.pop("ef_envoi", None)
    if not e:
        return
    s = st.session_state
    s.update(ef_scen="Personnalisé", ef_var_ventes=e["ventes"], ef_var_produits=e["produits"], ef_var_charges=0.0, ef_var_taux=0.0,
             ef_depuis=e["annee"] if e["annee"] in j.annees else j.annees[-1], ef_origine=e)


def _origine():
    """Rappel du scénario envoyé par une autre vue, tant que les curseurs n'ont pas bougé."""
    s, e = st.session_state, st.session_state.get("ef_origine")
    if e and (s.get("ef_var_ventes"), s.get("ef_var_produits"), s.get("ef_var_charges"), s.get("ef_var_taux")) == (e["ventes"], e["produits"], 0.0, 0.0):
        st.info(f"Scénario « prix des métaux — {e['libelle'].lower()} » appliqué à FY{s['ef_depuis']} : ventes {e['ventes']:+.1f} %, prix des produits "
                f"achetés {e['produits']:+.1f} %. Pour le modifier, voir la vue « 🔩 Prix des métaux ».".replace("$", "\\$"))


def _preset():
    ventes, charges = ef.SCENARIOS.get(st.session_state["ef_scen"], (None, None))
    if ventes is not None:
        st.session_state["ef_var_ventes"] = 100 * ventes
        st.session_state["ef_var_produits"] = 100 * ventes          # les achats suivent le volume vendu
        st.session_state["ef_var_charges"] = 100 * charges


def _parametres(j: ef.Journal) -> ef.Parametres:
    s = st.session_state
    return ef.Parametres(
        var_ventes=s["ef_var_ventes"] / 100, var_cout_produits=s["ef_var_produits"] / 100, var_charges=s["ef_var_charges"] / 100,
        var_taux=s["ef_var_taux"] / 100, annee_scenario=s["ef_depuis"], dso=s["ef_dso"], dio=s["ef_dio"], dpo=s["ef_dpo"],
        capex=s["ef_capex"], taux_amort=s["ef_amort"] / 100, taux_impot=s["ef_impot"] / 100, impot_impaye=s["ef_impaye"] / 100,
        dividendes_pct=s["ef_div"] / 100, emission_actions=s["ef_emission"], tirages_marge_pct=s["ef_tirages"] / 100,
        part_interets_bdc=s["ef_int_bdc"] / 100, encaisse_ouverture=s["ef_cash0"], immobilisations_ouverture=s["ef_immo0"],
        bdc_ouverture=s["ef_bdc0"], marge_ouverture=s["ef_marge0"], capital_actions=s["ef_capital"])


def _hypotheses(j: ef.Journal, ouvert: bool = True):
    with st.expander("⚙ Hypothèses — tout se recalcule à chaque changement", expanded=ouvert):
        a, b, c = st.columns(3)
        with a:
            st.markdown("**Scénario**")
            st.selectbox("Scénario prédéfini", ["Pessimiste", "Base", "Optimiste", "Personnalisé"], key="ef_scen", on_change=_preset,
                         help="Reprend les scénarios de la table `parametres` : ventes −10 % / charges +10 % (pessimiste), +5 % / −5 % (optimiste).")
            st.slider("Variation des ventes (%)", -30.0, 30.0, step=0.5, key="ef_var_ventes")
            st.slider("Variation du prix des produits achetés (%)", -30.0, 30.0, step=0.5, key="ef_var_produits")
            st.slider("Variation des autres charges (%)", -30.0, 30.0, step=0.5, key="ef_var_charges")
            st.slider("Variation du taux d'intérêt (%)", -50.0, 50.0, step=1.0, key="ef_var_taux")
            st.selectbox("S'applique à partir de l'exercice", j.annees, key="ef_depuis",
                         help="Les exercices antérieurs restent les chiffres du journal.")
        with b:
            st.markdown("**Fonds de roulement**")
            st.slider("Jours de ventes en comptes clients", 0.0, 120.0, step=1.0, key="ef_dso")
            st.slider("Jours d'achats en stock", 0.0, 90.0, step=1.0, key="ef_dio")
            st.slider("Jours d'achats en fournisseurs", 0.0, 120.0, step=1.0, key="ef_dpo")
            st.markdown("**Impôts et capital**")
            st.slider("Taux d'impôt (%)", 0.0, 50.0, step=0.5, key="ef_impot")
            st.slider("Part de l'impôt encore à payer à la clôture (%)", 0.0, 100.0, step=5.0, key="ef_impaye")
            st.slider("Dividendes (% du résultat net)", 0.0, 100.0, step=5.0, key="ef_div")
            st.number_input("Émission d'actions ($ par exercice)", min_value=0.0, step=50_000.0, key="ef_emission")
        with c:
            st.markdown("**Investissements et dettes**")
            st.number_input("Acquisitions d'immobilisations ($ par exercice)", min_value=0.0, step=50_000.0, key="ef_capex")
            st.slider("Taux d'amortissement (%)", 0.0, 40.0, step=0.5, key="ef_amort")
            st.slider("Tirages sur la marge (% des remboursements)", 0.0, 150.0, step=5.0, key="ef_tirages",
                      help="100 % : la marge est redéployée, son solde reste stable. Moins : elle se rembourse.")
            st.slider("Part d'intérêts des remboursements BDC (%)", 0.0, 60.0, step=1.0, key="ef_int_bdc")
            with st.expander("Bilan d'ouverture (début " + str(j.annees[0]) + ")"):
                st.number_input("Encaisse", step=50_000.0, key="ef_cash0")
                st.number_input("Immobilisations nettes", min_value=0.0, step=100_000.0, key="ef_immo0")
                st.number_input("Emprunt BDC", min_value=0.0, step=100_000.0, key="ef_bdc0")
                st.number_input("Marge de crédit", min_value=0.0, step=50_000.0, key="ef_marge0")
                st.number_input("Capital-actions", min_value=0.0, step=50_000.0, key="ef_capital")
                st.caption("Les créances, stocks et fournisseurs d'ouverture suivent les jours ci-contre ; les bénéfices non répartis "
                           "d'ouverture équilibrent le bilan.")
        st.button("↺ Revenir aux hypothèses de départ", on_click=_reinitialiser, args=(j,))


def afficher():
    chemin = M.BASE_DEMO
    if not os.path.isfile(chemin):
        st.info("La base de démonstration n'existe pas encore : lancez un passage.")
        return
    j = _journal(chemin, os.path.getmtime(chemin))
    if not j.annees:
        st.info("Le journal général est vide.")
        return
    _initialiser(j)
    _appliquer_envoi(j)
    st.caption("États financiers **pro forma**, reconstruits du journal général avec les hypothèses ci-dessous (créances, stocks, amortissement, "
               "impôts, dividendes, dettes). Le journal ne contient ni impôts, ni dividendes, ni investissements : ces postes viennent des hypothèses, "
               "et l'encaisse du bilan sort du tableau des flux. Elle peut donc différer du solde bancaire du tableau de trésorerie.")
    exp = NAV.expert()
    _hypotheses(j, ouvert=exp)                      # fermé en statut Simple : les réglages restent accessibles sans encombrer la lecture
    _origine()

    p = _parametres(j)
    res = ef.calculer(j, p)
    c1, c2 = st.columns([2, 5])
    annee = c1.selectbox("Exercice", j.annees, index=len(j.annees) - 1, key="ef_annee", format_func=lambda a: f"FY{a}")
    e, prec = res["annees"][annee], res["annees"].get(annee - 1)
    if e["scenario_applique"] and any((p.var_ventes, p.var_cout_produits, p.var_charges, p.var_taux)):
        c2.info(f"Le scénario (variations ci-dessus) est appliqué à FY{annee} : ce ne sont plus les chiffres du journal.")
    elif not e["scenario_applique"]:
        c2.caption(f"FY{annee} précède l'exercice de départ du scénario ({res['annee_scenario']}) : chiffres du journal.")

    ind, ind_p = ef.indicateurs(e), ef.indicateurs(prec) if prec else None
    k = st.columns(5)
    r = e["resultats"]
    d = lambda cle, v: (None if not prec else nombre(v - prec[cle[0]][cle[1]]))
    k[0].metric("Produits", nombre(r["revenus"]) + " $", delta=d(("resultats", "revenus"), r["revenus"]))
    k[1].metric("BAIIA", f"{ind['BAIIA (%)']:.1f} %", delta=(f"{ind['BAIIA (%)'] - ind_p['BAIIA (%)']:+.1f} pt" if ind_p else None))
    k[2].metric("Résultat net", nombre(r["net"]) + " $", delta=d(("resultats", "net"), r["net"]))
    k[3].metric("Encaisse (fin)", nombre(e["bilan"]["encaisse"]) + " $", delta=d(("bilan", "encaisse"), e["bilan"]["encaisse"]))
    k[4].metric("Liquidité générale", f"{ind['Liquidité générale (x)']:.2f} x")
    for a in e["alertes"]:
        st.warning(a)
    echecs = [v for v in ef.verifications(res) if not v["ok"]]
    if echecs:
        st.error(f"{len(echecs)} contrôle(s) comptable(s) en échec — voir l'onglet Analyse.")

    pres = ef.presenter(res, j, annee)
    titre_bilan = (f"Au 31 déc. {annee}", f"Au 31 déc. {annee - 1}" if annee > j.annees[0] else "Ouverture")
    if exp:
        t1, t2, t3, t4, t6, t5, t7, t8 = st.tabs(["📈 État des résultats", "🏦 Bilan", "💧 Flux de trésorerie", "🧾 Capitaux propres",
                                                  "⚖ Balance de vérification", "🔬 Analyse", "🏢 Consolidé (3 divisions)", "🧮 Écritures de consolidation"])
    else:
        t1, t2, t3, t7, t8 = st.tabs(["📈 État des résultats", "🏦 Bilan", "💧 Flux de trésorerie", "🏢 Consolidé (3 divisions)", "🧮 Écritures de consolidation"])
        t4 = t5 = t6 = None
        st.caption("Capitaux propres, balance de vérification, indicateurs et contrôles comptables : statut Expert.")
    with t7:
        consolidation_ui.afficher_consolide(res, j, annee, pres, titre_bilan)
    with t8:
        consolidation_ui.afficher_ecritures(res, annee)
    with t1:
        st.html(tableau_html(pres["resultats"], annee))
    with t2:
        st.html(tableau_html(pres["bilan"], annee, titre_bilan))
    with t3:
        st.html(tableau_html(pres["flux"], annee))
    if exp:
        with t4:
            st.html(tableau_html(pres["capitaux"], annee))
        with t6:
            _balance(ef.balance_de_verification(res, j, annee), annee)
        with t5:
            _analyse(res, ind, ind_p, annee)
    st.download_button("⬇ Télécharger les quatre états (Excel)", ef.classeur_excel(res, j, annee), file_name=f"Etats_financiers_FY{annee}.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


def _balance(bv: dict, annee: int):
    """Balance de vérification avant clôture : un compte par ligne, regroupés, avec les totaux et l'équilibre."""
    st.caption("Soldes de tous les comptes avant les écritures de clôture : les comptes de produits et de charges portent encore les "
               "montants de l'exercice et les bénéfices non répartis sont ceux du début. Si les états sont cohérents, débits = crédits.")
    corps, groupe = [], None
    for l in bv["lignes"]:
        if l["groupe"] != groupe:
            groupe = l["groupe"]
            corps.append(f'<tr class="titre"><td colspan="4">{groupe}</td></tr>')
        corps.append(f'<tr class="ligne"><td>{l["numero"]}</td><td>{l["compte"]}</td><td class="n">{nombre(l["debit"]) if l["debit"] else ""}</td>'
                     f'<td class="n">{nombre(l["credit"]) if l["credit"] else ""}</td></tr>')
    corps.append(f'<tr class="total"><td></td><td>Total</td><td class="n">{nombre(bv["total_debit"])}</td><td class="n">{nombre(bv["total_credit"])}</td></tr>')
    st.html(f'{CSS}<table class="ef"><thead><tr><th>N°</th><th>Compte — FY{annee}</th><th>Débit</th><th>Crédit</th></tr></thead>'
            f'<tbody>{"".join(corps)}</tbody></table>')
    if bv["equilibre"]:
        st.success("La balance est équilibrée : le total des débits égale le total des crédits.")
    else:
        st.error(f"La balance n'est pas équilibrée : écart de {bv['ecart']:,.2f} $.".replace(",", " "))


def _analyse(res, ind, ind_p, annee):
    st.markdown("**Indicateurs**")
    st.dataframe(pd.DataFrame({"Indicateur": list(ind), f"FY{annee}": [round(v, 2) for v in ind.values()],
                               f"FY{annee - 1}": [round(v, 2) for v in ind_p.values()] if ind_p else [None] * len(ind)}),
                 hide_index=True, width="stretch")
    st.markdown("**Contrôles comptables** (identités vérifiées à chaque calcul, exercice par exercice)")
    ver = pd.DataFrame(ef.verifications(res))
    ver["Résultat"] = ver["ok"].map({True: "✓", False: "✕"})
    st.dataframe(ver.rename(columns={"exercice": "Exercice", "controle": "Contrôle", "ecart": "Écart ($)"})[["Exercice", "Contrôle", "Résultat", "Écart ($)"]],
                 hide_index=True, width="stretch")
    with st.expander("Méthode et limites"):
        st.markdown(
            "- **Produits et charges** : les catégories du journal, avec le scénario appliqué à partir de l'exercice choisi.\n"
            "- **Coût des produits vendus** : achats + variation des stocks (stock = jours d'achats). **BAIIA** avant amortissement, intérêts et impôts.\n"
            "- **Amortissement** : taux × (valeur nette d'ouverture + la moitié des acquisitions de l'exercice).\n"
            "- **Dettes** : la marge se rembourse du montant journalisé et se redéploie selon le % de tirages ; les remboursements BDC se partagent "
            "entre intérêts et capital. Le crédit-bail reste une charge d'exploitation.\n"
            "- **Encaisse** : jamais saisie, elle est le résultat du tableau des flux (méthode indirecte) ; le bilan s'équilibre par construction "
            "et les contrôles ci-dessus le confirment.\n"
            "- **Limites** : pas de report de pertes, pas d'impôts différés, pas de taxes de vente, un seul compte de dettes à long terme. "
            "Des états financiers audités exigent le grand livre comptable complet ; ceux-ci servent à tester des hypothèses.")
