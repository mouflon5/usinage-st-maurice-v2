"""
Nœuds de l'agent A6 — Contrôle.

Principe : A6 ne fait confiance à aucun agent amont. Il REFAIT les calculs critiques de façon
indépendante (SQL direct, rejeu des soldes, recalcul de la prévision) et compare. Un contrôle
« bloquant » en échec interdit toute sortie ; un contrôle « réserve » en échec laisse passer
avec mention explicite.
"""

import hashlib
import json
import math
import sqlite3
from collections import defaultdict
from pathlib import Path

from a6_state import ControleState
import a5_nodes as a5
from prevision_outils import prevision_a_date

B, R = "bloquant", "reserve"


def _c(cid, libelle, gravite, ok, detail=""):
    return {"id": cid, "libelle": libelle, "gravite": gravite, "ok": bool(ok), "detail": detail}


def controler_node(state: ControleState) -> dict:
    db, per = state["db_path"], state["periode"]
    annee, mois = int(per[:4]), int(per[5:])
    ctl = []
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    q = lambda s, p=(): conn.execute(s, p).fetchall()
    try:
        # C1 intégrité
        qc = q("PRAGMA quick_check")[0][0]
        ctl.append(_c("C1", "Intégrité SQLite (quick_check)", B, qc == "ok", qc))

        # C2 invariants du grand livre
        viol = {
            "nature ≠ categories": q("SELECT COUNT(*) FROM journal_general j JOIN categories c ON c.categorie=j.categorie WHERE j.nature<>c.nature")[0][0],
            "catégorie inconnue": q("SELECT COUNT(*) FROM journal_general WHERE categorie NOT IN (SELECT categorie FROM categories)")[0][0],
            "mois/année ≠ date": q("SELECT COUNT(*) FROM journal_general WHERE CAST(substr(date_ecriture,6,2) AS INT)<>mois OR CAST(substr(date_ecriture,1,4) AS INT)<>annee")[0][0],
            "exercice ≠ FY+année": q("SELECT COUNT(*) FROM journal_general WHERE exercice<>'FY'||annee")[0][0],
            "préfixe no_ecriture": q("SELECT COUNT(*) FROM journal_general WHERE substr(no_ecriture,4,4)<>CAST(annee AS TEXT)")[0][0],
            "montant non fini/nul": q("SELECT COUNT(*) FROM journal_general WHERE montant IS NULL OR montant=0")[0][0],
        }
        mauvais = {k: v for k, v in viol.items() if v}
        ctl.append(_c("C2", "Invariants de journal_general", B, not mauvais, str(mauvais) if mauvais else "6 invariants respectés"))

        # C3 signes
        n_signe = q("SELECT COUNT(*) FROM journal_general WHERE (nature='Revenu' AND montant<0) OR (nature<>'Revenu' AND montant>0)")[0][0]
        ctl.append(_c("C3", "Signe des montants (revenus > 0, charges < 0)", R, n_signe == 0,
                      f"{n_signe} écriture(s) à signe inattendu (notes de crédit ?)" if n_signe else "conforme"))

        # C4 historique
        nm = q("SELECT COUNT(DISTINCT printf('%04d-%02d',annee,mois)) FROM journal_general")[0][0]
        ctl.append(_c("C4", "Historique de 48 mois distincts (exigé par R8/SARIMAX)", B, nm == 48, f"{nm} mois"))

        # C5 traçabilité A2 → base
        trans = state.get("transactions", [])
        manquantes_saisie, manquantes_jg = [], []
        for t in trans:
            cle = f"{t['date']}|{round(t['montant'], 2)}|{t['description']}"
            row = q("SELECT categorie FROM journal_saisie WHERE cle_doublon=? LIMIT 1", (cle,))
            if not row:
                manquantes_saisie.append(cle)
            elif row[0][0] != "À classer":
                if not q("SELECT 1 FROM journal_general WHERE date_ecriture=? AND description=? AND ROUND(montant,2)=ROUND(?,2) LIMIT 1",
                         (t["date"], t["description"], t["montant"])):
                    manquantes_jg.append(cle)
        ctl.append(_c("C5", "Traçabilité : chaque transaction d'A2 est retrouvée en base", B,
                      not manquantes_saisie and not manquantes_jg,
                      f"absentes de journal_saisie: {len(manquantes_saisie)}; classées mais absentes de journal_general: {len(manquantes_jg)}"
                      if (manquantes_saisie or manquantes_jg) else f"{len(trans)} transaction(s) retrouvée(s)"))

        # C6 conservation
        r3 = state.get("resume_a3", {})
        conserve = len(trans) == r3.get("inseres_staging", 0) + r3.get("doublons_ignores", 0)
        ctl.append(_c("C6", "Conservation : transactions A2 = insérées + doublons", B, conserve,
                      f"{len(trans)} = {r3.get('inseres_staging', 0)} + {r3.get('doublons_ignores', 0)}"))

        # C7 rejeu des soldes
        par_fichier = defaultdict(list)
        for t in trans:
            par_fichier[t["fichier"]].append(t)
        ecarts_solde = []
        for f, ts in par_fichier.items():
            ts = sorted(ts, key=lambda t: t["date"])
            ouverture = round(ts[0]["solde"] - ts[0]["montant"], 2)
            attendu = round(ouverture + sum(t["montant"] for t in ts), 2)
            if abs(attendu - ts[-1]["solde"]) > 0.01:
                ecarts_solde.append(f"{f}: attendu {attendu}, déclaré {ts[-1]['solde']}")
        ctl.append(_c("C7", "Rejeu des soldes : ouverture + Σ mouvements = solde de clôture", B,
                      not ecarts_solde, "; ".join(ecarts_solde) if ecarts_solde else f"{len(par_fichier)} relevé(s) rejoué(s)"))

        # C8 recalcul indépendant du réel et du budget d'A5
        lignes = state.get("ecarts", [])
        reel_sql = {n: abs(v) for n, v in q("SELECT nature, SUM(montant) FROM journal_general WHERE annee=? AND mois=? GROUP BY nature", (annee, mois))}
        budget_sql = {a5.POSTE_VERS_NATURE[p]: m for p, m in q("SELECT poste, montant FROM budget_mensuel WHERE annee=? AND mois=?", (annee, mois)) if p in a5.POSTE_VERS_NATURE}
        diffs = []
        for l in lignes:
            if l["code"] == "Flux":
                continue
            if abs((l["reel"] or 0) - reel_sql.get(l["code"], 0.0)) > 0.01:
                diffs.append(f"réel {l['code']}")
            if l["budget"] is not None and abs(l["budget"] - budget_sql.get(l["code"], float('nan'))) > 0.01:
                diffs.append(f"budget {l['code']}")
        flux = next((l for l in lignes if l["code"] == "Flux"), None)
        if flux and flux["reel"] is not None:
            recalc = reel_sql.get("Revenu", 0) - sum(reel_sql.get(k, 0) for k in ("Fixe", "Variable", "Financement"))
            if abs(flux["reel"] - recalc) > 0.01:
                diffs.append("flux net réel")
        ctl.append(_c("C8", "Recalcul indépendant du réel et du budget (SQL direct)", B, not diffs and bool(lignes),
                      ", ".join(diffs) if diffs else f"{len(lignes)} ligne(s) recalculée(s), concordance exacte"))
    finally:
        conn.close()

    # C9 reproductibilité de la prévision
    rev = next((l for l in state.get("ecarts", []) if l["code"] == "Revenu"), None)
    if rev and rev.get("prevu") is not None:
        try:
            nouveau = prevision_a_date(db, "Revenu", per)["prevu"]
            ok = abs(nouveau - rev["prevu"]) < 0.01
            ctl.append(_c("C9", "Reproductibilité de la prévision SARIMAX (relance)", B, ok,
                          f"relance {nouveau:,.2f} vs {rev['prevu']:,.2f}"))
        except Exception as e:
            ctl.append(_c("C9", "Reproductibilité de la prévision SARIMAX (relance)", B, False, f"{type(e).__name__}: {e}"))
    else:
        ctl.append(_c("C9", "Reproductibilité de la prévision SARIMAX (relance)", R, False, "aucune prévision à rejouer"))

    # C10 cohérence des prévisions A4
    pb = []
    for s, p in state.get("previsions", {}).items():
        vals = p["valeurs"]
        if len(vals) != len(p["periodes"]) or any(not math.isfinite(v) for v in vals):
            pb.append(f"{s}: valeurs invalides")
        for v, (lo, hi) in zip(vals, p["ci95"]):
            if not (lo - 0.01 <= v <= hi + 0.01):
                pb.append(f"{s}: prévision hors de son IC 95 %")
                break
            if p.get("methode") == "SARIMAX" and (not math.isfinite(hi) or hi > 20 * max(abs(v), 1.0)):
                pb.append(f"{s}: IC 95 % aberrant ({hi:.3g})")
                break
    ctl.append(_c("C10", "Cohérence des prévisions A4 (finies, dans leur IC 95 %)", R, not pb and bool(state.get("previsions")),
                  "; ".join(pb) if pb else f"{len(state.get('previsions', {}))} série(s) cohérente(s)"))

    # C11 chiffres du commentaire
    com = state.get("commentaire", {})
    if com:
        texte = com.get("resume", "") + "\n" + "\n".join(com.get("points", []))
        ctx = a5._contexte_formate({"periode": per, "lignes": lignes, "causes": state.get("causes_a5", {}), "seuil_pct": 0.10, "seuil_abs": 25_000.0})
        hors = sorted(a5._nombres(texte) - a5._nombres(ctx))
        ctl.append(_c("C11", "Chaque chiffre du commentaire figure dans le tableau d'écarts", B, not hors,
                      f"non sourcés: {hors}" if hors else "tous les chiffres sont sourcés"))
    else:
        ctl.append(_c("C11", "Chaque chiffre du commentaire figure dans le tableau d'écarts", B, False, "commentaire absent"))

    bloquants = [c for c in ctl if c["gravite"] == B and not c["ok"]]
    reserves = [c for c in ctl if c["gravite"] == R and not c["ok"]]
    verdict = "bloque" if bloquants else ("reserves" if (reserves or state.get("alertes_amont")) else "approuve")
    figures = {"periode": per, "ecarts": [{k: l.get(k) for k in ("code", "reel", "budget", "prevu")} for l in lignes],
               "previsions": {s: p["valeurs"] for s, p in state.get("previsions", {}).items()}}
    empreinte = hashlib.sha256(json.dumps(figures, sort_keys=True, default=str).encode()).hexdigest()[:16]
    return {"controles": ctl, "verdict": verdict, "empreinte": empreinte}


def router_verdict(state: ControleState) -> str:
    return state["verdict"]


def _resume(state: ControleState) -> str:
    ctl = state["controles"]
    ok = sum(c["ok"] for c in ctl)
    return f"{ok}/{len(ctl)} contrôles réussis (empreinte {state['empreinte']})"


def approuver_node(state: ControleState) -> dict:
    return {"statut": "approuve", "message": f"Approuvé : {_resume(state)}."}


def approuver_reserves_node(state: ControleState) -> dict:
    echecs = [f"{c['id']} {c['libelle']} ({c['detail']})" for c in state["controles"] if not c["ok"]]
    amont = state.get("alertes_amont", [])
    return {"statut": "reserves", "message": f"Approuvé avec réserves : {_resume(state)}. "
            + ("Réserves : " + " | ".join(echecs + amont) if (echecs or amont) else "")}


def bloquer_node(state: ControleState) -> dict:
    echecs = [f"{c['id']} {c['libelle']} ({c['detail']})" for c in state["controles"] if c["gravite"] == B and not c["ok"]]
    return {"statut": "bloque", "message": f"BLOQUÉ — rien ne sort : {_resume(state)}. Échecs : " + " | ".join(echecs)}
