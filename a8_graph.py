"""Graphe de l'agent A8 — Relecture : préparer → relire → valider → conclure (jamais de blocage)."""

from langgraph.graph import StateGraph, END

from a8_state import RelectureState
from a8_nodes import preparer_node, relire_node, valider_node, conclure_node

b = StateGraph(RelectureState)
b.add_node("preparer", preparer_node)
b.add_node("relire", relire_node)
b.add_node("valider", valider_node)
b.add_node("conclure", conclure_node)
b.set_entry_point("preparer")
b.add_edge("preparer", "relire")
b.add_edge("relire", "valider")
b.add_edge("valider", "conclure")
b.add_edge("conclure", END)
graph = b.compile()
