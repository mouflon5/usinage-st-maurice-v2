"""Historique des prix de marché (aluminium, acier, nickel, cuivre, minerai de fer, zinc, change) dans la base SQLite.

Deux tables, qui suivent les conventions de gouvernance du projet :
  ref_serie_marche   catalogue des séries (code FRED, libellé, unité, fréquence, source)
  core_prix_marche   une ligne par série et par date d'observation

    python -m prevision_metaux.base --db tresorerie.db            # importe les CSV de donnees_externes/metaux/ (ou met à jour)
    python -m prevision_metaux.base --db tresorerie.db --fred     # télécharge d'abord les dernières valeurs de FRED

L'import est idempotent : on peut le rejouer sur n'importe quelle base (tresorerie.db, base de démonstration, copie restaurée).
"""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

import pandas as pd

from . import donnees

SCHEMA = """
CREATE TABLE IF NOT EXISTS ref_serie_marche (
    code        TEXT PRIMARY KEY,
    libelle_fr  TEXT NOT NULL,
    libelle_en  TEXT NOT NULL,
    description TEXT,
    unite       TEXT NOT NULL,
    frequence   TEXT NOT NULL CHECK (frequence IN ('quotidienne', 'hebdomadaire', 'mensuelle')),
    source      TEXT NOT NULL,
    date_debut  TEXT NOT NULL DEFAULT '1900-01-01',
    date_fin    TEXT,
    actif       INTEGER NOT NULL DEFAULT 1 CHECK (actif IN (0, 1)),
    CHECK (date_fin IS NULL OR date_fin >= date_debut)
);
CREATE TABLE IF NOT EXISTS core_prix_marche (
    serie_code TEXT NOT NULL REFERENCES ref_serie_marche (code),
    date_obs   TEXT NOT NULL,
    valeur     REAL NOT NULL,
    maj_le     TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (serie_code, date_obs)
);
CREATE INDEX IF NOT EXISTS idx_core_prix_marche_date ON core_prix_marche (date_obs);
"""

# code FRED → (libellé fr, libellé en, unité, fréquence, description)
SERIES = {
    "PALUMUSDM": ("Aluminium, prix mondial", "Global price of aluminum", "$ US par tonne métrique", "mensuelle",
                  "Prix moyen mensuel du Fonds monétaire international, depuis 1992 : référence des barres, plaques et profilés d'aluminium."),
    "WPU1017": ("Produits d'aciérie, indice des prix à la production", "PPI: steel mill products", "indice (1982 = 100)", "mensuelle",
                "Indice américain des prix de vente des aciéries : référence des barres et plaques d'acier au carbone et allié."),
    "WPU101": ("Fer et acier, indice des prix à la production", "PPI: iron and steel", "indice (1982 = 100)", "mensuelle",
               "Indice américain plus large (fonte, ferro-alliages, acier), depuis 1926."),
    "PNICKUSDM": ("Nickel, prix mondial", "Global price of nickel", "$ US par tonne métrique", "mensuelle",
                  "Prix moyen mensuel du FMI, depuis 1992 : le nickel détermine le prix des aciers inoxydables 304 et 316."),
    "PCOPPUSDM": ("Cuivre, prix mondial", "Global price of copper", "$ US par tonne métrique", "mensuelle",
                  "Prix moyen mensuel du FMI, depuis 1992 : référence du laiton, du bronze et du cuivre."),
    "PIORECRUSDM": ("Minerai de fer, prix mondial", "Global price of iron ore", "$ US par tonne métrique", "mensuelle",
                    "Prix moyen mensuel du FMI : intrant de l'acier brut, indicateur avancé du prix de l'acier."),
    "PZINCUSDM": ("Zinc, prix mondial", "Global price of zinc", "$ US par tonne métrique", "mensuelle",
                  "Prix moyen mensuel du FMI : le zinc entre dans la galvanisation des pièces sous-traitées."),
    "DEXCAUS": ("Taux de change dollar canadien par dollar américain", "CAD per USD exchange rate", "CAD par USD", "quotidienne",
                "Taux de la Réserve fédérale (H.10), depuis 1971 : les métaux se négocient en dollars américains."),
}


def assurer_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


def _bornes(conn: sqlite3.Connection, code: str) -> tuple[str | None, int]:
    d, n = conn.execute("SELECT MAX(date_obs), COUNT(*) FROM core_prix_marche WHERE serie_code = ?", (code,)).fetchone()
    return d, n


def importer(db_path: str | Path, dossier: Path | None = None) -> dict[str, int]:
    """Charge les CSV FRED dans la base : ajoute les séries absentes et les nouvelles observations. Retourne le nombre de lignes
    ajoutées ou corrigées par série."""
    dossier = Path(dossier or donnees.DOSSIER)
    conn = sqlite3.connect(str(db_path), timeout=30)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        assurer_schema(conn)
        resultat = {}
        for code, (fr, en, unite, freq, desc) in SERIES.items():
            fichier = dossier / f"{code}.csv"
            if not fichier.is_file():
                continue
            s = donnees.lire_csv(fichier)
            if s.empty:
                continue
            conn.execute("INSERT INTO ref_serie_marche (code, libelle_fr, libelle_en, description, unite, frequence, source, date_debut, date_fin) "
                         "VALUES (?, ?, ?, ?, ?, ?, 'FRED (Réserve fédérale de St. Louis)', ?, ?) "
                         "ON CONFLICT (code) DO UPDATE SET date_debut = excluded.date_debut, date_fin = excluded.date_fin",
                         (code, fr, en, desc, unite, freq, f"{s.index[0]:%Y-%m-%d}", f"{s.index[-1]:%Y-%m-%d}"))
            dernier, n = _bornes(conn, code)
            if dernier == f"{s.index[-1]:%Y-%m-%d}" and n == len(s):
                resultat[code] = 0                                   # déjà à jour
                continue
            lignes = [(code, f"{d:%Y-%m-%d}", float(v)) for d, v in s.items()]
            conn.executemany("INSERT INTO core_prix_marche (serie_code, date_obs, valeur) VALUES (?, ?, ?) "
                             "ON CONFLICT (serie_code, date_obs) DO UPDATE SET valeur = excluded.valeur, maj_le = datetime('now')", lignes)
            resultat[code] = len(lignes) - n if n else len(lignes)
        conn.commit()
        return resultat
    finally:
        conn.close()


def lire(db_path: str | Path, code: str) -> pd.Series:
    """Série (date → valeur) lue de la base."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=30)
    try:
        lignes = conn.execute("SELECT date_obs, valeur FROM core_prix_marche WHERE serie_code = ? ORDER BY date_obs", (code,)).fetchall()
    finally:
        conn.close()
    return pd.Series([v for _, v in lignes], index=pd.to_datetime([d for d, _ in lignes]), dtype=float, name=code)


def catalogue(db_path: str | Path) -> pd.DataFrame:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=30)
    try:
        return pd.read_sql_query(
            "SELECT s.code, s.libelle_fr, s.unite, s.frequence, s.date_debut, s.date_fin, COUNT(p.valeur) AS observations "
            "FROM ref_serie_marche s LEFT JOIN core_prix_marche p ON p.serie_code = s.code GROUP BY s.code ORDER BY s.code", conn)
    finally:
        conn.close()


def disponible(db_path: str | Path) -> bool:
    """Vrai si la base contient déjà l'historique de l'aluminium (série témoin)."""
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=30)
        try:
            return conn.execute("SELECT COUNT(*) FROM core_prix_marche WHERE serie_code = 'PALUMUSDM'").fetchone()[0] > 0
        finally:
            conn.close()
    except sqlite3.Error:
        return False


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--db", required=True, help="chemin de la base SQLite (tresorerie.db)")
    p.add_argument("--fred", action="store_true", help="télécharger d'abord les dernières valeurs de FRED")
    a = p.parse_args()
    if a.fred:
        donnees.telecharger_fred()
    for code, n in importer(a.db).items():
        print(f"{code:12s} {'à jour' if n == 0 else f'{n} ligne(s) ajoutée(s) ou corrigée(s)'}")
    print(catalogue(a.db).to_string(index=False))


if __name__ == "__main__":
    main()
