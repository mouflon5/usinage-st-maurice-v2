"""Graphe de l'agent A5 — Analyse des écarts."""

from langgraph.graph import StateGraph, END

from a5_state import EcartsState
from a5_nodes import (preparer_node, router_apres_preparation, calculer_ecarts_node, analyser_causes_node,
                      commenter_node, verifier_commentaire_node, router_conclusion,
                      marquer_complet_node, signaler_degrade_node)

b = StateGraph(EcartsState)
b.add_node("preparer", preparer_node)
b.add_node("calculer_ecarts", calculer_ecarts_node)
b.add_node("analyser_causes", analyser_causes_node)
b.add_node("commenter", commenter_node)
b.add_node("verifier_commentaire", verifier_commentaire_node)
b.add_node("marquer_complet", marquer_complet_node)
b.add_node("signaler_degrade", signaler_degrade_node)

b.set_entry_point("preparer")
b.add_conditional_edges("preparer", router_apres_preparation, {"calculer": "calculer_ecarts", "erreur": END})
b.add_edge("calculer_ecarts", "analyser_causes")
b.add_edge("analyser_causes", "commenter")
b.add_edge("commenter", "verifier_commentaire")
b.add_conditional_edges("verifier_commentaire", router_conclusion,
                        {"complet": "marquer_complet", "degrade": "signaler_degrade"})
b.add_edge("marquer_complet", END)
b.add_edge("signaler_degrade", END)

graph = b.compile()
