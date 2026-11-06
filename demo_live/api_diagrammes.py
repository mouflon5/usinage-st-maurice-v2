"""Données en direct pour les trois diagrammes interactifs (servies par tresorerie_dashboard.py, mode démo).

    GET  /diagrammes/<page>.html          pages statiques (demo_live/diagrammes/)
    GET  /api/diag/etat?run=<id|latest>   passages de la démo, événements du passage choisi, durées moyennes par agent
    GET  /api/diag/rag                    index, journal des questions, dernière évaluation, latences
    POST /api/diag/rag/question           {"question": "..."}  → réponse + trace (journalisée)
    POST /api/diag/rag/evaluer            lance le jeu d'évaluation (mémorisé)
    POST /api/diag/rag/reconstruire       reconstruit l'index
    GET  /api/diag/perf                   performance des agents et des modèles LLM (passages de démo + banc d'essai)
    POST /api/diag/perf/rafale            joue les 12 scénarios à la suite (sans remettre la base à zéro)
"""
from __future__ import annotations

import json
import os
import sqlite3
import statistics
import sys

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RACINE not in sys.path:
    sys.path.insert(0, RACINE)
PAGES = os.path.join(RACINE, "demo_live", "diagrammes")


def _db():
    from demo_live import moteur as M
    chemin = os.environ.get("DEMO_DB") or M.DB_EVENEMENTS
    if not os.path.isfile(chemin):
        return None
    c = sqlite3.connect(chemin, timeout=10)
    c.row_factory = sqlite3.Row
    return c


def page(nom: str) -> bytes | None:
    if not nom.endswith((".html", ".js", ".css")) or "/" in nom or ".." in nom:
        return None
    f = os.path.join(PAGES, nom)
    return open(f, "rb").read() if os.path.isfile(f) else None


def etat(run: str | None) -> dict:
    c = _db()
    if c is None:
        return {"runs": [], "run": None, "evenements": [], "moyennes": {}}
    try:
        runs = [dict(r) for r in c.execute("SELECT run_id, titre, statut, debut, fin, mode, pas_a_pas, periode FROM runs ORDER BY debut DESC")]
        choisi = next((r for r in runs if r["run_id"] == run), runs[0] if runs else None)
        evts = []
        if choisi:
            for r in c.execute("SELECT * FROM evenements WHERE run_id=? ORDER BY id", (choisi["run_id"],)):
                d = dict(r)
                d["detail"] = json.loads(d["detail"]) if d["detail"] else {}
                d["kpi"] = json.loads(d["kpi"]) if d["kpi"] else None
                evts.append(d)
        # durées par agent sur tous les passages (pour situer le passage affiché)
        durees: dict = {}
        for noeud, duree in c.execute("SELECT noeud, duree FROM evenements WHERE type='agent' AND duree IS NOT NULL AND noeud LIKE 'executer_%'"):
            durees.setdefault(noeud[-2:].upper(), []).append(duree)
        moy = {a: {"moyenne": statistics.mean(v), "p90": sorted(v)[min(len(v) - 1, int(len(v) * 0.9))], "n": len(v)} for a, v in durees.items()}
        issues: dict = {}
        for (res,) in c.execute("SELECT resume FROM runs WHERE resume IS NOT NULL"):
            k = json.loads(res).get("statut_pipeline") or "?"
            issues[k] = issues.get(k, 0) + 1
        llm_run = {"appels": 0, "cout": 0.0, "ms": 0.0, "tok": 0, "erreurs": 0, "rejets": 0}
        if choisi:
            try:
                for t, st, d, ci, co, cc in c.execute("SELECT type, statut, duree_ms, tok_in, tok_out, cout FROM llm_appels WHERE run_id=?", (choisi["run_id"],)):
                    if t == "appel":
                        llm_run["appels"] += 1
                        llm_run["cout"] += cc or 0
                        llm_run["ms"] += d or 0
                        llm_run["tok"] += (ci or 0) + (co or 0)
                        llm_run["erreurs"] += st != "ok"
                    elif st != "ok":
                        llm_run["rejets"] += 1
            except sqlite3.OperationalError:
                pass
        return {"runs": runs, "run": choisi, "evenements": evts, "moyennes": moy, "issues": issues, "llm_run": llm_run}
    finally:
        c.close()


def rag_etat() -> dict:
    from demo_live import rag
    if not rag.etat_index().get("existe"):
        rag.construire()
    c = _db()
    out = {"index": rag.etat_index(), "requetes": [], "eval": None}
    if c is None:
        return out
    try:
        rag._tables_journal(c)
        out["requetes"] = [{**dict(r), "trace": json.loads(r["trace"])} for r in
                           c.execute("SELECT * FROM rag_requetes ORDER BY id DESC LIMIT 40")]
        lot = c.execute("SELECT lot FROM rag_eval ORDER BY id DESC LIMIT 1").fetchone()
        if lot:
            rows = [dict(r) for r in c.execute("SELECT genre, question, attendu, ok, rang, ms FROM rag_eval WHERE lot=?", (lot[0],))]
            out["eval"] = {"lot": lot[0], "lignes": rows}
        out["nb_lots"] = c.execute("SELECT COUNT(DISTINCT lot) FROM rag_eval").fetchone()[0]
    finally:
        c.close()
    return out


_RAFALE = {"proc": None, "debut": None}


def _quant(v: list, p: float):
    if not v:
        return None
    s = sorted(v)
    return s[min(len(s) - 1, int(len(s) * p))]


def _classe(statut):
    if statut in (None, "complet", "approuve", "ok", "approuver"):
        return "ok"
    if statut in ("reserves", "a_arbitrer", "degrade", "indisponible", "complet_avec_reserves"):
        return "res"
    return "stop"


def perf() -> dict:
    """Statistiques de performance : agents, modèles LLM, garde-fous, conformité, banc d'essai."""
    from demo_live import moteur as M
    from demo_live.repetition import ATTENDU
    out: dict = {"agents": {}, "runs": {}, "llm": [], "gardes": [], "classement": {}, "controles": {}, "bench": None,
                 "rafale": _rafale_etat()}
    c = _db()
    if c is None:
        return out
    try:
        runs = [dict(r) for r in c.execute("SELECT run_id, titre, scenario, mode, statut, debut, fin, resume FROM runs ORDER BY debut")]
        ids = [r["run_id"] for r in runs]
        # ---- agents
        ag: dict = {}
        evts_a3, ctrl = [], {}
        for r in c.execute("SELECT run_id, noeud, statut, duree, message, detail FROM evenements WHERE type='agent' AND noeud LIKE 'executer_%' ORDER BY id"):
            k = r["noeud"][-2:].upper()
            d = ag.setdefault(k, {"n": 0, "ok": 0, "res": 0, "stop": 0, "durees": [], "motifs": {}})
            d["n"] += 1
            cl = _classe(r["statut"])
            d[cl] += 1
            if r["duree"] is not None:
                d["durees"].append(r["duree"])
            if cl != "ok":
                m = (r["statut"] or "?") if cl == "res" else (r["message"] or r["statut"] or "?")[:90]
                d["motifs"][m] = d["motifs"].get(m, 0) + 1
            det = json.loads(r["detail"]) if r["detail"] else {}
            if k == "A3":
                evts_a3.append(det)
            if k == "A6":
                for x in (det.get("resume") or {}).get("controles", []):
                    z = ctrl.setdefault(x["id"], {"libelle": x.get("libelle"), "n": 0, "ok": 0})
                    z["n"] += 1
                    z["ok"] += bool(x.get("ok"))
        nb_runs = len(runs)
        for k, d in ag.items():
            v = d.pop("durees")
            d.update(p50=_quant(v, .5), p90=_quant(v, .9), max=max(v) if v else None, moy=sum(v) / len(v) if v else None,
                     serie=v[-30:], atteint=round(d["n"] / nb_runs, 3) if nb_runs else None,
                     motifs=sorted(d["motifs"].items(), key=lambda x: -x[1])[:4])
        out["agents"] = ag
        out["controles"] = ctrl
        # ---- passages
        issues, conformes, mesures, durees_run = {}, 0, 0, []
        for r in runs:
            res = json.loads(r["resume"]) if r["resume"] else {}
            iss = res.get("statut_pipeline")
            if iss:
                issues[iss] = issues.get(iss, 0) + 1
            att = ATTENDU.get(r["scenario"])
            if att and iss:
                mesures += 1
                conformes += iss in att[0]
            if r["debut"] and r["fin"]:
                try:
                    from datetime import datetime
                    f = "%Y-%m-%dT%H:%M:%S"
                    durees_run.append((datetime.strptime(r["fin"][:19], f) - datetime.strptime(r["debut"][:19], f)).total_seconds())
                except Exception:
                    pass
        out["runs"] = {"n": nb_runs, "issues": issues, "conformes": conformes, "mesures": mesures,
                       "duree_p50": _quant(durees_run, .5), "duree_p90": _quant(durees_run, .9),
                       "reel": sum(1 for r in runs if r["mode"] == "réel")}
        # ---- répartition du classement (règles / LLM / à classer)
        rep = {"regle": 0, "llm": 0, "simule": 0, "a_classer": 0, "doublons": 0}
        for d in evts_a3:
            for x in d.get("classees", []):
                rep[x.get("methode") if x.get("methode") in rep else "regle"] += 1
            rep["a_classer"] += len(d.get("a_classer", []))
            rep["doublons"] += len(d.get("doublons", []))
        out["classement"] = rep
        # ---- LLM
        try:
            lignes = [dict(r) for r in c.execute("SELECT * FROM llm_appels ORDER BY id")]
        except sqlite3.OperationalError:
            lignes = []
        grp: dict = {}
        gar: dict = {}
        conf = []
        par_run: dict = {}
        for l in lignes:
            meta = json.loads(l["meta"]) if l["meta"] else {}
            if l["type"] == "garde":
                g = gar.setdefault((l["agent"], l["modele"]), {"agent": l["agent"], "garde": l["modele"], "n": 0, "rejets": 0, "raisons": {}})
                g["n"] += 1
                if l["statut"] != "ok":
                    g["rejets"] += 1
                    rz = str(meta.get("raison") or meta.get("non_sources") or meta.get("hors_source") or "?")[:70]
                    g["raisons"][rz] = g["raisons"].get(rz, 0) + 1
                continue
            k = (l["agent"], l["modele"], l["mode"])
            g = grp.setdefault(k, {"agent": l["agent"], "modele": l["modele"], "mode": l["mode"], "n": 0, "erreurs": 0, "ms": [],
                                   "tok_in": 0, "tok_out": 0, "estimes": 0, "cout": 0.0, "acceptes": 0, "avec_decision": 0, "conf": []})
            g["n"] += 1
            g["erreurs"] += l["statut"] != "ok"
            g["ms"].append(l["duree_ms"])
            g["tok_in"] += l["tok_in"] or 0
            g["tok_out"] += l["tok_out"] or 0
            g["estimes"] += l["estime"] or 0
            g["cout"] += l["cout"] or 0
            if "accepte" in meta:
                g["avec_decision"] += 1
                g["acceptes"] += bool(meta["accepte"])
            if meta.get("confiance") is not None:
                g["conf"].append(meta["confiance"])
                conf.append(meta["confiance"])
            pr = par_run.setdefault(l["run_id"], {"run_id": l["run_id"], "appels": 0, "cout": 0.0, "ms": 0.0})
            pr["appels"] += 1
            pr["cout"] += l["cout"] or 0
            pr["ms"] += l["duree_ms"] or 0
        for g in grp.values():
            ms = g.pop("ms")
            g.update(p50=_quant(ms, .5), p95=_quant(ms, .95), max=max(ms) if ms else None, conf_moy=(sum(g["conf"]) / len(g["conf"])) if g["conf"] else None)
            g.pop("conf")
        for g in gar.values():
            g["raisons"] = sorted(g["raisons"].items(), key=lambda x: -x[1])[:3]
        out["llm"] = sorted(grp.values(), key=lambda g: g["agent"])
        out["gardes"] = sorted(gar.values(), key=lambda g: g["agent"])
        out["confiance"] = [round(sum(1 for v in conf if i / 10 <= v < (i + 1) / 10 or (i == 9 and v == 1.0))) for i in range(10)]
        out["llm_par_passage"] = [par_run[i] for i in ids if i in par_run][-30:]
    finally:
        c.close()
    out["bench"] = _bench()
    try:
        _ops(out)
    except Exception as e:          # la page doit toujours s'afficher
        out["ops_erreur"] = f"{type(e).__name__}: {e}"
    return out


CRITERES_SEUILS = {"conformite": 1.0, "bench_ok": 0.95, "fantomes": 0, "surconfiance": 0, "rag": 0.95, "p90_passage_s": 30.0, "cout_passage": 0.10, "pannes_llm": 0.05}


def config_en_vigueur() -> dict:
    """Ce qu'on publie : modèles, seuils, paramètres du RAG — la « version » évaluée par la porte de qualité."""
    g = os.getenv
    return {
        "A3": {"modele": g("A3_MODELE", "claude-haiku-5-5"), "seuil_confiance": float(g("A3_SEUIL_CONFIANCE", "0.8"))},
        "A5": {"modele": g("A5_MODELE", "claude-sonnet-5-5")},
        "A7": {"modele": g("A7_MODELE", "claude-sonnet-5-5")},
        "A8": {"modele": g("A8_MODELE", "claude-sonnet-5-5"), "actif": g("A8_ACTIF", "1") != "0", "echec_est_reserve": g("A8_ECHEC_EST_RESERVE", "1") != "0"},
        "RAG": {"modele": g("RAG_MODELE", "claude-sonnet-5-5"), "top_k": 5, "seuil_couverture": [0.5, 1.0, 0.8], "recherche": "FTS5/BM25"},
        "A6": {"controles": 11},
        "mode_llm": g("LLM_MODE", "auto"),
    }


def _ops(out: dict) -> None:
    """Boucle LLM Ops : traces, juge, évaluation du RAG, diagnostic, porte de qualité, publications."""
    import hashlib
    c = _db()
    if c is None:
        out.update(traces=[], juge=None, rag_eval=None, diagnostic={"demo": [], "agents": {}, "bench": []}, porte={"criteres": [], "autorise": False}, publications=[], config=config_en_vigueur())
        return
    try:
        runs = [dict(r) for r in c.execute("SELECT run_id, titre, scenario, mode, statut, debut, fin, resume FROM runs ORDER BY debut")]
        evs: dict = {}
        for r in c.execute("SELECT run_id, type, noeud, statut, duree, message, detail FROM evenements ORDER BY id"):
            evs.setdefault(r["run_id"], []).append(dict(r))
        try:
            llm = [dict(r) for r in c.execute("SELECT run_id, type, agent, mode, duree_ms, tok_in, tok_out, cout, statut FROM llm_appels")]
        except sqlite3.OperationalError:
            llm = []
        # ---- traces (20 derniers passages)
        par_run: dict = {}
        for l in llm:
            if l["type"] != "appel":
                continue
            z = par_run.setdefault(l["run_id"], {}).setdefault(l["agent"], {"n": 0, "ms": 0.0, "cout": 0.0, "tok_in": 0, "tok_out": 0, "erreurs": 0})
            z["n"] += 1; z["ms"] += l["duree_ms"] or 0; z["cout"] += l["cout"] or 0; z["tok_in"] += l["tok_in"] or 0; z["tok_out"] += l["tok_out"] or 0; z["erreurs"] += l["statut"] != "ok"
        traces = []
        for r in reversed(runs[-20:]):
            res = json.loads(r["resume"]) if r["resume"] else {}
            etapes = []
            for e in evs.get(r["run_id"], []):
                if e["type"] == "agent" and e["noeud"].startswith("executer_"):
                    k = e["noeud"][-2:].upper()
                    etapes.append({"agent": k, "statut": e["statut"], "classe": _classe(e["statut"]), "duree": e["duree"], "message": (e["message"] or "")[:110], "llm": par_run.get(r["run_id"], {}).get(k)})
                elif e["type"] == "agent" and e["noeud"] == "approbation_humaine":
                    etapes.append({"agent": "Humain", "statut": "approuve", "classe": "ok", "duree": e["duree"], "message": (e["message"] or "")[:110], "llm": None})
            tot = par_run.get(r["run_id"], {}).values()
            traces.append({"run_id": r["run_id"], "titre": r["titre"], "scenario": r["scenario"], "mode": r["mode"], "debut": r["debut"], "issue": res.get("statut_pipeline"),
                           "message": (res.get("message") or "")[:160], "etapes": etapes, "appels": sum(z["n"] for z in tot), "cout": sum(z["cout"] for z in tot),
                           "tok": sum(z["tok_in"] + z["tok_out"] for z in tot), "erreurs": sum(z["erreurs"] for z in tot),
                           "rejets": sum(1 for l in llm if l["run_id"] == r["run_id"] and l["type"] == "garde" and l["statut"] != "ok")})
        out["traces"] = traces
        # ---- juge LLM = notes de la relecture A8
        notes: dict = {}
        for rid, lst in evs.items():
            for e in lst:
                if e["type"] == "agent" and e["noeud"] == "executer_a8":
                    d = json.loads(e["detail"]) if e["detail"] else {}
                    for k, v in (((d.get("resume") or {}).get("relecture") or {}).get("notes") or {}).items():
                        if isinstance(v, (int, float)):
                            notes.setdefault(k, []).append(v)
        out["juge"] = {"n": max((len(v) for v in notes.values()), default=0), "moy": {k: sum(v) / len(v) for k, v in notes.items()}, "min": {k: min(v) for k, v in notes.items()}} if notes else None
        # ---- évaluation du RAG
        try:
            lot = c.execute("SELECT lot FROM rag_eval ORDER BY id DESC LIMIT 1").fetchone()
            rows = [dict(r) for r in c.execute("SELECT genre, ok, rang, ms FROM rag_eval WHERE lot=?", (lot[0],))] if lot else []
        except sqlite3.OperationalError:
            rows = []
        if rows:
            genres: dict = {}
            for x in rows:
                z = genres.setdefault(x["genre"], [0, 0]); z[0] += 1; z[1] += x["ok"]
            out["rag_eval"] = {"n": len(rows), "ok": sum(x["ok"] for x in rows), "genres": {g: {"n": v[0], "ok": v[1]} for g, v in genres.items()}, "ms_p50": _quant([x["ms"] for x in rows], .5)}
        else:
            out["rag_eval"] = None
        # ---- diagnostic : où et pourquoi la chaîne a rompu
        diag, pareto = [], {}
        for r in runs:
            res = json.loads(r["resume"]) if r["resume"] else {}
            iss = res.get("statut_pipeline")
            if not iss or _classe(iss) == "ok":
                continue
            cause = None
            for e in evs.get(r["run_id"], []):
                if e["type"] == "agent" and e["noeud"].startswith("executer_") and _classe(e["statut"]) != "ok":
                    cause = e
            ag = cause["noeud"][-2:].upper() if cause else "?"
            pareto.setdefault(ag, {"stop": 0, "res": 0})[_classe(iss)] += 1
            diag.append({"run_id": r["run_id"], "titre": r["titre"], "issue": iss, "classe": _classe(iss), "agent": ag, "motif": ((cause or {}).get("message") or res.get("message") or "")[:150]})
        out["diagnostic"] = {"demo": diag[-25:][::-1], "agents": pareto, "bench": (out.get("bench") or {}).get("echecs", [])}
        # ---- porte de qualité
        S_ = CRITERES_SEUILS
        crit = []

        def ajouter(id_, lib, val, seuil, ok, fmt, bloquant=True, note=None):
            crit.append({"id": id_, "libelle": lib, "valeur": val, "seuil": seuil, "ok": ok, "fmt": fmt, "bloquant": bloquant, "note": note})
        R = out["runs"]
        ajouter("conformite", "Passages de démo conformes à l'attendu", (R["conformes"] / R["mesures"]) if R["mesures"] else None, S_["conformite"], (R["conformes"] / R["mesures"] >= S_["conformite"]) if R["mesures"] else None, "pct", note="Jouer la rafale de 12 scénarios" if not R["mesures"] else None)
        B = out.get("bench")
        if B:
            ajouter("bench_ok", "Banc d'essai : verdict OK", B["verdicts"].get("OK", 0) / B["n"], S_["bench_ok"], B["verdicts"].get("OK", 0) / B["n"] >= S_["bench_ok"], "pct")
            ajouter("fantomes", "Lignes fantômes (inventées)", B["lignes"]["fantomes"], S_["fantomes"], B["lignes"]["fantomes"] <= S_["fantomes"], "nb")
            ajouter("surconfiance", "Lignes mal classées en surconfiance", B["lignes"]["surconfiance"], S_["surconfiance"], B["lignes"]["surconfiance"] <= S_["surconfiance"], "nb")
        else:
            for id_, lib in (("bench_ok", "Banc d'essai : verdict OK"), ("fantomes", "Lignes fantômes (inventées)"), ("surconfiance", "Lignes mal classées en surconfiance")):
                ajouter(id_, lib, None, S_[id_], None, "pct" if id_ == "bench_ok" else "nb", note="Lancer le banc d'essai")
        RE = out["rag_eval"]
        ajouter("rag", "Évaluation du RAG : questions réussies", (RE["ok"] / RE["n"]) if RE else None, S_["rag"], (RE["ok"] / RE["n"] >= S_["rag"]) if RE else None, "pct", note=None if RE else "Cliquer sur « Évaluer » dans le diagramme RAG")
        ajouter("p90", "Durée p90 d'un passage (s)", R["duree_p90"], S_["p90_passage_s"], (R["duree_p90"] <= S_["p90_passage_s"]) if R["duree_p90"] is not None else None, "s")
        couts = [t["cout"] for t in traces if t["appels"]]
        ajouter("cout", "Coût équivalent moyen par passage ($)", (sum(couts) / len(couts)) if couts else None, S_["cout_passage"], (sum(couts) / len(couts) <= S_["cout_passage"]) if couts else None, "usd")
        reel = [g for g in out["llm"] if g["mode"] == "reel"]
        nr = sum(g["n"] for g in reel)
        ajouter("pannes", "Pannes du LLM en mode réel", (sum(g["erreurs"] for g in reel) / nr) if nr else None, S_["pannes_llm"], (sum(g["erreurs"] for g in reel) / nr <= S_["pannes_llm"]) if nr else None, "pct", bloquant=False, note=None if nr else "Non mesurable en mode simulé")
        out["porte"] = {"criteres": crit, "autorise": all(x["ok"] is True for x in crit if x["bloquant"]), "seuils": S_}
        # ---- publications
        c.execute("CREATE TABLE IF NOT EXISTS publications(id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, version TEXT, empreinte TEXT, config TEXT, porte TEXT, note TEXT)")
        cfg = config_en_vigueur()
        out["config"] = {"valeurs": cfg, "empreinte": hashlib.sha1(json.dumps(cfg, sort_keys=True).encode()).hexdigest()[:10]}
        out["publications"] = [dict(r) for r in c.execute("SELECT id, ts, version, empreinte, note FROM publications ORDER BY id DESC LIMIT 10")]
    finally:
        c.close()


def publier(note: str = "") -> dict:
    """Publication maîtrisée : refusée tant que la porte de qualité n'est pas franchie."""
    import hashlib
    import time as _t
    p = perf()
    if not p.get("porte", {}).get("autorise"):
        return {"ok": False, "erreur": "La porte de qualité n'est pas franchie.", "bloquants": [x["libelle"] for x in p["porte"]["criteres"] if x["bloquant"] and x["ok"] is not True]}
    cfg = config_en_vigueur()
    emp = hashlib.sha1(json.dumps(cfg, sort_keys=True).encode()).hexdigest()[:10]
    c = _db()
    try:
        c.execute("CREATE TABLE IF NOT EXISTS publications(id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, version TEXT, empreinte TEXT, config TEXT, porte TEXT, note TEXT)")
        n = c.execute("SELECT COUNT(*) FROM publications").fetchone()[0] + 1
        c.execute("INSERT INTO publications(ts, version, empreinte, config, porte, note) VALUES (?,?,?,?,?,?)",
                  (_t.strftime("%Y-%m-%dT%H:%M:%S"), f"v{n}", emp, json.dumps(cfg), json.dumps(p["porte"]["criteres"], default=str), note[:200]))
        c.commit()
    finally:
        c.close()
    return {"ok": True, "version": f"v{n}", "empreinte": emp}


def _bench():
    """Résumé du banc d'essai (banc_essai/resultats/resultats.db) s'il existe : qualité sur de nombreux scénarios."""
    chemin = os.path.join(RACINE, "banc_essai", "resultats", "resultats.db")
    if not os.path.isfile(chemin):
        return None
    try:
        c = sqlite3.connect(chemin, timeout=10)
        c.row_factory = sqlite3.Row
        try:
            rows = [dict(r) for r in c.execute("SELECT * FROM test_runs")]
            lots = [dict(r) for r in c.execute("SELECT * FROM lots ORDER BY debut DESC")]
        finally:
            c.close()
    except Exception:
        return None
    if not rows:
        return None
    verd: dict = {}
    par_cat: dict = {}
    durees: dict = {}
    for r in rows:
        verd[r["verdict"]] = verd.get(r["verdict"], 0) + 1
        k = par_cat.setdefault(r["categorie_test"] or r["type"] or "?", {"n": 0, "ok": 0})
        k["n"] += 1
        k["ok"] += r["verdict"] == "OK"
        try:
            for a, v in json.loads(r["durees_agents"] or "{}").items():
                durees.setdefault(a, []).append(v)
        except Exception:
            pass
    som = lambda c: sum((r[c] or 0) for r in rows)
    a8 = {"justes": sum((r.get("a8_lignes_justes") or 0) for r in rows), "total": sum((r.get("a8_lignes_total") or 0) for r in rows)}
    echecs = [{"id": r["id"], "type": r["type"], "categorie": r["categorie_test"], "verdict": r["verdict"], "agent": r["agent_arret"], "statut": r["statut_obtenu"], "message": (r["message"] or "")[:140]}
              for r in rows if r["verdict"] != "OK"][:25]
    return {"n": len(rows), "lots": len(lots), "verdicts": verd, "a8": a8, "echecs": echecs,
            "par_categorie": sorted(({"categorie": k, **v} for k, v in par_cat.items()), key=lambda x: x["categorie"]),
            "lignes": {"ok": som("lignes_ok"), "escaladees": som("lignes_escaladees"), "mal_classees": som("lignes_mal_classees"),
                       "surconfiance": som("lignes_surconfiance"), "perdues": som("lignes_perdues"), "fantomes": som("lignes_fantomes")},
            "durees": {a: {"p50": _quant(v, .5), "p90": _quant(v, .9), "n": len(v)} for a, v in durees.items() if v and isinstance(v[0], (int, float))},
            "duree_s": {"p50": _quant([r["duree_s"] for r in rows if r["duree_s"] is not None], .5), "p90": _quant([r["duree_s"] for r in rows if r["duree_s"] is not None], .9)},
            "jetons": {"entree": som("jetons_entree"), "sortie": som("jetons_sortie")},
            "modes": sorted({l["mode"] for l in lots if l.get("mode")})}


def _rafale_etat() -> dict:
    p = _RAFALE["proc"]
    return {"en_cours": bool(p and p.poll() is None), "debut": _RAFALE["debut"]}


def lancer_rafale() -> dict:
    import subprocess
    from demo_live import moteur as M
    if _rafale_etat()["en_cours"] or M.run_actif():
        return {"ok": False, "erreur": "Un scénario ou une rafale est déjà en cours."}
    _RAFALE["proc"] = subprocess.Popen([sys.executable, "-m", "demo_live.repetition", "--garder", "--sans-reset"], cwd=RACINE,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=dict(os.environ))
    import time as _t
    _RAFALE["debut"] = _t.strftime("%H:%M:%S")
    return {"ok": True}


def post(chemin: str, corps: dict) -> dict:
    if chemin == "/api/diag/perf/rafale":
        return lancer_rafale()
    if chemin == "/api/diag/perf/publier":
        return publier((corps.get("note") or ""))
    from demo_live import rag
    os.environ.setdefault("SUIVI_DB", os.environ.get("DEMO_DB", ""))
    os.environ["SUIVI_RUN"] = "rag"
    if chemin == "/api/diag/rag/question":
        q = (corps.get("question") or "").strip()[:500]
        if not q:
            return {"ok": False, "erreur": "question vide"}
        r = rag.repondre(q, reel=bool(corps.get("reel")))
        return {"ok": True, "reponse": r["reponse"], "refus": r["refus"], "mode": r["mode"], "trace": r["trace"]}
    if chemin == "/api/diag/rag/evaluer":
        res = rag.evaluer()
        return {"ok": True, "n": len(res), "reussies": sum(1 for x in res if x["ok"])}
    if chemin == "/api/diag/rag/reconstruire":
        return {"ok": True, "passages": rag.construire()}
    return {"ok": False, "erreur": "inconnu"}
