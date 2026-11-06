"""État de l'agent A1 — Acquisition (copie intégrée à l'orchestrateur)."""

from typing import List, Optional
from typing_extensions import TypedDict, NotRequired


class AcquisitionState(TypedDict):
    compte: str
    dossier_releves: str
    periode_debut: str
    periode_fin: str
    db_path: NotRequired[str]   # base où sont classés les documents que la convention de nom ne reconnaît pas

    fichiers_trouves: NotRequired[List[str]]
    periodes_couvertes: NotRequired[List[str]]
    periodes_attendues: NotRequired[List[str]]
    trous_detectes: NotRequired[List[str]]
    periodes_en_double: NotRequired[List[str]]

    statut: NotRequired[str]
    message: NotRequired[Optional[str]]
