"""
Nœuds de l'orchestrateur.

Le patron utilisé ici est « graphe comme nœud » : chaque agent (A1 à A4) est
un graphe LangGraph déjà compilé et validé indépendamment. L'orchestrateur
ne réimplémente rien de leur logique — il les appelle via .invoke(), en
adaptant l'état de l'un à l'entrée attendue par l'autre.
"""

from a1_graph import graph as agent_a1_graph
from a2_graph import graph as agent_a2_graph
from a3_graph import graph as agent_a3_graph
from a4_graph import graph as agent_a4_graph
from a5_graph import graph as agent_a5_graph
from a6_graph import graph as agent_a6_graph
from a7_graph import graph as agent_a7_graph
from a8_graph import graph as agent_a8_graph
from langgraph.types import interrupt
from db_outils import resoudre_db
from classer_documents import classer_dossier
import gouvernance_pont
from state import OrchestrateurState


def executer_a1_node(state: OrchestrateurState) -> dict:
    db = resoudre_db(state.get("db_path"))
    # Les documents que la convention de nom ne reconnaît pas sont classés par le LLM (et leur compte créé au besoin).
    classement = classer_dossier(state["dossier_releves"], db)
    entree_a1 = {
        "compte": state["compte"],
        "dossier_releves": state["dossier_releves"],
        "periode_debut": state["periode_debut"],
        "periode_fin": state["periode_fin"],
        "db_path": db,
    }
    run_id = gouvernance_pont.demarrer(db, {"compte": state["compte"], "periode_debut": state["periode_debut"],
                                            "periode_fin": state["periode_fin"]})
    resultat = agent_a1_graph.invoke(entree_a1)
    fichiers = resultat.get("fichiers_trouves", [])
    return {
        "statut_a1": resultat["statut"],
        "message_a1": resultat.get("message"),
        "fichiers_trouves": fichiers,
        "classement_documents": classement,
        "gouv_run_id": run_id,
        "gouv_fichiers": gouvernance_pont.enregistrer_fichiers(db, run_id, fichiers),
    }


def router_apres_a1(state: OrchestrateurState) -> str:
    return "continuer" if state.get("statut_a1") == "complet" else "arreter"


def executer_a2_node(state: OrchestrateurState) -> dict:
    entree_a2 = {"fichiers_a_traiter": state.get("fichiers_trouves", []),
                 "db_path": resoudre_db(state.get("db_path"))}
    resultat = agent_a2_graph.invoke(entree_a2)
    resume = None
    if resultat["statut"] == "complet":   # rien n'est chargé tant qu'A2 signale une anomalie
        resume = gouvernance_pont.charger_extraction(
            resoudre_db(state.get("db_path")), state.get("gouv_run_id"), state["compte"],
            resultat.get("transactions", []), state.get("gouv_fichiers"))
    return {
        "statut_a2": resultat["statut"],
        "message_a2": resultat.get("message"),
        "transactions": resultat.get("transactions", []),
        "gouv_chargement": resume or {},
    }


def router_apres_a2(state: OrchestrateurState) -> str:
    return "complet" if state.get("statut_a2") == "complet" else "probleme"


def executer_a3_node(state: OrchestrateurState) -> dict:
    entree_a3 = {
        "transactions": state.get("transactions", []),
        "compte": state["compte"],
        "db_path": resoudre_db(state.get("db_path")),
    }
    resultat = agent_a3_graph.invoke(entree_a3)
    return {
        "statut_a3": resultat.get("statut", "erreur"),
        "message_a3": resultat.get("message"),
        "resume_a3": resultat.get("resume_chargement", {}),
        "residu_a3": resultat.get("residu", []),
        "mode_llm": resultat.get("mode_llm", ""),
        "classees_a3": resultat.get("classees", []),
        "doublons_a3": resultat.get("doublons", []),
    }


def router_apres_a3(state: OrchestrateurState) -> str:
    # A3 « a_arbitrer » : on ne prévoit pas sur un grand livre incomplet → arbitrage humain d'abord.
    return {"complet": "complet", "a_arbitrer": "a_arbitrer"}.get(state.get("statut_a3"), "probleme")


def executer_a4_node(state: OrchestrateurState) -> dict:
    resultat = agent_a4_graph.invoke({"db_path": resoudre_db(state.get("db_path"))})
    return {
        "statut_a4": resultat.get("statut", "erreur"),
        "message_a4": resultat.get("message"),
        "previsions": resultat.get("previsions", {}),
        "flux_net_prevu": resultat.get("flux_net", {}),
        "alertes_a4": resultat.get("alertes", []),
    }


def router_apres_a4(state: OrchestrateurState) -> str:
    # Une prévision dégradée (repli naïf) n'empêche pas A5 : elle sera signalée dans le statut final.
    return "continuer" if state.get("statut_a4") in ("complet", "degrade") else "probleme"


def executer_a5_node(state: OrchestrateurState) -> dict:
    resultat = agent_a5_graph.invoke({
        "db_path": resoudre_db(state.get("db_path")),
        "periode": state["periode_fin"],
    })
    return {
        "statut_a5": resultat.get("statut", "erreur"),
        "message_a5": resultat.get("message"),
        "ecarts_a5": resultat.get("lignes", []),
        "commentaire_a5": resultat.get("commentaire", {}),
        "alertes_a5": resultat.get("alertes", []),
        "causes_a5": resultat.get("causes", {}),
    }


def router_apres_a5(state: OrchestrateurState) -> str:
    return "continuer" if state.get("statut_a5") in ("complet", "degrade") else "probleme"


def _alertes_amont(state: OrchestrateurState) -> list:
    out = []
    if state.get("statut_a4") == "degrade":
        out.append(f"A4 : {state.get('message_a4')}")
    if state.get("statut_a5") == "degrade":
        out.extend(state.get("alertes_a5", []))
    for c in state.get("constats_a8", []):          # A8 ne peut qu'ajouter des réserves (jamais bloquer)
        if c.get("gravite") == "reserve":
            out.append(f"A8 ({c.get('ref')}) : {c.get('texte')}")
    return out


def executer_a6_node(state: OrchestrateurState) -> dict:
    resultat = agent_a6_graph.invoke({
        "db_path": resoudre_db(state.get("db_path")),
        "periode": state["periode_fin"],
        "transactions": state.get("transactions", []),
        "resume_a3": state.get("resume_a3", {}),
        "previsions": state.get("previsions", {}),
        "ecarts": state.get("ecarts_a5", []),
        "commentaire": state.get("commentaire_a5", {}),
        "causes_a5": state.get("causes_a5", {}),
        "alertes_amont": _alertes_amont(state),
    })
    return {
        "statut_a6": resultat.get("statut", "bloque"),
        "message_a6": resultat.get("message"),
        "controles_a6": resultat.get("controles", []),
        "empreinte_a6": resultat.get("empreinte", ""),
    }


def router_apres_a6(state: OrchestrateurState) -> str:
    return "bloque" if state.get("statut_a6") not in ("approuve", "reserves") else "continuer"


def router_apres_a8(state: OrchestrateurState) -> str:
    return "arbitrage" if state.get("statut_a3") == "a_arbitrer" else "approbation"


def executer_a8_node(state: OrchestrateurState) -> dict:
    """Relecture qualitative (LLM en mode réel, règles en mode simulé). N'est exécutée que si A6 a laissé passer.
    Son résultat n'alimente que les réserves : aucun routeur ne peut s'arrêter sur A8."""
    resultat = agent_a8_graph.invoke({
        "db_path": resoudre_db(state.get("db_path")), "compte": state["compte"], "periode": state["periode_fin"],
        "transactions": state.get("transactions", []), "classees": state.get("classees_a3", []),
        "residu": state.get("residu_a3", []), "doublons": state.get("doublons_a3", []),
        "resume_a3": state.get("resume_a3", {}), "ecarts": state.get("ecarts_a5", []),
        "commentaire": state.get("commentaire_a5", {}), "causes_a5": state.get("causes_a5", {}),
        "controles": state.get("controles_a6", []), "alertes_amont": _alertes_amont(state),
    })
    return {
        "statut_a8": resultat.get("statut", "indisponible"), "message_a8": resultat.get("message"),
        "origine_a8": resultat.get("origine", "indisponible"), "constats_a8": resultat.get("constats", []),
        "constats_rejetes_a8": resultat.get("constats_rejetes", []), "notes_a8": resultat.get("notes", {}),
    }


def approbation_humaine_node(state: OrchestrateurState) -> dict:
    """A6 est la seule porte vers un humain. Si approbation_humaine=True, le graphe s'interrompt ici
    (Studio affiche le dossier ; reprendre avec {"decision": "approuver"|"rejeter", "commentaire": "..."})."""
    if not state.get("approbation_humaine"):
        return {"decision_humaine": {"decision": "approuver", "commentaire": "approbation automatique (mode démo)"}}
    reponse = interrupt({
        "demande": "Approbation requise avant production du rapport",
        "verdict_a6": state.get("statut_a6"),
        "message_a6": state.get("message_a6"),
        "relecture_a8": {"statut": state.get("statut_a8"), "constats": state.get("constats_a8", [])},
        "empreinte": state.get("empreinte_a6"),
        "ecarts": [{k: l.get(k) for k in ("libelle", "reel", "budget", "prevu", "jugement_budget", "jugement_prevision")}
                   for l in state.get("ecarts_a5", [])],
        "commentaire": state.get("commentaire_a5", {}),
    })
    if isinstance(reponse, str):
        reponse = {"decision": reponse, "commentaire": ""}
    return {"decision_humaine": reponse}


def router_apres_approbation(state: OrchestrateurState) -> str:
    return "continuer" if state.get("decision_humaine", {}).get("decision") == "approuver" else "rejete"


def executer_a7_node(state: OrchestrateurState) -> dict:
    dossier = {
        "verdict": state.get("statut_a6"), "empreinte": state.get("empreinte_a6"),
        "controles": state.get("controles_a6", []), "ecarts": state.get("ecarts_a5", []),
        "commentaire": state.get("commentaire_a5", {}), "previsions": state.get("previsions", {}),
        "flux_net_prevu": state.get("flux_net_prevu", {}), "resume_a3": state.get("resume_a3", {}),
        "transactions": state.get("transactions", []), "mode_llm": state.get("mode_llm"),
        "decision_humaine": state.get("decision_humaine", {}),
        "db_path": resoudre_db(state.get("db_path")),                 # pour la balance de vérification du journal
        "alertes": _alertes_amont(state),
        "statut_pipeline": "complet_avec_reserves" if (state.get("statut_a6") == "reserves" or _alertes_amont(state)) else "complet",
    }
    resultat = agent_a7_graph.invoke({"periode": state["periode_fin"], "dossier": dossier})
    return {"statut_a7": resultat.get("statut", "erreur"), "message_a7": resultat.get("message"),
            "fichiers_a7": resultat.get("fichiers", [])}


def router_apres_a7(state: OrchestrateurState) -> str:
    if state.get("statut_a7") != "complet":
        return "probleme"
    return "reserves" if (state.get("statut_a6") == "reserves" or _alertes_amont(state)) else "complet"


def _reserves_a8_texte(state: OrchestrateurState) -> str:
    res = [c for c in state.get("constats_a8", []) if c.get("gravite") == "reserve"]
    return (f" Relecture A8 : {len(res)} réserve(s) — " + " | ".join(f"{c['ref']} {c['texte']}" for c in res[:5])) if res else ""


def finaliser_succes_node(state: OrchestrateurState) -> dict:
    return {
        "statut_pipeline": "complet",
        "message_pipeline": f"Pipeline A1→A7 réussi. {state.get('message_a3')} {state.get('message_a4')} {state.get('message_a5')} {state.get('message_a6')} {state.get('message_a7')}",
    }


def finaliser_reserves_node(state: OrchestrateurState) -> dict:
    return {
        "statut_pipeline": "complet_avec_reserves",
        "message_pipeline": f"Pipeline terminé avec réserves. A4 : {state.get('message_a4')} A5 : {state.get('message_a5')} A6 : {state.get('message_a6')} A7 : {state.get('message_a7')}",
    }


def finaliser_arret_a5_node(state: OrchestrateurState) -> dict:
    return {
        "statut_pipeline": "arrete_a5",
        "message_pipeline": f"Arrêté après A5 : {state.get('message_a5')}",
    }


def finaliser_arret_a4_node(state: OrchestrateurState) -> dict:
    return {
        "statut_pipeline": "arrete_a4",
        "message_pipeline": f"Arrêté après A4 : {state.get('message_a4')}",
    }


def finaliser_arbitrage_node(state: OrchestrateurState) -> dict:
    return {
        "statut_pipeline": "a_arbitrer",
        "message_pipeline": f"Pipeline terminé, arbitrage humain requis. {state.get('message_a3')}" + _reserves_a8_texte(state),
    }


def finaliser_arret_a3_node(state: OrchestrateurState) -> dict:
    return {
        "statut_pipeline": "arrete_a3",
        "message_pipeline": f"Arrêté après A3 : {state.get('message_a3')}",
    }


def finaliser_arret_a1_node(state: OrchestrateurState) -> dict:
    return {
        "statut_pipeline": "arrete_a1",
        "message_pipeline": f"Arrêté après A1 : {state.get('message_a1')}",
    }


def finaliser_arret_a2_node(state: OrchestrateurState) -> dict:
    return {
        "statut_pipeline": "arrete_a2",
        "message_pipeline": f"Arrêté après A2 : {state.get('message_a2')}",
    }


def finaliser_bloque_a6_node(state: OrchestrateurState) -> dict:
    return {"statut_pipeline": "bloque_a6", "message_pipeline": f"{state.get('message_a6')}"}


def finaliser_rejet_humain_node(state: OrchestrateurState) -> dict:
    h = state.get("decision_humaine", {})
    return {"statut_pipeline": "rejete_humain", "message_pipeline": f"Rejeté par l'humain : {h.get('commentaire', '')}"}


def finaliser_arret_a7_node(state: OrchestrateurState) -> dict:
    return {"statut_pipeline": "arrete_a7", "message_pipeline": f"Arrêté après A7 : {state.get('message_a7')}"}
