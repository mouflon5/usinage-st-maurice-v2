"""États financiers dynamiques — résultats, bilan, flux de trésorerie, variation des capitaux propres.

Le journal général ne contient que des mouvements bancaires classés par catégorie : ni créances, ni stocks, ni immobilisations,
ni impôts, ni dividendes. Ces états sont donc un MODÈLE à trois états liés, reconstruit à partir du journal et d'hypothèses
explicites (les « paramètres ») :

  * l'état des résultats prend les catégories du journal comme produits et charges de l'exercice ; le scénario (variation des ventes,
    du coût des produits, des charges, du taux d'intérêt) s'applique aux exercices à partir de `annee_scenario` (par défaut le dernier) ;
  * le bilan se déduit des jours de créances, de stocks et de fournisseurs, des investissements, de l'amortissement, des impôts à payer
    et des dettes (marge de crédit, emprunt BDC) ;
  * l'encaisse du bilan n'est PAS saisie : elle sort du tableau des flux de trésorerie (méthode indirecte). Le bilan s'équilibre alors par
    construction, et `verifications()` le contrôle quand même, exercice par exercice.

Catégories reconnues par leur rang (`categories.ordre`), donc valables quel que soit le vocabulaire de l'entreprise :
    1 marge de crédit · 12 emprunt BDC (financement) ; 2, 6 achats et consommables (coût des produits) ; 20-23 ventes ; 24 subventions ;
    25 autres revenus ; 16 intérêts et frais bancaires ; les autres rangs sont des charges d'exploitation ou d'administration.
"""
from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass, field, replace

VENTES = (20, 21, 22, 23)
AUTRES_REVENUS = (25,)
SUBVENTIONS = (24,)
ACHATS = (2, 6)
CHARGES_OPERATIONS = (3, 5, 7, 8, 9, 10, 11, 13)
CHARGES_ADMIN = (4, 14, 15, 17, 18, 19)
INTERETS = (16,)
MARGE, BDC = 1, 12
HORS_SALAIRES = (5, 7, 8, 9, 10, 11, 13, 14, 15, 17, 18, 19)       # base des fournisseurs (jours de paiement)
AUTRES_CHARGES = CHARGES_OPERATIONS + CHARGES_ADMIN


# --------------------------------------------------------------------------- #
# Paramètres
# --------------------------------------------------------------------------- #
@dataclass
class Parametres:
    # scénario (fractions : 0,05 = +5 %) — appliqué aux exercices >= annee_scenario
    var_ventes: float = 0.0
    var_cout_produits: float = 0.0
    var_charges: float = 0.0
    var_taux: float = 0.0
    annee_scenario: int | None = None
    # fonds de roulement
    dso: float = 48.0                      # jours de ventes en créances
    dio: float = 12.0                      # jours d'achats en stock
    dpo: float = 30.0                      # jours d'achats et de services en fournisseurs
    # immobilisations
    capex: float = 450_000.0
    taux_amort: float = 0.12               # amortissement dégressif sur (valeur nette d'ouverture + moitié des acquisitions)
    # impôts, dividendes, capital
    taux_impot: float = 0.265
    impot_impaye: float = 0.25             # part de l'impôt de l'exercice encore à payer à la clôture
    dividendes_pct: float = 0.50           # part du résultat net distribuée
    emission_actions: float = 0.0
    # dettes
    tirages_marge_pct: float = 1.0         # tirages sur la marge, en % des remboursements journalisés (100 % : solde stable)
    part_interets_bdc: float = 0.15        # part intérêts des remboursements BDC journalisés
    # bilan d'ouverture (au début du premier exercice du journal)
    encaisse_ouverture: float = 400_000.0
    immobilisations_ouverture: float = 3_500_000.0
    bdc_ouverture: float = 1_000_000.0
    marge_ouverture: float | None = None   # None : solde de la facilité de la base
    capital_actions: float = 500_000.0

    def modifie(self, **kw) -> "Parametres":
        return replace(self, **kw)


SCENARIOS = {"Pessimiste": (-0.10, 0.10), "Base": (0.0, 0.0), "Optimiste": (0.05, -0.05)}   # (ventes, charges) — comme la table `parametres`


# --------------------------------------------------------------------------- #
# Lecture du journal
# --------------------------------------------------------------------------- #
@dataclass
class Journal:
    annees: list[int]
    montants: dict[int, dict[int, float]]          # année → rang de catégorie → somme du journal (produits +, charges −)
    libelles: dict[int, str]
    marge_solde: float = 0.0
    marge_limite: float = 0.0
    dso_base: float | None = None


def lire_journal(db_path: str) -> Journal:
    c = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        ordre = {cat: o for cat, o in c.execute("SELECT categorie, ordre FROM categories")}
        libelles = {o: cat for cat, o in ordre.items()}
        montants: dict[int, dict[int, float]] = {}
        for annee, cat, tot in c.execute("SELECT annee, categorie, SUM(montant) FROM journal_general GROUP BY annee, categorie"):
            if cat in ordre:
                montants.setdefault(int(annee), {})[ordre[cat]] = float(tot)
        marge = c.execute("SELECT solde, limite FROM facilites_credit WHERE lower(facilite) LIKE '%marge%'").fetchone() or (0.0, 0.0)
        dso = c.execute("SELECT valeur FROM parametres WHERE domaine='monte_carlo' AND cle='dso_moyen'").fetchone()
    finally:
        c.close()
    return Journal(sorted(montants), montants, libelles, float(marge[0]), float(marge[1]), float(dso[0]) if dso else None)


def parametres_par_defaut(j: Journal) -> Parametres:
    p = Parametres(marge_ouverture=j.marge_solde or None)
    if j.dso_base:
        p.dso = j.dso_base
    return p


# --------------------------------------------------------------------------- #
# Calcul
# --------------------------------------------------------------------------- #
def _s(m: dict, ordres) -> float:
    return sum(m.get(o, 0.0) for o in ordres)


def _ajuste(m: dict, p: Parametres) -> dict:
    """Applique le scénario aux montants d'un exercice."""
    out = dict(m)
    for o in VENTES + AUTRES_REVENUS:
        out[o] = out.get(o, 0.0) * (1 + p.var_ventes)
    for o in ACHATS:
        out[o] = out.get(o, 0.0) * (1 + p.var_cout_produits)
    for o in AUTRES_CHARGES:
        out[o] = out.get(o, 0.0) * (1 + p.var_charges)
    for o in INTERETS:
        out[o] = out.get(o, 0.0) * (1 + p.var_taux)
    return out


def _fonds_de_roulement(m: dict, p: Parametres) -> tuple[float, float, float]:
    revenus = _s(m, VENTES + AUTRES_REVENUS)
    achats = -_s(m, ACHATS)
    base_fournisseurs = achats - _s(m, HORS_SALAIRES)
    return p.dso * revenus / 365, p.dio * achats / 365, p.dpo * base_fournisseurs / 365


def calculer(j: Journal, p: Parametres) -> dict:
    """Retourne {'ouverture': bilan, 'annees': {annee: {resultats, bilan, flux, capitaux}}, 'parametres': …}."""
    if not j.annees:
        raise ValueError("Le journal général est vide.")
    an_sc = p.annee_scenario if p.annee_scenario is not None else j.annees[-1]
    marge0 = p.marge_ouverture if p.marge_ouverture is not None else j.marge_solde

    premier = _ajuste(j.montants[j.annees[0]], p) if j.annees[0] >= an_sc else j.montants[j.annees[0]]
    ar, stock, ap = _fonds_de_roulement(premier, p)
    ouv = {"encaisse": p.encaisse_ouverture, "clients": ar, "stocks": stock, "immobilisations": p.immobilisations_ouverture,
           "fournisseurs": ap, "impots_a_payer": 0.0, "bdc": p.bdc_ouverture, "marge": marge0, "capital": p.capital_actions}
    ouv["bnr"] = (ouv["encaisse"] + ar + stock + p.immobilisations_ouverture) - (ap + p.bdc_ouverture + marge0) - p.capital_actions
    ouv["bdc_courant"] = 0.0

    etats, prev = {}, ouv
    for an in j.annees:
        m = _ajuste(j.montants[an], p) if an >= an_sc else j.montants[an]
        # --- état des résultats
        ventes = {o: m.get(o, 0.0) for o in VENTES}
        total_ventes = sum(ventes.values())
        autres_rev = _s(m, AUTRES_REVENUS)
        revenus = total_ventes + autres_rev
        achats = -_s(m, ACHATS)
        ar, stock, ap = _fonds_de_roulement(m, p)
        var_stock = prev["stocks"] - stock                      # +: on a puisé dans le stock → coût plus élevé
        cout_produits = achats + var_stock
        marge_brute = revenus - cout_produits
        ch_ops = {o: -m.get(o, 0.0) for o in CHARGES_OPERATIONS}
        ch_adm = {o: -m.get(o, 0.0) for o in CHARGES_ADMIN}
        baiia = marge_brute - sum(ch_ops.values()) - sum(ch_adm.values())
        amort = p.taux_amort * (prev["immobilisations"] + p.capex / 2)
        baii = baiia - amort
        remb_bdc = -m.get(BDC, 0.0)
        int_bdc = remb_bdc * p.part_interets_bdc
        principal_prevu = remb_bdc - int_bdc
        principal = min(principal_prevu, prev["bdc"])
        interets = -_s(m, INTERETS) + int_bdc
        subventions = _s(m, SUBVENTIONS)
        avant_impot = baii - interets + subventions
        impot = max(0.0, avant_impot) * p.taux_impot
        net = avant_impot - impot
        # --- dettes, impôts, dividendes
        remb_marge = -m.get(MARGE, 0.0)
        tirages = max(p.tirages_marge_pct * remb_marge, remb_marge - prev["marge"])     # le solde ne devient jamais négatif
        marge = prev["marge"] - remb_marge + tirages
        bdc = prev["bdc"] - principal
        impots_a_payer = impot * p.impot_impaye
        impots_payes = impot + prev["impots_a_payer"] - impots_a_payer
        dividendes = p.dividendes_pct * max(net, 0.0)
        # --- flux de trésorerie (méthode indirecte)
        d_clients, d_stocks = ar - prev["clients"], stock - prev["stocks"]
        d_fourn, d_impots = ap - prev["fournisseurs"], impots_a_payer - prev["impots_a_payer"]
        exploitation = net + amort - d_clients - d_stocks + d_fourn + d_impots
        investissement = -p.capex
        financement = -principal - remb_marge + tirages - dividendes + p.emission_actions
        variation = exploitation + investissement + financement
        encaisse = prev["encaisse"] + variation
        immo = prev["immobilisations"] + p.capex - amort
        capital = prev["capital"] + p.emission_actions
        bnr = prev["bnr"] + net - dividendes
        bdc_courant = min(principal_prevu, bdc)
        bilan = {"encaisse": encaisse, "clients": ar, "stocks": stock, "immobilisations": immo,
                 "fournisseurs": ap, "impots_a_payer": impots_a_payer, "bdc_courant": bdc_courant, "marge": marge, "bdc": bdc,
                 "capital": capital, "bnr": bnr}
        etats[an] = {
            "resultats": {"ventes": ventes, "total_ventes": total_ventes, "autres_revenus": autres_rev, "revenus": revenus,
                          "achats": achats, "var_stock": var_stock, "cout_produits": cout_produits, "marge_brute": marge_brute,
                          "charges_operations": ch_ops, "charges_admin": ch_adm, "baiia": baiia, "amortissement": amort, "baii": baii,
                          "interets": interets, "subventions": subventions, "avant_impot": avant_impot, "impot": impot, "net": net},
            "bilan": bilan,
            "flux": {"net": net, "amortissement": amort, "d_clients": -d_clients, "d_stocks": -d_stocks, "d_fournisseurs": d_fourn,
                     "d_impots": d_impots, "exploitation": exploitation, "acquisitions": -p.capex, "investissement": investissement,
                     "remb_bdc": -principal, "remb_marge": -remb_marge, "tirages_marge": tirages, "dividendes": -dividendes,
                     "emission": p.emission_actions, "financement": financement, "variation": variation,
                     "encaisse_debut": prev["encaisse"], "encaisse_fin": encaisse, "interets_payes": interets, "impots_payes": impots_payes},
            "capitaux": {"capital_debut": prev["capital"], "bnr_debut": prev["bnr"], "net": net, "dividendes": -dividendes,
                         "emission": p.emission_actions, "capital_fin": capital, "bnr_fin": bnr},
            "scenario_applique": an >= an_sc,
            "alertes": _alertes(an, marge, j.marge_limite, principal, principal_prevu, avant_impot),
        }
        prev = {**bilan, "encaisse": encaisse}
    return {"ouverture": ouv, "annees": etats, "parametres": asdict(p), "annee_scenario": an_sc}


def _alertes(an, marge, limite, principal, principal_prevu, avant_impot) -> list[str]:
    a = []
    if limite and marge > limite + 0.5:
        a.append(f"{an} : la marge de crédit ({marge:,.0f} $) dépasse la limite autorisée ({limite:,.0f} $).".replace(",", " "))
    if principal < principal_prevu - 0.5:
        a.append(f"{an} : l'emprunt BDC est remboursé en entier ; le surplus de remboursements journalisés est ignoré.")
    if avant_impot < 0:
        a.append(f"{an} : perte avant impôts — aucun impôt n'est calculé et aucun report de perte n'est modélisé.")
    return a


# --------------------------------------------------------------------------- #
# Contrôles et indicateurs
# --------------------------------------------------------------------------- #
def total_actif(b: dict) -> float:
    return b["encaisse"] + b["clients"] + b["stocks"] + b["immobilisations"]


def total_passif(b: dict) -> float:
    return b["fournisseurs"] + b["impots_a_payer"] + b["marge"] + b["bdc"]          # `bdc` = solde total, dont la tranche courante


def total_cp(b: dict) -> float:
    return b["capital"] + b["bnr"]


def _comptes(res: dict, annee: int, libelles: dict) -> list[tuple[str, str, str, float]]:
    """Soldes de tous les comptes AVANT clôture, en convention « débit positif » : (numéro, compte, groupe, solde)."""
    e = res["annees"][annee]
    b, r, c = e["bilan"], e["resultats"], e["capitaux"]
    lib = lambda o, defaut: libelles.get(o, defaut)
    L = [("1010", "Encaisse", "Actif", b["encaisse"]), ("1100", "Comptes clients", "Actif", b["clients"]),
         ("1200", "Stocks de produits", "Actif", b["stocks"]), ("1500", "Immobilisations corporelles nettes", "Actif", b["immobilisations"]),
         ("2010", "Fournisseurs et charges à payer", "Passif", -b["fournisseurs"]), ("2100", "Impôts à payer", "Passif", -b["impots_a_payer"]),
         ("2400", "Marge de crédit d'exploitation", "Passif", -b["marge"]), ("2500", "Emprunt BDC (tranche courante comprise)", "Passif", -b["bdc"]),
         ("3010", "Capital-actions", "Capitaux propres", -c["capital_fin"]),
         ("3100", "Bénéfices non répartis au début de l'exercice", "Capitaux propres", -c["bnr_debut"]),
         ("3200", "Dividendes déclarés", "Capitaux propres", -c["dividendes"])]
    L += [(str(4000 + (o - 19) * 10), lib(o, f"Ventes {o}"), "Produits", -r["ventes"][o]) for o in VENTES]
    L += [("4500", lib(25, "Autres revenus"), "Produits", -r["autres_revenus"]), ("4900", lib(24, "Subventions"), "Produits", -r["subventions"]),
          ("5010", "Coût des produits vendus (achats et variation des stocks)", "Charges", r["cout_produits"])]
    L += [(str(6000 + o * 10), lib(o, f"Charges {o}"), "Charges", r["charges_operations"][o]) for o in CHARGES_OPERATIONS]
    L += [(str(7000 + o * 10), lib(o, f"Charges {o}"), "Charges", r["charges_admin"][o]) for o in CHARGES_ADMIN]
    L += [("8010", "Amortissement des immobilisations", "Charges", r["amortissement"]),
          ("8100", "Intérêts et frais bancaires (dont intérêts BDC)", "Charges", r["interets"]),
          ("9010", "Impôts sur le résultat", "Charges", r["impot"])]
    return sorted(L, key=lambda x: x[0])


def balance_de_verification(res: dict, j: Journal | None, annee: int) -> dict:
    """Balance de vérification avant clôture : un compte par ligne, débits et crédits, totaux et équilibre."""
    lignes = []
    for numero, compte, groupe, v in _comptes(res, annee, j.libelles if j else {}):
        lignes.append({"numero": numero, "compte": compte, "groupe": groupe, "debit": max(v, 0.0), "credit": max(-v, 0.0)})
    td, tc = sum(l["debit"] for l in lignes), sum(l["credit"] for l in lignes)
    return {"annee": annee, "lignes": lignes, "total_debit": td, "total_credit": tc, "ecart": td - tc, "equilibre": abs(td - tc) < 0.01}


def verifications(res: dict) -> list[dict]:
    """Identités comptables, exercice par exercice : [{exercice, controle, ok, ecart}]."""
    out, prev = [], res["ouverture"]
    for an, e in res["annees"].items():
        b, f, c, r = e["bilan"], e["flux"], e["capitaux"], e["resultats"]
        tests = {
            "Actif = passif + capitaux propres": total_actif(b) - total_passif(b) - total_cp(b),
            "Encaisse du bilan = encaisse finale des flux": b["encaisse"] - f["encaisse_fin"],
            "Variation de l'encaisse = exploitation + investissement + financement": f["variation"] - (f["exploitation"] + f["investissement"] + f["financement"]),
            "Bénéfices non répartis : début + résultat net − dividendes = fin": c["bnr_fin"] - (c["bnr_debut"] + c["net"] + c["dividendes"]),
            "Résultat net des flux = résultat net de l'état des résultats": f["net"] - r["net"],
            "Capitaux propres du bilan = état de la variation": total_cp(b) - (c["capital_fin"] + c["bnr_fin"]),
            "Balance de vérification : total des débits = total des crédits": balance_de_verification(res, None, an)["ecart"],
        }
        out += [{"exercice": an, "controle": k, "ok": abs(v) < 0.01, "ecart": v} for k, v in tests.items()]
        prev = b
    return out


def indicateurs(e: dict) -> dict:
    r, b, f = e["resultats"], e["bilan"], e["flux"]
    cp, passif_courant = total_cp(b), b["fournisseurs"] + b["impots_a_payer"] + b["bdc_courant"] + b["marge"]
    actif_courant = b["encaisse"] + b["clients"] + b["stocks"]
    dette = b["marge"] + b["bdc"]
    rev = r["revenus"] or 1.0
    return {"Marge brute (%)": 100 * r["marge_brute"] / rev, "BAIIA (%)": 100 * r["baiia"] / rev, "Marge nette (%)": 100 * r["net"] / rev,
            "Liquidité générale (x)": actif_courant / passif_courant if passif_courant else float("nan"),
            "Fonds de roulement ($)": actif_courant - passif_courant,
            "Dette nette ($)": dette - b["encaisse"],
            "Dette nette / BAIIA (x)": (dette - b["encaisse"]) / r["baiia"] if r["baiia"] else float("nan"),
            "Dette / capitaux propres (x)": dette / cp if cp else float("nan"),
            "Couverture des intérêts (x)": r["baii"] / r["interets"] if r["interets"] else float("nan"),
            "Rendement des capitaux propres (%)": 100 * r["net"] / cp if cp else float("nan"),
            "Flux d'exploitation ($)": f["exploitation"]}


# --------------------------------------------------------------------------- #
# Présentation : lignes prêtes à afficher (même source pour l'écran et pour Excel)
# --------------------------------------------------------------------------- #
# style : "titre" · "ligne" · "sous" (sous-total) · "total" · "info"
def _cols(res: dict, annee: int, cle: str, f) -> list:
    """Valeurs de la ligne pour [exercice, exercice précédent] ; None si l'exercice précédent n'existe pas."""
    out = []
    for an in (annee, annee - 1):
        if an in res["annees"]:
            out.append(f(res["annees"][an][cle]))
        else:
            out.append(None)
    return out


def presenter(res: dict, j: Journal, annee: int) -> dict:
    lib = lambda o: j.libelles.get(o, f"Catégorie {o}")
    R = lambda f: _cols(res, annee, "resultats", f)
    resultats = [("titre", "Produits", [None, None])]
    resultats += [("ligne", lib(o), R(lambda r, o=o: r["ventes"][o])) for o in VENTES]
    resultats += [("sous", "Total des ventes", R(lambda r: r["total_ventes"])),
                  ("ligne", lib(25), R(lambda r: r["autres_revenus"])),
                  ("sous", "Total des produits", R(lambda r: r["revenus"])),
                  ("titre", "Coût des produits vendus", [None, None]),
                  ("ligne", "Achats de produits et consommables", R(lambda r: r["achats"])),
                  ("ligne", "Variation des stocks", R(lambda r: r["var_stock"])),
                  ("sous", "Coût des produits vendus", R(lambda r: r["cout_produits"])),
                  ("total", "Marge brute", R(lambda r: r["marge_brute"])),
                  ("titre", "Charges d'exploitation", [None, None])]
    resultats += [("ligne", lib(o), R(lambda r, o=o: r["charges_operations"][o])) for o in CHARGES_OPERATIONS]
    resultats += [("titre", "Frais de vente et d'administration", [None, None])]
    resultats += [("ligne", lib(o), R(lambda r, o=o: r["charges_admin"][o])) for o in CHARGES_ADMIN]
    resultats += [("total", "Résultat avant intérêts, impôts et amortissement (BAIIA)", R(lambda r: r["baiia"])),
                  ("ligne", "Amortissement des immobilisations", R(lambda r: r["amortissement"])),
                  ("sous", "Résultat d'exploitation (BAII)", R(lambda r: r["baii"])),
                  ("ligne", "Intérêts et frais bancaires (dont intérêts BDC)", R(lambda r: r["interets"])),
                  ("ligne", lib(24), R(lambda r: r["subventions"])),
                  ("sous", "Résultat avant impôts", R(lambda r: r["avant_impot"])),
                  ("ligne", "Impôts sur le résultat", R(lambda r: r["impot"])),
                  ("total", "Résultat net", R(lambda r: r["net"]))]

    def bil(f):
        out = []
        for an in (annee, annee - 1):
            if an in res["annees"]:
                out.append(f(res["annees"][an]["bilan"]))
            elif an == annee - 1 and annee == j.annees[0]:
                out.append(f({**res["ouverture"]}))                       # bilan d'ouverture comme comparatif
            else:
                out.append(None)
        return out
    bilan = [("titre", "Actif courant", [None, None]),
             ("ligne", "Encaisse", bil(lambda b: b["encaisse"])), ("ligne", "Comptes clients", bil(lambda b: b["clients"])),
             ("ligne", "Stocks de produits", bil(lambda b: b["stocks"])),
             ("sous", "Total de l'actif courant", bil(lambda b: b["encaisse"] + b["clients"] + b["stocks"])),
             ("ligne", "Immobilisations corporelles nettes", bil(lambda b: b["immobilisations"])),
             ("total", "Total de l'actif", bil(total_actif)),
             ("titre", "Passif courant", [None, None]),
             ("ligne", "Fournisseurs et charges à payer", bil(lambda b: b["fournisseurs"])),
             ("ligne", "Impôts à payer", bil(lambda b: b["impots_a_payer"])),
             ("ligne", "Tranche à court terme de l'emprunt BDC", bil(lambda b: b["bdc_courant"])),
             ("ligne", "Marge de crédit d'exploitation", bil(lambda b: b["marge"])),
             ("sous", "Total du passif courant", bil(lambda b: b["fournisseurs"] + b["impots_a_payer"] + b["bdc_courant"] + b["marge"])),
             ("ligne", "Emprunt BDC à long terme", bil(lambda b: b["bdc"] - b["bdc_courant"])),
             ("sous", "Total du passif", bil(total_passif)),
             ("titre", "Capitaux propres", [None, None]),
             ("ligne", "Capital-actions", bil(lambda b: b["capital"])), ("ligne", "Bénéfices non répartis", bil(lambda b: b["bnr"])),
             ("sous", "Total des capitaux propres", bil(total_cp)),
             ("total", "Total du passif et des capitaux propres", bil(lambda b: total_passif(b) + total_cp(b)))]

    F = lambda f: _cols(res, annee, "flux", f)
    flux = [("titre", "Activités d'exploitation", [None, None]),
            ("ligne", "Résultat net", F(lambda f: f["net"])), ("ligne", "Amortissement", F(lambda f: f["amortissement"])),
            ("ligne", "Variation des comptes clients", F(lambda f: f["d_clients"])),
            ("ligne", "Variation des stocks", F(lambda f: f["d_stocks"])),
            ("ligne", "Variation des fournisseurs et charges à payer", F(lambda f: f["d_fournisseurs"])),
            ("ligne", "Variation des impôts à payer", F(lambda f: f["d_impots"])),
            ("sous", "Flux de trésorerie d'exploitation", F(lambda f: f["exploitation"])),
            ("titre", "Activités d'investissement", [None, None]),
            ("ligne", "Acquisition d'immobilisations (centres d'usinage CNC, outillage, équipements d'atelier)", F(lambda f: f["acquisitions"])),
            ("sous", "Flux de trésorerie d'investissement", F(lambda f: f["investissement"])),
            ("titre", "Activités de financement", [None, None]),
            ("ligne", "Remboursement du capital de l'emprunt BDC", F(lambda f: f["remb_bdc"])),
            ("ligne", "Remboursement de la marge de crédit", F(lambda f: f["remb_marge"])),
            ("ligne", "Tirages sur la marge de crédit", F(lambda f: f["tirages_marge"])),
            ("ligne", "Dividendes versés", F(lambda f: f["dividendes"])),
            ("ligne", "Émission d'actions", F(lambda f: f["emission"])),
            ("sous", "Flux de trésorerie de financement", F(lambda f: f["financement"])),
            ("total", "Variation nette de l'encaisse", F(lambda f: f["variation"])),
            ("ligne", "Encaisse au début de l'exercice", F(lambda f: f["encaisse_debut"])),
            ("total", "Encaisse à la fin de l'exercice", F(lambda f: f["encaisse_fin"])),
            ("info", "Intérêts payés (inclus dans le résultat net)", F(lambda f: f["interets_payes"])),
            ("info", "Impôts payés (inclus dans le résultat net)", F(lambda f: f["impots_payes"]))]

    C = lambda f: _cols(res, annee, "capitaux", f)
    capitaux = [("ligne", "Solde au début de l'exercice — capital-actions", C(lambda c: c["capital_debut"])),
                ("ligne", "Solde au début de l'exercice — bénéfices non répartis", C(lambda c: c["bnr_debut"])),
                ("sous", "Solde au début de l'exercice — total", C(lambda c: c["capital_debut"] + c["bnr_debut"])),
                ("ligne", "Résultat net de l'exercice", C(lambda c: c["net"])),
                ("ligne", "Dividendes déclarés", C(lambda c: c["dividendes"])),
                ("ligne", "Émission d'actions", C(lambda c: c["emission"])),
                ("ligne", "Solde à la fin — capital-actions", C(lambda c: c["capital_fin"])),
                ("ligne", "Solde à la fin — bénéfices non répartis", C(lambda c: c["bnr_fin"])),
                ("total", "Solde à la fin de l'exercice — total", C(lambda c: c["capital_fin"] + c["bnr_fin"]))]
    return {"resultats": resultats, "bilan": bilan, "flux": flux, "capitaux": capitaux}


def classeur_excel(res: dict, j: Journal, annee: int) -> bytes:
    """Les quatre états de l'exercice (avec le précédent en comparatif) dans un classeur Excel."""
    import io
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    wb = Workbook()
    wb.remove(wb.active)
    pres = presenter(res, j, annee)
    titres = {"resultats": "Résultats", "bilan": "Bilan", "flux": "Flux de trésorerie", "capitaux": "Capitaux propres"}
    for cle, lignes in pres.items():
        ws = wb.create_sheet(titres[cle])
        ws.append([titres[cle], f"FY{annee}", f"FY{annee - 1}"])
        for c in ws[1]:
            c.font, c.fill = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="1F5F8B")
        for style, libelle, vals in lignes:
            ws.append([libelle, *[None if v is None else round(v, 2) for v in vals]])
            row = ws[ws.max_row]
            if style in ("titre", "sous", "total"):
                for c in row:
                    c.font = Font(bold=True)
            if style == "total":
                for c in row:
                    c.fill = PatternFill("solid", fgColor="E6F2EE")
            for c in row[1:]:
                c.number_format = '#,##0;(#,##0);"—"'
                c.alignment = Alignment(horizontal="right")
        ws.column_dimensions["A"].width = 74
        ws.column_dimensions["B"].width = ws.column_dimensions["C"].width = 18
    bv = balance_de_verification(res, j, annee)
    ws = wb.create_sheet("Balance de vérification")
    ws.append([f"Balance de vérification avant clôture — FY{annee}", "", "Débit", "Crédit"])
    for c in ws[1]:
        c.font, c.fill = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="1F5F8B")
    for l in bv["lignes"]:
        ws.append([l["numero"], l["compte"], round(l["debit"], 2) or None, round(l["credit"], 2) or None])
        for c in ws[ws.max_row][2:]:
            c.number_format = '#,##0.00'
    ws.append(["", "TOTAL", round(bv["total_debit"], 2), round(bv["total_credit"], 2)])
    for c in ws[ws.max_row]:
        c.font, c.fill = Font(bold=True), PatternFill("solid", fgColor="E6F2EE")
        c.number_format = '#,##0.00'
    ws.append(["", "Équilibre", "OK" if bv["equilibre"] else f"ÉCART {bv['ecart']:,.2f}"])
    ws.column_dimensions["A"].width, ws.column_dimensions["B"].width = 10, 62
    ws.column_dimensions["C"].width = ws.column_dimensions["D"].width = 18
    hyp = wb.create_sheet("Hypothèses")
    hyp.append(["Paramètre", "Valeur"])
    for k, v in res["parametres"].items():
        hyp.append([k, v])
    hyp.column_dimensions["A"].width = 30
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
