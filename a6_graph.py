"""Graphe de l'agent A6 — Contrôle."""

from langgraph.graph import StateGraph, END

from a6_state import ControleState
from a6_nodes import controler_node, router_verdict, approuver_node, approuver_reserves_node, bloquer_node

b = StateGraph(ControleState)
b.add_node("controler", controler_node)
b.add_node("approuver", approuver_node)
b.add_node("approuver_reserves", approuver_reserves_node)
b.add_node("bloquer", bloquer_node)
b.set_entry_point("controler")
b.add_conditional_edges("controler", router_verdict,
                        {"approuve": "approuver", "reserves": "approuver_reserves", "bloque": "bloquer"})
for n in ("approuver", "approuver_reserves", "bloquer"):
    b.add_edge(n, END)
graph = b.compile()
