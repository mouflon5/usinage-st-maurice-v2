"""État de l'agent A6 — Contrôle (seul agent autorisé à valider avant toute sortie vers un humain)."""

from typing import List, Optional
from typing_extensions import TypedDict, NotRequired


class ControleState(TypedDict):
    db_path: str
    periode: str
    transactions: NotRequired[List[dict]]     # sortie d'A2
    resume_a3: NotRequired[dict]
    previsions: NotRequired[dict]             # sortie d'A4
    ecarts: NotRequired[List[dict]]           # lignes d'A5
    commentaire: NotRequired[dict]            # commentaire d'A5
    causes_a5: NotRequired[dict]              # causes calculées par A5 (sources légitimes du commentaire)
    alertes_amont: NotRequired[List[str]]     # alertes d'A4/A5

    controles: NotRequired[List[dict]]        # {id, libelle, gravite, ok, detail}
    verdict: NotRequired[str]                 # "approuve" | "reserves" | "bloque"
    empreinte: NotRequired[str]               # sha256 des chiffres contrôlés
    statut: NotRequired[str]
    message: NotRequired[Optional[str]]
