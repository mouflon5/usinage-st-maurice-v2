"""Chemins et remise à zéro de la base de démo."""

import os
import shutil

DB_DEMO = "tresorerie_demo.db"


def resoudre_db(db_path=None) -> str:
    """Priorité : argument > variable TRESORERIE_DB > copie de démo locale."""
    return str(db_path or os.getenv("TRESORERIE_DB") or DB_DEMO)


def reinitialiser_demo(source: str, destination: str = DB_DEMO) -> str:
    """Recopie la base d'origine (jamais modifiée) vers la copie de démo."""
    shutil.copy2(source, destination)
    return destination
