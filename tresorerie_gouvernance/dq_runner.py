"""Moteur de contrôle qualité (DMBOK : Data Quality).

executer(conn, run_id=None) :
  1. évalue chaque règle active de dq_regle (violations / lignes évaluées) ;
  2. enregistre un résultat par règle dans dq_resultat et une synthèse dans dq_execution ;
  3. met à jour core_mouvement.statut_dq :
       règle bloquante      -> 'quarantaine' (exclu des vues mart_) + élément placé dans stg_rejet
       règle avertissement  -> 'avertissement'
  4. rejouable sans doublon : la revue en attente (stg_rejet 'a_revoir') n'est jamais dupliquée.

Usage :
    python dq_runner.py --db tresorerie.db                 # contrôle complet
    python dq_runner.py --db tresorerie.db --run-id A2-... # limité à un run
    python dq_runner.py --db tresorerie.db --sans-quarantaine
"""
import argparse
import json
import sqlite3
import uuid
from datetime import datetime, timezone

from dq_regles import REGLES

CLES = {"core_mouvement": "mouvement_id", "core_solde_releve": "solde_id", "mdm_compte": "compte_id"}


def charger_regles(conn):
    """Synchronise dq_regle avec dq_regles.py. Le champ 'actif' choisi par l'utilisateur est préservé."""
    for r in REGLES:
        conn.execute(
            "INSERT INTO dq_regle (regle_id, nom, description, dimension, cible_table, severite, "
            " sql_violations, sql_total, seuil_pct) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (regle_id) DO UPDATE SET nom = excluded.nom, description = excluded.description, "
            " dimension = excluded.dimension, cible_table = excluded.cible_table, severite = excluded.severite, "
            " sql_violations = excluded.sql_violations, sql_total = excluded.sql_total, "
            " seuil_pct = excluded.seuil_pct, "
            " version = CASE WHEN dq_regle.sql_violations <> excluded.sql_violations "
            "                  OR dq_regle.sql_total <> excluded.sql_total "
            "                  OR dq_regle.seuil_pct <> excluded.seuil_pct "
            "                THEN dq_regle.version + 1 ELSE dq_regle.version END, "
            " maj_le = datetime('now')",
            (r["regle_id"], r["nom"], r.get("description"), r["dimension"], r["cible_table"], r["severite"],
             r["sql_violations"], r["sql_total"], r.get("seuil_pct", 100)),
        )
    conn.commit()


def _payload(conn, table, cle_nom, cle):
    curseur = conn.execute(f"SELECT * FROM {table} WHERE {cle_nom} = ?", (cle,))
    ligne = curseur.fetchone()
    if ligne is None:
        return None
    return json.dumps(dict(zip([d[0] for d in curseur.description], ligne)), ensure_ascii=False, default=str)


def executer(conn, run_id=None, quarantaine=True):
    """Exécute toutes les règles actives. Retourne un dict de synthèse (voir afficher())."""
    execution_id = f"DQ-{datetime.now(timezone.utc):%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:6]}"
    conn.execute("INSERT INTO dq_execution (execution_id, run_id, portee) VALUES (?, ?, ?)",
                 (execution_id, run_id, "run" if run_id else "complet"))
    params = {"run_id": run_id}
    if quarantaine:
        conn.execute("UPDATE core_mouvement SET statut_dq = 'ok' "
                     "WHERE statut_dq <> 'ok' AND (:run_id IS NULL OR run_id = :run_id)", params)

    resultats = []
    regles = conn.execute(
        "SELECT regle_id, nom, severite, cible_table, sql_violations, sql_total, seuil_pct, dimension "
        "FROM dq_regle WHERE actif = 1 ORDER BY regle_id"
    ).fetchall()
    for regle_id, nom, severite, cible, sql_v, sql_t, seuil, dimension in regles:
        nb_total = conn.execute(sql_t, params).fetchone()[0]
        ids = list(dict.fromkeys(r[0] for r in conn.execute(sql_v, params)))
        nb_viol = len(ids)
        score = 100.0 if nb_total == 0 else round(100.0 * (1 - nb_viol / nb_total), 2)
        statut = "pass" if score >= seuil else "fail"
        conn.execute(
            "INSERT INTO dq_resultat (execution_id, regle_id, nb_evalue, nb_violation, score_pct, statut, detail_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (execution_id, regle_id, nb_total, nb_viol, score, statut,
             json.dumps({"ids_exemples": ids[:20]}) if ids else None),
        )

        if quarantaine and ids and cible == "core_mouvement":
            if severite == "bloquante":
                conn.executemany("UPDATE core_mouvement SET statut_dq = 'quarantaine' WHERE mouvement_id = ?",
                                 [(i,) for i in ids])
            elif severite == "avertissement":
                conn.executemany(
                    "UPDATE core_mouvement SET statut_dq = 'avertissement' WHERE mouvement_id = ? AND statut_dq = 'ok'",
                    [(i,) for i in ids])
        if quarantaine and ids and severite == "bloquante":
            cle_nom = CLES.get(cible)
            for i in ids:
                deja = conn.execute(
                    "SELECT 1 FROM stg_rejet WHERE table_source = ? AND cle_source = ? AND regle_id = ? "
                    "AND statut_traitement = 'a_revoir'", (cible, i, regle_id)).fetchone()
                if deja:
                    continue
                conn.execute(
                    "INSERT INTO stg_rejet (execution_id, run_id, table_source, cle_source, regle_id, motif, payload_json) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (execution_id, run_id, cible, i, regle_id, nom,
                     _payload(conn, cible, cle_nom, i) if cle_nom else None))
        resultats.append({"regle_id": regle_id, "nom": nom, "dimension": dimension, "severite": severite,
                          "nb_evalue": nb_total, "nb_violation": nb_viol, "score_pct": score, "statut": statut})

    comptes = [r for r in resultats if r["severite"] != "info"]
    score_global = round(sum(r["score_pct"] for r in comptes) / len(comptes), 2) if comptes else 100.0
    nb_echecs = sum(1 for r in comptes if r["statut"] == "fail")
    nb_bloquants = sum(1 for r in comptes if r["statut"] == "fail" and r["severite"] == "bloquante")
    conn.execute(
        "UPDATE dq_execution SET score_global = ?, nb_regles = ?, nb_echecs = ?, nb_bloquants_echec = ? "
        "WHERE execution_id = ?", (score_global, len(resultats), nb_echecs, nb_bloquants, execution_id))
    conn.commit()
    return {"execution_id": execution_id, "run_id": run_id, "score_global": score_global,
            "nb_regles": len(resultats), "nb_echecs": nb_echecs, "nb_bloquants_echec": nb_bloquants,
            "resultats": resultats}


def afficher(resume):
    print(f"Exécution {resume['execution_id']}  |  score global : {resume['score_global']} %  |  "
          f"règles en échec : {resume['nb_echecs']}/{resume['nb_regles']}  |  "
          f"bloquantes en échec : {resume['nb_bloquants_echec']}")
    for r in resume["resultats"]:
        marque = "OK  " if r["statut"] == "pass" else "FAIL"
        print(f"  [{marque}] {r['regle_id']}  {r['severite']:<13} {r['nb_violation']:>5}/{r['nb_evalue']:<6} "
              f"{r['score_pct']:>6} %  {r['nom']}")


def main():
    p = argparse.ArgumentParser(description="Exécute les contrôles qualité des données.")
    p.add_argument("--db", required=True)
    p.add_argument("--run-id", help="Limiter le contrôle aux mouvements d'un run")
    p.add_argument("--sans-quarantaine", action="store_true", help="Mesurer sans modifier statut_dq ni stg_rejet")
    a = p.parse_args()
    conn = sqlite3.connect(a.db)
    conn.execute("PRAGMA foreign_keys = ON")
    charger_regles(conn)
    afficher(executer(conn, run_id=a.run_id, quarantaine=not a.sans_quarantaine))
    conn.close()


if __name__ == "__main__":
    main()
