"""
Lance N scénarios aléatoires (graine fixe) à travers l'orchestrateur complet A1→A7 et produit le
tableau « attendu vs obtenu ».

    python lancer_scenarios.py --source tresorerie.db --seed 42 --n 10
Options : --reel (appelle Claude si ANTHROPIC_API_KEY est défini), --garder-sorties
Avant CHAQUE scénario, la copie de démo est recréée depuis la base d'origine (jamais modifiée).
"""

import argparse
import csv
import os
import shutil
import sqlite3
import time

from db_outils import reinitialiser_demo
import scenarios as sc


def _obtenu(r, db):
    a3 = r.get("resume_a3", {}) or {}
    return {"statut_pipeline": r.get("statut_pipeline"), "promus": a3.get("promus_journal_general"),
            "a_classer": a3.get("a_classer"), "doublons": a3.get("doublons_ignores")}


def executer(scn, source, db):
    from graph import graph
    reinitialiser_demo(source, db)
    if scn.corruption_sql:
        c = sqlite3.connect(db)
        c.execute(scn.corruption_sql)
        c.commit()
        c.close()
    r = None
    for _ in range(scn.rejeux):
        r = graph.invoke({"compte": sc.COMPTE, "dossier_releves": scn.dossier, "periode_debut": scn.periode_debut,
                          "periode_fin": scn.periode, "db_path": db})
    return r


def comparer(scn, r, db):
    obt, att, ecarts = _obtenu(r, db), scn.attendu, []
    for k in ("statut_pipeline", "promus", "a_classer", "doublons"):
        if k in att and obt.get(k) != att[k]:
            ecarts.append(f"{k}: attendu {att[k]}, obtenu {obt.get(k)}")
    if att.get("ecart_significatif"):
        if not any("defavorable" in f"{l['jugement_budget']}{l['jugement_prevision']}" for l in r.get("ecarts_a5", [])):
            ecarts.append("aucun écart défavorable significatif détecté")
    if "categorie_ligne_resolue" in att:
        c = sqlite3.connect(db)
        n = c.execute("SELECT COUNT(*) FROM journal_general WHERE categorie=? AND date_ecriture LIKE ?",
                      (att["categorie_ligne_resolue"], scn.periode + "%")).fetchone()[0]
        c.close()
        if n == 0:
            ecarts.append(f"ligne résolue non retrouvée en « {att['categorie_ligne_resolue']} »")
    return obt, ecarts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default=os.getenv("TRESORERIE_SOURCE", "tresorerie.db"))
    ap.add_argument("--demo", default="tresorerie_demo.db")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--n", type=int, default=10)
    ap.add_argument("--reel", action="store_true")
    ap.add_argument("--sorties", default="sorties_scenarios")
    a = ap.parse_args()
    if not a.reel:
        os.environ["LLM_MODE"] = "simule"
    os.environ["SORTIES_DIR"] = a.sorties

    scs = sc.generer(a.seed, a.n, a.source)
    lignes, ok = [], 0
    for s in scs:
        t0 = time.time()
        try:
            r = executer(s, a.source, a.demo)
            obt, ecarts = comparer(s, r, a.demo)
            detail = r.get("message_pipeline", "")
        except Exception as e:
            obt, ecarts, detail = {}, [f"exception {type(e).__name__}: {e}"], ""
        verdict = "OK" if not ecarts else "ÉCART"
        ok += verdict == "OK"
        lignes.append({"scenario": s.nom, "periode": s.periode, "attendu": s.attendu["statut_pipeline"],
                       "obtenu": obt.get("statut_pipeline"), "verdict": verdict,
                       "ecarts": "; ".join(ecarts), "duree_s": round(time.time() - t0, 1),
                       "description": s.description, "detail": detail[:300]})
        print(f"[{verdict:5}] {s.nom:24} attendu={s.attendu['statut_pipeline']:12} obtenu={obt.get('statut_pipeline')} ({lignes[-1]['duree_s']}s)")
        for e in ecarts:
            print("        ↳", e)

    os.makedirs(a.sorties, exist_ok=True)
    with open(os.path.join(a.sorties, "resultats_scenarios.csv"), "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(lignes[0]))
        w.writeheader()
        w.writerows(lignes)
    md = [f"# Résultats des scénarios — graine {a.seed}, {len(lignes)} scénarios, {ok}/{len(lignes)} conformes", "",
          "| Scénario | Période | Attendu | Obtenu | Verdict | Écarts |", "|---|---|---|---|---|---|"]
    md += [f"| {l['scenario']} | {l['periode']} | {l['attendu']} | {l['obtenu']} | {l['verdict']} | {l['ecarts']} |" for l in lignes]
    md += ["", "## Descriptions", *[f"- **{l['scenario']}** — {l['description']}" for l in lignes]]
    with open(os.path.join(a.sorties, "resultats_scenarios.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(md) + "\n")
    print(f"\n{ok}/{len(lignes)} scénarios conformes → {a.sorties}/resultats_scenarios.md")
    return 0 if ok == len(lignes) else 1


if __name__ == "__main__":
    raise SystemExit(main())
