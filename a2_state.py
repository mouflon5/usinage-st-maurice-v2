"""État de l'agent A2 — Extraction (copie intégrée à l'orchestrateur)."""

from typing import List, Optional
from typing_extensions import TypedDict, NotRequired


class ExtractionState(TypedDict):
    fichiers_a_traiter: List[str]
    db_path: NotRequired[str]   # pour retrouver le compte et le mois des documents classés par le LLM

    transactions: NotRequired[List[dict]]
    lignes_rejetees: NotRequired[List[dict]]
    fichiers_echec: NotRequired[List[str]]
    anomalies_solde: NotRequired[List[dict]]
    anomalies_structure: NotRequired[List[dict]]   # période, compte, soldes d'ouverture/clôture, format inconnu
    formats_detectes: NotRequired[dict]

    statut: NotRequired[str]
    message: NotRequired[Optional[str]]
