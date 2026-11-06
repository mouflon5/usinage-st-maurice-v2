"""Pilotage d'un lot depuis le tableau de bord : lancer l'exécuteur en processus détaché, lui envoyer une commande
(pause / reprendre / arreter / tuer), juger s'il est vivant. Aucune dépendance à Streamlit (testable seul)."""

import os
import re
import sqlite3
import subprocess
import sys
from datetime import datetime

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOSSIER = os.path.join(RACINE, "banc_essai", "resultats")
DB = os.path.join(DOSSIER, "resultats.db")
ACTIFS = ("en cours", "en pause", "arrêt en cours")
DELAI_MORT_S = 20          # sans battement de cœur depuis 20 s, on considère l'exécuteur arrêté


def _ecriture():
    from banc_essai.executeur import ouvrir_resultats
    return ouvrir_resultats()


def nom_valide(run_id: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9_\-]{1,40}", run_id or ""))


def chemin_journal(run_id: str) -> str:
    return os.path.join(DOSSIER, f"{run_id}.log")


def lancer(run_id: str, seed: int, n: int, workers: int, reel: bool, sans_a8: bool,
           categories=None, types=None, ids=None, forcer=False) -> str:
    """Démarre l'exécuteur détaché ; renvoie le chemin de son journal."""
    if not nom_valide(run_id):
        raise ValueError("Nom de lot invalide (lettres, chiffres, _ et - ; 40 caractères max).")
    cmd = [sys.executable, "-m", "banc_essai.executeur", "--seed", str(int(seed)), "--n", str(int(n)),
           "--workers", str(int(workers)), "--run-id", run_id]
    if reel:
        cmd.append("--reel")
    if sans_a8:
        cmd.append("--sans-a8")
    if categories:
        cmd += ["--categories", ",".join(categories)]
    if types:
        cmd += ["--types", ",".join(types)]
    if ids:
        cmd += ["--ids", ",".join(ids)]
    if forcer:
        cmd.append("--forcer")
    os.makedirs(DOSSIER, exist_ok=True)
    journal = open(chemin_journal(run_id), "a", encoding="utf-8")
    kw = {}
    if os.name == "nt":
        kw["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    else:
        kw["start_new_session"] = True
    subprocess.Popen(cmd, cwd=RACINE, stdout=journal, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, **kw)
    return journal.name


def envoyer_commande(run_id: str, commande: str):
    if commande not in ("pause", "reprendre", "arreter", "tuer"):
        raise ValueError(commande)
    c = _ecriture()
    try:
        c.execute("UPDATE lots SET commande=? WHERE run_id=?", (commande, run_id))
        c.commit()
    finally:
        c.close()


def marquer_interrompu(run_id: str):
    c = _ecriture()
    try:
        c.execute("UPDATE lots SET statut='interrompu', commande=NULL WHERE run_id=?", (run_id,))
        c.commit()
    finally:
        c.close()


def supprimer_lot(run_id: str):
    c = _ecriture()
    try:
        c.execute("DELETE FROM test_runs WHERE run_id=?", (run_id,))
        c.execute("DELETE FROM lots WHERE run_id=?", (run_id,))
        c.commit()
    finally:
        c.close()


def age_battement(heartbeat) -> float | None:
    if not isinstance(heartbeat, str) or not heartbeat:
        return None
    try:
        return (datetime.now() - datetime.fromisoformat(heartbeat)).total_seconds()
    except ValueError:
        return None


def etat_vivant(statut: str, heartbeat) -> str:
    """'actif' | 'mort' (statut actif mais plus de battement) | 'inactif'."""
    if statut not in ACTIFS:
        return "inactif"
    age = age_battement(heartbeat)
    return "actif" if age is not None and age <= DELAI_MORT_S else "mort"


def fin_du_journal(run_id: str, lignes: int = 15) -> str:
    try:
        with open(chemin_journal(run_id), encoding="utf-8", errors="replace") as f:
            return "".join(f.readlines()[-lignes:])
    except OSError:
        return ""
