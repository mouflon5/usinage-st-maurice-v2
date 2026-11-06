"""État de l'agent A4 — Prévision (SARIMAX sur l'historique mensuel de journal_general)."""

from typing import List, Optional
from typing_extensions import TypedDict, NotRequired


class ForecastState(TypedDict):
    db_path: str
    series: NotRequired[List[str]]        # défaut : ["Revenu", "Decaissements"]
    horizon: NotRequired[int]             # mois, 3 à 12 (défaut 6)

    previsions: NotRequired[dict]         # {serie: {periodes, valeurs, ci80_*, ci95_*, backtest, diagnostics, methode}}
    flux_net: NotRequired[dict]           # {periodes, valeurs} = revenus - décaissements (calcul déterministe)
    alertes: NotRequired[List[str]]
    series_en_echec: NotRequired[List[str]]

    statut: NotRequired[str]              # "complet" | "degrade" | "erreur"
    message: NotRequired[Optional[str]]
