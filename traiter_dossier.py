"""
Traite automatiquement un dossier de documents, quel que soit le nombre de comptes.

    python traiter_dossier.py --dossier "C:\\chemin\\vers\\les\\releves"
    python traiter_dossier.py --dossier releves_demo --db tresorerie_demo.db --approbation

Étapes :
  1. Le LLM classe les documents que la convention de nom ne reconnaît pas (relevé ou non, compte, mois).
     Les comptes inconnus sont créés dans mdm_compte ; les autres sont réutilisés.
  2. Les documents sont regroupés par compte. Chaque compte passe dans le pipeline A1 → A7 avec la période
     couverte par ses documents (les mois manquants sont signalés par A1, jamais comblés).
  3. Un résumé indique ce qui a été classé, refusé, et ce qui reste à arbitrer.

Sans LLM configuré (LLM_FOURNISSEUR = simule), les documents non reconnus ne sont pas classés : ils sont
signalés. Pour un classement réel, configurer Claude (ANTHROPIC_API_KEY) ou Ollama dans l'interface.
"""

import argparse
import os
import sys

from classer_documents import analyser_document, classer_dossier
from db_outils import resoudre_db
from formats_releves import EXTENSIONS


def regrouper_par_compte(dossier: str, db: str) -> dict:
    """{compte: {"periodes": [AAAA-MM, ...], "fichiers": [nom, ...]}} pour les documents reconnus."""
    comptes: dict = {}
    for nom in sorted(os.listdir(dossier)):
        if os.path.splitext(nom)[1].lower() not in EXTENSIONS:
            continue
        info = analyser_document(nom, db)
        if not info:
            continue
        entree = comptes.setdefault(info[0], {"periodes": [], "fichiers": []})
        entree["periodes"].append(info[1])
        entree["fichiers"].append(nom)
    return comptes


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dossier", required=True, help="dossier contenant les relevés et autres documents")
    ap.add_argument("--db", default=None, help="base SQLite (défaut : TRESORERIE_DB ou tresorerie_demo.db)")
    ap.add_argument("--approbation", action="store_true", help="arrêter avant le rapport pour une approbation humaine")
    a = ap.parse_args()

    if not os.path.isdir(a.dossier):
        sys.exit(f"Dossier introuvable : {a.dossier}")
    db = resoudre_db(a.db)
    if not os.path.isfile(db):
        sys.exit(f"Base introuvable : {db}")

    # Import tardif : la chaîne d'agents charge pandas, pdfplumber et LangGraph.
    from graph import builder
    from langgraph.checkpoint.memory import MemorySaver

    print(f"1. Classement des documents non reconnus ({a.dossier})")
    classement = classer_dossier(a.dossier, db)
    for c in classement["classes"]:
        print(f"   + {c['fichier']} → compte « {c['compte']} », {c['periode']}")
    for r in classement["refuses"]:
        print(f"   - {r['fichier']} : {r['raison']}")
    if classement["sans_llm"]:
        print("   ! LLM non configuré : les documents non reconnus n'ont pas été classés (fournisseur « simulé »).")

    comptes = regrouper_par_compte(a.dossier, db)
    print(f"\n2. {len(comptes)} compte(s) à traiter")
    if not comptes:
        print("   Aucun document reconnu : rien à traiter.")
        return

    graphe = builder.compile(checkpointer=MemorySaver()) if a.approbation else builder.compile()
    bilan = {}
    for compte, info in comptes.items():
        periodes = sorted(set(info["periodes"]))
        print(f"\n   Compte « {compte} » : {len(info['fichiers'])} document(s), {periodes[0]} → {periodes[-1]}")
        config = {"configurable": {"thread_id": compte}}
        final = graphe.invoke({
            "compte": compte,
            "dossier_releves": a.dossier,
            "periode_debut": periodes[0],
            "periode_fin": periodes[-1],
            "db_path": db,
            "approbation_humaine": a.approbation,
        }, config=config)
        bilan[compte] = final.get("statut_pipeline") or final.get("statut_a1") or "inconnu"
        print(f"   → {bilan[compte]} : {final.get('message_pipeline') or final.get('message_a1') or ''}")

    print("\n3. Bilan")
    for compte, statut in bilan.items():
        print(f"   {compte} : {statut}")
    print(f"   Documents classés par le LLM : {len(classement['classes'])} ; refusés : {len(classement['refuses'])}")


if __name__ == "__main__":
    main()
