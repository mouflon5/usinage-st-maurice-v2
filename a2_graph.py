"""Graphe de l'agent A2 — Extraction (copie intégrée à l'orchestrateur)."""

from langgraph.graph import StateGraph, END

from a2_state import ExtractionState
from a2_nodes import (
    extraire_node,
    valider_coherence_node,
    router_extraction,
    marquer_complet_node,
    signaler_probleme_node,
)

builder = StateGraph(ExtractionState)
builder.add_node("extraire", extraire_node)
builder.add_node("valider_coherence", valider_coherence_node)
builder.add_node("marquer_complet", marquer_complet_node)
builder.add_node("signaler_probleme", signaler_probleme_node)

builder.set_entry_point("extraire")
builder.add_edge("extraire", "valider_coherence")
builder.add_conditional_edges(
    "valider_coherence",
    router_extraction,
    {"complet": "marquer_complet", "probleme": "signaler_probleme"},
)
builder.add_edge("marquer_complet", END)
builder.add_edge("signaler_probleme", END)

graph = builder.compile()
