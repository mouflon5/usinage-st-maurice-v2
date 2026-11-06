"""Pont entre l'orchestrateur et le socle de gouvernance (tresorerie_gouvernance/).

Principe : le fonctionnement actuel ne change pas. Ces fonctions sont facultatives et ne lèvent jamais
d'exception : si la base n'a pas été initialisée (python tresorerie_gouvernance/init_db.py --db ...),
ou si une écriture échoue, elles ne font rien et le pipeline continue comme avant.

    demarrer(db)                         -> run_id | None      (orchestrateur, au départ)
    enregistrer_fichiers(db, run, ...)   -> {nom: fichier_id}   (A1 : trace + hash, sans jamais sauter un fichier)
    charger_extraction(db, run, ...)     -> résumé | None       (A2 : stg_releve_ligne puis core_mouvement)
    terminer(db, run, statut_pipeline)   -> résumé qualité | None (fin : ferme le run, lance le contrôle qualité)

Variables d'environnement :
    GOUV_SEL_COMPTE   sel du hash des numéros de compte (à définir ; défaut local non secret)
    GOUV_ENTITE       nom légal de l'entité par défaut (défaut : « Entité par défaut »)
    GOUV_BANQUE       code ref_banque des comptes créés automatiquement (défaut : AUTRE)
    GOUV_TYPE_COMPTE  code ref_compte_type des comptes créés automatiquement (défaut : EXPLOITATION)
"""
import json
import os
import sqlite3
import sys

_DOSSIER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tresorerie_gouvernance")
if _DOSSIER not in sys.path:
    sys.path.insert(0, _DOSSIER)

try:
    import dq_runner
    import lineage
    import mdm_utils
    DISPONIBLE = True
except Exception:  # module absent ou incomplet : le pont reste inactif
    DISPONIBLE = False

STATUT_RUN = {"complet": "succes", "complet_avec_reserves": "succes", "a_arbitrer": "partiel"}


def _connecter(db):
    if not DISPONIBLE or not db or not os.path.isfile(db):
        return None
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA foreign_keys = ON")
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'meta_run'").fetchone() is None:
        conn.close()
        return None
    return conn


def _compte_id(conn, libelle):
    """Retourne le compte maître correspondant au compte de l'orchestrateur, en le créant au besoin."""
    sel = os.getenv("GOUV_SEL_COMPTE", "local-non-secret")
    banque = os.getenv("GOUV_BANQUE", "AUTRE")
    h = mdm_utils.hash_numero_compte(libelle, sel) if any(c.isdigit() for c in str(libelle)) else \
        mdm_utils.hash_transaction(0, "compte", 0, str(libelle))
    ligne = conn.execute("SELECT compte_id FROM mdm_compte WHERE banque_code = ? AND numero_hash = ?",
                         (banque, h)).fetchone()
    if ligne:
        return ligne[0]
    nom = os.getenv("GOUV_ENTITE", "Entité par défaut")
    conn.execute("INSERT OR IGNORE INTO mdm_entite_juridique (nom_legal) VALUES (?)", (nom,))
    entite = conn.execute("SELECT entite_id FROM mdm_entite_juridique WHERE nom_legal = ?", (nom,)).fetchone()[0]
    return conn.execute(
        "INSERT INTO mdm_compte (entite_id, banque_code, type_code, numero_masque, numero_hash, libelle) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (entite, banque, os.getenv("GOUV_TYPE_COMPTE", "EXPLOITATION"), mdm_utils.masquer_compte(libelle), h,
         str(libelle))).lastrowid


def demarrer(db, parametres=None):
    conn = _connecter(db)
    if conn is None:
        return None
    try:
        run_id = lineage.demarrer_run(conn, "ORCH", parametres)
        conn.commit()
        return run_id
    except Exception:
        return None
    finally:
        conn.close()


def enregistrer_fichiers(db, run_id, chemins):
    """Trace chaque relevé (hash SHA-256). Un fichier déjà vu est seulement signalé, jamais sauté."""
    conn = _connecter(db)
    if conn is None or not run_id:
        return {}
    ids = {}
    try:
        for chemin in chemins:
            fichier_id, _ = lineage.enregistrer_fichier(conn, chemin, format_code="PDF_TEXTE", run_id=run_id)
            ids[os.path.basename(chemin)] = fichier_id
        conn.commit()
    except Exception:
        conn.rollback()
    finally:
        conn.close()
    return ids


def charger_extraction(db, run_id, compte, transactions, fichier_ids=None):
    """Écrit les lignes extraites par A2 dans stg_releve_ligne, puis les charge dans core_mouvement."""
    conn = _connecter(db)
    if conn is None or not run_id or not transactions:
        return None
    fichier_ids = fichier_ids or {}
    resume = {"stg": 0, "insere": 0, "doublon": 0, "rejete": 0}
    try:
        compte_id = _compte_id(conn, compte)
        vus = {}
        derniers = {}
        for i, t in enumerate(transactions, 1):
            fid = fichier_ids.get(t.get("fichier"))
            cents = round(float(t["montant"]) * 100)
            stg_id = conn.execute(
                "INSERT INTO stg_releve_ligne (run_id, fichier_id, format_code, ligne_no, compte_ref_brut, "
                "date_operation_brut, libelle_brut, montant_brut, solde_brut, charge_json) "
                "VALUES (?, ?, 'PDF_TEXTE', ?, ?, ?, ?, ?, ?, ?)",
                (run_id, fid, i, str(compte), t.get("date"), t.get("description"), str(t.get("montant")),
                 str(t.get("solde")), json.dumps(t, ensure_ascii=False, default=str))).lastrowid
            resume["stg"] += 1
            cle = (fid, t.get("date"), cents, t.get("description"))
            vus[cle] = vus.get(cle, 0) + 1
            res = mdm_utils.charger_mouvement(
                conn, compte_id=compte_id, date_operation=t.get("date"), libelle_brut=t.get("description"),
                montant_cents=cents, run_id=run_id, fichier_id=fid, stg_id=stg_id, occurrence=vus[cle])
            resume[{"insere": "insere", "doublon": "doublon", "rejete": "rejete"}[res["statut"]]] += 1
            if t.get("solde") is not None:
                derniers[(t.get("fichier"), compte_id)] = (t["date"], round(float(t["solde"]) * 100))
        for (_, cid), (jour, solde) in derniers.items():
            conn.execute("INSERT OR IGNORE INTO core_solde_releve (compte_id, date_solde, solde_cents, source, run_id) "
                         "VALUES (?, ?, ?, 'releve', ?)", (cid, jour, solde, run_id))
        conn.commit()
        return resume
    except Exception:
        conn.rollback()
        return None
    finally:
        conn.close()


def terminer(db, run_id, statut_pipeline):
    """Ferme le run puis lance le contrôle qualité limité à ce run. Retourne un résumé, ou None."""
    conn = _connecter(db)
    if conn is None or not run_id:
        return None
    try:
        lineage.terminer_run(conn, run_id, STATUT_RUN.get(statut_pipeline, "echec"))
        conn.commit()
        dq_runner.charger_regles(conn)
        resume = dq_runner.executer(conn, run_id=run_id)
        conn.commit()
        return resume
    except Exception:
        conn.rollback()
        return None
    finally:
        conn.close()
