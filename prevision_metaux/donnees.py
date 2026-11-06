"""Chargement et préparation des séries FRED de métaux (mensuelles) et du change.

Source de référence : la base SQLite (tables ref_serie_marche et core_prix_marche, voir base.py). Les CSV de donnees_externes/metaux/
ne servent qu'à alimenter la base et à mettre à jour depuis FRED.
"""
from __future__ import annotations

import subprocess
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

DOSSIER = Path(__file__).resolve().parent.parent / "donnees_externes" / "metaux"

# code FRED → clé courte
SERIES = {
    "PALUMUSDM": "alu",        # aluminium, $ US par tonne métrique, mensuel depuis 1992
    "WPU1017": "acier",        # indice des prix à la production : produits d'aciérie (1982 = 100), mensuel
    "PNICKUSDM": "nickel",     # nickel (inox), $ US par tonne métrique
    "PCOPPUSDM": "cuivre",     # cuivre (laiton, bronze), $ US par tonne métrique
}
# Séries seulement affichées (historique) ou utilisées pour la conversion en dollars canadiens
AUTRES = ("WPU101", "PIORECRUSDM", "PZINCUSDM", "DEXCAUS")

# Panier des matières premières de Groupe Usinage Saint-Maurice (poids dans les achats de matières, hypothèse modifiable)
PANIER = {"acier": 0.50, "alu": 0.25, "nickel": 0.15, "cuivre": 0.10}


def telecharger_fred(timeout: int = 90) -> None:
    """Met à jour les CSV locaux depuis FRED. En cas d'échec, garde les fichiers existants (essaie urllib puis curl)."""
    DOSSIER.mkdir(parents=True, exist_ok=True)
    for fred_id in list(SERIES) + list(AUTRES):
        url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={fred_id}"
        contenu = None
        try:
            with urllib.request.urlopen(url, timeout=timeout) as r:
                contenu = r.read()
        except Exception as e:
            try:
                contenu = subprocess.run(["curl", "-sS", "-L", "-m", str(timeout), url], capture_output=True, check=True).stdout
            except Exception as e2:      # réseau indisponible : on garde la version locale
                print(f"[données] {fred_id} non mis à jour ({e} / {e2}), version locale conservée")
        if contenu and contenu.startswith(b"observation_date") or contenu and contenu.startswith(b"DATE"):
            (DOSSIER / f"{fred_id}.csv").write_bytes(contenu)
            print(f"[données] {fred_id} mis à jour")


def lire_csv(chemin: Path) -> pd.Series:
    df = pd.read_csv(chemin, na_values=["."])
    return pd.Series(df.iloc[:, 1].astype(float).to_numpy(), index=pd.to_datetime(df.iloc[:, 0])).dropna()


def lire_serie(fred_id: str, db: str | Path | None = None) -> pd.Series:
    """Série FRED : lue de la base SQLite si on en donne une (source de référence), sinon du CSV de donnees_externes/metaux/."""
    if db is not None:
        from . import base
        return base.lire(db, fred_id)
    return lire_csv(DOSSIER / f"{fred_id}.csv")


def _mensuel(s: pd.Series) -> pd.Series:
    """Moyenne mensuelle, indexée au premier jour du mois."""
    return s[s > 0].resample("MS").mean().dropna()


def panier(series: dict[str, pd.Series], poids: dict[str, float] | None = None, base_mois: int = 12) -> pd.Series:
    """Indice du panier de matières : somme pondérée des prix de chaque métal rapportés à leur moyenne des `base_mois` derniers mois
    (le panier vaut donc 1 en moyenne sur la dernière année). Mensuel, depuis la date où toutes les séries existent."""
    poids = poids or PANIER
    total = sum(poids.values())
    d = pd.concat({k: _mensuel(series[k]) for k in poids}, axis=1).dropna()
    ref = d.iloc[-base_mois:].mean()
    return sum(poids[k] / total * d[k] / ref[k] for k in poids).rename("panier")


def charger_series(db: str | Path | None = None) -> dict[str, pd.Series]:
    """Toutes les séries (mensuelles pour les métaux, quotidienne pour le change) et le panier, par clé courte."""
    s = {cle: lire_serie(code, db) for code, cle in SERIES.items()}
    s["fx"] = lire_serie("DEXCAUS", db)
    s["panier"] = panier(s)
    return s


def charger_cible(cible: str, db: str | Path | None = None) -> pd.Series:
    """Série mensuelle d'une cible (« panier », « acier », « alu », « nickel » ou « cuivre »)."""
    s = charger_series(db)
    return _mensuel(s[cible]) if cible != "panier" else s["panier"]


def log_prix(y: pd.Series) -> np.ndarray:
    return np.log(y.to_numpy(dtype=float))
