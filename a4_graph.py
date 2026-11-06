"""Graphe de l'agent A4 — Prévision."""

from langgraph.graph import StateGraph, END

from a4_state import ForecastState
from a4_nodes import (preparer_node, router_apres_preparation, prevoir_node, flux_net_node,
                      router_apres_prevision, marquer_complet_node, signaler_degrade_node,
                      signaler_erreur_node)

b = StateGraph(ForecastState)
b.add_node("preparer", preparer_node)
b.add_node("prevoir", prevoir_node)
b.add_node("flux_net", flux_net_node)
b.add_node("marquer_complet", marquer_complet_node)
b.add_node("signaler_degrade", signaler_degrade_node)
b.add_node("signaler_erreur", signaler_erreur_node)

b.set_entry_point("preparer")
b.add_conditional_edges("preparer", router_apres_preparation, {"prevoir": "prevoir", "erreur": END})
b.add_edge("prevoir", "flux_net")
b.add_conditional_edges("flux_net", router_apres_prevision,
                        {"complet": "marquer_complet", "degrade": "signaler_degrade", "erreur": "signaler_erreur"})
b.add_edge("marquer_complet", END)
b.add_edge("signaler_degrade", END)
b.add_edge("signaler_erreur", END)

graph = b.compile()
