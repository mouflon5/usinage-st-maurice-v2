"""Projection du prix des métaux (acier, aluminium, inox, cuivre) et de son effet sur la trésorerie de Groupe Usinage Saint-Maurice.

Chaîne de calcul, du marché des métaux à la trésorerie :

  1. Trajectoire du prix sur N mois (scénarios bas / central / haut = quantiles 10 / 50 / 90 %) d'un modèle au choix : la marche aléatoire
     réglable (dernier prix, volatilité récente proportionnelle à la racine du temps) ou l'un des modèles du paquet prevision_metaux
     (ARIMA, GARCH, Ensemble), évalués par un backtest walk-forward. La cible est un métal ou le « panier » de matières de l'atelier.
  2. Prix d'achat chez le distributeur : une partie du prix (la matière) suit le marché en dollars américains puis en dollars canadiens ;
     le reste (extrusion, coupe, fret, marge du distributeur) est fixe. prix d'achat = prix de référence × [1 + part × (variation du marché)].
  3. Effet sur le journal : les achats de matières suivent le prix d'achat aussitôt ; les ventes reçoivent la part répercutée de cette variation
     (clauses d'indexation des contrats aéro et rail, soumissions), avec un délai ; le volume réagit au prix de vente. L'écart avec le journal
     est décalé par les jours de créances et de fournisseurs pour obtenir l'effet sur l'encaisse.

L'historique (aluminium, nickel, cuivre depuis 1992, acier depuis 1939, change) est dans la base SQLite (tables ref_serie_marche et
core_prix_marche, voir prevision_metaux/base.py) ; les prévisions des modèles et le backtest sont dans donnees_externes/metaux/<cible>/.
Tous les paramètres sont des hypothèses explicites (classe Hypotheses) : ce module teste des scénarios, il ne prédit pas le prix.
"""
from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np
import pandas as pd

from prevision_metaux import base, donnees

DOSSIER = Path(__file__).resolve().parent / "donnees_externes" / "metaux"
Z90 = 1.2815515655               # quantile 90 % de la loi normale : bornes basse et haute = quantiles 10 % et 90 %
VENTES = (20, 21, 22, 23)        # rang des catégories : usinage sur mesure, contrats récurrents (aéro et rail), pièces de rechange, prototypage
ACHATS = (2,)                    # matières premières (acier, aluminium, inox)
SCENARIOS = ("bas", "central", "haut")
MODELE_REGLABLE = "Marche aléatoire (réglable)"   # calculé à la volée avec la volatilité et la tendance choisies
CIBLES = {"panier": "Panier de matières (pondéré)", "acier": "Acier (produits d'aciérie)", "alu": "Aluminium", "nickel": "Nickel (inox)", "cuivre": "Cuivre (laiton)"}
UNITES = {"panier": "indice (moyenne 12 mois = 1)", "acier": "indice (1982 = 100)", "alu": "$ US/t", "nickel": "$ US/t", "cuivre": "$ US/t"}
PRODUIT_REF = {"panier": "matières de l'atelier (prix moyen)", "acier": "acier 1018, barre ronde", "alu": "aluminium 6061-T6, barre",
               "nickel": "inox 304/316, barre", "cuivre": "laiton, barre"}
PRIX_REF = {"panier": 4.20, "acier": 2.85, "alu": 7.80, "nickel": 12.50, "cuivre": 14.00}   # $ CAD/kg payé aujourd'hui (cycle d'achats, ordre de grandeur)


@dataclass
class Hypotheses:
    # trajectoire du prix
    cible: str = "panier"
    horizon_mois: int = 12
    modele: str = MODELE_REGLABLE        # ou un modèle de prevision_metaux : ARIMA, GARCH, Ensemble…
    fenetre_vol: int = 36                # mois pour la volatilité (modèle réglable)
    derive_annuelle: float = 0.0         # tendance du prix, fraction par an
    choc: float = 0.0                    # variation immédiate du prix de départ (0,10 = +10 %)
    taux_change: float | None = None     # CAD par USD (None = dernier cours FRED)
    # du prix de marché au prix d'achat
    part_matiere: float = 0.55           # part du prix chez le distributeur qui suit le marché (le reste : transformation, coupe, fret, marge)
    prix_ref: float | None = None        # prix d'achat actuel ($ CAD/kg) ; None = valeur type de la cible
    reference: str = "Moyenne 12 mois"   # niveau de référence des montants du journal : ou « Dernier prix »
    # effet sur la trésorerie
    passage: float = 0.60                # part de la variation du coût des matières répercutée aux clients
    delai_mois: int = 2                  # délai de répercussion (clauses d'indexation, soumissions)
    elasticite: float = -0.05            # variation du volume pour 1 % de variation du prix de vente
    dso: float = 48.0                    # jours de ventes en créances
    dpo: float = 30.0                    # jours d'achats en fournisseurs

    def modifie(self, **kw) -> "Hypotheses":
        return replace(self, **kw)

    @property
    def prix_reference(self) -> float:
        return self.prix_ref if self.prix_ref is not None else PRIX_REF[self.cible]


# --------------------------------------------------------------------------- #
# Données
# --------------------------------------------------------------------------- #
def charger_series(db_path: str | None = None) -> dict[str, pd.Series]:
    """Historique : séries mensuelles des métaux, panier pondéré et change quotidien (CAD par USD), en dollars américains.

    Avec `db_path`, les séries viennent de la base SQLite (importées des CSV si la base ne les contient pas encore) ; sans base, des CSV
    de donnees_externes/metaux/."""
    if db_path is not None and not base.disponible(db_path):
        base.importer(db_path)
    return donnees.charger_series(db_path)


def charger_modeles(cible: str = "panier") -> dict | None:
    """Prévisions des modèles de la cible et backtest walk-forward, ou None s'ils n'ont pas été calculés.

    `previsions` : quantiles 5, 10, 50, 90 et 95 % du prix à chaque mois, à partir du dernier mois connu ;
    `backtest` : les mêmes quantiles pour chaque origine du test, avec le prix réalisé (y_true) ; `meta` : paramètres du calcul."""
    try:
        prev = pd.read_csv(DOSSIER / cible / "forecast.csv", parse_dates=["cutoff_date", "date"])
        meta = json.loads((DOSSIER / cible / "meta.json").read_text(encoding="utf-8"))
        bt = pd.read_csv(DOSSIER / cible / "backtest.csv", parse_dates=["cutoff_date", "date"])
    except (OSError, ValueError):
        return None
    meta.setdefault("jours_par_mois", 1)
    meta.setdefault("horizon_mois", int(meta["horizon"]))
    return {"previsions": prev, "backtest": bt, "meta": meta}


def noms_modeles(m: dict | None) -> list[str]:
    """Modèles précalculés disponibles, dans un ordre stable (Ensemble en premier)."""
    if not m:
        return []
    ordre = ["Ensemble", "GARCH", "ARIMA", "Marche aléatoire"]
    dispo = set(m["previsions"]["model"].unique())
    return [x for x in ordre if x in dispo] + sorted(dispo - set(ordre))


# --------------------------------------------------------------------------- #
# Prix
# --------------------------------------------------------------------------- #
def volatilite_annuelle(serie: pd.Series, fenetre: int) -> float:
    r = np.log(serie[serie > 0]).diff().dropna().iloc[-fenetre:]
    return float(r.std() * math.sqrt(12))


@dataclass
class Contexte:
    """Tout ce qui est déduit des données pour un jeu d'hypothèses : change, niveaux de départ et de référence, volatilité."""
    h: Hypotheses
    serie: pd.Series           # prix mensuel de la cible (dollars américains ou indice)
    fx: float                  # change retenu pour la projection (CAD par USD)
    fx_ref: float              # change moyen des 12 derniers mois, base des prix d'achat actuels
    spot: float                # prix de départ (avec le choc)
    ref: float                 # prix de référence (moyenne 12 mois ou dernier prix)
    vol: float
    modeles: dict | None
    horizon: int = 12          # horizon effectif en mois : les modèles précalculés ne vont pas au-delà de leur propre horizon
    alertes: tuple = ()
    fx_serie: pd.Series | None = None


def contexte(h: Hypotheses, series: dict | None = None, modeles: dict | None = None) -> Contexte:
    s = series or charger_series()
    serie = donnees._mensuel(s[h.cible]) if h.cible != "panier" else s["panier"]
    modeles = modeles if modeles is not None else charger_modeles(h.cible)
    horizon, alertes = h.horizon_mois, []
    if h.modele != MODELE_REGLABLE:
        if h.modele not in noms_modeles(modeles):
            alertes.append(f"Le modèle « {h.modele} » n'a pas de prévision calculée pour cette cible : projection par la marche aléatoire réglable.")
        else:
            meta = modeles["meta"]
            if horizon > meta["horizon_mois"]:
                alertes.append(f"Les modèles sont calculés jusqu'à {meta['horizon_mois']} mois : l'horizon est ramené à {meta['horizon_mois']} mois "
                               f"(la marche aléatoire réglable va jusqu'à 24 mois).")
                horizon = meta["horizon_mois"]
            if meta["last_date"] < f"{serie.index[-1]:%Y-%m-%d}":
                alertes.append(f"Les prévisions des modèles ont été calculées avec les prix de {meta['last_date'][:7]} ; des prix plus récents sont dans la base. "
                               f"Elles sont recalées sur le dernier prix : recalculez les modèles pour les mettre à jour.")
    fx_s = s["fx"]
    fx_ref = float(fx_s.iloc[-250:].mean())
    fx = h.taux_change if h.taux_change is not None else float(fx_s.iloc[-1])
    spot = float(serie.iloc[-1]) * (1 + h.choc)
    ref = spot if h.reference == "Dernier prix" else float(serie.iloc[-12:].mean())
    return Contexte(h, serie, fx, fx_ref, spot, ref, volatilite_annuelle(serie, h.fenetre_vol), modeles,
                    horizon=horizon, alertes=tuple(alertes), fx_serie=fx_s)


def trajectoire(c: Contexte, nom: str | None = None) -> pd.DataFrame:
    """Prix de la cible par mois (0 = dernier mois connu) pour les trois scénarios d'un modèle, avec la date et le mois civil de chaque point.

    Marche aléatoire réglable : central = dernier prix avec la tendance choisie, bornes = volatilité récente × √temps.
    Modèle précalculé (prevision_metaux) : médiane et quantiles 10 et 90 % du modèle au mois m, recalés sur le dernier prix connu, puis
    modifiés par le choc immédiat et la tendance.
    """
    h, nom = c.h, nom or c.h.modele
    m = np.arange(0, c.horizon + 1)
    if nom == MODELE_REGLABLE or nom not in noms_modeles(c.modeles):
        centre = c.spot * np.exp(h.derive_annuelle * m / 12)
        sigma = c.vol * np.sqrt(m / 12)
        bas, haut = centre * np.exp(-Z90 * sigma), centre * np.exp(Z90 * sigma)
    else:
        meta, pr = c.modeles["meta"], c.modeles["previsions"]
        pr = pr[pr["model"] == nom].sort_values("h")
        facteur = (1 + h.choc) * float(c.serie.iloc[-1]) / meta["last_price"] * np.exp(h.derive_annuelle * m / 12)
        bas, centre, haut = (np.interp(np.maximum(m, 1), pr["h"], pr[col]) * facteur for col in ("q10", "q50", "q90"))
        bas[0] = centre[0] = haut[0] = c.spot                              # le mois 0 est le dernier prix connu
    d = pd.DataFrame({"mois_no": m, "central": centre, "bas": bas, "haut": haut})
    dernier = c.serie.index[-1]
    periodes = [pd.Period(dernier, "M") + int(k) for k in m]
    d["periode"] = [str(p) for p in periodes]
    d["mois_civil"] = [p.month for p in periodes]
    d["date"] = [dernier] + [p.to_timestamp() + pd.Timedelta(days=14) for p in periodes[1:]]
    return d


def trajectoires_prix(c: Contexte) -> pd.DataFrame:
    """Trajectoires du modèle choisi dans les hypothèses."""
    return trajectoire(c, c.h.modele)


def indice_achat(c: Contexte, prix, fx: float | None = None) -> np.ndarray:
    """Indice du prix d'achat (1 = niveau de référence) : 1 + part de la matière × variation du prix de marché en dollars canadiens."""
    fx = c.fx if fx is None else fx
    rel = (np.asarray(prix, dtype=float) * fx) / (c.ref * c.fx_ref)
    return 1 + c.h.part_matiere * (rel - 1)


def prix_achat(c: Contexte, prix) -> pd.DataFrame:
    """Prix de marché et prix d'achat chez le distributeur ($ CAD/kg) correspondant à une série de prix de la cible."""
    idx = indice_achat(c, prix)
    return pd.DataFrame({"marche": np.asarray(prix, dtype=float), "achat_kg": c.h.prix_reference * idx, "indice": idx})


def historique_prix(c: Contexte) -> pd.DataFrame:
    """Prix d'achat estimé par le modèle pour chaque mois passé (prix de marché et change moyens du mois).

    Le prix de référence d'aujourd'hui est appliqué à tout l'historique : avant quelques années, le niveau est indicatif, pas un prix observé."""
    fx = c.fx_serie.resample("MS").mean().reindex(c.serie.index).ffill().bfill()
    idx = 1 + c.h.part_matiere * ((c.serie.to_numpy() * fx.to_numpy()) / (c.ref * c.fx_ref) - 1)
    return pd.DataFrame({"marche": c.serie, "fx": fx, "achat_kg": c.h.prix_reference * idx}, index=c.serie.index)


# --------------------------------------------------------------------------- #
# Effet sur la trésorerie
# --------------------------------------------------------------------------- #
def base_mensuelle(db_path: str, annee: int | None = None) -> pd.DataFrame:
    """Ventes et achats de matières par mois civil (valeurs positives), tirés du journal général."""
    c = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        annee = annee or c.execute("SELECT MAX(annee) FROM journal_general").fetchone()[0]
        rows = c.execute("SELECT j.mois, k.ordre, SUM(j.montant) FROM journal_general j JOIN categories k ON k.categorie = j.categorie "
                         "WHERE j.annee = ? GROUP BY j.mois, k.ordre", (annee,)).fetchall()
    finally:
        c.close()
    d = pd.DataFrame(0.0, index=range(1, 13), columns=["ventes", "achats"])
    for mois, ordre, tot in rows:
        if ordre in VENTES:
            d.loc[int(mois), "ventes"] += float(tot)
        elif ordre in ACHATS:
            d.loc[int(mois), "achats"] += -float(tot)
    d.attrs["annee"] = int(annee)
    return d


def seuil_securite(db_path: str) -> float | None:
    c = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        r = c.execute("SELECT valeur FROM parametres WHERE domaine='forecast' AND cle='seuil_securite'").fetchone()
    finally:
        c.close()
    return float(r[0]) if r else None


def _decale(delta: np.ndarray, retard_mois: float) -> np.ndarray:
    """Valeur de `delta` (indexé par mois, 0 = aujourd'hui, effet nul) retardée de `retard_mois`, par interpolation linéaire."""
    pos = np.arange(len(delta)) - retard_mois
    return np.where(pos <= 0, 0.0, np.interp(pos, np.arange(len(delta)), delta))


def impact(c: Contexte, prix_mois: np.ndarray, mois_civil: np.ndarray, base_j: pd.DataFrame) -> pd.DataFrame:
    """Journal projeté et effet sur l'encaisse pour une trajectoire du prix (indice 0 = aujourd'hui, puis un point par mois)."""
    h = c.h
    indice = indice_achat(c, prix_mois)
    n = len(prix_mois)
    base_v = np.array([base_j.loc[int(m), "ventes"] for m in mois_civil], dtype=float)
    base_a = np.array([base_j.loc[int(m), "achats"] for m in mois_civil], dtype=float)
    k = np.arange(n)
    indice_retarde = indice[np.maximum(k - h.delai_mois, 0)]
    # Les achats suivent le prix d'achat ; les ventes gardent leur niveau et reçoivent la part répercutée de la variation DU COÛT D'ACHAT en
    # dollars (la marge est préservée dans la mesure du passage) ; le volume réagit au prix de vente.
    prix_vente = 1 + h.passage * np.divide(base_a, base_v, out=np.zeros(n), where=base_v > 0) * (indice_retarde - 1)
    volume = 1 + h.elasticite * (prix_vente - 1)
    achats = base_a * indice * volume
    ventes = base_v * prix_vente * volume
    ventes[0], achats[0] = base_v[0], base_a[0]                     # le mois 0 est déjà dans le journal : pas d'écart
    d_ventes, d_achats = ventes - base_v, achats - base_a
    d_cash = _decale(d_ventes, h.dso / 30) - _decale(d_achats, h.dpo / 30)
    out = pd.DataFrame({"ventes": ventes, "achats": achats, "marge": ventes - achats, "base_ventes": base_v, "base_achats": base_a,
                        "base_marge": base_v - base_a, "d_marge": d_ventes - d_achats, "d_cash": d_cash})
    out["d_cash_cumul"] = out["d_cash"].cumsum()
    return out.iloc[1:].reset_index(drop=True)                      # on ne montre que les mois projetés (1 à N)


@dataclass
class Resultat:
    contexte: Contexte
    trajectoires: pd.DataFrame
    prix: dict[str, pd.DataFrame]          # scénario → prix de marché et prix d'achat (mois 0 à N)
    impacts: dict[str, pd.DataFrame]       # scénario → journal projeté (mois 1 à N)
    base: pd.DataFrame
    seuil: float | None


def projeter(h: Hypotheses, db_path: str, series: dict | None = None, modeles: dict | None = None) -> Resultat:
    c = contexte(h, series, modeles)
    t = trajectoires_prix(c)
    mois_civil = t["mois_civil"].to_numpy()
    base_j = base_mensuelle(db_path)
    prix = {s: prix_achat(c, t[s]) for s in SCENARIOS}
    imp = {s: impact(c, t[s].to_numpy(), mois_civil, base_j) for s in SCENARIOS}
    for s in SCENARIOS:
        imp[s].insert(0, "periode", t["periode"].iloc[1:].to_numpy())
        imp[s].insert(1, "marche", t[s].iloc[1:].to_numpy())
        imp[s].insert(2, "achat_kg", prix[s]["achat_kg"].iloc[1:].to_numpy())
    return Resultat(c, t, prix, imp, base_j, seuil_securite(db_path))


def variations_etats_financiers(r: Resultat, scenario: str, journal) -> dict:
    """Variations de ventes et de prix des produits achetés (en fractions) à saisir dans les états financiers pour reproduire,
    en dollars, l'effet du scénario sur le dernier exercice du journal.

    Les états financiers appliquent un pourcentage aux ventes (catégories 20 à 23 et 25) et aux achats (catégories 2 et 6) d'un
    exercice : on divise donc l'écart annuel en dollars du scénario par ces totaux. Si l'horizon n'est pas de 12 mois, l'écart
    moyen par mois est ramené à une année.
    """
    import etats_financiers as ef
    annee = journal.annees[-1]
    m = journal.montants[annee]
    ventes = sum(m.get(o, 0.0) for o in ef.VENTES + ef.AUTRES_REVENUS)
    achats = -sum(m.get(o, 0.0) for o in ef.ACHATS)
    d = r.impacts[scenario]
    annualise = 12 / len(d)
    d_ventes = float((d["ventes"] - d["base_ventes"]).sum()) * annualise
    d_achats = float((d["achats"] - d["base_achats"]).sum()) * annualise
    return {"annee": annee, "var_ventes": d_ventes / ventes if ventes else 0.0, "var_produits": d_achats / achats if achats else 0.0,
            "d_ventes": d_ventes, "d_achats": d_achats, "ventes_base": ventes, "achats_base": achats}


def sensibilite(r: Resultat, variations: list[float]) -> pd.DataFrame:
    """Effet sur 12 mois (ou l'horizon) si le prix du métal passait tout de suite de `variation` (en fraction) et y restait."""
    c, mois_civil = r.contexte, r.trajectoires["mois_civil"].to_numpy()
    lignes = []
    for v in variations:
        serie = np.concatenate([[c.spot], np.full(c.horizon, c.spot * (1 + v))])
        d = impact(c, serie, mois_civil, r.base)
        achat = float(prix_achat(c, np.array([c.spot * (1 + v)]))["achat_kg"].iloc[0])
        lignes.append({"Variation du prix du métal (%)": 100 * v, "Prix d'achat ($/kg)": achat, "Variation de la marge brute ($)": d["d_marge"].sum(),
                       "Effet sur l'encaisse ($)": d["d_cash"].sum()})
    return pd.DataFrame(lignes)
