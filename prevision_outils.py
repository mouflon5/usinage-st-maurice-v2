"""Prévision « à date » : SARIMAX entraîné uniquement sur les mois AVANT `periode`, puis prévision du mois.

Même moteur et mêmes paramètres par défaut que R8 / A4 (tresorerie_dashboard.py), mais sans fuite
d'information : aucune donnée de `periode` ni des mois suivants n'entre dans l'entraînement.
"""
from pathlib import Path

import numpy as np

import tresorerie_dashboard as td

PARAMS = dict(p=1, d=0, q=0, P=1, D=0, Q=1, s=12, use_trend=True, fourier_k=1)


def prevision_a_date(db_path: str, serie: str, periode: str) -> dict:
    periodes, y, meta = td.load_monthly_series(serie, Path(db_path))
    if periode not in periodes:
        raise ValueError(f"Période {periode} absente de l'historique")
    i = periodes.index(periode)
    if i < 18:
        raise ValueError(f"Historique insuffisant avant {periode} ({i} mois, 18 requis)")
    res = td._fit_sarimax(y[:i], **PARAMS)
    exog = td._exog_matrix(1, PARAMS["s"], PARAMS["use_trend"], PARAMS["fourier_k"], i)
    fc = res.get_forecast(steps=1, exog=exog)
    pred = float(np.array(fc.predicted_mean, float)[0])
    ci95 = np.array(fc.conf_int(alpha=0.05), float)[0]
    if meta["nonnegative"]:
        pred, ci95 = max(0.0, pred), np.maximum(0.0, ci95)
    converged = bool(getattr(res, "mle_retvals", {}).get("converged", True))
    return {"prevu": pred, "ci95": [float(ci95[0]), float(ci95[1])], "converge": converged,
            "mois_entrainement": i, "reel": float(y[i])}
