"""Modèles de prévision du log-prix mensuel d'un métal.

Chaque modèle renvoie, pour une date d'origine (cutoff) et un horizon H en mois, les quantiles 5, 10, 50, 90 et 95 % du log-prix à chaque mois 1..H.
Trois modèles statistiques, plus un ensemble (moyenne de leurs quantiles) : aucune bibliothèque d'apprentissage profond n'est nécessaire.
"""
from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
from scipy.stats import norm

QUANTILES = [0.05, 0.10, 0.50, 0.90, 0.95]
QCOLS = ["q05", "q10", "q50", "q90", "q95"]
Z = norm.ppf(QUANTILES)

REFERENCE = "Marche aléatoire"
STATISTIQUES = ["Marche aléatoire", "ARIMA", "GARCH"]
ENSEMBLE = "Ensemble"


def _quantiles_normales(centre: np.ndarray, ecart: np.ndarray) -> np.ndarray:
    return centre[:, None] + ecart[:, None] * Z[None, :]


def marche_aleatoire(y: np.ndarray, H: int, fenetre_vol: int = 60) -> np.ndarray:
    """Prix futur = dernier prix ; incertitude = volatilité mensuelle récente × √h."""
    sigma = np.diff(y[-fenetre_vol - 1:]).std()
    h = np.arange(1, H + 1)
    return _quantiles_normales(np.full(H, y[-1]), sigma * np.sqrt(h))


def arima(y: np.ndarray, H: int, fenetre: int = 240) -> np.ndarray:
    """ARIMA(1,1,1) sur le log-prix (= ARMA(1,1) sur les log-rendements mensuels)."""
    from statsmodels.tsa.arima.model import ARIMA

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        res = ARIMA(y[-fenetre:], order=(1, 1, 1)).fit()
    prev = res.get_forecast(H)
    return _quantiles_normales(np.asarray(prev.predicted_mean), np.sqrt(np.asarray(prev.var_pred_mean)))


def garch(y: np.ndarray, H: int, fenetre: int = 400) -> np.ndarray:
    """Rendement moyen constant + volatilité GARCH(1,1) à innovations de Student (la variance du rendement cumulé est la somme des variances prévues)."""
    from arch import arch_model

    r = 100 * np.diff(y[-fenetre - 1:])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        res = arch_model(r, mean="Constant", vol="GARCH", p=1, q=1, dist="t").fit(disp="off")
    var = res.forecast(horizon=H, reindex=False).variance.values[-1] / 1e4
    mu = res.params["mu"] / 100
    h = np.arange(1, H + 1)
    return _quantiles_normales(y[-1] + mu * h, np.sqrt(np.cumsum(var)))


CLASSIQUES = {"Marche aléatoire": marche_aleatoire, "ARIMA": arima, "GARCH": garch}


def _cadre(nom: str, origine: int, q: np.ndarray) -> pd.DataFrame:
    q = np.sort(q, axis=1)                      # garantit des quantiles croissants
    out = pd.DataFrame(q, columns=QCOLS)
    out.insert(0, "h", np.arange(1, len(q) + 1))
    out.insert(0, "cutoff", origine)
    out.insert(0, "model", nom)
    return out


def lancer_classiques(y: np.ndarray, origines: list[int], H: int) -> pd.DataFrame:
    morceaux = []
    for nom, fn in CLASSIQUES.items():
        for c in origines:
            morceaux.append(_cadre(nom, c, fn(y[: c + 1], H)))
        print(f"[modèles] {nom} : {len(origines)} origine(s)", flush=True)
    return pd.concat(morceaux, ignore_index=True)


def ajouter_ensemble(prev: pd.DataFrame) -> pd.DataFrame:
    """Ajoute « Ensemble » : moyenne des quantiles des modèles, à chaque origine et chaque horizon."""
    moy = prev.groupby(["cutoff", "h"], as_index=False)[QCOLS].mean()
    moy[QCOLS] = np.sort(moy[QCOLS].to_numpy(), axis=1)
    moy.insert(0, "model", ENSEMBLE)
    return pd.concat([prev, moy[prev.columns]], ignore_index=True)
