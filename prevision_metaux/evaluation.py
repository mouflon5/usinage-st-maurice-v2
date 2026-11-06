"""Métriques d'évaluation des prévisions (walk-forward)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .modeles import QCOLS, QUANTILES, REFERENCE


def perte_quantile(y: np.ndarray, q: np.ndarray) -> np.ndarray:
    """Perte quantile moyenne sur les 5 quantiles (approximation du CRPS)."""
    tau = np.asarray(QUANTILES)[None, :]
    ecart = y[:, None] - q
    return np.mean(np.maximum(tau * ecart, (tau - 1) * ecart), axis=1)


def metriques(bt: pd.DataFrame, horizons: list[int] | None = None) -> pd.DataFrame:
    """Une ligne par modèle. `bt` contient les prix réels (y_true) et prévus, dans l'unité de la série.

    Le skill est le rapport à la marche aléatoire : < 1 signifie que le modèle fait mieux.
    """
    d = bt if horizons is None else bt[bt["h"].isin(horizons)]
    d = d.assign(
        err=d["q50"] - d["y_true"],
        ape=(d["q50"] - d["y_true"]).abs() / d["y_true"],
        dans80=(d["y_true"] >= d["q10"]) & (d["y_true"] <= d["q90"]),
        dans90=(d["y_true"] >= d["q05"]) & (d["y_true"] <= d["q95"]),
        perte=perte_quantile(d["y_true"].to_numpy(), d[QCOLS].to_numpy()),
        direction=np.sign(d["q50"] - d["last_price"]) == np.sign(d["y_true"] - d["last_price"]),
    )
    g = d.groupby("model")
    out = pd.DataFrame({
        "MAE": g["err"].apply(lambda e: e.abs().mean()),
        "RMSE": g["err"].apply(lambda e: np.sqrt((e ** 2).mean())),
        "MAPE (%)": g["ape"].mean() * 100,
        "Perte quantile": g["perte"].mean(),
        "Couverture 80 % (%)": g["dans80"].mean() * 100,
        "Couverture 90 % (%)": g["dans90"].mean() * 100,
        "Direction (%)": g["direction"].mean() * 100,
        "Observations": g["err"].size(),
    })
    if REFERENCE in out.index:           # la marche aléatoire prévoit « aucun changement » : la direction n'a pas de sens pour elle
        out.loc[REFERENCE, "Direction (%)"] = np.nan
        out.insert(1, "Skill MAE vs MA", out["MAE"] / out.loc[REFERENCE, "MAE"])
        out.insert(5, "Skill quantile vs MA", out["Perte quantile"] / out.loc[REFERENCE, "Perte quantile"])
    return out.sort_values("Perte quantile")
