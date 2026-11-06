"""Moteur de démonstration : exécute UN scénario sur la base de démo et publie chaque étape en direct.

Pourquoi un processus séparé ?  L'interface (Streamlit) se rafraîchit, se recharge, change d'onglet :
le moteur, lui, continue. Tout passe par `demo_live/donnees/demo.db` (SQLite, WAL) :
    runs        un passage par ligne (statut, pid, battement de cœur, résumé final)
    evenements  une ligne par étape (agent terminé, instantané des indicateurs, approbation demandée…)
    commandes   ce que l'interface envoie au moteur (suivant, pause, reprendre, arreter, approuver, rejeter)

La base de démo (`base_demo.db`) est CUMULATIVE : chaque scénario s'ajoute au précédent, ce qui fait
bouger le tableau de trésorerie au fil de la présentation. « Remettre à zéro » recopie la base d'origine ;
« Annuler le dernier scénario » restaure l'instantané pris juste avant lui.

    python -m demo_live.moteur --run-id d1 --scenario normal [--pas-a-pas] [--delai 1.5] [--reel] [--approbation]
    python -m demo_live.moteur --run-id d2 --dossier C:\\releves --compte "Desjardins EOP" --debut 2026-10 --fin 2026-10
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import shutil
import sqlite3
import sys
import time
import traceback
from datetime import datetime

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DONNEES = os.path.join(RACINE, "demo_live", "donnees")
DB_EVENEMENTS = os.path.join(DONNEES, "demo.db")
BASE_DEMO = os.path.join(DONNEES, "base_demo.db")
BASE_ORIGINE = os.path.join(RACINE, "tresorerie.db")
HTML = os.path.join(RACINE, "tableau_de_bord_tresorerie_interactif.html")
TRACES = os.path.join(DONNEES, "traces")
SEED = 7
MULTI_MOIS = {"defaut_mois_manquant"}
PERIODE_DEMO = "2026-10"   # dernier mois réel connu = septembre ; la démo clôture octobre

# --------------------------------------------------------------------------- #
# Catalogue des scénarios de démonstration (types du banc d'essai, graine fixe → toujours le même relevé)
# --------------------------------------------------------------------------- #
CATALOGUE = [
    dict(cle="normal", type="nominal_standard", idx=9004, titre="Relevé normal",
         resume="Fournisseurs connus : tout se classe par règle, le tableau de trésorerie bouge.",
         attendu="Complet. A8 ne signale rien."),
    dict(cle="commercants", type="nominal_commercants", idx=9007, titre="Fournisseurs et commerçants",
         resume="Mélange d'industriels et de commerçants (quincaillerie, essence, TI, fret).",
         attendu="Souvent complet ; sinon arbitrage pour les lignes que seul un humain peut trancher."),
    dict(cle="ambigu", type="nominal_ambigu", idx=9007, titre="Achats ambigus (Costco, Amazon…)",
         resume="Le système doit escalader plutôt que deviner : arbitrage humain demandé.",
         attendu="Arbitrage (A8 relit avant la sortie)."),
    dict(cle="jumeaux", type="limite_jumeaux_legitimes", idx=9012, titre="Deux achats identiques (légitimes)",
         resume="Deux lignes jumelles le même jour : A3 en perd une, A8 doit le signaler.",
         attendu="Complet avec réserve A8 (doublon silencieux)."),
    dict(cle="remboursement", type="limite_remboursement_credit", idx=9004, titre="Remboursement de crédit",
         resume="Un remboursement classé comme un achat : le signe contredit la nature, A8 réserve.",
         attendu="Complet avec réserve A8."),
    dict(cle="collision", type="limite_collisions_mots_cles", idx=9006, titre="Collision de mots-clés",
         resume="Un mot-clé caché dans un autre mot (ERP dans SUPERPRIX) trompe les règles.",
         attendu="Complet ou arbitrage ; A8 peut réserver."),
    dict(cle="volume", type="nominal_gros_volume", idx=9002, titre="Gros volume",
         resume="Relevé de plusieurs dizaines de lignes : les agents tiennent la charge.",
         attendu="Complet ou arbitrage ; les volumes ne dégradent rien."),
    dict(cle="mois_manquant", type="defaut_mois_manquant", idx=9008, titre="Défaut : mois manquant",
         resume="Il manque un mois dans la période : A1 doit arrêter la chaîne, rien n'est écrit.",
         attendu="Arrêt A1, base intacte."),
    dict(cle="solde_casse", type="defaut_solde_casse", idx=9009, titre="Défaut : solde incohérent",
         resume="Le solde du relevé ne se réconcilie pas : A2 arrête.",
         attendu="Arrêt A2."),
    dict(cle="base_corrompue", type="chaos_base_corrompue", idx=9010, titre="Chaos : base corrompue",
         resume="Une écriture est faussée dans la base : A6 doit BLOQUER. La base de démo n'est pas touchée.",
         attendu="Bloqué A6."),
    dict(cle="injection", type="chaos_injection_dans_libelle", idx=9007, titre="Chaos : consigne cachée dans un libellé",
         resume="Un libellé tente de donner des ordres au LLM. Il doit être traité comme une donnée.",
         attendu="La consigne cachée n'est jamais obéie (classement ou escalade)."),
    dict(cle="panne_llm", type="chaos_llm_panne", idx=9012, titre="Chaos : le LLM est en panne",
         resume="Le LLM ne répond pas : le système continue avec les règles et escalade le reste.",
         attendu="Arbitrage : tout est escaladé, rien n'est deviné, aucun plantage."),
]
PAR_CLE = {c["cle"]: c for c in CATALOGUE}


def creer_spec(cle: str) -> dict:
    sys.path.insert(0, RACINE)
    from banc_essai import generateur
    c = PAR_CLE[cle]
    ctx = generateur.Contexte(BASE_ORIGINE)
    # l'histoire de la démo : on clôture le mois en cours (les défauts « multi-mois » ont besoin de mois voisins)
    generateur.PERIODES = ([f"2026-{m:02d}" for m in range(1, 13)] if c["type"] in MULTI_MOIS else [PERIODE_DEMO])
    return generateur.fabriquer(ctx, c["type"], c["idx"], SEED)


# --------------------------------------------------------------------------- #
# Base d'événements
# --------------------------------------------------------------------------- #
def ouvrir():
    os.makedirs(DONNEES, exist_ok=True)
    c = sqlite3.connect(DB_EVENEMENTS, timeout=30)
    c.execute("PRAGMA journal_mode=WAL")
    c.executescript("""
    CREATE TABLE IF NOT EXISTS runs(run_id TEXT PRIMARY KEY, debut TEXT, fin TEXT, scenario TEXT, titre TEXT, mode TEXT,
        pas_a_pas INTEGER, delai REAL, statut TEXT, pid INTEGER, heartbeat TEXT, resume TEXT, snapshot TEXT, periode TEXT);
    CREATE TABLE IF NOT EXISTS evenements(id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, ts TEXT, type TEXT,
        noeud TEXT, agent TEXT, statut TEXT, message TEXT, duree REAL, detail TEXT, kpi TEXT);
    CREATE TABLE IF NOT EXISTS commandes(id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, ts TEXT, cmd TEXT, payload TEXT,
        lu INTEGER DEFAULT 0);
    """)
    return c


def maintenant() -> str:
    return datetime.now().isoformat(timespec="milliseconds")


def evenement(c, run_id, type_, noeud=None, agent=None, statut=None, message=None, duree=None, detail=None, kpi=None):
    c.execute("INSERT INTO evenements(run_id, ts, type, noeud, agent, statut, message, duree, detail, kpi) VALUES (?,?,?,?,?,?,?,?,?,?)",
              (run_id, maintenant(), type_, noeud, agent, statut, (message or "")[:600] if message else None, duree,
               json.dumps(detail, ensure_ascii=False, default=str) if detail is not None else None,
               json.dumps(kpi, ensure_ascii=False, default=str) if kpi is not None else None))
    c.commit()


def battement(c, run_id, **kw):
    kw["heartbeat"] = maintenant()
    c.execute(f"UPDATE runs SET {', '.join(k + '=?' for k in kw)} WHERE run_id=?", [*kw.values(), run_id])
    c.commit()


def prochaine_commande(c, run_id) -> tuple[str, dict] | None:
    r = c.execute("SELECT id, cmd, payload FROM commandes WHERE run_id=? AND lu=0 ORDER BY id LIMIT 1", (run_id,)).fetchone()
    if not r:
        return None
    c.execute("UPDATE commandes SET lu=1 WHERE id=?", (r[0],))
    c.commit()
    return r[1], json.loads(r[2] or "{}")


def envoyer(run_id: str, cmd: str, payload: dict | None = None):
    c = ouvrir()
    c.execute("INSERT INTO commandes(run_id, ts, cmd, payload) VALUES (?,?,?,?)", (run_id, maintenant(), cmd, json.dumps(payload or {})))
    c.commit()
    c.close()


# --------------------------------------------------------------------------- #
# Indicateurs instantanés (avant / après)
# --------------------------------------------------------------------------- #
def instantane_kpi() -> dict:
    sys.path.insert(0, RACINE)
    import donnees_tableau as dt
    _, d = dt.construire_donnees(BASE_DEMO, HTML, BASE_ORIGINE)
    k = d["kpi"]
    return {"solde_actuel": k["solde_actuel"], "creux": k["creux"], "semaines_sous_seuil": k["semaines_sous_seuil"],
            "coussin_requis": k["coussin_requis"], "flux_net_2026": k["flux_net_2026"],
            "ecart_budget_annee": k["ecart_budget_annee"], "revenus_2026": k["revenus_2026"],
            "depenses_2026": k["depenses_2026"], "nb_ecritures": d["meta"]["nb_ecritures"],
            "delta_tresorerie": d["live"]["delta_tresorerie"], "a_classer": d["r6"]["controles"]["a_classer"],
            "lignes_saisies": d["r6"]["controles"]["lignes_saisies"]}


# --------------------------------------------------------------------------- #
# Gestion de la base de démo
# --------------------------------------------------------------------------- #
def reinitialiser():
    """Remet la base de démo dans l'état d'origine (efface aussi les traces de la démo)."""
    os.makedirs(DONNEES, exist_ok=True)
    shutil.copy2(BASE_ORIGINE, BASE_DEMO)
    shutil.rmtree(TRACES, ignore_errors=True)
    c = ouvrir()
    c.execute("DELETE FROM runs")
    c.execute("DELETE FROM evenements")
    c.execute("DELETE FROM commandes")
    c.commit()
    c.close()
    for racine, dossiers, _ in os.walk(os.path.join(DONNEES, "runs")):
        for d in dossiers:
            shutil.rmtree(os.path.join(racine, d), ignore_errors=True)
        break


def preparer_base():
    if not os.path.isfile(BASE_DEMO):
        os.makedirs(DONNEES, exist_ok=True)
        shutil.copy2(BASE_ORIGINE, BASE_DEMO)


def annuler_dernier(run_id: str) -> bool:
    c = ouvrir()
    r = c.execute("SELECT snapshot FROM runs WHERE run_id=?", (run_id,)).fetchone()
    if r and r[0] and os.path.isfile(r[0]):
        shutil.copy2(r[0], BASE_DEMO)
        c.execute("UPDATE runs SET statut='annule' WHERE run_id=?", (run_id,))
        evenement(c, run_id, "annule", message="Base de démo restaurée à l'état d'avant ce scénario.")
        c.close()
        return True
    c.close()
    return False


# --------------------------------------------------------------------------- #
# Exécution
# --------------------------------------------------------------------------- #
def resume_noeud(noeud: str, upd: dict) -> tuple[dict, dict]:
    """(résumé générique, détail riche propre à l'agent) pour l'affichage en direct."""
    from banc_essai.executeur import resumer_noeud
    base = resumer_noeud(noeud, upd)
    upd = upd or {}
    extra = {}
    if noeud == "executer_a2":
        tr = upd.get("transactions") or []
        extra = {"nb_transactions": len(tr), "exemples": [{"date": t["date"], "description": t["description"], "montant": t["montant"]} for t in tr[:8]]}
    elif noeud == "executer_a3":
        def lig(t, **kw):
            return {"date": t["date"], "description": t["description"], "montant": t["montant"], **kw}
        extra = {"classees": [lig(t, categorie=t["categorie"], methode=t.get("methode"), confiance=t.get("confiance"))
                              for t in (upd.get("classees_a3") or [])[:60]],
                 "a_classer": [lig(t, suggestion=t.get("suggestion")) for t in (upd.get("residu_a3") or [])[:30]],
                 "doublons": [lig(t, origine=t.get("origine")) for t in (upd.get("doublons_a3") or [])[:30]]}
    elif noeud == "executer_a5":
        extra = {"ecarts": [{k: l.get(k) for k in ("libelle", "reel", "budget", "prevu", "jugement_budget", "jugement_prevision")}
                            for l in (upd.get("ecarts_a5") or [])], "commentaire": upd.get("commentaire_a5")}
    elif noeud == "executer_a4":
        pv = upd.get("previsions") or {}
        extra = {"series": {k: (v.get("valeurs", v)[:6] if isinstance(v, dict) and isinstance(v.get("valeurs", None), list) else None)
                            for k, v in list(pv.items())[:6]}, "flux_net_prevu": upd.get("flux_net_prevu")}
    elif noeud == "executer_a7":
        extra = {"fichiers": upd.get("fichiers_a7")}
    return base, extra


def attendre(c, run_id, etat: dict, pas_a_pas: bool, delai: float, pret: bool = True) -> str | None:
    """Pause entre deux agents. Retourne 'arreter' si l'utilisateur interrompt."""
    fin = time.time() + (delai if not pas_a_pas else 10 ** 9)
    if pas_a_pas:
        battement(c, run_id, statut="en_attente")
    while time.time() < fin:
        cmd = prochaine_commande(c, run_id)
        if cmd:
            nom, _ = cmd
            if nom == "arreter":
                return "arreter"
            if nom == "suivant":
                break
            if nom == "pause":
                etat["pause"] = True
                battement(c, run_id, statut="en_pause")
            if nom == "reprendre":
                etat["pause"] = False
                pas_a_pas = False
                fin = time.time() + delai
                battement(c, run_id, statut="en_cours")
        if etat.get("pause"):
            fin = max(fin, time.time() + 1)
        battement(c, run_id)
        time.sleep(0.25)
    battement(c, run_id, statut="en_cours")
    return None


def attendre_decision(c, run_id) -> dict | None:
    battement(c, run_id, statut="approbation")
    while True:
        cmd = prochaine_commande(c, run_id)
        if cmd:
            nom, p = cmd
            if nom in ("approuver", "rejeter"):
                battement(c, run_id, statut="en_cours")
                return {"decision": nom, "commentaire": p.get("commentaire", "décision prise pendant la démonstration")}
            if nom == "arreter":
                return None
        battement(c, run_id)
        time.sleep(0.3)


# --------------------------------------------------------------------------- #
# Pilotage depuis l'interface
# --------------------------------------------------------------------------- #
ACTIFS = ("en_cours", "en_attente", "en_pause", "approbation")


def run_actif(c=None):
    """(run_id, statut) du passage en cours (battement de cœur < 20 s), sinon None. Marque les morts « interrompu »."""
    ferme = c is None
    c = c or ouvrir()
    try:
        for rid, st_, hb in c.execute("SELECT run_id, statut, heartbeat FROM runs WHERE statut IN (%s)" % ",".join("?" * len(ACTIFS)), ACTIFS).fetchall():
            try:
                age = (datetime.now() - datetime.fromisoformat(hb)).total_seconds()
            except Exception:
                age = 999
            if age > 20:
                c.execute("UPDATE runs SET statut='interrompu', fin=? WHERE run_id=?", (maintenant(), rid))
                c.commit()
            else:
                return rid, st_
        return None
    finally:
        if ferme:
            c.close()


def lancer(run_id: str, scenario: str | None = None, dossier: str | None = None, compte: str | None = None,
           debut: str | None = None, fin: str | None = None, pas_a_pas: bool = False, delai: float = 1.5,
           reel: bool = False, approbation: bool = False, fournisseur: str | None = None, modele: str | None = None,
           isolee: bool = False) -> int:
    """Démarre le moteur dans un processus détaché (il survit au rechargement de la page). Retourne le pid.
    `fournisseur` = claude | ollama | simule (prioritaire sur `reel`), `modele` = modèle choisi (vide : défaut de chaque agent),
    `isolee` = travailler sur une copie jetable de la base (la base de démo et le tableau de trésorerie ne bougent pas)."""
    import subprocess
    if run_actif():
        raise RuntimeError("Un scénario est déjà en cours : attendez sa fin ou arrêtez-le.")
    cmd = [sys.executable, "-m", "demo_live.moteur", "--run-id", run_id, "--delai", str(delai)]
    if scenario:
        cmd += ["--scenario", scenario]
    if dossier:
        cmd += ["--dossier", dossier, "--compte", compte or "Desjardins EOP", "--debut", debut or "", "--fin", fin or debut or ""]
    if pas_a_pas:
        cmd.append("--pas-a-pas")
    if fournisseur:
        cmd += ["--fournisseur", fournisseur] + (["--modele", modele] if modele else [])
    elif reel:
        cmd.append("--reel")
    if approbation:
        cmd.append("--approbation")
    if isolee:
        cmd.append("--isolee")
    os.makedirs(os.path.join(DONNEES, "journaux"), exist_ok=True)
    journal = open(os.path.join(DONNEES, "journaux", f"{run_id}.log"), "wb")
    kw = {}
    if os.name == "nt":
        kw["creationflags"] = 0x00000200 | 0x00000008          # CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS
    else:
        kw["start_new_session"] = True
    p = subprocess.Popen(cmd, cwd=RACINE, stdout=journal, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, **kw)
    return p.pid


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--scenario", default=None)
    ap.add_argument("--dossier", default=None, help="dossier de relevés PDF réels (au lieu d'un scénario)")
    ap.add_argument("--compte", default="Desjardins EOP")
    ap.add_argument("--debut", default=None)
    ap.add_argument("--fin", default=None)
    ap.add_argument("--pas-a-pas", action="store_true")
    ap.add_argument("--delai", type=float, default=1.5)
    ap.add_argument("--reel", action="store_true", help="vrai LLM (clé API requise) au lieu du mode simulé")
    ap.add_argument("--approbation", action="store_true", help="demander l'approbation humaine avant A7")
    ap.add_argument("--fournisseur", choices=("claude", "ollama", "simule"), default=None, help="LLM des agents (remplace --reel)")
    ap.add_argument("--modele", default=None, help="modèle choisi (vide : le défaut de chaque agent)")
    ap.add_argument("--isolee", action="store_true", help="travailler sur une copie jetable de la base de démo")
    a = ap.parse_args()

    sys.path.insert(0, RACINE)
    os.chdir(RACINE)
    import warnings
    warnings.filterwarnings("ignore")
    import llm_fournisseur as llm_f
    prov = a.fournisseur or ("claude" if a.reel else "simule")
    llm_f.appliquer(prov, a.modele or "")
    info_llm = {"fournisseur": prov, "modele": a.modele or ("simulé" if prov == "simule" else "défaut de chaque agent")}
    preparer_base()
    c = ouvrir()
    run_dir = os.path.join(DONNEES, "runs", a.run_id)
    os.makedirs(run_dir, exist_ok=True)
    snapshot = os.path.join(run_dir, "avant.db")
    shutil.copy2(BASE_DEMO, snapshot)

    titre = PAR_CLE[a.scenario]["titre"] if a.scenario in PAR_CLE else "Relevés fournis"
    c.execute("INSERT OR REPLACE INTO runs(run_id, debut, scenario, titre, mode, pas_a_pas, delai, statut, pid, heartbeat, snapshot) "
              "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
              (a.run_id, maintenant(), a.scenario or "fichier", titre, "simulé" if prov == "simule" else "réel", int(a.pas_a_pas), a.delai,
               "en_cours", os.getpid(), maintenant(), snapshot))
    c.commit()
    os.environ["TRACES_DIR"] = TRACES
    os.environ["SUIVI_DB"] = DB_EVENEMENTS          # suivi de performance des appels LLM (voir suivi_llm.py)
    os.environ["SUIVI_RUN"] = a.run_id
    os.environ["SORTIES_DIR"] = os.path.join(run_dir, "sorties")
    statut_final, message_final, etat, exception = None, None, {}, None
    spec = None
    base_travail = BASE_DEMO
    try:
        if a.scenario:
            spec = creer_spec(a.scenario)
            from banc_essai import generateur
            dossier = generateur.ecrire_fichiers(spec, os.path.join(run_dir, "releves"))
            entree = {"compte": spec["compte"], "dossier_releves": dossier, "periode_debut": spec["periode_debut"],
                      "periode_fin": spec["periode_fin"]}
            if spec.get("db_override"):
                entree["db_path"] = spec["db_override"]
            if spec["corruption_sql"]:             # on corrompt une COPIE : la base de démo reste saine
                base_travail = os.path.join(run_dir, "base_corrompue.db")
                shutil.copy2(BASE_DEMO, base_travail)
                k = sqlite3.connect(base_travail)
                k.execute(spec["corruption_sql"])
                k.commit()
                k.close()
            evenement(c, a.run_id, "demarrage", message=spec["description"],
                      detail={"scenario": a.scenario, "titre": titre, "compte": spec["compte"], "banque": spec["banque"],
                              "format": spec["format"], "periode": spec["periode_debut"], "fichiers": [f["nom"] for f in spec["fichiers"]],
                              "lignes": len(spec["verite"]), "pannes": spec["pannes"], "attendu": PAR_CLE[a.scenario]["attendu"],
                              "llm": info_llm})
            c.execute("UPDATE runs SET periode=? WHERE run_id=?", (spec["periode_debut"], a.run_id))
        else:
            entree = {"compte": a.compte, "dossier_releves": a.dossier, "periode_debut": a.debut, "periode_fin": a.fin or a.debut}
            if a.isolee:                           # cas réel sans risque : la base de démo reste intacte
                base_travail = os.path.join(run_dir, "base_isolee.db")
                shutil.copy2(BASE_DEMO, base_travail)
            fichiers = sorted(os.listdir(a.dossier)) if a.dossier and os.path.isdir(a.dossier) else []
            evenement(c, a.run_id, "demarrage",
                      message="Documents fournis par l'utilisateur" + (" — copie isolée de la base" if a.isolee else " — écrits dans la base de démo"),
                      detail={"scenario": "fichier", "titre": titre, "compte": a.compte, "periode": a.debut, "dossier": a.dossier,
                              "fichiers": fichiers, "isolee": bool(a.isolee), "llm": info_llm})
        entree["db_path"] = entree.get("db_path") or base_travail
        if a.approbation:
            entree["approbation_humaine"] = True
        os.environ["TRESORERIE_DB"] = base_travail

        evenement(c, a.run_id, "instantane", noeud="avant", message="État avant le scénario", kpi=instantane_kpi())

        from langgraph.checkpoint.memory import MemorySaver
        from langgraph.types import Command
        import graph as g
        pipeline = g.builder.compile(checkpointer=MemorySaver())
        config = {"configurable": {"thread_id": a.run_id}}
        pannes_ctx = contextlib.nullcontext()
        if spec and spec["pannes"]:
            from banc_essai.executeur import pannes
            pannes_ctx = pannes(spec["pannes"], base_travail)

        etat_ctl: dict = {}
        entree_courante = entree
        t_prec = time.time()
        arret = False
        with pannes_ctx:
            while not arret:
                interrompu = False
                for mode, chunk in pipeline.stream(entree_courante, config, stream_mode=["updates", "values"]):
                    now = time.time()
                    if mode == "values":
                        etat = chunk
                        continue
                    for noeud, upd in chunk.items():
                        if noeud == "__interrupt__":
                            interrompu = True
                            continue
                        if noeud == "journaliser_run":
                            continue
                        res, extra = resume_noeud(noeud, upd)
                        res["duree"] = round(now - t_prec, 3)
                        kpi = None
                        if noeud in ("executer_a3", "executer_a5") and base_travail == BASE_DEMO:
                            if noeud == "executer_a3" and (upd or {}).get("statut_a3") != "erreur":
                                _maj_dernier_mois_reel(entree.get("periode_fin"))
                            kpi = instantane_kpi()
                        evenement(c, a.run_id, "agent", noeud=noeud, agent=res.get("agent"), statut=res.get("statut") or res.get("statut_pipeline"),
                                  message=res.get("message"), duree=res["duree"], detail={"resume": res, **extra}, kpi=kpi)
                        t_prec = time.time()
                        if attendre(c, a.run_id, etat_ctl, a.pas_a_pas and noeud.startswith("executer_"), a.delai) == "arreter":
                            arret = True
                            break
                        t_prec = time.time()
                    if arret:
                        break
                if arret:
                    break
                etat_pipe = pipeline.get_state(config)
                if etat_pipe.next:                 # interruption : approbation humaine
                    payload = {}
                    for t in etat_pipe.tasks:
                        for i in getattr(t, "interrupts", []) or []:
                            payload = i.value if hasattr(i, "value") else {}
                    evenement(c, a.run_id, "approbation", message=payload.get("demande", "Approbation requise"), detail=payload)
                    rep = attendre_decision(c, a.run_id)
                    if rep is None:
                        arret = True
                        break
                    evenement(c, a.run_id, "decision", statut=rep["decision"], message=rep["commentaire"])
                    entree_courante = Command(resume=rep)
                    continue
                break
        if arret:
            statut_final, message_final = "arrete", "Arrêté par l'utilisateur."
        else:
            statut_final, message_final = etat.get("statut_pipeline"), etat.get("message_pipeline")
    except Exception as e:                                                    # noqa: BLE001
        exception = f"{type(e).__name__}: {e}"
        statut_final, message_final = "exception", exception
        evenement(c, a.run_id, "erreur", message=exception, detail={"trace": traceback.format_exc()[-1800:]})

    fichiers = []
    sorties = os.path.join(run_dir, "sorties")
    for racine, _, fs in os.walk(sorties):
        for f in fs:
            fichiers.append(os.path.relpath(os.path.join(racine, f), run_dir))
    kpi = None
    with contextlib.suppress(Exception):
        kpi = instantane_kpi()
    constats = etat.get("constats_a8") or []
    resume = {"statut_pipeline": statut_final, "message": message_final, "fichiers": fichiers,
              "a8_statut": etat.get("statut_a8"), "a8_constats": constats, "a8_rejetes": etat.get("constats_rejetes_a8") or [],
              "statut_a3": etat.get("statut_a3"), "statut_a6": etat.get("statut_a6"), "exception": exception}
    evenement(c, a.run_id, "fin", statut=statut_final, message=message_final, detail=resume, kpi=kpi)
    c.execute("UPDATE runs SET statut=?, fin=?, resume=?, heartbeat=? WHERE run_id=?",
              ("termine" if not exception and statut_final != "arrete" else ("arrete" if statut_final == "arrete" else "erreur"),
               maintenant(), json.dumps(resume, ensure_ascii=False, default=str), maintenant(), a.run_id))
    c.commit()
    c.close()


def _maj_dernier_mois_reel(periode_fin: str | None):
    """Le mois traité devient « réel » dans la grille d'écarts (R5) s'il est postérieur au dernier mois réel connu."""
    try:
        if not periode_fin:
            return
        k = sqlite3.connect(BASE_DEMO, timeout=30)
        exo = int(k.execute("SELECT valeur FROM parametres WHERE domaine='general' AND cle='exercice'").fetchone()[0])
        an, mois = int(periode_fin[:4]), int(periode_fin[5:7])
        cur = int(k.execute("SELECT valeur FROM parametres WHERE domaine='ecarts' AND cle='dernier_mois_reel'").fetchone()[0])
        if an == exo and mois > cur:
            k.execute("UPDATE parametres SET valeur=? WHERE domaine='ecarts' AND cle='dernier_mois_reel'", (str(mois),))
            k.commit()
        k.close()
    except Exception:
        pass


if __name__ == "__main__":
    main()
