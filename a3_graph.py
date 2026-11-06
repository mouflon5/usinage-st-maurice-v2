"""Graphe de l'agent A3 — Réconciliation."""

from langgraph.graph import StateGraph, END

from a3_state import ReconciliationState
from a3_nodes import (
    detecter_doublons_node,
    router_apres_doublons,
    classer_regles_node,
    classer_residu_llm_node,
    charger_node,
    router_apres_chargement,
    marquer_complet_node,
    escalader_node,
)

builder = StateGraph(ReconciliationState)
builder.add_node("detecter_doublons", detecter_doublons_node)
builder.add_node("classer_regles", classer_regles_node)
builder.add_node("classer_residu_llm", classer_residu_llm_node)
builder.add_node("charger", charger_node)
builder.add_node("marquer_complet", marquer_complet_node)
builder.add_node("escalader", escalader_node)

builder.set_entry_point("detecter_doublons")
builder.add_conditional_edges(
    "detecter_doublons", router_apres_doublons,
    {"classer": "classer_regles", "erreur": END},
)
builder.add_edge("classer_regles", "classer_residu_llm")
builder.add_edge("classer_residu_llm", "charger")
builder.add_conditional_edges(
    "charger", router_apres_chargement,
    {"complet": "marquer_complet", "escalade": "escalader", "erreur": END},
)
builder.add_edge("marquer_complet", END)
builder.add_edge("escalader", END)

graph = builder.compile()
