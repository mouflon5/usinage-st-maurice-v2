"""
Verdict d'un scénario : on compare ce que le pipeline a ÉCRIT en base à la vérité fixée par le générateur,
puis le statut final du pipeline à ceux qui étaient acceptables.

Verdicts (du plus grave au plus bénin) :
  PLANTAGE            exception non gérée dans le pipeline                                     critique
  DONNEES_FAUSSES     ligne perdue ou ligne fantôme en base (perte silencieuse, ex. jumeaux)   critique
  MAL_CLASSE          ligne classée dans une catégorie fausse alors que la bonne était claire  critique
  ECRITURE_PARTIELLE  le pipeline s'est arrêté AVANT le chargement mais des écritures existent critique
  DEFAUT_NON_DETECTE  l'entrée était défectueuse et le pipeline est allé au bout                critique
  SURCONFIANCE        ligne ambiguë classée automatiquement (un humain aurait dû trancher)     avertissement
  ESCALADE_INATTENDUE ligne claire envoyée à l'arbitrage alors qu'une règle devait la classer  avertissement
  ARRET_PRUDENT       entrée valide refusée par un agent (sans écrire) : prudent mais inutile   avertissement
  STATUT_INATTENDU    statut final hors de ceux attendus, sans dommage constaté                 avertissement
  ARRET_AUTRE_AGENT   arrêt attendu mais par un autre agent que prévu (sans dommage)            info
  OK
"""

import sqlite3
from collections import defaultdict

STOPS = {"arrete_a1", "arrete_a2", "arrete_a3", "arrete_a4", "arrete_a5", "arrete_a7", "bloque_a6", "rejete_humain"}
LOAD = {"complet", "complet_avec_reserves", "a_arbitrer"}
GRAVITE = {"PLANTAGE": "critique", "DONNEES_FAUSSES": "critique", "MAL_CLASSE": "critique", "ECRITURE_PARTIELLE": "critique",
           "DEFAUT_NON_DETECTE": "critique", "SURCONFIANCE": "avertissement", "ESCALADE_INATTENDUE": "avertissement",
           "ARRET_PRUDENT": "avertissement", "STATUT_INATTENDU": "avertissement", "ARRET_AUTRE_AGENT": "info", "OK": "ok"}


def instantane(db: str) -> dict:
    c = sqlite3.connect(db)
    try:
        return {"jg": {r[0] for r in c.execute("SELECT no_ecriture FROM journal_general")},
                "saisie_max": c.execute("SELECT COALESCE(MAX(id),0) FROM journal_saisie").fetchone()[0]}
    finally:
        c.close()


def nouvelles_ecritures(db: str, avant: dict):
    c = sqlite3.connect(db)
    try:
        jg = [r for r in c.execute("SELECT no_ecriture, date_ecriture, description, ROUND(montant,2), categorie FROM journal_general")
              if r[0] not in avant["jg"]]
        saisie = c.execute("SELECT date_brute, description, ROUND(montant_brut,2), categorie, statut FROM journal_saisie WHERE id>?",
                           (avant["saisie_max"],)).fetchall()
        return jg, saisie
    finally:
        c.close()


def agent_arret(statut: str | None):
    if not statut:
        return None
    if statut == "a_arbitrer":
        return "A3"
    if statut == "bloque_a6":
        return "A6"
    if statut.startswith("arrete_a"):
        return statut[-2:].upper()
    return "Humain" if statut == "rejete_humain" else None


def verifier_donnees(spec: dict, statut: str | None, etat: dict, avant: dict, db: str) -> tuple[list, dict]:
    jg, saisie = nouvelles_ecritures(db, avant)
    issues = []
    stats = dict(lignes_verite=len(spec["verite"]), lignes_ok=0, lignes_escaladees=0, lignes_mal_classees=0,
                 lignes_surconfiance=0, lignes_perdues=0, lignes_fantomes=0)

    # 1) arrêt avant le chargement : aucune écriture ne doit exister (chargement atomique)
    arret_avant_a3 = statut in ("arrete_a1", "arrete_a2", "arrete_a3")
    if arret_avant_a3 or not spec["attendu"]["charge"]:
        if (jg or saisie) and (arret_avant_a3 or statut in STOPS):
            issues.append(dict(type="ecriture_partielle", gravite="critique",
                               detail=f"{len(saisie)} ligne(s) en staging et {len(jg)} au grand livre alors que le pipeline s'est arrêté ({statut})"))
        return issues, stats
    if not saisie and not jg and statut not in LOAD and statut not in STOPS:
        return issues, stats

    # 2) comparaison à la vérité (multi-ensemble sur date|description|montant)
    par_cle = defaultdict(list)
    for d, desc, m, cat, st in saisie:
        par_cle[(d, desc, round(m, 2))].append((cat, st))
    jg_cle = defaultdict(list)
    for _, d, desc, m, cat in jg:
        jg_cle[(d, desc, round(m, 2))].append(cat)

    for t in spec["verite"]:
        k = (t["date"], t["description"], round(t["montant"], 2))
        if not par_cle[k]:
            stats["lignes_perdues"] += 1
            issues.append(dict(type="perdue", gravite="critique", detail=f"ligne absente de la base : {k[0]} {k[1]} {k[2]:.2f}"))
            continue
        cat, st = par_cle[k].pop()
        promue = cat != "À classer"
        if promue and jg_cle[k]:
            jg_cle[k].pop()
        elif promue:
            issues.append(dict(type="incoherence_staging", gravite="critique", detail=f"classée en staging mais absente du grand livre : {k[1]}"))
        if t["cible"] == "escalade":
            if promue:
                stats["lignes_surconfiance"] += 1
                issues.append(dict(type="surconfiance", gravite="avertissement", detail=f"{k[1]} → « {cat} » ({t['raison']})"))
            else:
                stats["lignes_escaladees"] += 1
        elif promue:
            if cat == t["categorie"]:
                stats["lignes_ok"] += 1
            else:
                stats["lignes_mal_classees"] += 1
                issues.append(dict(type="mal_classee", gravite="critique",
                                   detail=f"{k[1]} → « {cat} » au lieu de « {t['categorie']} » ({t['raison'] or 'règle'})"))
        else:
            stats["lignes_escaladees"] += 1
            if t["cible"] == "promue":
                issues.append(dict(type="escalade_inattendue", gravite="avertissement", detail=f"{k[1]} devait être classée par règle"))

    restes = [(k, v) for k, v in par_cle.items() for _ in v]
    for k, _ in restes:
        stats["lignes_fantomes"] += 1
        issues.append(dict(type="fantome", gravite="critique", detail=f"ligne en base absente de la vérité : {k[0]} {k[1]} {k[2]:.2f}"))
    return issues, stats


def verdict(spec: dict, statut: str | None, exception: str | None, issues: list) -> str:
    acceptable = set(spec["attendu"]["statuts"])
    if exception:
        return "PLANTAGE"
    types = {i["type"] for i in issues}
    if types & {"perdue", "fantome", "incoherence_staging"}:
        return "DONNEES_FAUSSES"
    if "mal_classee" in types:
        return "MAL_CLASSE"
    if "ecriture_partielle" in types:
        return "ECRITURE_PARTIELLE"
    if statut in LOAD and not (acceptable & LOAD):
        return "DEFAUT_NON_DETECTE"
    if statut == "complet" and "complet" not in acceptable and "complet_avec_reserves" in acceptable:
        return "DEFAUT_NON_DETECTE"
    if "surconfiance" in types:
        return "SURCONFIANCE"
    if "escalade_inattendue" in types:
        return "ESCALADE_INATTENDUE"
    if statut in acceptable:
        return "OK"
    if statut in STOPS and (acceptable & STOPS):
        return "ARRET_AUTRE_AGENT"
    if statut in STOPS:
        return "ARRET_PRUDENT"
    return "STATUT_INATTENDU"
