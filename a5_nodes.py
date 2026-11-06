"""
Nœuds de l'agent A5 — Analyse des écarts.

Séparation stricte : les chiffres viennent du SQL et de SARIMAX ; le LLM ne fait que rédiger sur un
tableau déjà calculé. Un contrôle déterministe rejette tout commentaire qui cite un nombre absent
du tableau fourni (repli sur un commentaire gabarit, statut « degrade »).
"""

import suivi_llm as suivi
import os
import re
import sqlite3

import llm_fournisseur as llm_f
import llm_outils as llm
from a5_state import EcartsState
from prevision_outils import prevision_a_date

POSTE_VERS_NATURE = {"Revenus": "Revenu", "Frais fixes": "Fixe",
                     "Frais variables": "Variable", "Remb. financement revolving": "Financement"}
LIGNES = [("Revenu", "Revenus"), ("Fixe", "Frais fixes"), ("Variable", "Frais variables"),
          ("Financement", "Financement")]
MODELE_COMMENTAIRE = os.getenv("A5_MODELE", "claude-sonnet-5-5")


# ---------- formats (français) ---------- #
def fmt_montant(x: float) -> str:
    return f"{x:,.0f}".replace(",", " ") + " $"


def fmt_pct(x) -> str:
    return "n/d" if x is None else f"{x * 100:+.1f}".replace(".", ",") + " %"


# ---------- 1. préparation ---------- #
def preparer_node(state: EcartsState) -> dict:
    db, per = state["db_path"], state["periode"]
    if not os.path.isfile(db):
        return {"statut": "erreur", "message": f"Base introuvable : {db}"}
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", per or ""):
        return {"statut": "erreur", "message": f"Période invalide : {per!r} (attendu AAAA-MM)"}
    conn = sqlite3.connect(db)
    try:
        n = conn.execute("SELECT COUNT(*) FROM journal_general WHERE annee=? AND mois=?",
                         (int(per[:4]), int(per[5:]))).fetchone()[0]
    finally:
        conn.close()
    if n == 0:
        return {"statut": "erreur", "message": f"Aucune écriture dans journal_general pour {per}"}
    return {"alertes": []}


def router_apres_preparation(state: EcartsState) -> str:
    return "erreur" if state.get("statut") == "erreur" else "calculer"


# ---------- 2. calcul des écarts ---------- #
def calculer_ecarts_node(state: EcartsState) -> dict:
    db, per = state["db_path"], state["periode"]
    annee, mois = int(per[:4]), int(per[5:])
    seuil_pct, seuil_abs = state.get("seuil_pct", 0.10), state.get("seuil_abs", 25_000.0)
    alertes = list(state.get("alertes", []))

    conn = sqlite3.connect(db)
    try:
        reel = {n: abs(v) for n, v in conn.execute(
            "SELECT nature, SUM(montant) FROM journal_general WHERE annee=? AND mois=? GROUP BY nature",
            (annee, mois))}
        budget = {POSTE_VERS_NATURE[p]: m for p, m in conn.execute(
            "SELECT poste, montant FROM budget_mensuel WHERE annee=? AND mois=?", (annee, mois))
            if p in POSTE_VERS_NATURE}
    finally:
        conn.close()
    if not budget:
        alertes.append(f"Aucun budget mensuel pour {per} : comparaison au budget impossible")

    prevu = {}
    for nature, _ in LIGNES:
        try:
            r = prevision_a_date(db, nature, per)
            prevu[nature] = r["prevu"]
            if not r["converge"]:
                alertes.append(f"{nature} : SARIMAX sans convergence complète, prévision à interpréter avec prudence")
        except Exception as e:
            alertes.append(f"{nature} : prévision indisponible ({type(e).__name__}: {e})")

    def ligne(code, libelle, r, b, p, favorable_si_haut):
        def ecart(ref):
            if r is None or ref is None:
                return None, None, None
            e = r - ref
            fav = (e >= 0) == favorable_si_haut
            if code == "Flux":      # référence souvent proche de 0 ou négative : le % n'a pas de sens
                pct, sig = None, abs(e) >= seuil_abs
            else:
                pct = e / ref if ref else None
                sig = abs(e) >= seuil_abs and pct is not None and abs(pct) >= seuil_pct
            return e, pct, ("significatif_" + ("favorable" if fav else "defavorable")) if sig else "dans_la_tolerance"
        eb, pb, sb = ecart(b)
        ep, pp, sp = ecart(p)
        return {"code": code, "libelle": libelle, "reel": r, "budget": b, "prevu": p,
                "ecart_budget": eb, "ecart_budget_pct": pb, "jugement_budget": sb,
                "ecart_prevision": ep, "ecart_prevision_pct": pp, "jugement_prevision": sp}

    lignes = [ligne(n, lib, reel.get(n, 0.0), budget.get(n), prevu.get(n), n == "Revenu") for n, lib in LIGNES]

    def flux(d, cles):
        if any(d.get(k) is None for k in cles):
            return None
        return d["Revenu"] - d["Fixe"] - d["Variable"] - d["Financement"]
    cles = ["Revenu", "Fixe", "Variable", "Financement"]
    rr = {k: reel.get(k, 0.0) for k in cles}
    lignes.append(ligne("Flux", "Flux net", flux(rr, cles), flux(budget, cles), flux(prevu, cles), True))
    return {"lignes": lignes, "alertes": alertes}


# ---------- 3. causes (SQL, déterministe) ---------- #
def analyser_causes_node(state: EcartsState) -> dict:
    db, per = state["db_path"], state["periode"]
    annee, mois = int(per[:4]), int(per[5:])
    causes = {}
    conn = sqlite3.connect(db)
    try:
        for l in state["lignes"]:
            if l["code"] == "Flux":
                continue
            if "significatif" not in f"{l['jugement_budget']}{l['jugement_prevision']}":
                continue
            cats = conn.execute(
                """SELECT c.categorie,
                          ABS(COALESCE((SELECT SUM(montant) FROM journal_general
                                        WHERE categorie=c.categorie AND annee=? AND mois=?),0)) AS courant,
                          ABS(COALESCE((SELECT SUM(montant) FROM journal_general
                                        WHERE categorie=c.categorie
                                          AND (annee*12+mois) BETWEEN ? AND ?),0))/12.0 AS moy12
                   FROM categories c WHERE c.nature=?""",
                (annee, mois, annee * 12 + mois - 12, annee * 12 + mois - 1, l["code"])).fetchall()
            contrib = sorted(({"categorie": c, "courant": cur, "moyenne_12_mois": m, "variation": cur - m}
                              for c, cur, m in cats), key=lambda d: abs(d["variation"]), reverse=True)[:3]
            tx = conn.execute(
                "SELECT date_ecriture, description, montant FROM journal_general "
                "WHERE annee=? AND mois=? AND nature=? ORDER BY ABS(montant) DESC LIMIT 3",
                (annee, mois, l["code"])).fetchall()
            causes[l["code"]] = {
                "categories": contrib,
                "transactions": [{"date": d, "description": de, "montant": m} for d, de, m in tx]}
    finally:
        conn.close()
    return {"causes": causes}


# ---------- 4. commentaire ---------- #
def _contexte_formate(state: EcartsState) -> str:
    """Seule source de chiffres du LLM : tout est déjà formaté et calculé."""
    out = [f"Période analysée : {state['periode']}",
           "Seuil de signification : écart ≥ %s ET ≥ %s" % (
               fmt_pct(state.get("seuil_pct", 0.10)).replace("+", ""), fmt_montant(state.get("seuil_abs", 25_000)))]
    nsig = sum("significatif" in f"{l['jugement_budget']}{l['jugement_prevision']}" for l in state["lignes"])
    out.append(f"Nombre de lignes avec écart significatif : {nsig}")
    for l in state["lignes"]:
        def e(nom, ecart, pct, jug):
            return (f"{nom} : écart {fmt_montant(ecart)}{_p(pct)} → {jug}"
                    if ecart is not None else f"{nom} : n/d")
        out.append(f"- {l['libelle']} : réel {fmt_montant(l['reel']) if l['reel'] is not None else 'n/d'}; "
                   f"budget {fmt_montant(l['budget']) if l['budget'] is not None else 'n/d'}; "
                   f"prévu {fmt_montant(l['prevu']) if l['prevu'] is not None else 'n/d'}; "
                   + e("vs budget", l["ecart_budget"], l["ecart_budget_pct"], l["jugement_budget"]) + "; "
                   + e("vs prévision", l["ecart_prevision"], l["ecart_prevision_pct"], l["jugement_prevision"]))
    for code, c in state.get("causes", {}).items():
        out.append(f"Causes — {code} :")
        for k in c["categories"]:
            out.append(f"  · catégorie {k['categorie']} : {fmt_montant(k['courant'])} ce mois, "
                       f"moyenne 12 mois {fmt_montant(k['moyenne_12_mois'])}")
        for t in c["transactions"]:
            out.append(f"  · {t['date']} {t['description']} : {fmt_montant(abs(t['montant']))}")
    return "\n".join(out)


def _p(pct) -> str:
    return "" if pct is None else f" ({fmt_pct(pct)})"


def _commentaire_modele(state: EcartsState) -> dict:
    sig = [l for l in state["lignes"]
           if "significatif" in f"{l['jugement_budget']}{l['jugement_prevision']}"]
    if not sig:
        resume = f"Pour {state['periode']}, aucun écart significatif (budget ou prévision)."
        return {"resume": resume, "points": []}
    points = []
    for l in sig:
        morceaux = []
        if l["ecart_budget"] is not None and l["jugement_budget"] != "dans_la_tolerance":
            morceaux.append(f"{fmt_montant(l['ecart_budget'])}{_p(l['ecart_budget_pct'])} vs budget")
        if l["ecart_prevision"] is not None and l["jugement_prevision"] != "dans_la_tolerance":
            morceaux.append(f"{fmt_montant(l['ecart_prevision'])}{_p(l['ecart_prevision_pct'])} vs prévision")
        points.append(f"{l['libelle']} : " + " ; ".join(morceaux) + ".")
    return {"resume": f"Pour {state['periode']}, {len(sig)} ligne(s) présentent un écart significatif.",
            "points": points}


def commenter_node(state: EcartsState) -> dict:
    mode = llm.mode_llm()
    modele = _commentaire_modele(state)
    if mode == "simule":
        _c = _contexte_formate(state)
        suivi.noter("A5", "simulé", mode, 0.4, entree="Tu es analyste FP&A…" + _c, sortie=modele.get("resume", "") + " ".join(modele.get("points", [])), origine="gabarit")
        llm_f.tracer_regle("A5", "Gabarit déterministe appliqué au tableau d'écarts :\n" + _c,
                           modele.get("resume", "") + "\n" + "\n".join(modele.get("points", [])), meta={"periode": state.get("periode")})
        return {"commentaire": {**modele, "origine": "simule"}}
    contexte = _contexte_formate(state)
    from pydantic import BaseModel

    class Commentaire(BaseModel):
        resume: str
        points: list[str]

    prompt = (
        "Tu es analyste FP&A. Rédige en français, pour un contrôleur financier, un commentaire d'écarts "
        "à partir UNIQUEMENT du tableau ci-dessous.\n"
        "RÈGLES STRICTES : (1) recopie les montants et pourcentages EXACTEMENT comme écrits ; "
        "(2) n'invente, ne calcule et n'arrondis aucun chiffre, n'écris pas de totaux ou de moyennes qui "
        "n'y figurent pas ; (3) ne déduis pas de cause qui ne figure pas dans les « Causes » — sinon dis "
        "que la cause est à confirmer ; (4) distingue écart vs budget et écart vs prévision.\n"
        "Format : un résumé de 2-3 phrases, puis une phrase par ligne significative.\n\n" + contexte)
    try:
        with suivi.chrono() as _t:
            rep = llm_f.invoquer("A5", prompt, schema=Commentaire, max_tokens=900, defaut=MODELE_COMMENTAIRE,
                                 meta={"periode": state.get("periode")})
        r = rep.parse
        suivi.noter("A5", rep.modele, mode, _t[0], entree=prompt, sortie=r.resume + " ".join(r.points), fournisseur=rep.fournisseur)
        return {"commentaire": {"resume": r.resume, "points": r.points, "origine": "llm"}}
    except Exception as e:
        suivi.noter("A5", llm_f.nom_modele("A5", MODELE_COMMENTAIRE), mode, 0, entree=prompt, statut="erreur",
                    erreur=type(e).__name__, fournisseur=llm_f.fournisseur())
        suivi.decider(llm_f.dernier_trace_id(), "repli sur le gabarit", f"appel en échec ({type(e).__name__})")
        alertes = list(state.get("alertes", [])) + [f"Appel LLM échoué ({type(e).__name__}) : commentaire gabarit"]
        return {"commentaire": {**modele, "origine": "modele"}, "alertes": alertes}


# ---------- 5. contrôle des chiffres du commentaire ---------- #
_NOMBRE = re.compile(r"\d+(?:[   ]\d{3})*(?:[.,]\d+)?")


def _nombres(texte: str) -> set:
    return {re.sub(r"[   ]", "", n).replace(",", ".") for n in _NOMBRE.findall(texte)}


def verifier_commentaire_node(state: EcartsState) -> dict:
    c = state["commentaire"]
    if c["origine"] != "llm":
        return {"controle_commentaire": {"verifie": False, "raison": "commentaire non généré par LLM"}}
    texte = c["resume"] + "\n" + "\n".join(c["points"])
    non_sources = sorted(_nombres(texte) - _nombres(_contexte_formate(state)))
    suivi.noter_garde("A5", "nombres du commentaire", not non_sources, non_sources=non_sources)
    suivi.decider(llm_f.dernier_trace_id(), "rejeté par garde-fou" if non_sources else "accepté",
                  f"nombre(s) absent(s) du tableau : {non_sources} → gabarit utilisé" if non_sources
                  else "tous les nombres du commentaire figurent dans le tableau fourni")
    if non_sources:
        alertes = list(state.get("alertes", [])) + [
            f"Commentaire LLM rejeté : nombre(s) non sourcé(s) {non_sources} — remplacé par le gabarit"]
        return {"commentaire": {**_commentaire_modele(state), "origine": "modele"}, "alertes": alertes,
                "controle_commentaire": {"verifie": True, "ok": False, "non_sources": non_sources}}
    return {"controle_commentaire": {"verifie": True, "ok": True, "non_sources": []}}


# ---------- 6. conclusion ---------- #
def router_conclusion(state: EcartsState) -> str:
    return "degrade" if state.get("alertes") else "complet"


def marquer_complet_node(state: EcartsState) -> dict:
    n = sum("significatif" in f"{l['jugement_budget']}{l['jugement_prevision']}" for l in state["lignes"])
    flux = next(l for l in state["lignes"] if l["code"] == "Flux")
    return {"statut": "complet", "message": (
        f"{state['periode']} : {n} ligne(s) avec écart significatif ; flux net réel "
        f"{fmt_montant(flux['reel'])}. Commentaire : {state['commentaire']['origine']}.")}


def signaler_degrade_node(state: EcartsState) -> dict:
    return {"statut": "degrade", "message": "Analyse produite avec réserves : " + " | ".join(state["alertes"])}
