"""Traçabilité (lineage) : exécutions des agents et fichiers sources.

Chaque agent devrait ouvrir un run au départ, passer son run_id à toutes ses écritures,
puis fermer le run. Chaque fichier reçu est enregistré avec son hash SHA-256 : si le hash
existe déjà, le fichier a déjà été ingéré et peut être ignoré.
Aucune fonction ne fait de commit : l'appelant contrôle la transaction.
"""
import hashlib
import json
import uuid
from datetime import datetime, timezone


def demarrer_run(conn, agent, parametres=None, version_schema=None):
    """Crée un run et retourne son identifiant (ex. A2-20261022T140533-1f3a9c)."""
    maintenant = datetime.now(timezone.utc)
    run_id = f"{agent}-{maintenant:%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:6]}"
    conn.execute(
        "INSERT INTO meta_run (run_id, agent, parametres_json, version_schema) VALUES (?, ?, ?, ?)",
        (run_id, agent, json.dumps(parametres, ensure_ascii=False) if parametres is not None else None,
         version_schema),
    )
    return run_id


def terminer_run(conn, run_id, statut="succes"):
    """Ferme un run avec le statut : succes, echec ou partiel."""
    conn.execute(
        "UPDATE meta_run SET fin = datetime('now'), statut = ? WHERE run_id = ?",
        (statut, run_id),
    )


def hash_fichier(chemin, taille_bloc=1024 * 1024):
    """SHA-256 du contenu d'un fichier, lu par blocs."""
    h = hashlib.sha256()
    with open(chemin, "rb") as f:
        for bloc in iter(lambda: f.read(taille_bloc), b""):
            h.update(bloc)
    return h.hexdigest()


def enregistrer_fichier(conn, chemin, *, format_code=None, banque_code=None, run_id=None):
    """Enregistre un fichier source. Retourne (fichier_id, deja_vu).

    deja_vu = True si un fichier de même contenu a déjà été enregistré (même hash) :
    l'agent d'acquisition peut alors sauter l'extraction.
    """
    import os

    empreinte = hash_fichier(chemin)
    curseur = conn.execute(
        "INSERT OR IGNORE INTO meta_fichier_source "
        "(nom_fichier, hash_sha256, format_code, banque_code, taille_octets, run_id) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (os.path.basename(chemin), empreinte, format_code, banque_code, os.path.getsize(chemin), run_id),
    )
    deja_vu = curseur.rowcount == 0
    fichier_id = conn.execute(
        "SELECT fichier_id FROM meta_fichier_source WHERE hash_sha256 = ?", (empreinte,)
    ).fetchone()[0]
    return fichier_id, deja_vu
