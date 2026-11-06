"""Journal des exécutions : chaque passage du pipeline laisse une trace JSON lisible par le tableau de bord.

    sorties/dernier_run.json  (dossier TRACES_DIR, « sorties » par défaut)       dernier passage (complet)
    sorties/runs/<horodatage>.json tous les passages
    sorties/historique_runs.jsonl  une ligne de résumé par passage
"""
import json
import os
from datetime import datetime

AGENTS = [("A1", "Acquisition", "statut_a1", "message_a1"), ("A2", "Extraction", "statut_a2", "message_a2"),
          ("A3", "Réconciliation", "statut_a3", "message_a3"), ("A4", "Prévision", "statut_a4", "message_a4"),
          ("A5", "Écarts", "statut_a5", "message_a5"), ("A6", "Contrôle", "statut_a6", "message_a6"), ("A8", "Relecture", "statut_a8", "message_a8"),
          ("A7", "Reporting", "statut_a7", "message_a7")]


def construire(state: dict) -> dict:
    agents = [{"id": i, "nom": n, "statut": state.get(s), "message": state.get(m)} for i, n, s, m in AGENTS]
    return {
        "horodatage": datetime.now().isoformat(timespec="seconds"),
        "compte": state.get("compte"), "periode": state.get("periode_fin"),
        "periode_debut": state.get("periode_debut"), "db_path": state.get("db_path"),
        "statut_pipeline": state.get("statut_pipeline"), "message_pipeline": state.get("message_pipeline"),
        "mode_llm": state.get("mode_llm"), "agents": agents,
        "transactions": (state.get("transactions") or [])[:300],
        "resume_a3": state.get("resume_a3", {}), "residu_a3": state.get("residu_a3", []),
        "previsions": state.get("previsions", {}), "flux_net_prevu": state.get("flux_net_prevu", {}),
        "ecarts": state.get("ecarts_a5", []), "commentaire": state.get("commentaire_a5", {}),
        "controles": state.get("controles_a6", []),
        "relecture": {"origine": state.get("origine_a8"), "notes": state.get("notes_a8", {}),
                      "constats": state.get("constats_a8", []), "rejetes": state.get("constats_rejetes_a8", [])}, "empreinte": state.get("empreinte_a6"),
        "alertes": (state.get("alertes_a4") or []) + (state.get("alertes_a5") or []),
        "decision_humaine": state.get("decision_humaine", {}), "fichiers": state.get("fichiers_a7", []),
    }


def journaliser_run_node(state: dict) -> dict:
    """Dernier nœud du graphe : ne modifie pas l'état, n'échoue jamais (le journal est accessoire)."""
    try:
        from db_outils import resoudre_db
        import gouvernance_pont
        dq = gouvernance_pont.terminer(resoudre_db(state.get("db_path")), state.get("gouv_run_id"),
                                       state.get("statut_pipeline"))
        run = construire(state)
        run["gouvernance"] = {"run_id": state.get("gouv_run_id"), "chargement": state.get("gouv_chargement", {}),
                              "qualite": ({k: dq[k] for k in ("execution_id", "score_global", "nb_regles",
                                                              "nb_echecs", "nb_bloquants_echec")} if dq else {})}
        racine = os.getenv("TRACES_DIR", "sorties")   # traces lues par l'onglet Agents (distinct des rapports A7)
        os.makedirs(os.path.join(racine, "runs"), exist_ok=True)
        ident = datetime.now().strftime("%Y%m%dT%H%M%S%f")
        run["id"] = ident
        txt = json.dumps(run, ensure_ascii=False, indent=1, default=str)
        for chemin in (os.path.join(racine, "dernier_run.json"), os.path.join(racine, "runs", f"{ident}.json")):
            with open(chemin, "w", encoding="utf-8") as f:
                f.write(txt)
        resume = {k: run[k] for k in ("id", "horodatage", "compte", "periode", "statut_pipeline", "message_pipeline")}
        with open(os.path.join(racine, "historique_runs.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(resume, ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass
    return {}
