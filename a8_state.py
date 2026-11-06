"""État de l'agent A8 — Relecture (second avis qualitatif ; ne peut qu'ajouter des réserves)."""

from typing import List, Optional
from typing_extensions import TypedDict, NotRequired


class RelectureState(TypedDict):
    db_path: str
    compte: str
    periode: str
    transactions: NotRequired[List[dict]]
    classees: NotRequired[List[dict]]         # lignes classées par A3 (règle / LLM)
    residu: NotRequired[List[dict]]
    doublons: NotRequired[List[dict]]         # lignes écartées par A3 (+ origine : base | releve)
    resume_a3: NotRequired[dict]
    ecarts: NotRequired[List[dict]]
    commentaire: NotRequired[dict]
    causes_a5: NotRequired[dict]
    controles: NotRequired[List[dict]]        # contrôles déterministes d'A6
    alertes_amont: NotRequired[List[str]]

    # --- étapes ---
    lignes_revue: NotRequired[List[dict]]
    doublons_revue: NotRequired[List[dict]]
    contexte: NotRequired[str]
    refs_valides: NotRequired[List[str]]
    avis_brut: NotRequired[dict]
    jetons: NotRequired[dict]

    # --- résultat ---
    origine: NotRequired[str]                 # "simule" | "llm" | "indisponible"
    constats: NotRequired[List[dict]]         # {ref, theme, gravite, texte}
    constats_rejetes: NotRequired[List[dict]] # avis du LLM écartés par les garde-fous (avec la raison)
    notes: NotRequired[dict]                  # {classement, doublons, commentaire, coherence} de 1 à 5
    statut: NotRequired[str]                  # "ok" | "reserves" | "indisponible"
    message: NotRequired[Optional[str]]
