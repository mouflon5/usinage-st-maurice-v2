"""
Exécuteur du banc d'essai — lance N scénarios à travers l'orchestrateur A1→A7, en parallèle, et écrit chaque
résultat dans `banc_essai/resultats/resultats.db` AU FUR ET À MESURE (le tableau de bord le lit en direct).

    python -m banc_essai.executeur --seed 7 --n 1000 --workers 2
    python -m banc_essai.executeur --seed 7 --n 20 --reel        # avec Claude (coûte des jetons)
    python -m banc_essai.executeur --ids <id1>,<id2> --run-id X --forcer   # rejouer des scénarios précis
    python -m banc_essai.executeur --sans-a8 ...                 # même lot sans le relecteur (comparaison)

Pilotage en direct : le tableau de bord écrit une commande (pause | reprendre | arreter | tuer) dans la table `lots` ;
l'exécuteur la lit entre deux scénarios, et écrit un battement de cœur (`heartbeat`) toutes les secondes.

Garanties :
  * `tresorerie.db` n'est jamais modifiée : chaque scénario travaille sur sa propre copie, supprimée ensuite ;
  * mode LLM « simulé » par défaut (aucun appel réseau, déterministe) ; `--reel` utilise ANTHROPIC_API_KEY ;
  * chaque scénario est reproductible à partir de (graine, n, indice) — la spec complète est stockée avec le résultat.
"""

import argparse
import contextlib
import json
import multiprocessing as mp
import os
import shutil
import sqlite3
import sys
import threading
import time
import traceback
from datetime import datetime

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMA = """
CREATE TABLE IF NOT EXISTS lots (run_id TEXT PRIMARY KEY, debut TEXT, fin TEXT, seed INTEGER, n INTEGER, mode TEXT, workers INTEGER, statut TEXT);
CREATE TABLE IF NOT EXISTS test_runs (
  id TEXT, run_id TEXT, horodatage TEXT, idx INTEGER, type TEXT, categorie_test TEXT, banque TEXT, format TEXT, compte TEXT,
  nb_fichiers INTEGER, nb_lignes INTEGER, statut_attendu TEXT, statut_obtenu TEXT, agent_arret TEXT, verdict TEXT, gravite TEXT,
  limite_connue TEXT, duree_s REAL, durees_agents TEXT, lignes_ok INTEGER, lignes_escaladees INTEGER, lignes_mal_classees INTEGER,
  lignes_surconfiance INTEGER, lignes_perdues INTEGER, lignes_fantomes INTEGER, jetons_entree INTEGER, jetons_sortie INTEGER,
  message TEXT, details TEXT, description TEXT, spec TEXT, PRIMARY KEY (run_id, id));
"""
# colonnes ajoutées après la 1re version (les anciens résultats restent lisibles : valeurs NULL)
COLONNES = {
    "lots": {"pid": "INTEGER", "heartbeat": "TEXT", "commande": "TEXT", "filtre": "TEXT", "options": "TEXT"},
    "test_runs": {"trace": "TEXT", "a8_statut": "TEXT", "a8_origine": "TEXT", "a8_constats": "TEXT", "a8_rejetes": "TEXT",
                  "a8_notes": "TEXT", "a8_eval": "TEXT", "a8_lignes_justes": "INTEGER", "a8_lignes_total": "INTEGER"},
}


def chemin_resultats() -> str:
    d = os.path.join(RACINE, "banc_essai", "resultats")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "resultats.db")


def ouvrir_resultats():
    c = sqlite3.connect(chemin_resultats(), timeout=30)
    c.execute("PRAGMA journal_mode=WAL")
    c.executescript(SCHEMA)
    migrer(c)
    return c


def migrer(c):
    for table, cols in COLONNES.items():
        existantes = {r[1] for r in c.execute(f"PRAGMA table_info({table})")}
        for nom, typ in cols.items():
            if nom not in existantes:
                with contextlib.suppress(sqlite3.OperationalError):     # un autre processus l'a ajoutée entre-temps
                    c.execute(f"ALTER TABLE {table} ADD COLUMN {nom} {typ}")
    c.commit()


# --------------------------------------------------------------------------- #
# Pannes injectées
# --------------------------------------------------------------------------- #
@contextlib.contextmanager
def pannes(noms: list, db: str):
    from unittest import mock
    import llm_outils
    piles = contextlib.ExitStack()
    verrou = None
    try:
        for n in noms:
            if n == "llm_panne":
                piles.enter_context(mock.patch.object(llm_outils, "classer", side_effect=RuntimeError("API indisponible (panne injectée)")))
            elif n == "llm_categorie_inventee":
                piles.enter_context(mock.patch.object(llm_outils, "classer", side_effect=lambda t, c, p, m: llm_outils.Classement(
                    categorie="Dépenses diverses", confiance=0.99, justification="catégorie inventée (panne injectée)")))
            elif n == "llm_surconfiant_faux":
                piles.enter_context(mock.patch.object(llm_outils, "classer", side_effect=lambda t, c, p, m: llm_outils.Classement(
                    categorie="Ventes — usinage sur mesure", confiance=0.99, justification="réponse fausse mais sûre d'elle (panne injectée)")))
            elif n == "sarimax_panne":
                import tresorerie_dashboard as td
                piles.enter_context(mock.patch.object(td, "sarimax_analysis", side_effect=RuntimeError("SARIMAX indisponible (panne injectée)")))
            elif n == "db_verrouillee":
                verrou = sqlite3.connect(db, isolation_level=None)
                verrou.execute("BEGIN EXCLUSIVE")
        yield
    finally:
        piles.close()
        if verrou is not None:
            with contextlib.suppress(Exception):
                verrou.execute("ROLLBACK")
            verrou.close()


# --------------------------------------------------------------------------- #
# Trace des interactions entre agents (lue par le tableau de bord)
# --------------------------------------------------------------------------- #
def resumer_noeud(noeud: str, upd: dict) -> dict:
    """Ce qu'un nœud a produit, sans les données volumineuses : statut, message, volumes transmis à l'agent suivant."""
    upd = upd or {}
    d = {"noeud": noeud}
    if noeud.startswith("executer_a"):
        a = noeud[-2:]
        d.update(agent=a.upper(), statut=upd.get(f"statut_{a}"), message=str(upd.get(f"message_{a}") or "")[:500])
    d["sorties"] = {k: len(v) for k, v in upd.items() if isinstance(v, (list, dict)) and k not in ("constats_rejetes_a8",)}
    if noeud == "executer_a3":
        d["resume"] = upd.get("resume_a3")
    elif noeud == "executer_a6":
        d["controles"] = [{"id": c["id"], "ok": c["ok"], "gravite": c["gravite"], "libelle": c["libelle"],
                           "detail": str(c.get("detail"))[:200]} for c in upd.get("controles_a6", [])]
    elif noeud == "executer_a8":
        d["relecture"] = {"origine": upd.get("origine_a8"), "notes": upd.get("notes_a8", {}),
                          "constats": upd.get("constats_a8", [])[:12], "rejetes": upd.get("constats_rejetes_a8", [])[:12]}
    elif noeud.startswith("finaliser"):
        d["statut_pipeline"] = upd.get("statut_pipeline")
    return d


def classement_vu(etat: dict) -> list:
    """Ligne par ligne : ce qu'A3 a décidé (catégorie, méthode, confiance) ; pour le dossier d'un scénario."""
    out = []
    for t in (etat.get("classees_a3") or [])[:80]:
        out.append({"ref": f"L{len(out) + 1}", "date": t["date"], "description": t["description"], "montant": t["montant"],
                    "categorie": t["categorie"], "methode": t.get("methode"), "confiance": t.get("confiance")})
    for t in (etat.get("residu_a3") or [])[:40]:
        out.append({"ref": None, "date": t["date"], "description": t["description"], "montant": t["montant"],
                    "categorie": "À classer", "methode": "escalade", "confiance": t.get("confiance"),
                    "suggestion": t.get("suggestion")})
    return out


def evaluer_a8(etat: dict, stats: dict, issues: list) -> dict:
    """A8 a-t-il vu ce que la vérité terrain connaît ? (au niveau du scénario, puis des lignes citées)"""
    statut = etat.get("statut_a8")
    if statut is None:
        return dict(a8_eval="non_applicable", a8_lignes_justes=0, a8_lignes_total=0)
    if statut == "indisponible":
        return dict(a8_eval="indisponible", a8_lignes_justes=0, a8_lignes_total=0)
    defaut = any(stats.get(k, 0) for k in ("lignes_mal_classees", "lignes_perdues", "lignes_fantomes", "lignes_surconfiance"))
    reserves = [c for c in etat.get("constats_a8", []) if c.get("gravite") == "reserve"]
    signale = bool(reserves)
    ev = ("vrai_positif" if signale else "manque") if defaut else ("faux_positif" if signale else "vrai_negatif")
    desc = {f"L{i}": t["description"] for i, t in enumerate(etat.get("classees_a3") or [], 1)}
    desc.update({f"D{i}": t["description"] for i, t in enumerate(etat.get("doublons_a3") or [], 1)})
    texte_issues = " ".join(i.get("detail", "") for i in issues)
    justes = sum(1 for c in reserves if desc.get(c.get("ref")) and desc[c["ref"]] in texte_issues)
    return dict(a8_eval=ev, a8_lignes_justes=justes, a8_lignes_total=sum(1 for c in reserves if c.get("ref") in desc))


# --------------------------------------------------------------------------- #
# Un scénario
# --------------------------------------------------------------------------- #
_graph = None


def init_worker(reel: bool, sans_a8: bool = False):
    global _graph
    sys.path.insert(0, RACINE)
    os.chdir(RACINE)
    if not reel:
        os.environ["LLM_MODE"] = "simule"
    if sans_a8:
        os.environ["A8_ACTIF"] = "0"
    import warnings
    warnings.filterwarnings("ignore")
    from graph import graph
    _graph = graph


def executer_un(args: dict) -> dict:
    from banc_essai import generateur, verification
    spec, source, racine_scn, reel, run_id = args["spec"], args["source"], args["racine_scn"], args["reel"], args["run_id"]
    t_debut = time.time()
    travail = os.path.join(RACINE, "banc_essai", "travail", f"{os.getpid()}_{spec['id']}")
    os.makedirs(travail, exist_ok=True)
    db = os.path.join(travail, "tresorerie.db")
    res = dict(id=spec["id"], run_id=run_id, horodatage=datetime.now().isoformat(timespec="seconds"), idx=spec["index"], type=spec["type"],
               categorie_test=spec["categorie_test"], banque=spec["banque"], format=spec["format"], compte=spec["compte"],
               nb_fichiers=len(spec["fichiers"]), nb_lignes=len(spec["verite"]), statut_attendu=json.dumps(spec["attendu"]["statuts"]),
               limite_connue=spec.get("limite_connue"), description=spec["description"], spec=json.dumps(spec, ensure_ascii=False),
               jetons_entree=None, jetons_sortie=None)
    statut, etat, exception, durees, issues, stats, trace = None, {}, None, {}, [], {}, []
    try:
        dossier = generateur.ecrire_fichiers(spec, racine_scn)
        shutil.copy2(source, db)
        base = spec.get("db_override") or db
        if spec["corruption_sql"]:
            c = sqlite3.connect(db)
            c.execute(spec["corruption_sql"])
            c.commit()
            c.close()
        avant = verification.instantane(db)
        os.environ["TRACES_DIR"] = os.path.join(travail, "traces")
        os.environ["SORTIES_DIR"] = os.path.join(travail, "sorties")
        entree = {"compte": spec["compte"], "dossier_releves": dossier, "periode_debut": spec["periode_debut"],
                  "periode_fin": spec["periode_fin"], "db_path": base}
        cb = contextlib.nullcontext()
        if reel:
            with contextlib.suppress(Exception):
                from langchain_core.callbacks import get_usage_metadata_callback
                cb = get_usage_metadata_callback()
        with pannes(spec["pannes"], db), cb as usage:
            for _ in range(spec["rejeux"]):
                t0 = t_prec = time.time()
                etat, trace = {}, []
                for mode, chunk in _graph.stream(entree, stream_mode=["updates", "values"]):
                    now = time.time()
                    if mode == "updates":
                        for noeud, upd in chunk.items():
                            if noeud.startswith("executer_"):
                                durees[noeud[-2:].upper()] = round(durees.get(noeud[-2:].upper(), 0) + now - t_prec, 3)
                            if noeud != "journaliser_run":
                                trace.append({**resumer_noeud(noeud, upd), "debut": round(t_prec - t0, 3), "duree": round(now - t_prec, 3)})
                        t_prec = now
                    else:
                        etat = chunk
            if usage is not None and getattr(usage, "usage_metadata", None):
                res["jetons_entree"] = sum(u.get("input_tokens", 0) for u in usage.usage_metadata.values())
                res["jetons_sortie"] = sum(u.get("output_tokens", 0) for u in usage.usage_metadata.values())
        statut = etat.get("statut_pipeline")
        issues, stats = verification.verifier_donnees(spec, statut, etat, avant, db)
    except Exception as e:
        exception = f"{type(e).__name__}: {e}"
        issues = [dict(type="exception", gravite="critique", detail=traceback.format_exc()[-1500:])]
    v = verification.verdict(spec, statut, exception, issues)
    res.update(statut_obtenu=statut or ("exception" if exception else None), agent_arret=verification.agent_arret(statut), verdict=v,
               gravite=verification.GRAVITE[v], duree_s=round(time.time() - t_debut, 2), durees_agents=json.dumps(durees),
               message=(etat.get("message_pipeline") or exception or "")[:600], details=json.dumps(issues[:40], ensure_ascii=False))
    for k in ("lignes_ok", "lignes_escaladees", "lignes_mal_classees", "lignes_surconfiance", "lignes_perdues", "lignes_fantomes"):
        res[k] = stats.get(k, 0)
    res.update(evaluer_a8(etat, stats, issues))
    res.update(a8_statut=etat.get("statut_a8"), a8_origine=etat.get("origine_a8"),
               a8_constats=json.dumps(etat.get("constats_a8", []), ensure_ascii=False),
               a8_rejetes=json.dumps(etat.get("constats_rejetes_a8", []), ensure_ascii=False),
               a8_notes=json.dumps(etat.get("notes_a8", {}), ensure_ascii=False))
    res["trace"] = json.dumps({"noeuds": trace, "classement": classement_vu(etat),
                               "doublons": [{"date": d["date"], "description": d["description"], "montant": d["montant"],
                                             "origine": d.get("origine")} for d in (etat.get("doublons_a3") or [])[:40]],
                               "exception": exception}, ensure_ascii=False, default=str)
    shutil.rmtree(travail, ignore_errors=True)
    return res


def enregistrer(conn, res: dict):
    cols = list(res)
    conn.execute(f"INSERT OR REPLACE INTO test_runs ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", [res[c] for c in cols])
    conn.commit()


def resultat_plantage(tache: dict, erreur: str) -> dict:
    """Le worker lui-même est tombé (hors du try/except du scénario) : on l'enregistre comme PLANTAGE, le lot continue."""
    s = tache["spec"]
    return dict(id=s["id"], run_id=tache["run_id"], horodatage=datetime.now().isoformat(timespec="seconds"), idx=s["index"],
                type=s["type"], categorie_test=s["categorie_test"], banque=s["banque"], format=s["format"], compte=s["compte"],
                nb_fichiers=len(s["fichiers"]), nb_lignes=len(s["verite"]), statut_attendu=json.dumps(s["attendu"]["statuts"]),
                statut_obtenu="exception", verdict="PLANTAGE", gravite="critique", message=erreur[:600],
                details=json.dumps([dict(type="exception", gravite="critique", detail=erreur[-1500:])]),
                description=s["description"], spec=json.dumps(s, ensure_ascii=False), a8_eval="non_applicable")


# --------------------------------------------------------------------------- #
# Lot piloté
# --------------------------------------------------------------------------- #
def maj_lot(conn, run_id: str, **kw):
    conn.execute(f"UPDATE lots SET {', '.join(k + '=?' for k in kw)} WHERE run_id=?", [*kw.values(), run_id])
    conn.commit()


def commande(conn, run_id: str):
    r = conn.execute("SELECT commande FROM lots WHERE run_id=?", (run_id,)).fetchone()
    return r[0] if r else None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--n", type=int, default=1000)
    ap.add_argument("--workers", type=int, default=max(1, min(4, (os.cpu_count() or 2))))
    ap.add_argument("--source", default=os.path.join(RACINE, "tresorerie.db"))
    ap.add_argument("--reel", action="store_true", help="utilise Claude (ANTHROPIC_API_KEY) au lieu du mode simulé")
    ap.add_argument("--sans-a8", action="store_true", help="désactive le relecteur A8 (pour comparer deux lots)")
    ap.add_argument("--run-id", default=None, help="reprendre un lot existant (les scénarios déjà faits sont sautés)")
    ap.add_argument("--types", default=None, help="filtre : sous-chaînes du type de scénario, séparées par des virgules")
    ap.add_argument("--categories", default=None, help="filtre : nominal,limite,defectueux,chaos (séparés par des virgules)")
    ap.add_argument("--ids", default=None, help="filtre : identifiants exacts de scénarios, séparés par des virgules")
    ap.add_argument("--forcer", action="store_true", help="rejoue même les scénarios déjà faits dans ce lot")
    a = ap.parse_args()

    sys.path.insert(0, RACINE)
    from banc_essai import generateur
    specs = generateur.generer_specs(a.seed, a.n, a.source)
    if a.types:
        specs = [s for s in specs if any(t in s["type"] for t in a.types.split(","))]
    if a.categories:
        specs = [s for s in specs if s["categorie_test"] in a.categories.split(",")]
    if a.ids:
        specs = [s for s in specs if s["id"] in a.ids.split(",")]
    run_id = a.run_id or datetime.now().strftime("%Y%m%d-%H%M%S")
    conn = ouvrir_resultats()
    deja = set() if a.forcer else {r[0] for r in conn.execute("SELECT id FROM test_runs WHERE run_id=?", (run_id,))}
    options = json.dumps(dict(sans_a8=a.sans_a8, forcer=a.forcer), ensure_ascii=False)
    filtre = json.dumps(dict(types=a.types, categories=a.categories, ids=a.ids), ensure_ascii=False)
    if conn.execute("SELECT 1 FROM lots WHERE run_id=?", (run_id,)).fetchone():     # reprise / rejeu partiel : on garde le total du lot
        conn.execute("UPDATE lots SET statut='en cours', commande=NULL, pid=? WHERE run_id=?", (os.getpid(), run_id))
    else:
        conn.execute("INSERT INTO lots (run_id, debut, fin, seed, n, mode, workers, statut, pid, heartbeat, commande, filtre, options) "
                     "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (run_id, datetime.now().isoformat(timespec="seconds"), None, a.seed, len(specs), "reel" if a.reel else "simule",
                      a.workers, "en cours", os.getpid(), datetime.now().isoformat(timespec="seconds"), None, filtre, options))
    conn.commit()
    racine_scn = os.path.join(RACINE, "banc_essai", "scenarios")
    taches = [dict(spec=s, source=a.source, racine_scn=racine_scn, reel=a.reel, run_id=run_id) for s in specs if s["id"] not in deja]
    print(f"Lot {run_id} : {len(taches)} scénario(s) à exécuter ({len(deja)} déjà faits), {a.workers} worker(s), "
          f"mode {'réel' if a.reel else 'simulé'}{', sans A8' if a.sans_a8 else ''}", flush=True)

    t0, n_ok, fait, idx, fin = time.time(), 0, 0, 0, "terminé"
    en_vol: dict = {}
    pause = arret = tuer = False
    dernier_bpm = 0.0
    ctx = mp.get_context("spawn")
    pool = ctx.Pool(a.workers, initializer=init_worker, initargs=(a.reel, a.sans_a8), maxtasksperchild=60)
    try:
        while (idx < len(taches) and not arret) or en_vol:
            cmd = commande(conn, run_id)
            if cmd == "tuer" and not tuer:
                tuer = arret = True
                break
            if cmd == "arreter" and not arret:
                arret = True
                maj_lot(conn, run_id, statut="arrêt en cours")
            elif cmd == "pause" and not pause and not arret:
                pause = True
                maj_lot(conn, run_id, statut="en pause")
            elif cmd == "reprendre" and pause:
                pause = False
                maj_lot(conn, run_id, statut="en cours", commande=None)
            while not pause and not arret and idx < len(taches) and len(en_vol) < a.workers * 2:
                t = taches[idx]
                en_vol[t["spec"]["id"]] = (t, pool.apply_async(executer_un, (t,)))
                idx += 1
            for ident, (t, ar) in list(en_vol.items()):
                if not ar.ready():
                    continue
                del en_vol[ident]
                try:
                    res = ar.get()
                except Exception as e:                      # worker tombé : le lot continue
                    res = resultat_plantage(t, f"{type(e).__name__}: {e}")
                enregistrer(conn, res)
                fait += 1
                n_ok += res["verdict"] == "OK"
                if res["verdict"] != "OK" or fait % 25 == 0:
                    print(f"[{fait:4}/{len(taches)}] {res['verdict']:20} {res['id']:48} attendu={res['statut_attendu']} "
                          f"obtenu={res['statut_obtenu']}", flush=True)
            if time.time() - dernier_bpm >= 1.0:
                maj_lot(conn, run_id, heartbeat=datetime.now().isoformat(timespec="seconds"))
                dernier_bpm = time.time()
            time.sleep(0.05)
        if arret:
            fin = "arrêté"
    except KeyboardInterrupt:
        fin = "interrompu"
    finally:
        pool.terminate()
        pool.join()
        for ident in list(en_vol):                           # scénarios en cours lors d'un arrêt immédiat : leur dossier jetable est nettoyé
            shutil.rmtree(os.path.join(RACINE, "banc_essai", "travail"), ignore_errors=True)
        maj_lot(conn, run_id, fin=datetime.now().isoformat(timespec="seconds"), statut=fin, commande=None,
                heartbeat=datetime.now().isoformat(timespec="seconds"))
    print(f"\n{fin.capitalize()} en {time.time() - t0:.0f} s : {n_ok}/{fait} OK. Lot {run_id} → {chemin_resultats()}", flush=True)


if __name__ == "__main__":
    main()
