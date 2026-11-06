"""État de l'agent A5 — Analyse des écarts (réel vs budget vs prévision)."""

from typing import List, Optional
from typing_extensions import TypedDict, NotRequired


class EcartsState(TypedDict):
    db_path: str
    periode: str                          # "AAAA-MM"
    seuil_pct: NotRequired[float]         # défaut 0.10
    seuil_abs: NotRequired[float]         # défaut 25 000 $

    lignes: NotRequired[List[dict]]       # une par nature + flux net : reel, budget, prevu, écarts
    causes: NotRequired[dict]             # {ligne: {categories: [...], transactions: [...]}} (SQL)
    commentaire: NotRequired[dict]        # {resume, points, origine: "llm"|"simule"|"modele"}
    controle_commentaire: NotRequired[dict]
    alertes: NotRequired[List[str]]

    statut: NotRequired[str]              # "complet" | "degrade" | "erreur"
    message: NotRequired[Optional[str]]
