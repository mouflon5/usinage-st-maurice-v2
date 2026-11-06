"""Nœuds de l'agent A2 — Extraction (copie intégrée à l'orchestrateur).

Lit les relevés PDF dans 4 mises en page (voir formats_releves.py) et applique des contrôles de cohérence :
  * continuité des soldes ligne à ligne (comme avant) ;
  * solde d'ouverture + 1re ligne, et dernière ligne = solde de clôture, quand le relevé les imprime ;
  * chaque date appartient à la période indiquée par le nom du fichier (VERIFIER_PERIODE) ;
  * le compte imprimé dans l'en-tête est celui du nom du fichier ;
  * un PDF dont aucune mise en page n'est reconnue est refusé (avant : accepté sans transaction).
Toute anomalie arrête le pipeline : rien n'est deviné.
"""

import os
from collections import defaultdict

from a2_state import ExtractionState
from classer_documents import analyser_document
from formats_releves import lire_releve, normaliser_compte

VERIFIER_PERIODE = os.getenv("A2_VERIFIER_PERIODE", "1") != "0"


def extraire_node(state: ExtractionState) -> dict:
    transactions = []
    lignes_rejetees = []
    fichiers_echec = []
    anomalies_structure = []
    formats = {}

    for chemin in state["fichiers_a_traiter"]:
        nom = os.path.basename(chemin)
        try:
            lec = lire_releve(chemin)
        except Exception:
            fichiers_echec.append(chemin)
            continue

        if lec.format is None:
            # aucune des 4 mises en page reconnue : tout le contenu est « non reconnu »
            if lec.rejetees:
                lignes_rejetees.extend({"fichier": nom, "ligne": l} for l in lec.rejetees)
            else:
                fichiers_echec.append(chemin)           # PDF vide ou sans texte lisible
            continue

        formats[nom] = lec.format
        lignes_rejetees.extend({"fichier": nom, "ligne": l} for l in lec.rejetees)
        for t in lec.transactions:
            transactions.append({"fichier": nom, **t})

        info = analyser_document(nom, state.get("db_path"))
        if info:
            compte_nom, periode = info[0], info[1]
            if VERIFIER_PERIODE:
                hors = sorted({t["date"] for t in lec.transactions if t["date"][:7] != periode})
                if hors:
                    anomalies_structure.append({"fichier": nom, "type": "date_hors_periode",
                                                "detail": f"{len(hors)} date(s) hors de {periode} (ex. {hors[0]})"})
                if lec.periode_entete and lec.periode_entete[0][:7] != periode:
                    anomalies_structure.append({"fichier": nom, "type": "periode_entete",
                                                "detail": f"en-tête {lec.periode_entete[0]} → {lec.periode_entete[1]}, nom de fichier {periode}"})
            if lec.compte_entete and normaliser_compte(lec.compte_entete) != normaliser_compte(compte_nom):
                anomalies_structure.append({"fichier": nom, "type": "compte_entete",
                                            "detail": f"en-tête « {lec.compte_entete} », nom de fichier « {compte_nom} »"})

        trans = lec.transactions
        if lec.solde_ouverture is not None and trans:
            attendu = round(lec.solde_ouverture + trans[0]["montant"], 2)
            if abs(attendu - trans[0]["solde"]) > 0.01:
                anomalies_structure.append({"fichier": nom, "type": "solde_ouverture",
                                            "detail": f"ouverture {lec.solde_ouverture:.2f} + {trans[0]['montant']:.2f} ≠ {trans[0]['solde']:.2f}"})
        if lec.solde_cloture is not None:
            dernier = trans[-1]["solde"] if trans else lec.solde_ouverture
            if dernier is None or abs(dernier - lec.solde_cloture) > 0.01:
                anomalies_structure.append({"fichier": nom, "type": "solde_cloture",
                                            "detail": f"dernier solde lu {dernier}, clôture imprimée {lec.solde_cloture:.2f} (lignes manquantes ?)"})

    return {"transactions": transactions, "lignes_rejetees": lignes_rejetees, "fichiers_echec": fichiers_echec,
            "anomalies_structure": anomalies_structure, "formats_detectes": formats}


def valider_coherence_node(state: ExtractionState) -> dict:
    par_fichier = defaultdict(list)
    for t in state.get("transactions", []):
        par_fichier[t["fichier"]].append(t)

    anomalies = []
    for fichier, trans in par_fichier.items():
        trans_triees = sorted(trans, key=lambda t: t["date"])
        for i in range(1, len(trans_triees)):
            precedent = trans_triees[i - 1]
            courant = trans_triees[i]
            solde_attendu = round(precedent["solde"] + courant["montant"], 2)
            if abs(solde_attendu - courant["solde"]) > 0.01:
                anomalies.append({
                    "fichier": fichier,
                    "date": courant["date"],
                    "solde_attendu": solde_attendu,
                    "solde_declare": courant["solde"],
                })

    return {"anomalies_solde": anomalies}


def router_extraction(state: ExtractionState) -> str:
    if (state.get("fichiers_echec") or state.get("lignes_rejetees")
            or state.get("anomalies_solde") or state.get("anomalies_structure")):
        return "probleme"
    return "complet"


def marquer_complet_node(state: ExtractionState) -> dict:
    n = len(state.get("transactions", []))
    fm = sorted(set(state.get("formats_detectes", {}).values()))
    return {"statut": "complet", "message": f"{n} transaction(s) extraite(s) (format {', '.join(fm) or 'n/d'}), aucune anomalie. Prêt pour A3."}


def signaler_probleme_node(state: ExtractionState) -> dict:
    parts = []
    if state.get("fichiers_echec"):
        parts.append(f"{len(state['fichiers_echec'])} fichier(s) illisible(s)")
    if state.get("lignes_rejetees"):
        parts.append(f"{len(state['lignes_rejetees'])} ligne(s) non reconnue(s)")
    if state.get("anomalies_solde"):
        parts.append(f"{len(state['anomalies_solde'])} rupture(s) de continuité de solde")
    if state.get("anomalies_structure"):
        parts.append("; ".join(f"{a['type']} ({a['fichier']}: {a['detail']})" for a in state["anomalies_structure"][:3]))

    return {
        "statut": "incomplet",
        "message": "Problème détecté : " + ", ".join(parts) + ". Ne pas transmettre à A3 tant que non résolu.",
    }
