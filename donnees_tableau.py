"""Reconstruit, à partir d'une base SQLite, les données `D` et `BASE_PARAMS` du tableau de bord
de trésorerie (tableau_de_bord_tresorerie_interactif.html) pour qu'elles suivent les scénarios.

Principe
--------
* Le fichier HTML de Marco n'est JAMAIS modifié : on y remplace seulement, à la volée, les deux
  lignes de données (`const BASE_PARAMS = …;` et `const D = …;`). La mise en page est donc identique.
* Le HTML sert aussi de GABARIT : tout ce qui n'est pas recalculable depuis la base (textes de
  commentaires, libellés, tables d'amortissement…) est repris tel quel.
* Recalculé depuis la base (exact, validé contre le tableau d'origine) :
    R4 (structure annuelle), R5 (écarts), R6 (journal, saisie, historique, correspondance),
    R1 (liquidité semaine par semaine), kpi, meta.
* Effet de trésorerie : la somme des écritures AJOUTÉES depuis une base de référence
  (`db_ref`) décale le solde de départ ; R0/R1/R2/R3/R7 suivent ce décalage (les soldes sont additifs).
  Les probabilités des simulations (R3/R7) sont recalées par interpolation sur la distribution
  d'origine : c'est une approximation, signalée dans `D["live"]`.
"""
from __future__ import annotations

import copy
import json
import math
import re
import sqlite3
from datetime import datetime
from pathlib import Path

NAN = float("nan")
NATURES_DEPENSES = ("Fixe", "Variable", "Financement")
POSTES = [("Revenus", "Revenu"), ("Frais fixes", "Fixe"), ("Frais variables", "Variable"),
          ("Remb. financement revolving", "Financement")]
ABS_SEUIL_DEFAUT = 25_000.0


# ----------------------------------------------------------------------------------------------
# Gabarit HTML
# ----------------------------------------------------------------------------------------------
def _ligne_donnees(lignes: list[str], debut: str) -> int:
    for i, l in enumerate(lignes):
        if l.startswith(debut):
            return i
    raise ValueError(f"Ligne '{debut}' introuvable dans le HTML")


def charger_gabarit(html_path: str | Path) -> tuple[str, dict, dict]:
    """Retourne (texte html, BASE_PARAMS, D) lus dans le HTML d'origine."""
    texte = Path(html_path).read_text(encoding="utf-8")
    lignes = texte.split("\n")
    out = []
    for debut in ("const BASE_PARAMS", "const D "):
        l = lignes[_ligne_donnees(lignes, debut)]
        out.append(json.loads(l[l.index("=") + 1:].strip().rstrip(";")))
    return texte, out[0], out[1]


def injecter(html: str, base_params: dict, d: dict) -> str:
    """Remplace les deux lignes de données du HTML par des données fraîches (layout intact)."""
    lignes = html.split("\n")
    i = _ligne_donnees(lignes, "const BASE_PARAMS")
    j = _ligne_donnees(lignes, "const D ")
    lignes[i] = "const BASE_PARAMS = " + json.dumps(base_params, ensure_ascii=False) + ";"
    lignes[j] = "const D = " + json.dumps(d, ensure_ascii=False) + ";"
    return "\n".join(lignes)


# ----------------------------------------------------------------------------------------------
# Lecture de la base
# ----------------------------------------------------------------------------------------------
def lire_parametres(conn: sqlite3.Connection) -> dict:
    p: dict = {}
    for dom, cle, val, typ in conn.execute("SELECT domaine, cle, valeur, type_valeur FROM parametres"):
        if typ == "int":
            v = int(val)
        elif typ == "float":
            v = float(val)
        elif typ == "json":
            v = json.loads(val)
        elif typ == "bool":
            v = str(val).lower() in ("1", "true", "vrai")
        else:
            v = val
        p.setdefault(dom, {})[cle] = v
    return p


def _nz(x):
    return NAN if x is None else x


def _isnan(x) -> bool:
    return isinstance(x, float) and math.isnan(x)


def _sens(poste: str, ecart: float) -> str:
    if abs(ecart) < 0.005:
        return "Neutre"
    bon_si_positif = poste in ("Revenus", "Flux net")
    return "Favorable" if (ecart > 0) == bon_si_positif else "Défavorable"


def _materialite(ecart: float, seuil_abs: float) -> str:
    return "⚠ À expliquer" if abs(ecart) >= seuil_abs else ""


# ----------------------------------------------------------------------------------------------
# R4 — structure annuelle
# ----------------------------------------------------------------------------------------------
def _mensuel(conn, annee: int):
    """{(mois, nature): somme signée} et {(mois, categorie, nature): somme signée}."""
    nat = {}
    for m, n, s in conn.execute(
            "SELECT mois, nature, SUM(montant) FROM journal_general WHERE annee=? GROUP BY mois, nature", (annee,)):
        nat[(m, n)] = s
    return nat


def construire_r4(conn, annee: int, base_r4: dict) -> dict:
    nat = _mensuel(conn, annee)
    flux, cumul, mens_nat = [], [], []
    rc = dc = 0.0
    for m in range(1, 13):
        rev = nat.get((m, "Revenu"), 0.0)
        fx = -nat.get((m, "Fixe"), 0.0)
        va = -nat.get((m, "Variable"), 0.0)
        fi = -nat.get((m, "Financement"), 0.0)
        dep = fx + va + fi
        flux.append({"annee": annee, "mois": m, "revenus": rev, "frais_fixes": fx, "frais_variables": va,
                     "financement": fi, "flux_net": rev - dep, "depenses_totales": dep,
                     "mois_label": f"{annee}-{m:02d}"})
        rc += rev
        dc += dep
        cumul.append({"mois": m, "revenus": rev, "depenses_totales": dep, "flux_net": rev - dep,
                      "revenus_cumules": rc, "depenses_cumulees": dc, "flux_cumule": rc - dc})
        mens_nat.append({"mois": m, "Financement": fi, "Fixe": fx, "Variable": va})
    rev_t = sum(r["revenus"] for r in flux)
    dep_t = sum(r["depenses_totales"] for r in flux)
    fixes = sum(r["frais_fixes"] for r in flux)
    var = sum(r["frais_variables"] for r in flux)
    fin = sum(r["financement"] for r in flux)
    par_nature = [{"nature": n, "montant": v, "part": (v / dep_t if dep_t else 0.0)}
                  for n, v in (("Financement", fin), ("Fixe", fixes), ("Variable", var))]

    top10 = [{"categorie": c, "nature": n, "montant": -s} for c, n, s in conn.execute(
        "SELECT categorie, nature, SUM(montant) s FROM journal_general WHERE annee=? AND nature IN ('Fixe','Variable','Financement') "
        "GROUP BY categorie, nature ORDER BY s ASC LIMIT 10", (annee,))]
    rcat = conn.execute("SELECT categorie, SUM(montant) FROM journal_general WHERE annee=? AND nature='Revenu' "
                        "GROUP BY categorie ORDER BY 2 DESC", (annee,)).fetchall()
    revenus_categorie = [{"categorie": c, "montant": s, "part": (s / rev_t if rev_t else 0.0)} for c, s in rcat]
    cats = sorted(c for c, _ in rcat)
    par_cat_mois = {(m, c): s for m, c, s in conn.execute(
        "SELECT mois, categorie, SUM(montant) FROM journal_general WHERE annee=? AND nature='Revenu' "
        "GROUP BY mois, categorie", (annee,))}
    rev_mens = []
    for m in range(1, 13):
        ligne = {"mois": m}
        for c in cats:
            ligne[c] = par_cat_mois.get((m, c), NAN)
        rev_mens.append(ligne)

    out = copy.deepcopy(base_r4)
    out.update({
        "kpi": {"revenus": rev_t, "depenses": dep_t, "flux_net": rev_t - dep_t,
                "part_fixes": fixes / rev_t if rev_t else 0.0, "part_variables": var / rev_t if rev_t else 0.0},
        "flux_mensuel": flux, "cumul": cumul, "par_nature": par_nature, "top10": top10,
        "revenus_categorie": revenus_categorie, "mensuel_par_nature": mens_nat,
        "revenus_mensuels_categorie": rev_mens,
    })
    return out


# ----------------------------------------------------------------------------------------------
# R5 — écarts budget / projeté / réel
# ----------------------------------------------------------------------------------------------
def _budget(conn, annee):
    b = {}
    for poste, mois, s in conn.execute("SELECT poste, mois, montant FROM budget_mensuel WHERE annee=?", (annee,)):
        b[(poste, mois)] = s
    return b


def construire_r5(conn, annee: int, params: dict, base_r5: dict, r4: dict) -> dict:
    seuil_abs = params.get("ecarts", {}).get("seuil_materialite_dollars", ABS_SEUIL_DEFAUT)
    dernier = int(params.get("ecarts", {}).get("dernier_mois_reel", 9))
    bud = _budget(conn, annee)
    fm = r4["flux_mensuel"]
    cle_r4 = {"Revenus": "revenus", "Frais fixes": "frais_fixes", "Frais variables": "frais_variables",
              "Remb. financement revolving": "financement"}

    def serie(source):
        s = {}
        for poste, _ in POSTES:
            s[poste] = [source(poste, m) for m in range(1, 13)]
        s["Total des dépenses"] = [sum(s[p][i] for p in s if p not in ("Revenus",)) for i in range(12)]
        s["Flux net"] = [s["Revenus"][i] - s["Total des dépenses"][i] for i in range(12)]
        return s

    S_bud = serie(lambda p, m: bud.get((p, m), 0.0))
    S_pro = serie(lambda p, m: fm[m - 1][cle_r4[p]])
    ordre = [p for p, _ in POSTES] + ["Total des dépenses", "Flux net"]
    # le "réel" = projeté sur les mois déjà clos, vide ensuite
    S_ree = {p: [S_pro[p][i] if i < dernier else NAN for i in range(12)] for p in ordre}

    def tableau(S):
        rows = []
        for p in ordre:
            r = {"poste": p}
            vals = S[p]
            for i, v in enumerate(vals, 1):
                r[str(i)] = v
            ok = [v for v in vals if not _isnan(v)]
            r["Total %d" % annee] = sum(ok) if ok else NAN
            r["Moy. / mois"] = (sum(ok) / len(ok)) if ok else NAN
            rows.append(r)
        return rows

    def ligne_ecart(p, b, r):
        e = r - b
        return e, (e / b if b else 0.0)

    performance, derive = [], []
    for p in ordre:
        b = sum(S_bud[p][:dernier])
        r = sum(S_ree[p][:dernier])
        e, pct = ligne_ecart(p, b, r)
        performance.append({"poste": p, "budget_cumule": b, "reel_cumule": r, "ecart": e, "ecart_pct": pct,
                            "sens": _sens(p, e) if p in ("Revenus", "Flux net") else
                            ("Neutre" if abs(e) < .005 else ("Défavorable" if e > 0 else "Favorable")),
                            "materialite": _materialite(e, seuil_abs), "cause": "À déterminer"})
        b = sum(S_bud[p])
        r = sum(S_pro[p])
        e, pct = ligne_ecart(p, b, r)
        derive.append({"poste": p, "budget_annuel": b, "projete_annuel": r, "ecart": e, "ecart_pct": pct,
                       "sens": _sens(p, e) if p in ("Revenus", "Flux net") else
                       ("Neutre" if abs(e) < .005 else ("Défavorable" if e > 0 else "Favorable")),
                       "materialite": _materialite(e, seuil_abs), "cause": "À déterminer"})

    d = {x["poste"]: x for x in derive}
    flux_b = d["Flux net"]["budget_annuel"]
    pont = [{"etape": f"Flux net budgété {annee}", "contribution": NAN, "cumul": flux_b,
             "effet": "Point de départ — référentiel figé", "libelle_court": ""}]
    cumul = flux_b
    noms = {"Revenus": "Écart sur revenus", "Frais fixes": "Écart sur frais fixes",
            "Frais variables": "Écart sur frais variables",
            "Remb. financement revolving": "Écart sur remb. du financement revolving"}
    for p, _ in POSTES:
        e = d[p]["ecart"]
        contrib = e if p == "Revenus" else -e
        cumul += contrib
        pont.append({"etape": noms[p], "contribution": contrib, "cumul": cumul,
                     "effet": ("Favorable — améliore le flux net" if contrib > 0 else "Défavorable — dégrade le flux net")
                     if abs(contrib) >= .005 else "Neutre",
                     "libelle_court": p})
    flux_p = d["Flux net"]["projete_annuel"]
    pont.append({"etape": f"Flux net projeté {annee}", "contribution": flux_p - flux_b, "cumul": flux_p,
                 "effet": "Point d'arrivée — atterrissage prévu", "libelle_court": ""})
    equilibre = abs(cumul - flux_p) < 1.0

    grille, cumules = [], []
    cb = cp = 0.0
    cr = 0.0
    for i in range(12):
        b, p_, r = S_bud["Flux net"][i], S_pro["Flux net"][i], S_ree["Flux net"][i]
        cb += b
        cp += p_
        reel = not _isnan(r)
        if reel:
            cr += r
        e_rb = r - b if reel else NAN
        grille.append({"no": i + 1, "mois": f"{annee}-{i + 1:02d}", "statut": "Réel" if reel else "Projeté",
                       "budget": b, "projete": p_, "reel": r, "ecart_reel_budget": e_rb,
                       "ecart_projete_budget": p_ - b, "ecart_reel_projete": (r - p_) if reel else NAN,
                       "cumul_reel_budget": (cr - cb) if reel else NAN,
                       "alerte": "⚠" if reel and abs(e_rb) >= seuil_abs else ""})
        cumules.append({"no": i + 1, "mois": f"{annee}-{i + 1:02d}", "budget_cumule": cb, "projete_cumule": cp,
                        "reel_cumule": cr if reel else NAN, "derive_cumulee": (cr - cb) if reel else NAN,
                        "reference": 0.0})

    out = copy.deepcopy(base_r5)
    out.update({"performance": performance, "derive": derive, "pont": pont, "pont_equilibre": bool(equilibre),
                "grille": grille, "cumules": cumules,
                "referentiels": {"budget": tableau(S_bud), "projete": tableau(S_pro), "reel": tableau(S_ree)}})
    return out


# ----------------------------------------------------------------------------------------------
# R6 — journal, saisie, historique, correspondance
# ----------------------------------------------------------------------------------------------
def construire_r6(conn, annee: int, base_r6: dict) -> dict:
    sais = conn.execute("SELECT date_brute, description, montant_brut, compte_source, categorie, nature, statut, "
                        "est_doublon FROM journal_saisie ORDER BY id").fetchall()
    saisie = [{"date_brute": a, "description": b, "montant_brut": c, "compte_source": d_, "categorie": e,
               "nature": f, "statut": g} for a, b, c, d_, e, f, g, _ in sais]
    st = [s[6] or "" for s in sais]
    valides = sum(1 for x in st if x.startswith("✓"))
    a_classer = sum(1 for x in st if "classer" in x.lower())
    dates_inv = sum(1 for x in st if "date" in x.lower() and "invalide" in x.lower())
    mont_inv = sum(1 for x in st if "montant" in x.lower() and "invalide" in x.lower())
    doublons = sum(1 for s in sais if s[7])
    # totaux sur les lignes valides uniquement (les lignes « à classer » ne sont pas encore archivables)
    ok = [s for s in sais if (s[6] or "").startswith("✓")]
    entrees = sum(s[2] for s in ok if s[2] and s[2] > 0)
    sorties = sum(s[2] for s in ok if s[2] and s[2] < 0)
    ctrl = {"lignes_saisies": len(sais), "lignes_valides": valides, "dates_invalides": dates_inv,
            "montants_invalides": mont_inv, "doublons": doublons, "a_classer": a_classer,
            "total_entrees": entrees, "total_sorties": sorties, "flux_net": entrees + sorties,
            "pret_a_archiver": bool(sais) and a_classer == 0 and doublons == 0 and dates_inv == 0 and mont_inv == 0}

    mots: dict[str, list[str]] = {}
    for c, k in conn.execute("SELECT categorie, mot_cle FROM mots_cles"):
        mots.setdefault(c, []).append(k)
    corr = [{"ordre": o, "categorie": c, "nature": n, "mots_cles": " · ".join(sorted(mots.get(c, [])))}
            for c, n, o in conn.execute("SELECT categorie, nature, ordre FROM categories ORDER BY ordre")]

    piv = {}
    for an, mo, n, s in conn.execute("SELECT annee, mois, nature, SUM(montant) FROM journal_general GROUP BY 1,2,3"):
        piv.setdefault(f"{an}-{mo:02d}", {})[n] = s
    hist = []
    for per in sorted(piv):
        v = piv[per]
        rev, fx, va, fi = v.get("Revenu", 0.0), -v.get("Fixe", 0.0), -v.get("Variable", 0.0), -v.get("Financement", 0.0)
        hist.append({"periode": per, "Revenu": rev, "Fixe": fx, "Variable": va, "Financement": fi,
                     "Flux net": rev - fx - va - fi})

    jx = [{"no_ecriture": a, "date_ecriture": b, "description": c, "montant": d_, "categorie": e, "nature": f}
          for a, b, c, d_, e, f in conn.execute(
              "SELECT no_ecriture, date_ecriture, description, montant, categorie, nature FROM journal_general "
              "WHERE annee=? ORDER BY date_ecriture DESC, rowid DESC LIMIT 150", (annee,))]
    out = copy.deepcopy(base_r6)
    out.update({"controles": ctrl, "saisie": saisie, "correspondance": corr, "historique": hist, "journal_extrait": jx})
    return out


# ----------------------------------------------------------------------------------------------
# Trésorerie (R0/R1/R2/kpi/R3/R7) — décalage additif du solde
# ----------------------------------------------------------------------------------------------
def _decaler(x, delta):
    if isinstance(x, list):
        return [_decaler(v, delta) for v in x]
    if isinstance(x, (int, float)) and not _isnan(x):
        return x + delta
    return x


def _cdf_creux(st: dict, x: float) -> float:
    """CDF interpolée du creux (distribution d'origine) — sert à recaler les probabilités."""
    pts = [(st.get("creux_min"), 0.0), (st.get("creux_p5"), .05), (st.get("creux_p10"), .10),
           (st.get("creux_p25"), .25), (st.get("creux_median"), .50), (st.get("creux_p75"), .75),
           (st.get("creux_p90"), .90), (st.get("creux_max"), 1.0)]
    pts = sorted((a, b) for a, b in pts if a is not None)
    if len(pts) < 2:
        return 0.5
    if x <= pts[0][0]:
        return 0.0
    if x >= pts[-1][0]:
        return 1.0
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x0 <= x <= x1:
            return y0 + (y1 - y0) * ((x - x0) / (x1 - x0) if x1 > x0 else 0)
    return 0.0


def _decaler_simulation(sim: dict, delta: float, seuil: float) -> dict:
    sim = copy.deepcopy(sim)
    if not delta:
        return sim
    st, rk = sim["stats"], sim["risque"]
    base_st = copy.deepcopy(st)
    for k in list(st):
        if k.startswith("creux_") and k.endswith(("ecart_type",)):
            continue
        if k.startswith("flux_") or k == "ecart_type":
            continue
        if isinstance(st[k], (int, float)):
            st[k] = st[k] + delta
    sim["percentiles"] = {k: _decaler(v, delta) for k, v in sim["percentiles"].items()}
    for h in sim.get("histogramme", []):
        for k in ("borne_inf", "borne_sup", "centre"):
            h[k] += delta
    if "trajectoires" in sim:
        sim["trajectoires"] = _decaler(sim["trajectoires"], delta)
    # probabilités recalées : p' = p + F(seuil - delta) - F(seuil)
    for cle, seuil_x in (("prob_sous_seuil", seuil), ("prob_decouvert", 0.0)):
        if cle in rk:
            corr = _cdf_creux(base_st, seuil_x - delta) - _cdf_creux(base_st, seuil_x)
            rk[cle] = min(1.0, max(0.0, rk[cle] + corr))
    rk["creux_p5"] = st.get("creux_p5", rk.get("creux_p5"))
    rk["coussin_requis"] = max(0.0, seuil - rk["creux_p5"])
    if "perte_potentielle_95" in rk:
        rk["perte_potentielle_95"] = max(0.0, rk["perte_potentielle_95"] - delta)
    if "marge_creux_median" in rk:
        rk["marge_creux_median"] += delta
    return sim


def appliquer_tresorerie(conn, params: dict, d: dict, delta: float, r4: dict, r5: dict) -> None:
    """Met à jour in-place kpi/R0/R1/R2/R3/R7 : recalcule R1 depuis tresorerie_hebdo et décale le reste."""
    f = params["forecast"]
    seuil = f["seuil_securite"]
    solde0 = params["general"]["solde_initial"] + delta
    hebdo = conn.execute("SELECT libelle, entrees, sorties, statut, note FROM tresorerie_hebdo ORDER BY no_semaine").fetchall()

    # ---- R1 : liquidité immédiate (recalculée)
    sem, s = [], solde0
    for lib, ent, sor, stt, note in hebdo:
        s += ent - sor
        sem.append({"libelle": lib, "statut": stt, "entrees": ent, "sorties": sor, "net": ent - sor,
                    "solde": s, "note": note or ""})
    soldes = [x["solde"] for x in sem]
    reelles = [x for x in sem if x["statut"] == "Réel"]
    actuel = reelles[-1]["solde"] if reelles else solde0
    creux, sommet = min(soldes), max(soldes)
    r1 = d["r1"]
    ind = r1["indicateurs"]
    n_creux = sum(1 for i in range(1, len(soldes) - 1) if soldes[i] < soldes[i - 1] and soldes[i] < soldes[i + 1])
    ind.update({"solde_actuel": actuel, "creux": creux, "sommet": sommet, "amplitude": sommet - creux,
                "seuil": seuil, "marge_au_creux": creux - seuil,
                "semaines_sous_seuil": sum(1 for v in soldes if v < seuil), "nb_semaines": len(sem),
                "variation_nette_moyenne": (soldes[-1] - solde0) / len(sem), "nb_creux_detectes": n_creux,
                "nb_reelles": len(reelles), "nb_projetees": len(sem) - len(reelles)})
    r1["semaines"] = sem
    for row in r1["impact"]:
        for k in ("reel", "sans_remboursement", "avec_remboursement"):
            row[k] = _decaler(row[k], delta)

    # ---- facilités / couverture
    marge_disp = d["kpi"]["marge_disponible"]
    # ---- simulations
    for cle in ("r3",):
        d[cle] = _decaler_simulation(d[cle], delta, seuil)
    d["r7"]["bs"] = _decaler_simulation(d["r7"]["bs"], delta, seuil)
    d["r7"]["mc"] = _decaler_simulation(d["r7"]["mc"], delta, seuil)
    coussin = d["r7"]["mc"]["risque"]["coussin_requis"]

    # ---- R2 : rolling forecast (soldes décalés)
    r2 = d["r2"]
    for row in r2["table"]:
        row["solde"] += delta
        row["alerte"] = "⚠" if row["solde"] < seuil else ""
    for row in r2["cone"]:
        for k in ("plancher", "base", "plafond"):
            row[k] += delta
    for row in r2["recap"]:
        if row["indicateur"] in ("Solde final", "Creux (solde minimum)", "Marge au creux (vs seuil)"):
            for k in ("Pessimiste", "Base", "Optimiste"):
                row[k] += delta
    for row in r2["jalons"]:
        for k in ("Pessimiste", "Base", "Optimiste"):
            row[k] += delta
    for row in r2["referentiels"]:
        for k in ("solde_reel", "solde_projete", "solde_budgete"):
            row[k] = _decaler(row[k], delta)
    soldes2 = [r["solde"] for r in r2["table"]]
    r2["indicateurs"].update({"solde_final": soldes2[-1], "creux": min(soldes2),
                              "semaines_sous_seuil": sum(1 for v in soldes2 if v < seuil)})

    # ---- R0 trajectoire + constats
    d["r0"]["trajectoire"]["solde"] = [solde0] + [x["solde"] for x in sem]
    cons = d["r0"]["constats"]
    flux_ecart = next(x for x in r5["derive"] if x["poste"] == "Flux net")["ecart"]
    cons[0]["chiffre"] = creux
    cons[1]["chiffre"] = flux_ecart
    cons[3]["chiffre"] = coussin
    cons[0]["constat"] = ("Le creux du cycle passe sous le seuil de sécurité" if creux < seuil
                          else "Le creux du cycle reste au-dessus du seuil de sécurité")
    cons[1]["constat"] = "L'exercice va atterrir sous le budget" if flux_ecart < 0 else "L'exercice va atterrir au-dessus du budget"

    # ---- KPI
    k = d["kpi"]
    util = k["utilisation_marge"]
    k.update({"solde_actuel": actuel, "creux": creux, "sommet": sommet, "seuil": seuil,
              "marge_au_creux": creux - seuil, "semaines_sous_seuil": ind["semaines_sous_seuil"],
              "nb_semaines": len(sem), "amplitude": sommet - creux,
              "variation_nette": ind["variation_nette_moyenne"], "coussin_requis": coussin,
              "couverture": marge_disp - coussin, "utilisation_marge": util,
              "flux_net_2026": r4["kpi"]["flux_net"], "ecart_budget_annee": flux_ecart,
              "revenus_2026": r4["kpi"]["revenus"], "depenses_2026": r4["kpi"]["depenses"],
              "part_fixes": r4["kpi"]["part_fixes"], "part_variables": r4["kpi"]["part_variables"]})


# ----------------------------------------------------------------------------------------------
# Point d'entrée
# ----------------------------------------------------------------------------------------------
def _construire_donnees(db_path: str | Path, html_path: str | Path, db_ref: str | Path | None = None,
                       note: str = "") -> tuple[dict, dict]:
    """Retourne (BASE_PARAMS, D) pour la base `db_path`.

    db_ref : base de référence ; les écritures de `db_path` absentes de `db_ref` décalent la trésorerie.
    """
    _, base_params, d0 = charger_gabarit(html_path)
    d = copy.deepcopy(d0)
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        params = lire_parametres(conn)
        annee = int(params["general"]["exercice"])

        delta, nb_new = 0.0, 0
        if db_ref and Path(db_ref).resolve() != Path(db_path).resolve():
            ref = sqlite3.connect(f"file:{db_ref}?mode=ro", uri=True)
            try:
                connus = {r[0] for r in ref.execute("SELECT no_ecriture FROM journal_general")}
            finally:
                ref.close()
            for no, mt in conn.execute("SELECT no_ecriture, montant FROM journal_general"):
                if no not in connus:
                    delta += mt
                    nb_new += 1

        r4 = construire_r4(conn, annee, d["r4"])
        r5 = construire_r5(conn, annee, params, d["r5"], r4)
        r6 = construire_r6(conn, annee, d["r6"])
        d["r4"], d["r5"], d["r6"] = r4, r5, r6
        appliquer_tresorerie(conn, params, d, delta, r4, r5)
        d["meta"]["nb_ecritures"] = conn.execute("SELECT COUNT(*) FROM journal_general").fetchone()[0]
        d["meta"]["genere_le"] = datetime.now().strftime("%Y-%m-%d %H:%M")

        # paramètres pour le recalcul interactif du HTML (solde de départ lié au décalage)
        bp = copy.deepcopy(base_params)
        for dom in bp:
            if dom in params:
                for cle in bp[dom]:
                    if cle in params[dom]:
                        bp[dom][cle] = params[dom][cle]
        if delta:
            for dom in ("forecast", "monte_carlo", "bootstrap"):
                if "solde_depart" in bp.get(dom, {}):
                    bp[dom]["solde_depart"] += delta
                if "tresorerie_depart" in bp.get(dom, {}):
                    bp[dom]["tresorerie_depart"] += delta
        d["live"] = {"delta_tresorerie": delta, "ecritures_ajoutees": nb_new, "note": note,
                     "approximation": "Probabilités R3/R7 recalées par interpolation sur la distribution d'origine."}
        return bp, d
    finally:
        conn.close()


def construire_donnees(db_path, html_path, db_ref=None, note: str = "") -> tuple[dict, dict]:
    """Comme _construire_donnees, avec quelques reprises : la base peut être verrouillée un instant pendant qu'un agent écrit."""
    import time
    for essai in range(6):
        try:
            return _construire_donnees(db_path, html_path, db_ref, note)
        except sqlite3.OperationalError:
            if essai == 5:
                raise
            time.sleep(0.4)


def html_vivant(db_path, html_path, db_ref=None, note: str = "") -> str:
    texte, _, _ = charger_gabarit(html_path)
    bp, d = construire_donnees(db_path, html_path, db_ref, note)
    return injecter(texte, bp, d)


CDN_PLOTLY = "https://cdnjs.cloudflare.com/ajax/libs/plotly.js/2.27.0/plotly.min.js"


def plotly_local() -> Path | None:
    """plotly.min.js fourni par le paquet `plotly` (pip) : permet la démo sans internet."""
    try:
        import plotly
        p = Path(plotly.__file__).parent / "package_data" / "plotly.min.js"
        return p if p.is_file() else None
    except Exception:
        return None


def html_hors_ligne(html: str, url_plotly: str = "/static/plotly.min.js") -> str:
    """Remplace le CDN Plotly par une copie locale (polices Google : repli sur les polices système)."""
    return html.replace(CDN_PLOTLY, url_plotly)
