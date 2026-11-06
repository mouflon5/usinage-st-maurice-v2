"""État de l'agent A7 — Reporting (classeur miroir Excel + brouillon R0)."""

from typing import List, Optional
from typing_extensions import TypedDict, NotRequired


class ReportingState(TypedDict):
    periode: str
    dossier: dict                          # tout ce que les agents amont ont produit (voir orchestrateur)
    dossier_sortie: NotRequired[str]       # défaut : ./sorties/<periode>

    synthese: NotRequired[dict]            # {texte, origine}
    fichiers: NotRequired[List[str]]
    statut: NotRequired[str]               # "complet" | "erreur"
    message: NotRequired[Optional[str]]
