"""Vue « Prix des métaux » : projection du prix de l'acier, de l'aluminium, de l'inox et du cuivre, et de son effet sur la trésorerie.

  Projection        trajectoire du prix (scénarios bas / central / haut), prix d'achat chez le distributeur, effet sur la marge et sur l'encaisse,
                    envoi du scénario aux états financiers
  Sensibilité       effet d'une variation immédiate et durable du prix du métal
  Modèles           backtest walk-forward des modèles statistiques (marche aléatoire, ARIMA, GARCH, Ensemble)
  Historique        séries FRED importées dans la base, mise à jour

Le moteur est projection_metaux.py (testé par test_projection_metaux.py) ; les modèles sont calculés par `python -m prevision_metaux.calcul`.
Tous les paramètres sont des hypothèses explicites : cette vue teste des scénarios, elle ne prédit pas le prix.
"""
from __future__ import annotations

import os
import re

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import projection_metaux as pm
from demo_live import etats_ui, moteur as M
from prevision_metaux import base, donnees

VUE_ETATS = "📒 États financiers"            # même libellé que dans demo_live/application.py (PAGES)
CONFIG = {"displaylogo": False, "modeBarButtonsToRemove": ["lasso2d", "select2d"]}
COULEURS = {"bas": "#1baf7a", "central": "#2a78d6", "haut": "#eb6834"}
LIBELLES = {"bas": "Bas (10 %)", "central": "Central", "haut": "Haut (90 %)"}
GRIS, ROUGE = "#898781", "#d03b3b"
COULEURS_MODELES = {"Ensemble": "#2a78d6", "GARCH": "#008300", "ARIMA": "#6250d6", "Marche aléatoire": "#e34948", pm.MODELE_REGLABLE: "#5b6573"}
PERIODES = {"1 an": 12, "3 ans": 36, "10 ans": 120, "Depuis 1992": None}

DEFAUTS = {
    "mx_cible": "panier", "mx_modele": pm.MODELE_REGLABLE, "mx_compare": [], "mx_periode": "3 ans", "mx_horizon": 12, "mx_choc": 0.0, "mx_derive": 0.0,
    "mx_fenetre": 36, "mx_part": 55.0, "mx_prix_ref": 0.0, "mx_ref": "Moyenne 12 mois", "mx_passage": 60.0, "mx_delai": 2, "mx_elast": -0.05,
    "mx_dso": 48.0, "mx_dpo": 30.0,
}


def esc(t) -> str:
    """Le dollar ouvre une formule en Markdown : on l'échappe dans tout texte libre affiché."""
    return re.sub(r"(?<!\\)\$", r"\\$", str(t))


def f0(v: float) -> str:
    return f"{v:,.0f}".replace(",", " ")


def signe(v: float) -> str:
    return ("+" if v >= 0 else "−") + f0(abs(v))


def kg(v: float) -> str:
    return f"{v:.2f} $/kg".replace(".", ",")


@st.cache_data(show_spinner=False)
def _series(chemin: str, version: int):
    """Historique des prix lu dans la base (importé des CSV si la base ne l'a pas encore). `version` change après une mise à jour."""
    return pm.charger_series(chemin)


@st.cache_data(show_spinner=False)
def _modeles(cible: str, stamp: float):
    return pm.charger_modeles(cible)


def _stamp(cible: str) -> float:
    return max((os.path.getmtime(pm.DOSSIER / cible / f) for f in ("forecast.csv", "backtest.csv", "meta.json") if (pm.DOSSIER / cible / f).is_file()), default=0.0)


def _initialiser():
    for k, v in DEFAUTS.items():
        st.session_state.setdefault(k, list(v) if isinstance(v, list) else v)


def _reinitialiser():
    for k in list(DEFAUTS) + ["mx_fx", "mx_scen"]:
        st.session_state.pop(k, None)
    _initialiser()


def _graphique(fig: go.Figure, cle: str, hauteur: int = 330) -> None:
    fig.update_layout(height=hauteur, margin=dict(l=10, r=10, t=30, b=10), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", legend_title_text="",
                      legend=dict(orientation="h", y=1.12))
    st.plotly_chart(fig, theme="streamlit", width="stretch", config=CONFIG, key=cle)


# --------------------------------------------------------------------------- #
# Hypothèses
# --------------------------------------------------------------------------- #
def _hypotheses(fx0: float) -> pm.Hypotheses:
    s = st.session_state
    s.setdefault("mx_fx", round(fx0, 4))
    with st.expander("⚙ Hypothèses — tout se recalcule à chaque changement", expanded=False):
        a, b, c = st.columns(3)
        with a:
            st.markdown("**Prix du métal**")
            st.selectbox("Cible de la projection", list(pm.CIBLES), format_func=lambda k: pm.CIBLES[k], key="mx_cible",
                         help="Le panier regroupe les matières de l'atelier : acier 50 %, aluminium 25 %, inox (nickel) 15 %, cuivre (laiton) 10 %.")
            st.slider("Horizon (mois)", 3, 24, key="mx_horizon", help="Les modèles précalculés vont jusqu'à 12 mois ; au-delà, seule la marche aléatoire réglable s'applique.")
            st.slider("Choc immédiat sur le prix de départ (%)", -30.0, 30.0, step=1.0, key="mx_choc")
            st.slider("Tendance du prix (% par an)", -30.0, 30.0, step=1.0, key="mx_derive", help="Ajoutée à la trajectoire du modèle choisi.")
            st.selectbox("Fenêtre de volatilité (mois)", [12, 24, 36, 60, 120], key="mx_fenetre",
                         help="Seulement pour la marche aléatoire réglable : plus la fenêtre est courte, plus la volatilité récente pèse.")
        with b:
            st.markdown("**Du marché au prix d'achat**")
            st.number_input("Taux de change (CAD par USD)", min_value=0.5, max_value=3.0, step=0.01, format="%.4f", key="mx_fx",
                            help="Les métaux se négocient en dollars américains : un dollar canadien plus faible renchérit les achats.")
            st.slider("Part du prix suivant le marché du métal (%)", 10.0, 100.0, step=5.0, key="mx_part",
                      help="Le reste du prix chez le distributeur (extrusion, coupe, fret, marge) ne bouge pas avec le marché.")
            st.number_input("Prix d'achat actuel ($/kg, 0 = valeur type de la cible)", min_value=0.0, max_value=100.0, step=0.1, format="%.2f", key="mx_prix_ref",
                            help="Entrez le prix payé à votre fournisseur pour recaler le niveau (la sensibilité au marché ne change pas).")
        with c:
            st.markdown("**Effet sur la trésorerie**")
            st.segmented_control("Niveau de référence du journal", ["Moyenne 12 mois", "Dernier prix"], key="mx_ref",
                                 help="Les montants du dernier exercice sont supposés correspondre à ce prix du métal.")
            st.slider("Part de la hausse de coût répercutée aux clients (%)", 0.0, 100.0, step=5.0, key="mx_passage",
                      help="Clauses d'indexation des contrats aéro et rail, soumissions révisées : le reste est absorbé par la marge.")
            st.slider("Délai de répercussion (mois)", 0, 6, key="mx_delai")
            st.slider("Élasticité du volume au prix de vente", -0.6, 0.0, step=0.05, key="mx_elast", help="Variation du volume pour 1 % de variation du prix de vente.")
            st.slider("Jours de ventes en créances", 0.0, 120.0, step=1.0, key="mx_dso")
            st.slider("Jours d'achats en fournisseurs", 0.0, 120.0, step=1.0, key="mx_dpo")
        st.button("↺ Revenir aux hypothèses de départ", on_click=_reinitialiser, key="mx_reset")
    return pm.Hypotheses(
        cible=s["mx_cible"], horizon_mois=s["mx_horizon"], modele=s["mx_modele"], fenetre_vol=s["mx_fenetre"], derive_annuelle=s["mx_derive"] / 100,
        choc=s["mx_choc"] / 100, taux_change=float(s["mx_fx"]), part_matiere=s["mx_part"] / 100, prix_ref=s["mx_prix_ref"] or None, reference=s["mx_ref"],
        passage=s["mx_passage"] / 100, delai_mois=s["mx_delai"], elasticite=s["mx_elast"], dso=s["mx_dso"], dpo=s["mx_dpo"])


def _choix_modele(modeles: dict | None) -> list[str]:
    s = st.session_state
    disponibles = pm.noms_modeles(modeles)
    options = [pm.MODELE_REGLABLE, *disponibles]
    if s["mx_modele"] not in options:
        s["mx_modele"] = pm.MODELE_REGLABLE
    s["mx_compare"] = [x for x in s["mx_compare"] if x in options]
    a, b = st.columns(2)
    a.selectbox("Modèle de projection", options, key="mx_modele",
                help="La marche aléatoire réglable utilise la volatilité récente ; les autres modèles sont précalculés (ARIMA, GARCH, Ensemble).")
    b.multiselect("Comparer avec d'autres modèles", options, key="mx_compare", max_selections=3)
    return [x for x in s["mx_compare"] if x != s["mx_modele"]]


# --------------------------------------------------------------------------- #
# Graphiques
# --------------------------------------------------------------------------- #
def _fenetre(serie: pd.Series, periode: str) -> pd.Series:
    n = PERIODES[periode]
    return serie if n is None else serie.iloc[-n:]


def _graph_prix(r: pm.Resultat, periode: str, comp: dict[str, pd.DataFrame]) -> go.Figure:
    c, t = r.contexte, r.trajectoires
    hist = _fenetre(c.serie, periode)
    fig = go.Figure()
    fig.add_scatter(x=hist.index, y=hist.values, name="Historique", line=dict(color=GRIS, width=2))
    fig.add_scatter(x=t["date"], y=t["haut"], line=dict(width=0), showlegend=False, hoverinfo="skip")
    fig.add_scatter(x=t["date"], y=t["bas"], fill="tonexty", fillcolor="rgba(42,120,214,.15)", line=dict(width=0), name="Bandes 10-90 %", hoverinfo="skip")
    for sc in pm.SCENARIOS:
        fig.add_scatter(x=t["date"], y=t[sc], name=LIBELLES[sc], line=dict(color=COULEURS[sc], width=2.5 if sc == "central" else 1.5, dash="solid" if sc == "central" else "dot"))
    for nom, d in comp.items():
        fig.add_scatter(x=d["date"], y=d["central"], name=f"{nom} (central)", line=dict(color=COULEURS_MODELES.get(nom, GRIS), width=1.8, dash="dash"))
    fig.update_yaxes(title=pm.UNITES[c.h.cible])
    return fig


def _graph_achat(r: pm.Resultat) -> go.Figure:
    t = r.trajectoires
    fig = go.Figure()
    for sc in pm.SCENARIOS:
        fig.add_scatter(x=t["date"], y=r.prix[sc]["achat_kg"], name=LIBELLES[sc], line=dict(color=COULEURS[sc], width=2.5 if sc == "central" else 1.5))
    fig.add_hline(y=r.contexte.h.prix_reference, line_dash="dash", line_color=GRIS, annotation_text="prix actuel")
    fig.update_yaxes(title="Prix d'achat ($ CAD/kg)")
    return fig


def _graph_encaisse(r: pm.Resultat) -> go.Figure:
    fig = go.Figure()
    for sc in pm.SCENARIOS:
        d = r.impacts[sc]
        fig.add_scatter(x=d["periode"], y=d["d_cash_cumul"], name=LIBELLES[sc], line=dict(color=COULEURS[sc], width=2.5 if sc == "central" else 1.5))
    fig.add_hline(y=0, line_color=GRIS)
    if r.seuil:
        fig.add_hline(y=-r.seuil, line_dash="dash", line_color=ROUGE, annotation_text="seuil de sécurité")
    fig.update_yaxes(title="Effet cumulé sur l'encaisse ($)")
    return fig


# --------------------------------------------------------------------------- #
# Envoi aux états financiers
# --------------------------------------------------------------------------- #
def _envoyer_aux_etats(envoi: dict):
    """Dépose le scénario pour la vue États financiers (qui l'applique avant de dessiner ses curseurs) et ouvre cette vue."""
    st.session_state["ef_envoi"] = envoi
    st.session_state["vue"] = VUE_ETATS


def _bloc_etats_financiers(r: pm.Resultat, choix: str, chemin: str):
    j = etats_ui._journal(chemin, os.path.getmtime(chemin))
    v = pm.variations_etats_financiers(r, choix, j)
    ventes_pct, produits_pct = v["var_ventes"] * 100, v["var_produits"] * 100
    modele = r.contexte.h.modele
    # les curseurs des états financiers vont de −30 à +30 % par pas de 0,5
    envoi = {"ventes": round(max(-30.0, min(30.0, ventes_pct)) * 2) / 2, "produits": round(max(-30.0, min(30.0, produits_pct)) * 2) / 2,
             "annee": v["annee"], "libelle": f"{modele}, {LIBELLES[choix].lower()}", "horizon": r.contexte.horizon}
    with st.container(border=True):
        st.subheader("Envoyer ce scénario aux états financiers")
        st.markdown(esc(
            f"Pour reproduire l'effet du scénario **{LIBELLES[choix].lower()}** du modèle **{modele}** sur l'exercice **FY{v['annee']}** (résultats, bilan, "
            f"flux de trésorerie), les états financiers recevraient : **ventes {ventes_pct:+.1f} %** ({signe(v['d_ventes'])} $ sur {f0(v['ventes_base'])} $) et "
            f"**prix des matières achetées {produits_pct:+.1f} %** ({signe(v['d_achats'])} $ sur {f0(v['achats_base'])} $). "
            "Les autres variations du scénario (charges, taux d'intérêt) sont remises à 0."))
        if (envoi["ventes"], envoi["produits"]) != (round(ventes_pct * 2) / 2, round(produits_pct * 2) / 2):
            st.warning("Les curseurs des états financiers sont limités à ±30 % : les valeurs envoyées sont plafonnées.")
        elif r.contexte.horizon != 12:
            st.caption(f"L'effet moyen des {r.contexte.horizon} mois projetés est ramené à une année.")
        st.button("📒 Appliquer aux états financiers et les ouvrir", on_click=_envoyer_aux_etats, args=(envoi,), key="mx_envoyer")


def resume_central(chemin: str) -> dict | None:
    """Résumé de la projection par défaut (panier, marche aléatoire réglable, hypothèses de départ), pour la page d'accueil."""
    try:
        series = _series(chemin, st.session_state.get("mx_version_donnees", 0))
        r = pm.projeter(pm.Hypotheses(), chemin, series, _modeles("panier", _stamp("panier")))
    except Exception:                                                       # noqa: BLE001
        return None
    return {"achat0": float(r.prix["central"]["achat_kg"].iloc[0]), "achatN": float(r.prix["central"]["achat_kg"].iloc[-1]),
            "achat_bas": float(r.prix["bas"]["achat_kg"].iloc[-1]), "achat_haut": float(r.prix["haut"]["achat_kg"].iloc[-1]),
            "cash": float(r.impacts["central"]["d_cash_cumul"].iloc[-1]), "horizon": r.contexte.horizon,
            "pire": min(float(r.impacts[s]["d_cash_cumul"].min()) for s in pm.SCENARIOS), "cible": pm.PRODUIT_REF["panier"]}


# --------------------------------------------------------------------------- #
# Vue
# --------------------------------------------------------------------------- #
def afficher():
    chemin = M.BASE_DEMO
    if not os.path.isfile(chemin):
        st.info("La base de démonstration n'existe pas encore : lancez un passage.")
        return
    _initialiser()
    try:
        series = _series(chemin, st.session_state.get("mx_version_donnees", 0))
    except Exception as e:                                                  # noqa: BLE001
        st.error(f"Historique des prix indisponible : {e}")
        return
    st.caption(esc("Projection du prix des métaux (aluminium, acier, nickel, cuivre) et de son effet sur la trésorerie de Groupe Usinage Saint-Maurice : du marché au prix d'achat "
                   "chez le distributeur, puis aux achats, aux ventes (clauses d'indexation) et à l'encaisse. Ce sont des scénarios, pas une prédiction."))
    h = _hypotheses(float(series["fx"].iloc[-1]))
    modeles = _modeles(h.cible, _stamp(h.cible))
    comp_noms = _choix_modele(modeles)
    r = pm.projeter(h, chemin, series, modeles)
    c = r.contexte
    for a in c.alertes:
        st.warning(esc(a))
    comp = {n: pm.trajectoire(c, n) for n in comp_noms}

    t_proj, t_sens, t_mod, t_hist = st.tabs(["📈 Projection", "🎚 Sensibilité", "🧪 Modèles et backtest", "🗄 Historique et données"])
    N = c.horizon
    achat0 = float(r.prix["central"]["achat_kg"].iloc[0])
    with t_proj:
        k = st.columns(4)
        k[0].metric(f"Prix de marché ({pm.CIBLES[h.cible].split(' (')[0].lower()})", f"{c.spot:,.2f}".replace(",", " ").replace(".", ","), pm.UNITES[h.cible], delta_color="off")
        k[1].metric(f"Prix d'achat — {pm.PRODUIT_REF[h.cible]}", kg(achat0),
                    esc(f"dans {N} mois : {kg(float(r.prix['bas']['achat_kg'].iloc[-1]))} à {kg(float(r.prix['haut']['achat_kg'].iloc[-1]))}"), delta_color="off")
        d = r.impacts["central"]
        k[2].metric("Marge brute — scénario central", signe(float(d["d_marge"].sum())) + " $", f"sur {N} mois", delta_color="off")
        k[3].metric("Encaisse — scénario central", signe(float(d["d_cash_cumul"].iloc[-1])) + " $", f"pire scénario : {signe(min(float(r.impacts[s]['d_cash_cumul'].min()) for s in pm.SCENARIOS))} $",
                    delta_color="off")
        periode = st.segmented_control("Historique affiché", list(PERIODES), key="mx_periode") or "3 ans"
        g1, g2 = st.columns(2)
        with g1:
            st.markdown("**Prix du métal : historique et scénarios**")
            _graphique(_graph_prix(r, periode, comp), "mx_g_prix")
        with g2:
            st.markdown(f"**Prix d'achat chez le distributeur** ({pm.PRODUIT_REF[h.cible]})")
            _graphique(_graph_achat(r), "mx_g_achat")
        st.markdown("**Effet cumulé sur l'encaisse**")
        _graphique(_graph_encaisse(r), "mx_g_cash", 300)
        choix = st.segmented_control("Scénario affiché dans le tableau et envoyé aux états", pm.SCENARIOS, default="central", key="mx_scen", format_func=lambda s: LIBELLES[s]) or "central"
        tab = r.impacts[choix][["periode", "marche", "achat_kg", "ventes", "achats", "d_marge", "d_cash", "d_cash_cumul"]].rename(columns={
            "periode": "Mois", "marche": "Prix du métal", "achat_kg": "Prix d'achat ($/kg)", "ventes": "Ventes ($)", "achats": "Achats de matières ($)",
            "d_marge": "Écart de marge ($)", "d_cash": "Effet sur l'encaisse ($)", "d_cash_cumul": "Cumul ($)"})
        st.dataframe(tab.style.format({c_: "{:,.0f}" for c_ in tab.columns if c_ not in ("Mois", "Prix du métal", "Prix d'achat ($/kg)")} | {"Prix du métal": "{:,.2f}", "Prix d'achat ($/kg)": "{:.2f}"}),
                     hide_index=True, width="stretch")
        _bloc_etats_financiers(r, choix, chemin)
        with st.expander("Méthode et limites"):
            st.markdown(esc(
                f"- **Prix d'achat** = prix actuel × [1 + {h.part_matiere:.0%} × (variation du marché en dollars canadiens)] : la part « matière » suit le métal et le change, le reste "
                "(transformation, coupe, fret, marge du distributeur) est fixe.\n"
                f"- **Achats** : suivent le prix d'achat aussitôt. **Ventes** : reçoivent {h.passage:.0%} de la variation du coût des matières avec {h.delai_mois} mois de délai "
                f"(clauses d'indexation des contrats aéro et rail, soumissions) ; le volume réagit au prix de vente (élasticité {h.elasticite}).\n"
                f"- **Encaisse** : l'écart de ventes est décalé de {h.dso:.0f} jours (créances), l'écart d'achats de {h.dpo:.0f} jours (fournisseurs).\n"
                "- **Limites** : un seul prix de référence par cible ; pas de stock de couverture ni de contrats à prix fixe avec les fournisseurs ; l'acier suit un indice américain "
                "des prix à la production, pas un prix québécois. Les modèles sont des scénarios statistiques, pas des prévisions."))

    with t_sens:
        st.markdown(esc("Si le prix du métal changeait **tout de suite** et y restait pendant tout l'horizon, quel serait l'effet sur la marge et sur l'encaisse ?"))
        niveaux = [-0.30, -0.20, -0.10, 0.10, 0.20, 0.30]
        sens = pm.sensibilite(r, niveaux)
        fig = go.Figure(go.Bar(x=[f"{v:+.0f} %" for v in sens["Variation du prix du métal (%)"]], y=sens["Effet sur l'encaisse ($)"],
                               marker_color=[ROUGE if v < 0 else "#1baf7a" for v in sens["Effet sur l'encaisse ($)"]]))
        fig.update_yaxes(title="Effet sur l'encaisse ($)")
        _graphique(fig, "mx_g_sens", 300)
        st.dataframe(sens.style.format({"Variation du prix du métal (%)": "{:+.0f}", "Prix d'achat ($/kg)": "{:.2f}", "Variation de la marge brute ($)": "{:,.0f}", "Effet sur l'encaisse ($)": "{:,.0f}"}),
                     hide_index=True, width="stretch")
        st.caption(esc(f"Calcul avec les hypothèses ci-dessus : {h.passage:.0%} de répercussion, délai de {h.delai_mois} mois, {h.part_matiere:.0%} du prix d'achat qui suit le marché."))

    with t_mod:
        _onglet_modeles(h, modeles)
    with t_hist:
        _onglet_historique(chemin, series)


def _onglet_modeles(h: pm.Hypotheses, modeles: dict | None) -> None:
    if not modeles:
        st.info(f"Aucune prévision calculée pour « {pm.CIBLES[h.cible]} ». Calculez-les depuis le dossier du projet : `python -m prevision_metaux.calcul --cibles {h.cible}`.")
        return
    meta = modeles["meta"]
    st.caption(esc(f"Backtest walk-forward : {meta['windows']} origines tous les {meta['step']} mois, du {meta['backtest_start']} au {meta['backtest_last_origin']}, horizon de {meta['horizon_mois']} mois. "
                   "Chaque modèle ne voit que les prix connus à la date d'origine. Skill < 1 : le modèle fait mieux que la marche aléatoire."))
    from prevision_metaux.evaluation import metriques
    bt = modeles["backtest"]
    horizon = st.select_slider("Horizon évalué (mois)", options=[1, 3, 6, 12], value=12, key="mx_h_eval")
    m = metriques(bt, [horizon])
    st.dataframe(m.style.format("{:.3f}", subset=[c for c in m.columns if c not in ("Observations",)]), width="stretch")
    modele = st.selectbox("Prévu contre réalisé", [x for x in pm.noms_modeles(modeles)], key="mx_bt_modele")
    d = bt[(bt["model"] == modele) & (bt["h"] == horizon)].sort_values("date")
    fig = go.Figure()
    fig.add_scatter(x=d["date"], y=d["q90"], line=dict(width=0), showlegend=False, hoverinfo="skip")
    fig.add_scatter(x=d["date"], y=d["q10"], fill="tonexty", fillcolor="rgba(42,120,214,.15)", line=dict(width=0), name="Bande 10-90 %", hoverinfo="skip")
    fig.add_scatter(x=d["date"], y=d["q50"], name="Prévu (médiane)", line=dict(color=COULEURS_MODELES.get(modele, GRIS), width=2))
    fig.add_scatter(x=d["date"], y=d["y_true"], name="Réalisé", line=dict(color="#1b2430", width=2, dash="dot"))
    fig.update_yaxes(title=pm.UNITES[h.cible])
    _graphique(fig, "mx_g_bt", 320)


def _onglet_historique(chemin: str, series: dict) -> None:
    cat = base.catalogue(chemin)
    st.markdown("**Séries importées dans la base** (tables `ref_serie_marche` et `core_prix_marche`)")
    st.dataframe(cat.rename(columns={"code": "Code FRED", "libelle_fr": "Série", "unite": "Unité", "frequence": "Fréquence", "date_debut": "Début", "date_fin": "Fin",
                                     "observations": "Observations"}), hide_index=True, width="stretch")
    debut = st.slider("Depuis l'année", 1992, 2025, 2015, key="mx_debut")
    fig = go.Figure()
    for cle, nom in (("alu", "Aluminium"), ("nickel", "Nickel"), ("cuivre", "Cuivre"), ("acier", "Acier (indice)"), ("panier", "Panier")):
        s = donnees._mensuel(series[cle]) if cle != "panier" else series["panier"]
        s = s[s.index >= f"{debut}-01-01"]
        fig.add_scatter(x=s.index, y=100 * s / s.iloc[-12:].mean(), name=nom, line=dict(width=3 if cle == "panier" else 1.5))
    fig.update_yaxes(title="Indice (moyenne des 12 derniers mois = 100)")
    _graphique(fig, "mx_g_hist", 340)
    st.caption("Les métaux ne se comparent pas en dollars (une tonne d'aluminium et un indice d'acier n'ont pas la même unité) : chaque série est rapportée à sa moyenne des 12 derniers mois.")
    if st.button("⟳ Mettre à jour depuis FRED", key="mx_maj", help="Télécharge les dernières valeurs (fred.stlouisfed.org) puis les ajoute à la base. Les prévisions des modèles ne sont pas recalculées."):
        with st.spinner("Téléchargement des séries…"):
            donnees.telecharger_fred()
            base.importer(chemin)
        st.session_state["mx_version_donnees"] = st.session_state.get("mx_version_donnees", 0) + 1
        st.rerun()
    st.caption("Recalculer les modèles (quelques minutes) : `python -m prevision_metaux.calcul --update`.")
