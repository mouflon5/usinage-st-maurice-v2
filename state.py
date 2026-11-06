"""
État de l'orchestrateur A1 → A2 → A3 → A4 → A5 → A6 → A7.

Ce state ne remplace pas ceux d'A1/A2 — il les enveloppe. Chaque agent garde
sa propre logique interne ; l'orchestrateur ne fait que décider s'il faut
appeler A2 après A1, selon le statut retourné par A1.
"""

from typing import List, Optional
from typing_extensions import TypedDict, NotRequired


class OrchestrateurState(TypedDict):
    # --- Entrées pour A1 ---
    compte: str
    dossier_releves: str
    periode_debut: str
    periode_fin: str
    db_path: NotRequired[str]   # base SQLite ; défaut : TRESORERIE_DB ou tresorerie_demo.db

    # --- Résultat d'A1 ---
    statut_a1: NotRequired[str]
    message_a1: NotRequired[Optional[str]]
    fichiers_trouves: NotRequired[List[str]]
    classement_documents: NotRequired[dict]     # documents classés par le LLM : {classes, refuses, sans_llm, ...}

    # --- Résultat d'A2 ---
    statut_a2: NotRequired[str]
    message_a2: NotRequired[Optional[str]]
    transactions: NotRequired[List[dict]]

    # --- Gouvernance des données (facultatif : inactif si tresorerie_gouvernance/init_db.py n'a pas été exécuté) ---
    gouv_run_id: NotRequired[Optional[str]]
    gouv_fichiers: NotRequired[dict]            # nom de fichier -> fichier_id (meta_fichier_source)
    gouv_chargement: NotRequired[dict]          # {"stg", "insere", "doublon", "rejete"}
    gouv_qualite: NotRequired[dict]             # résumé du dernier contrôle qualité

    # --- Résultat d'A3 ---
    statut_a3: NotRequired[str]                 # "complet" | "a_arbitrer" | "erreur"
    message_a3: NotRequired[Optional[str]]
    resume_a3: NotRequired[dict]
    residu_a3: NotRequired[List[dict]]
    mode_llm: NotRequired[str]

    # --- Résultat d'A4 ---
    statut_a4: NotRequired[str]                 # "complet" | "degrade" | "erreur"
    message_a4: NotRequired[Optional[str]]
    previsions: NotRequired[dict]
    flux_net_prevu: NotRequired[dict]
    alertes_a4: NotRequired[List[str]]

    # --- Résultat d'A5 ---
    statut_a5: NotRequired[str]                 # "complet" | "degrade" | "erreur"
    message_a5: NotRequired[Optional[str]]
    ecarts_a5: NotRequired[List[dict]]
    commentaire_a5: NotRequired[dict]
    alertes_a5: NotRequired[List[str]]

    # --- Résultat d'A6 (contrôle) et décision humaine ---
    approbation_humaine: NotRequired[bool]      # True : le pipeline s'arrête pour une approbation dans Studio
    causes_a5: NotRequired[dict]
    statut_a6: NotRequired[str]                 # "approuve" | "reserves" | "bloque"
    message_a6: NotRequired[Optional[str]]
    controles_a6: NotRequired[List[dict]]
    empreinte_a6: NotRequired[str]
    decision_humaine: NotRequired[dict]         # {"decision": "approuver"|"rejeter", "commentaire": str}

    # --- Résultat d'A8 (relecture qualitative : ne peut qu'ajouter des réserves) ---
    classees_a3: NotRequired[List[dict]]
    doublons_a3: NotRequired[List[dict]]
    statut_a8: NotRequired[str]                 # "ok" | "reserves" | "indisponible"
    message_a8: NotRequired[Optional[str]]
    origine_a8: NotRequired[str]                # "simule" | "llm" | "indisponible" | "desactive"
    constats_a8: NotRequired[List[dict]]
    constats_rejetes_a8: NotRequired[List[dict]]
    notes_a8: NotRequired[dict]

    # --- Résultat d'A7 (reporting) ---
    statut_a7: NotRequired[str]
    message_a7: NotRequired[Optional[str]]
    fichiers_a7: NotRequired[List[str]]

    # --- Statut global du pipeline ---
    statut_pipeline: NotRequired[str]           # "complet" | "complet_avec_reserves" | "a_arbitrer" | "arrete_a1" | "arrete_a2" | "arrete_a3" | "arrete_a4" | "arrete_a5" | "bloque_a6" | "rejete_humain" | "arrete_a7"
    message_pipeline: NotRequired[Optional[str]]
