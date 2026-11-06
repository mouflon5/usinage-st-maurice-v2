"""Nœuds de l'agent A1 — Acquisition (copie intégrée à l'orchestrateur).

Conventions de nom de fichier acceptées (voir formats_releves.analyser_nom_fichier) :
    Compte_2026-05.pdf | Compte - 2026-05.pdf | Compte_202605.pdf | Compte_05-2026.pdf
Deux relevés pour la même période = ambigu → le pipeline s'arrête (jamais de fusion silencieuse).
"""

import os
from collections import Counter
from dateutil.relativedelta import relativedelta
from datetime import datetime

from a1_state import AcquisitionState
from classer_documents import analyser_document
from formats_releves import normaliser_compte


def _mois_entre(debut: str, fin: str) -> list[str]:
    d = datetime.strptime(debut, "%Y-%m")
    f = datetime.strptime(fin, "%Y-%m")
    mois = []
    courant = d
    while courant <= f:
        mois.append(courant.strftime("%Y-%m"))
        courant += relativedelta(months=1)
    return mois


def scan_node(state: AcquisitionState) -> dict:
    dossier = state["dossier_releves"]
    compte = normaliser_compte(state["compte"])

    if not os.path.isdir(dossier):
        return {"fichiers_trouves": [], "statut": "erreur", "message": f"Dossier introuvable : {dossier}"}

    fichiers_trouves = []
    for nom in sorted(os.listdir(dossier)):
        info = analyser_document(nom, state.get("db_path"))
        if info and normaliser_compte(info[0]) == compte:
            fichiers_trouves.append(os.path.join(dossier, nom))

    return {"fichiers_trouves": fichiers_trouves}


def analyse_couverture_node(state: AcquisitionState) -> dict:
    periodes_attendues = _mois_entre(state["periode_debut"], state["periode_fin"])

    periodes_couvertes = []
    for chemin in state["fichiers_trouves"]:
        info = analyser_document(os.path.basename(chemin), state.get("db_path"))
        if info:
            periodes_couvertes.append(info[1])

    trous = [p for p in periodes_attendues if p not in periodes_couvertes]
    doubles = sorted(p for p, n in Counter(periodes_couvertes).items() if n > 1)

    return {
        "periodes_attendues": periodes_attendues,
        "periodes_couvertes": sorted(set(periodes_couvertes)),
        "trous_detectes": trous,
        "periodes_en_double": doubles,
    }


def router_completude(state: AcquisitionState) -> str:
    if state.get("statut") == "erreur":
        return "erreur"
    return "incomplet" if (state["trous_detectes"] or state.get("periodes_en_double")) else "complet"


def marquer_complet_node(state: AcquisitionState) -> dict:
    return {
        "statut": "complet",
        "message": (
            f"Compte {state['compte']} : {len(state['periodes_couvertes'])} période(s) "
            f"couverte(s), aucun trou détecté. Prêt pour A2 (Extraction)."
        ),
    }


def signaler_trou_node(state: AcquisitionState) -> dict:
    parts = []
    if state["trous_detectes"]:
        parts.append(f"trou(s) détecté(s) sur {', '.join(state['trous_detectes'])}")
    if state.get("periodes_en_double"):
        parts.append(f"plusieurs relevés pour {', '.join(state['periodes_en_double'])}")
    return {
        "statut": "incomplet",
        "message": f"Compte {state['compte']} : {' ; '.join(parts)}. Ne pas transmettre à A2 tant que non résolu.",
    }
