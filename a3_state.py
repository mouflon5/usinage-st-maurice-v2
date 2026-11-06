"""État de l'agent A3 — Réconciliation (classement + chargement dans tresorerie.db)."""

from typing import List, Optional
from typing_extensions import TypedDict, NotRequired


class ReconciliationState(TypedDict):
    # --- Entrées ---
    transactions: List[dict]      # sortie d'A2 : fichier, date, description, montant, solde
    compte: str                   # ex. "Desjardins EOP"
    db_path: str                  # chemin vers tresorerie.db (ou la copie de démo)

    # --- Étapes intermédiaires ---
    transactions_nouvelles: NotRequired[List[dict]]
    doublons: NotRequired[List[dict]]
    classees: NotRequired[List[dict]]    # + categorie, nature, methode, confiance
    residu: NotRequired[List[dict]]      # « À classer » : suggestion, confiance, justification
    erreurs_llm: NotRequired[List[str]]
    mode_llm: NotRequired[str]           # "reel" | "simule"

    # --- Résultat ---
    resume_chargement: NotRequired[dict]
    statut: NotRequired[str]             # "complet" | "a_arbitrer" | "erreur"
    message: NotRequired[Optional[str]]
