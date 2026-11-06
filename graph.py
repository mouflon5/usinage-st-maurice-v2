r"""
Graphe orchestrateur — A1 → A2 → A3 → A4 → A5 → A6 → A8 → (approbation) → A7.

    A1 acquisition ─ trou ─────────────────────────► arrêt A1
    A2 extraction ─ anomalie ──────────────────────► arrêt A2
    A3 réconciliation ─ À classer ─────────────────► A8 (relecture) → arbitrage humain
    A4 prévision ─ erreur ─────────────────────────► arrêt A4
    A5 écarts ─ erreur ────────────────────────────► arrêt A5
    A6 contrôle ─ bloquant ────────────────────────► BLOQUÉ (rien ne sort)
    A8 relecture (LLM) ─ réserves seulement ───────► jamais de blocage
    approbation humaine (optionnelle) ─ rejet ─────► rejet humain
    A7 reporting ──► succès | succès avec réserves

Le nom `builder` est exporté pour pouvoir compiler avec un checkpointer dans les tests
(l'interruption d'approbation exige un checkpointer ; Studio en fournit un).
"""

from langgraph.graph import StateGraph, END

from state import OrchestrateurState
from journal_run import journaliser_run_node
from nodes import (
    executer_a1_node, router_apres_a1,
    executer_a2_node, router_apres_a2,
    executer_a3_node, router_apres_a3,
    executer_a4_node, router_apres_a4,
    executer_a5_node, router_apres_a5,
    executer_a6_node, router_apres_a6, executer_a8_node, router_apres_a8,
    approbation_humaine_node, router_apres_approbation,
    executer_a7_node, router_apres_a7,
    finaliser_succes_node, finaliser_reserves_node, finaliser_arbitrage_node,
    finaliser_arret_a1_node, finaliser_arret_a2_node, finaliser_arret_a3_node,
    finaliser_arret_a4_node, finaliser_arret_a5_node, finaliser_bloque_a6_node,
    finaliser_rejet_humain_node, finaliser_arret_a7_node,
)

builder = StateGraph(OrchestrateurState)

for nom, fn in [
    ("executer_a1", executer_a1_node), ("executer_a2", executer_a2_node), ("executer_a3", executer_a3_node),
    ("executer_a4", executer_a4_node), ("executer_a5", executer_a5_node), ("executer_a6", executer_a6_node), ("executer_a8", executer_a8_node),
    ("approbation_humaine", approbation_humaine_node), ("executer_a7", executer_a7_node),
    ("finaliser_succes", finaliser_succes_node), ("finaliser_reserves", finaliser_reserves_node),
    ("finaliser_arbitrage", finaliser_arbitrage_node),
    ("finaliser_arret_a1", finaliser_arret_a1_node), ("finaliser_arret_a2", finaliser_arret_a2_node),
    ("finaliser_arret_a3", finaliser_arret_a3_node), ("finaliser_arret_a4", finaliser_arret_a4_node),
    ("finaliser_arret_a5", finaliser_arret_a5_node), ("finaliser_bloque_a6", finaliser_bloque_a6_node),
    ("finaliser_rejet_humain", finaliser_rejet_humain_node), ("finaliser_arret_a7", finaliser_arret_a7_node),
]:
    builder.add_node(nom, fn)
builder.add_node("journaliser_run", journaliser_run_node)

builder.set_entry_point("executer_a1")
builder.add_conditional_edges("executer_a1", router_apres_a1,
                              {"continuer": "executer_a2", "arreter": "finaliser_arret_a1"})
builder.add_conditional_edges("executer_a2", router_apres_a2,
                              {"complet": "executer_a3", "probleme": "finaliser_arret_a2"})
builder.add_conditional_edges("executer_a3", router_apres_a3,
                              {"complet": "executer_a4", "a_arbitrer": "executer_a8",
                               "probleme": "finaliser_arret_a3"})
builder.add_conditional_edges("executer_a4", router_apres_a4,
                              {"continuer": "executer_a5", "probleme": "finaliser_arret_a4"})
builder.add_conditional_edges("executer_a5", router_apres_a5,
                              {"continuer": "executer_a6", "probleme": "finaliser_arret_a5"})
builder.add_conditional_edges("executer_a6", router_apres_a6,
                              {"continuer": "executer_a8", "bloque": "finaliser_bloque_a6"})
# A8 passe aussi avant un arbitrage humain (A4–A6 n'ont pas tourné : pas de contrôles, mais les lignes classées et les
# doublons écartés sont relus) ; il ne change jamais la destination, seulement ce que l'humain lit.
builder.add_conditional_edges("executer_a8", router_apres_a8,
                              {"approbation": "approbation_humaine", "arbitrage": "finaliser_arbitrage"})
builder.add_conditional_edges("approbation_humaine", router_apres_approbation,
                              {"continuer": "executer_a7", "rejete": "finaliser_rejet_humain"})
builder.add_conditional_edges("executer_a7", router_apres_a7,
                              {"complet": "finaliser_succes", "reserves": "finaliser_reserves",
                               "probleme": "finaliser_arret_a7"})

for fin in ("finaliser_succes", "finaliser_reserves", "finaliser_arbitrage", "finaliser_arret_a1",
            "finaliser_arret_a2", "finaliser_arret_a3", "finaliser_arret_a4", "finaliser_arret_a5",
            "finaliser_bloque_a6", "finaliser_rejet_humain", "finaliser_arret_a7"):
    builder.add_edge(fin, "journaliser_run")
builder.add_edge("journaliser_run", END)

# Exposé à LangGraph Studio via langgraph.json ("orchestrateur": "./graph.py:graph")
graph = builder.compile()
