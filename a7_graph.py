"""Graphe de l'agent A7 — Reporting."""

from langgraph.graph import StateGraph, END

from a7_state import ReportingState
from a7_nodes import (preparer_node, router_apres_preparation, rediger_node, construire_excel_node,
                      construire_r0_node, finaliser_node)

b = StateGraph(ReportingState)
b.add_node("preparer", preparer_node)
b.add_node("rediger", rediger_node)
b.add_node("construire_excel", construire_excel_node)
b.add_node("construire_r0", construire_r0_node)
b.add_node("finaliser", finaliser_node)
b.set_entry_point("preparer")
b.add_conditional_edges("preparer", router_apres_preparation, {"rediger": "rediger", "erreur": END})
b.add_edge("rediger", "construire_excel")
b.add_edge("construire_excel", "construire_r0")
b.add_edge("construire_r0", "finaliser")
b.add_edge("finaliser", END)
graph = b.compile()
