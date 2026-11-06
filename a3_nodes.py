"""
Nœuds de l'agent A3 — Réconciliation.

Flux : détecter doublons → classer par règles → classer le résidu (LLM) → charger → conclure.
Le chargement reprend la logique de chargeur.py (journal_saisie = staging,
journal_general = grand livre interrogé par R8/SARIMAX) mais :
  - les règles sont lues dans l'ordre (mots_cles.ordre),
  - le LLM n'est appelé que sur le résidu, et seulement au-dessus du seuil de confiance,
  - tout est écrit dans UNE transaction SQLite (tout ou rien).
"""

import suivi_llm as suivi
import os
import sqlite3

import llm_fournisseur as llm_f
import llm_outils as llm
from a3_state import ReconciliationState


def _cle_doublon(t: dict) -> str:
    # Même format que chargeur.py : date|montant arrondi|description
    return f"{t['date']}|{round(t['montant'], 2)}|{t['description']}"


def _prochain_no_ecriture(cur: sqlite3.Cursor, annee: int) -> str:
    cur.execute(
        "SELECT no_ecriture FROM journal_general WHERE no_ecriture LIKE ? "
        "ORDER BY no_ecriture DESC LIMIT 1",
        (f"JG-{annee}-%",),
    )
    row = cur.fetchone()
    dernier = int(row[0].split("-")[-1]) if row else 0
    return f"JG-{annee}-{dernier + 1:05d}"


# --------------------------------------------------------------------------- #
# 1. Doublons
# --------------------------------------------------------------------------- #
def detecter_doublons_node(state: ReconciliationState) -> dict:
    db = state["db_path"]
    if not os.path.isfile(db):
        return {
            "statut": "erreur",
            "message": f"Base introuvable : {db}",
            "transactions_nouvelles": [],
            "doublons": [],
        }

    conn = sqlite3.connect(db)
    try:
        vues = {r[0] for r in conn.execute(
            "SELECT cle_doublon FROM journal_saisie WHERE cle_doublon IS NOT NULL")}
    finally:
        conn.close()

    deja_en_base = set(vues)
    nouvelles, doublons = [], []
    for t in state["transactions"]:
        cle = _cle_doublon(t)
        if cle in vues:
            # origine : « base » = déjà chargée avant ce passage ; « releve » = ligne identique dans le même lot
            # (peut être un vrai achat répété : A8 le signale pour vérification)
            doublons.append({**t, "cle_doublon": cle, "origine": "base" if cle in deja_en_base else "releve"})
        else:
            vues.add(cle)
            nouvelles.append({**t, "cle_doublon": cle})
    return {"transactions_nouvelles": nouvelles, "doublons": doublons}


def router_apres_doublons(state: ReconciliationState) -> str:
    return "erreur" if state.get("statut") == "erreur" else "classer"


# --------------------------------------------------------------------------- #
# 2. Classement par règles (table mots_cles)
# --------------------------------------------------------------------------- #
def classer_regles_node(state: ReconciliationState) -> dict:
    conn = sqlite3.connect(state["db_path"])
    try:
        mots = conn.execute(
            "SELECT m.mot_cle, m.categorie, c.nature "
            "FROM mots_cles m JOIN categories c ON c.categorie = m.categorie "
            "ORDER BY m.ordre, m.id"
        ).fetchall()
    finally:
        conn.close()

    classees, residu = [], []
    for t in state.get("transactions_nouvelles", []):
        desc = t["description"].upper()
        trouve = next(((c, n) for mot, c, n in mots if mot.upper() in desc), None)
        if trouve:
            classees.append({**t, "categorie": trouve[0], "nature": trouve[1],
                             "methode": "regle", "confiance": 1.0})
        else:
            residu.append(t)
    return {"classees": classees, "residu": residu}


# --------------------------------------------------------------------------- #
# 3. Classement du résidu par LLM (précédents + liste fermée de catégories)
# --------------------------------------------------------------------------- #
def classer_residu_llm_node(state: ReconciliationState) -> dict:
    residu = state.get("residu", [])
    mode = llm.mode_llm()
    if not residu:
        return {"erreurs_llm": [], "mode_llm": mode}

    conn = sqlite3.connect(state["db_path"])
    try:
        categories = dict(conn.execute("SELECT categorie, nature FROM categories").fetchall())
        precedents = llm.charger_precedents(conn)
    finally:
        conn.close()

    classees = list(state.get("classees", []))
    restants, erreurs = [], []
    for t in residu:
        res = None
        _err = None
        with suivi.chrono() as _t:
            try:
                res = llm.classer(t, categories, precedents, mode)
            except Exception as e:  # réseau, clé, quota : on n'invente rien, on escalade
                _err = type(e).__name__
                erreurs.append(f"{t['description'][:40]} : {type(e).__name__}: {e}")
        accepte = bool(res and res.categorie in categories and res.confiance >= llm.SEUIL_CONFIANCE)
        suivi.noter("A3", llm_f.nom_modele("A3", llm.MODELE_DEFAUT), mode, _t[0], entree_chars=350 + 25 * len(categories) + len(t["description"]),
                    sortie=(res.justification if res else ""), statut="erreur" if _err else "ok",
                    confiance=(res.confiance if res else None), accepte=accepte, erreur=_err, fournisseur=llm_f.fournisseur())
        if res is None:
            raison = "appel au modèle en échec → ligne escaladée (rien n'est deviné)"
        elif res.categorie == "À classer":
            raison = "le modèle s'abstient (« À classer ») faute de précédent ou de certitude → escaladée à l'humain"
        elif res.categorie not in categories:
            raison = f"catégorie « {res.categorie} » absente de la liste fermée → escaladée"
        elif res.confiance < llm.SEUIL_CONFIANCE:
            raison = f"confiance {res.confiance:.2f} < seuil {llm.SEUIL_CONFIANCE:.2f} → escaladée à l'humain"
        else:
            raison = f"confiance {res.confiance:.2f} ≥ seuil {llm.SEUIL_CONFIANCE:.2f} et catégorie valide → écrite au journal"
        suivi.decider(llm_f.dernier_trace_id(), "acceptée" if accepte else "escaladée", raison)

        if accepte:
            classees.append({**t, "categorie": res.categorie, "nature": categories[res.categorie],
                             "methode": "llm" if mode == "reel" else "simule",
                             "confiance": res.confiance, "justification": res.justification})
        else:
            restants.append({**t,
                             "suggestion": res.categorie if res else None,
                             "confiance": res.confiance if res else 0.0,
                             "justification": res.justification if res else "Échec de l'appel LLM"})
    return {"classees": classees, "residu": restants, "erreurs_llm": erreurs, "mode_llm": mode}


# --------------------------------------------------------------------------- #
# 4. Chargement (une seule transaction SQLite)
# --------------------------------------------------------------------------- #
def charger_node(state: ReconciliationState) -> dict:
    compte = state["compte"]
    resume = {"inseres_staging": 0, "promus_journal_general": 0,
              "doublons_ignores": len(state.get("doublons", [])),
              "a_classer": 0, "par_methode": {}}

    conn = sqlite3.connect(state["db_path"])
    try:
        cur = conn.cursor()
        sql_saisie = (
            "INSERT INTO journal_saisie (date_brute, description, montant_brut, compte_source, "
            "date_valide, categorie, nature, mois, cle_doublon, est_doublon, statut) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)"
        )
        for t in state.get("classees", []):
            annee, mois = int(t["date"][:4]), int(t["date"][5:7])
            statut = "✓ Valide" if t["methode"] == "regle" else "✓ Valide (LLM)"
            cur.execute(sql_saisie, (t["date"], t["description"], t["montant"], compte, t["date"],
                                     t["categorie"], t["nature"], mois, t["cle_doublon"], statut))
            cur.execute(
                "INSERT INTO journal_general (no_ecriture, date_ecriture, description, montant, "
                "categorie, nature, mois, annee, compte_source, exercice) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (_prochain_no_ecriture(cur, annee), t["date"], t["description"], t["montant"],
                 t["categorie"], t["nature"], mois, annee, compte, f"FY{annee}"))
            resume["inseres_staging"] += 1
            resume["promus_journal_general"] += 1
            resume["par_methode"][t["methode"]] = resume["par_methode"].get(t["methode"], 0) + 1

        for t in state.get("residu", []):  # staging seulement, comme chargeur.py
            mois = int(t["date"][5:7])
            cur.execute(sql_saisie, (t["date"], t["description"], t["montant"], compte, t["date"],
                                     "À classer", "À classer", mois, t["cle_doublon"], "⚠ À classer"))
            resume["inseres_staging"] += 1
            resume["a_classer"] += 1
        conn.commit()
    except Exception as e:
        conn.rollback()
        return {"statut": "erreur", "message": f"Échec du chargement (annulé) : {type(e).__name__}: {e}"}
    finally:
        conn.close()
    return {"resume_chargement": resume}


def router_apres_chargement(state: ReconciliationState) -> str:
    if state.get("statut") == "erreur":
        return "erreur"
    return "escalade" if state.get("residu") else "complet"


# --------------------------------------------------------------------------- #
# 5. Conclusion
# --------------------------------------------------------------------------- #
def marquer_complet_node(state: ReconciliationState) -> dict:
    r = state["resume_chargement"]
    return {"statut": "complet", "message": (
        f"{r['promus_journal_general']} écriture(s) chargée(s) {r['par_methode']}, "
        f"{r['doublons_ignores']} doublon(s) ignoré(s). Prêt pour A4 (Prévision).")}


def escalader_node(state: ReconciliationState) -> dict:
    r = state["resume_chargement"]
    lignes = "; ".join(f"« {t['description'][:45]} » ({t['montant']:,.2f} $)" for t in state["residu"])
    return {"statut": "a_arbitrer", "message": (
        f"{r['promus_journal_general']} écriture(s) chargée(s), {len(state['residu'])} ligne(s) "
        f"« À classer » à arbitrer par le contrôleur : {lignes}.")}
