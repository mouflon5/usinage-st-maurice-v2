"""Lance le backtest walk-forward et la projection future des modèles de chaque cible (panier, acier, aluminium, nickel, cuivre).

Exemples (depuis la racine du projet) :
    python -m prevision_metaux.calcul                       # horizon 12 mois, 36 fenêtres de test, toutes les cibles
    python -m prevision_metaux.calcul --update              # met d'abord à jour les données (FRED → base SQLite)
    python -m prevision_metaux.calcul --cibles alu --fenetres 12
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from . import base, donnees, modeles
from .evaluation import metriques
from .modeles import QCOLS

RACINE = Path(__file__).resolve().parent.parent
CIBLES = ("panier", "acier", "alu", "nickel", "cuivre")
MIN_HISTORIQUE = 120                     # mois d'historique exigés avant la première origine du backtest


def en_prix(prev: pd.DataFrame, serie: pd.Series, dates_futures: pd.DatetimeIndex | None = None) -> pd.DataFrame:
    """Passe du log-prix au prix et ajoute dates, dernier prix connu et prix réalisé."""
    out = prev.copy()
    out[QCOLS] = np.exp(out[QCOLS])
    dates, prix = serie.index, serie.to_numpy()
    out["cutoff_date"] = dates[out["cutoff"]]
    out["last_price"] = prix[out["cutoff"]]
    if dates_futures is None:
        idx = out["cutoff"] + out["h"]
        out["date"] = dates[idx]
        out["y_true"] = prix[idx]
    else:
        out["date"] = dates_futures[out["h"] - 1]
    return out


def calculer_cible(cible: str, db: str, H: int, fenetres: int, pas: int, sortie: Path) -> None:
    serie = donnees.charger_cible(cible, db)
    y, n = donnees.log_prix(serie), len(serie)
    origines = [n - 1 - H - pas * k for k in range(fenetres)][::-1]
    if origines[0] < MIN_HISTORIQUE:
        raise SystemExit(f"{cible} : trop de fenêtres pour l'historique disponible (première origine au mois {origines[0]}).")
    dates_futures = pd.date_range(serie.index[-1] + pd.offsets.MonthBegin(), periods=H, freq="MS")
    print(f"[calcul] {cible} : {n} mois, de {serie.index[0]:%Y-%m} à {serie.index[-1]:%Y-%m}; backtest {fenetres} fenêtres de {H} mois", flush=True)
    t0 = time.time()
    bt = en_prix(modeles.ajouter_ensemble(modeles.lancer_classiques(y, origines, H)), serie)
    fut = en_prix(modeles.ajouter_ensemble(modeles.lancer_classiques(y, [n - 1], H)), serie, dates_futures)
    dossier = sortie / cible
    dossier.mkdir(parents=True, exist_ok=True)
    bt.to_csv(dossier / "backtest.csv", index=False)
    fut.to_csv(dossier / "forecast.csv", index=False)
    metriques(bt, [3, H]).to_csv(dossier / "metrics.csv")
    meta = {"run_at": datetime.now().isoformat(timespec="seconds"), "cible": cible, "last_date": f"{serie.index[-1]:%Y-%m-%d}",
            "last_price": float(serie.iloc[-1]), "horizon": H, "horizon_mois": H, "jours_par_mois": 1, "windows": fenetres, "step": pas,
            "backtest_start": f"{serie.index[origines[0]]:%Y-%m-%d}", "backtest_last_origin": f"{serie.index[origines[-1]]:%Y-%m-%d}",
            "base": Path(db).name, "models": sorted(bt["model"].unique().tolist()), "duration_s": round(time.time() - t0)}
    (dossier / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    with pd.option_context("display.width", 200, "display.max_columns", 20, "display.precision", 3):
        print(metriques(bt, [H]), flush=True)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--db", default=str(RACINE / "tresorerie.db"), help="base SQLite qui contient l'historique des prix de marché")
    p.add_argument("--horizon-mois", type=int, default=12)
    p.add_argument("--fenetres", type=int, default=36, help="nombre de fenêtres de test du backtest (défaut 36)")
    p.add_argument("--pas", type=int, default=3, help="mois entre deux origines (défaut 3)")
    p.add_argument("--cibles", nargs="+", default=list(CIBLES), choices=CIBLES)
    p.add_argument("--update", action="store_true", help="télécharger les dernières données FRED avant de calculer")
    p.add_argument("--sortie", default=str(donnees.DOSSIER), help="dossier des résultats")
    a = p.parse_args()
    sys.stdout.reconfigure(line_buffering=True)
    if a.update:
        donnees.telecharger_fred()
    importe = base.importer(a.db)
    print("[base] " + ", ".join(f"{k} {'à jour' if v == 0 else f'+{v}'}" for k, v in importe.items()))
    for cible in a.cibles:
        calculer_cible(cible, a.db, a.horizon_mois, a.fenetres, a.pas, Path(a.sortie))


if __name__ == "__main__":
    main()
