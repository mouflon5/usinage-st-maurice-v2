"""Initialise ou met à niveau la base de gouvernance des données de trésorerie.

Non destructif : tout est en CREATE ... IF NOT EXISTS / INSERT OR IGNORE. Peut être rejoué sans risque
sur une base existante : les tables existantes de votre projet ne sont jamais modifiées.

Étapes : schéma (sql/*.sql dans l'ordre) -> valeurs de référence -> dimension de dates ->
règles qualité -> dictionnaire de données.

Usage :
    python init_db.py --db tresorerie.db
"""
import argparse
import sqlite3
from datetime import date, timedelta
from pathlib import Path

import dictionnaire
import dq_runner

VERSION_SCHEMA = "1.0.0"
DESCRIPTION_VERSION = ("Socle de gouvernance DMBOK : métadonnées, données de référence, données maîtres, "
                       "qualité des données, couches stg/core/mart")
SQL_DIR = Path(__file__).parent / "sql"


def connecter(chemin):
    conn = sqlite3.connect(chemin)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def appliquer_schema(conn):
    for fichier in sorted(SQL_DIR.glob("*.sql")):
        conn.executescript(fichier.read_text(encoding="utf-8"))
    conn.execute("PRAGMA foreign_keys = ON")


def peupler_dim_date(conn, annee_debut=2020, annee_fin=2035):
    """Remplit dim_date. est_ouvrable = lundi à vendredi (les jours fériés ne sont pas gérés)."""
    jour, fin = date(annee_debut, 1, 1), date(annee_fin, 12, 31)
    lignes = []
    while jour <= fin:
        lendemain = jour + timedelta(days=1)
        lignes.append((jour.isoformat(), jour.year, (jour.month - 1) // 3 + 1, jour.month, jour.day,
                       jour.isocalendar()[1], jour.isoweekday(), 1 if jour.isoweekday() <= 5 else 0,
                       1 if lendemain.month != jour.month else 0))
        jour = lendemain
    conn.executemany("INSERT OR IGNORE INTO dim_date VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", lignes)


def initialiser(chemin):
    """Applique tout et retourne (connexion, statistiques du dictionnaire)."""
    conn = connecter(chemin)
    appliquer_schema(conn)
    conn.execute("INSERT OR IGNORE INTO meta_version_schema (version, description) VALUES (?, ?)",
                 (VERSION_SCHEMA, DESCRIPTION_VERSION))
    peupler_dim_date(conn)
    conn.commit()
    dq_runner.charger_regles(conn)
    stats = dictionnaire.construire_dictionnaire(conn, version_schema=VERSION_SCHEMA)
    return conn, stats


def main():
    p = argparse.ArgumentParser(description="Initialise la base de gouvernance des données.")
    p.add_argument("--db", required=True, help="Chemin de tresorerie.db (créée si absente)")
    a = p.parse_args()
    conn, stats = initialiser(a.db)
    print(f"Schéma {VERSION_SCHEMA} appliqué sur {a.db}")
    print(f"Dictionnaire : {stats['documentes']}/{stats['total']} champs documentés")
    if stats["a_documenter"]:
        print("À DOCUMENTER :", ", ".join(stats["a_documenter"]))
    nb = conn.execute("SELECT COUNT(*) FROM dq_regle WHERE actif = 1").fetchone()[0]
    print(f"Règles qualité actives : {nb}")
    conn.close()


if __name__ == "__main__":
    main()
