"""Graphe de l'agent A1 — Acquisition (copie intégrée à l'orchestrateur)."""

from langgraph.graph import StateGraph, END

from a1_state import AcquisitionState
from a1_nodes import (
    scan_node,
    analyse_couverture_node,
    router_completude,
    marquer_complet_node,
    signaler_trou_node,
)

builder = StateGraph(AcquisitionState)
builder.add_node("scan", scan_node)
builder.add_node("analyse_couverture", analyse_couverture_node)
builder.add_node("marquer_complet", marquer_complet_node)
builder.add_node("signaler_trou", signaler_trou_node)

builder.set_entry_point("scan")
builder.add_edge("scan", "analyse_couverture")
builder.add_conditional_edges(
    "analyse_couverture",
    router_completude,
    {"complet": "marquer_complet", "incomplet": "signaler_trou", "erreur": END},
)
builder.add_edge("marquer_complet", END)
builder.add_edge("signaler_trou", END)

graph = builder.compile()
