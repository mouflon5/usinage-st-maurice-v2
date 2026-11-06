"""
Nœuds de l'agent A4 — Prévision.

Le LLM n'intervient pas ici : tout est calculé par SARIMAX (statsmodels), réutilisé tel quel
depuis tresorerie_dashboard.py (même moteur que R8). Chaque prévision porte sa source
(méthode, paramètres, backtest, convergence). Si SARIMAX échoue ou ne converge pas,
repli déterministe sur le naïf saisonnier, signalé comme tel ("degrade").
"""

import os
from pathlib import Path

import numpy as np

from a4_state import ForecastState
import tresorerie_dashboard as td

SERIES_DEFAUT = ["Revenu", "Decaissements"]
SEUIL_MAPE = float(os.getenv("A4_SEUIL_MAPE", "0.25"))   # au-delà : prévision signalée peu fiable


def preparer_node(state: ForecastState) -> dict:
    db = state["db_path"]
    if not os.path.isfile(db):
        return {"statut": "erreur", "message": f"Base introuvable : {db}"}
    h = int(state.get("horizon", 6))
    if not 3 <= h <= 12:
        return {"statut": "erreur", "message": f"Horizon hors limites (3 à 12) : {h}"}
    series = state.get("series") or SERIES_DEFAUT
    try:
        for s in series:                      # valide que l'historique est exploitable (48 mois)
            td.load_monthly_series(s, Path(db))
    except Exception as e:
        return {"statut": "erreur", "message": f"Historique inutilisable : {type(e).__name__}: {e}"}
    return {"series": series, "horizon": h, "alertes": [], "series_en_echec": []}


def router_apres_preparation(state: ForecastState) -> str:
    return "erreur" if state.get("statut") == "erreur" else "prevoir"


def _naif_saisonnier(y: np.ndarray, h: int, periodes: list) -> dict:
    pred = [float(y[-12 + (i % 12)]) for i in range(h)]
    return {"forecast": pred, "ci80_low": pred, "ci80_high": pred, "ci95_low": pred, "ci95_high": pred,
            "future_periods": td._future_periods(periodes[-1], h),
            "backtest": {"mae": None, "rmse": None, "bias": None},
            "diagnostics": {"converged": None}}


def prevoir_node(state: ForecastState) -> dict:
    h = state["horizon"]
    previsions, alertes, echecs = {}, list(state.get("alertes", [])), []
    for s in state["series"]:
        methode = "SARIMAX"
        try:
            r = td.sarimax_analysis({"series": s, "horizon": h, "holdout": 6}, Path(state["db_path"]))
            if not r["diagnostics"]["converged"]:
                raise RuntimeError("non convergence")
        except Exception as e:
            alertes.append(f"{s} : SARIMAX indisponible ({type(e).__name__}: {e}) — repli naïf saisonnier")
            try:
                periodes, y, meta = td.load_monthly_series(s, Path(state["db_path"]))
                r = _naif_saisonnier(y, h, periodes)
                r.update({"periods": periodes, "values": [float(v) for v in y]})
                methode = "Naïf saisonnier (repli)"
            except Exception as e2:
                echecs.append(s)
                alertes.append(f"{s} : échec total ({type(e2).__name__}: {e2})")
                continue

        mape = None
        bt = r.get("backtest", {})
        if bt.get("actual"):
            a, p = np.array(bt["actual"]), np.array(bt["pred"])
            mask = np.abs(a) > 1e-9
            if mask.any():
                mape = float(np.mean(np.abs(p[mask] - a[mask]) / np.abs(a[mask])))
        if mape is not None and mape > SEUIL_MAPE:
            alertes.append(f"{s} : erreur de backtest élevée (MAPE {mape:.0%} > {SEUIL_MAPE:.0%}) — prévision peu fiable")

        # Intervalles : le SARIMAX configuré (enforce_stationarity=False) peut produire des IC qui explosent.
        # On les contrôle ; s'ils sont aberrants, on les remplace par un encadrement transparent fondé sur
        # la RMSE du backtest, et on le dit.
        ic_methode, ic_note = ("SARIMAX" if methode == "SARIMAX" else "aucun"), ""
        rmse = bt.get("rmse")
        if methode == "SARIMAX" and rmse:
            def sain(lo, hi, p):
                return np.isfinite(lo) and np.isfinite(hi) and lo <= p <= hi and (hi - p) <= max(5 * abs(p), 6 * rmse)
            if not all(sain(a, b, p) for (a, b), p in zip(zip(r["ci95_low"], r["ci95_high"]), r["forecast"])):
                nonneg = True
                for z, k in ((1.2816, "ci80"), (1.96, "ci95")):
                    r[k + "_low"] = [max(0.0, p - z * rmse) if nonneg else p - z * rmse for p in r["forecast"]]
                    r[k + "_high"] = [p + z * rmse for p in r["forecast"]]
                ic_methode = "RMSE du backtest"
                ic_note = (f"{s} : l'intervalle SARIMAX était instable (valeurs aberrantes) ; remplacé par prévision ± z × RMSE du "
                           f"backtest ({rmse:,.0f} $).".replace(",", " "))

        previsions[s] = {
            "ic_methode": ic_methode, "ic_note": ic_note,
            "methode": methode,
            "periodes": r["future_periods"],
            "valeurs": [round(v, 2) for v in r["forecast"]],
            "ci80": [[round(a, 2), round(b, 2)] for a, b in zip(r["ci80_low"], r["ci80_high"])],
            "ci95": [[round(a, 2), round(b, 2)] for a, b in zip(r["ci95_low"], r["ci95_high"])],
            "backtest": {**{k: (round(v, 2) if isinstance(v, float) else v) for k, v in bt.items()
                            if k in ("mae", "rmse", "bias")}, "mape": None if mape is None else round(mape, 4)},
            "diagnostics": r.get("diagnostics", {}),
            "parametres": r.get("params", {}),
            "derniere_observation": r["periods"][-1],
        }
    return {"previsions": previsions, "alertes": alertes, "series_en_echec": echecs}


def flux_net_node(state: ForecastState) -> dict:
    p = state.get("previsions", {})
    if "Revenu" in p and "Decaissements" in p:
        rev, dec = p["Revenu"], p["Decaissements"]
        return {"flux_net": {"periodes": rev["periodes"],
                             "valeurs": [round(a - b, 2) for a, b in zip(rev["valeurs"], dec["valeurs"])],
                             "source": "Revenu prévu − Décaissements prévus (calcul déterministe)"}}
    return {}


def router_apres_prevision(state: ForecastState) -> str:
    if not state.get("previsions"):
        return "erreur"
    return "degrade" if (state.get("alertes") or state.get("series_en_echec")) else "complet"


def marquer_complet_node(state: ForecastState) -> dict:
    p = state["previsions"]
    fn = state.get("flux_net", {})
    tot = f" Flux net prévu cumulé : {sum(fn['valeurs']):,.0f} $." if fn else ""
    return {"statut": "complet", "message": f"{len(p)} série(s) prévue(s) sur {state['horizon']} mois.{tot}"}


def signaler_degrade_node(state: ForecastState) -> dict:
    return {"statut": "degrade", "message": "Prévision produite avec réserves : " + " | ".join(state["alertes"])}


def signaler_erreur_node(state: ForecastState) -> dict:
    return {"statut": "erreur", "message": state.get("message") or "Aucune prévision produite : " + " | ".join(state.get("alertes", []))}
