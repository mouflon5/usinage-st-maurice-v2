"""Consolidation des trois divisions de Groupe Usinage Saint-Maurice : états des divisions, transactions intercompagnies, écritures d'élimination.

Les divisions sont des unités d'une même société (aucune participation de l'une dans l'autre) : il n'y a donc ni élimination de titres, ni écart
d'acquisition, ni part des actionnaires sans contrôle. La consolidation est un regroupement suivi de l'élimination des opérations internes.

Méthode (descendante) : les états existants de l'entreprise (`etats_financiers.calculer`) sont les états consolidés à retrouver. On
  1. répartit leurs produits, charges, actifs et passifs entre les trois divisions (clés de répartition ci-dessous) ;
  2. ajoute les transactions intercompagnies, vues des états de chaque division (ventes de pièces au prix de cession, temps-machine refacturé,
     frais de gestion, prêt et intérêts, soldes à recevoir et à payer, marge interne dans les stocks) ;
  3. additionne (états agrégés) puis élimine, par des écritures de consolidation, tout ce qui est interne.
Le consolidé égale alors exactement les états existants : `controles()` le vérifie, ligne par ligne.

Divisions : USI Usinage de précision (usine, machines CNC, soudure, siège) · PIE Pièces de rechange et service · PRO Prototypage et ingénierie.
L'encaisse et les bénéfices non répartis de chaque division sont des soldes de répartition : l'encaisse suit une clé, et les bénéfices non répartis
équilibrent le bilan de la division. L'impôt est calculé à l'échelle de la société et réparti selon le résultat avant impôts hors marge de cession
(une seule déclaration : aucun impôt différé sur la marge interne).
"""
from __future__ import annotations

from dataclasses import dataclass

import etats_financiers as ef

DIVISIONS = {"USI": "Usinage de précision", "PIE": "Pièces de rechange et service", "PRO": "Prototypage et ingénierie"}
CODES = list(DIVISIONS)

POIDS_CPV = (1.0, 1.2, 1.0)                     # coût des produits par dollar de vente, relatif aux divisions
PART_SUBVENTIONS = (0.7, 0.3, 0.0)
PART_STOCKS = (0.60, 0.25, 0.15)
PART_IMMO = (0.76, 0.14, 0.10)
PART_DETTES = (0.74, 0.16, 0.10)                # marge de crédit, emprunt BDC et intérêts
PART_ENCAISSE = (0.66, 0.16, 0.18)
PART_CAPITAL = (0.74, 0.14, 0.12)
PART_CHARGES = {                                # rang de catégorie du journal → (USI, PIE, PRO)
    3: (.82, .11, .07), 5: (.85, .09, .06), 7: (.83, .11, .06), 8: (.83, .07, .10), 9: (.83, .09, .08), 10: (.84, .11, .05),
    11: (.87, .09, .04), 13: (.85, .08, .07),
    4: (.81, .10, .09), 14: (.83, .08, .09), 15: (.81, .10, .09), 17: (.84, .10, .06), 18: (.77, .09, .14), 19: (.81, .09, .10),
}

@dataclass
class ParametresConso:
    achats_pie_chez_usi: float = 0.85     # part des pièces de PIE fabriquée par USI
    achats_pro_chez_usi: float = 0.55           # part des composants de PRO usinés par USI
    majoration: float = 0.08                    # prix de cession = coût × (1 + majoration)
    temps_machine_pct: float = 0.04                 # temps-machine refacturé à PIE, en % de ses ventes
    gestion_pct: float = 0.015                  # frais de gestion facturés à PIE et PRO, en % de leurs ventes
    pret: float = 250_000.0                     # prêt de USI à PRO
    taux_pret: float = 0.055
    jours_ic: float = 30.0                      # délai de règlement des factures intercompagnies


def _rep(total: float, parts) -> list[float]:
    return [total * p for p in parts]


def _somme(m: list[list[float]]) -> list[float]:
    return [sum(x) for x in zip(*m)]


def consolider(res: dict, annee: int, pc: ParametresConso | None = None) -> dict:
    """États des divisions, agrégés, éliminations et consolidés pour l'exercice (montants en dollars)."""
    pc = pc or ParametresConso()
    e = res["annees"][annee]
    r, b = e["resultats"], e["bilan"]
    prev = res["annees"].get(annee - 1, {"bilan": res["ouverture"]})["bilan"]
    m = pc.majoration

    # --- 1. répartition des états existants entre les divisions
    ventes = [r["ventes"][20] + r["ventes"][21], r["ventes"][22], r["ventes"][23]]
    autres = [0.0, 0.0, r["autres_revenus"]]
    rev = [v + a for v, a in zip(ventes, autres)]
    poids = [w * x for w, x in zip(POIDS_CPV, rev)]
    cpv = [r["cout_produits"] * p / sum(poids) for p in poids]
    ops = _somme([_rep(r["charges_operations"][o], PART_CHARGES[o]) for o in ef.CHARGES_OPERATIONS])
    adm = _somme([_rep(r["charges_admin"][o], PART_CHARGES[o]) for o in ef.CHARGES_ADMIN])
    amort, interets = _rep(r["amortissement"], PART_IMMO), _rep(r["interets"], PART_DETTES)
    subv = _rep(r["subventions"], PART_SUBVENTIONS)
    avant_ext = [rev[i] - cpv[i] - ops[i] - adm[i] - amort[i] - interets[i] + subv[i] for i in range(3)]
    t_eff = r["impot"] / r["avant_impot"] if r["avant_impot"] > 0 else 0.0
    impot = [t_eff * x for x in avant_ext]

    # --- 2. transactions intercompagnies (USI vend et facture à PIE et PRO)
    q = [0.0, pc.achats_pie_chez_usi, pc.achats_pro_chez_usi]
    stock = _rep(b["stocks"], PART_STOCKS)
    stock_prec = _rep(prev["stocks"], PART_STOCKS)
    c_vendu = [q[i] * cpv[i] for i in range(3)]                       # coût des produits internes vendus au client externe
    bc_fin, bc_deb = [q[i] * stock[i] for i in range(3)], [q[i] * stock_prec[i] for i in range(3)]
    d_bc = [bc_fin[i] - bc_deb[i] for i in range(3)]
    p_cout = [c_vendu[i] + d_bc[i] for i in range(3)]                 # produits transférés pendant l'exercice, au coût
    s_cession = [x * (1 + m) for x in p_cout]                         # … au prix de cession
    nr_fin, nr_deb = m * sum(bc_fin), m * sum(bc_deb)                 # marge interne contenue dans les stocks de fin et de début
    svc = pc.temps_machine_pct * ventes[1]
    gest = [0.0, pc.gestion_pct * ventes[1], pc.gestion_pct * ventes[2]]
    interet_ic = pc.pret * pc.taux_pret
    factures = [0.0, s_cession[1] + svc + gest[1], s_cession[2] + gest[2]]
    creance_ic = sum(factures) * pc.jours_ic / 365
    dette_ic = [x * pc.jours_ic / 365 for x in factures]

    R: dict[str, list[float]] = {
        "ventes": ventes, "ventes_ic": [sum(s_cession), 0.0, 0.0], "services_ic": [svc, 0.0, 0.0], "gestion_ic": [sum(gest), 0.0, 0.0], "autres": autres,
        "cpv_ext": [cpv[0] + sum(p_cout), cpv[1] - c_vendu[1], cpv[2] - c_vendu[2]],
        "achats_ic": [0.0, s_cession[1], s_cession[2]],
        "var_stock_ic": [0.0, -d_bc[1] * (1 + m), -d_bc[2] * (1 + m)],
        "ops": ops, "svc_ch": [0.0, svc, 0.0], "adm": adm, "gest_ch": gest,
        "amort": amort, "interets": interets, "interets_ic_ch": [0.0, 0.0, interet_ic], "prod_fin_ic": [interet_ic, 0.0, 0.0], "subventions": subv,
    }
    R["total_produits"] = [R["ventes"][i] + R["ventes_ic"][i] + R["services_ic"][i] + R["gestion_ic"][i] + R["autres"][i] for i in range(3)]
    R["cpv_total"] = [R["cpv_ext"][i] + R["achats_ic"][i] + R["var_stock_ic"][i] for i in range(3)]
    R["marge_brute"] = [R["total_produits"][i] - R["cpv_total"][i] for i in range(3)]
    R["baiia"] = [R["marge_brute"][i] - R["ops"][i] - R["svc_ch"][i] - R["adm"][i] - R["gest_ch"][i] for i in range(3)]
    R["baii"] = [R["baiia"][i] - R["amort"][i] for i in range(3)]
    R["avant_impot"] = [R["baii"][i] - R["interets"][i] - R["interets_ic_ch"][i] + R["prod_fin_ic"][i] + R["subventions"][i] for i in range(3)]
    R["impot"] = impot
    R["net"] = [R["avant_impot"][i] - impot[i] for i in range(3)]

    # --- bilan des divisions
    clients = _rep(b["clients"], [x / sum(rev) for x in rev])
    charges_tot = [cpv[i] + ops[i] + adm[i] for i in range(3)]
    fourn = _rep(b["fournisseurs"], [x / sum(charges_tot) for x in charges_tot])
    taxe = _rep(b["impots_a_payer"], [x / sum(impot) if sum(impot) else 0.0 for x in impot])
    B: dict[str, list[float]] = {
        "encaisse": _rep(b["encaisse"], PART_ENCAISSE), "clients": clients, "creances_ic": [creance_ic, 0.0, 0.0],
        "stocks": [stock[i] + m * bc_fin[i] for i in range(3)], "pret_ic": [pc.pret, 0.0, 0.0], "immobilisations": _rep(b["immobilisations"], PART_IMMO),
        "fournisseurs": fourn, "dettes_ic": dette_ic, "impots_a_payer": taxe, "bdc_courant": _rep(b["bdc_courant"], PART_DETTES),
        "marge": _rep(b["marge"], PART_DETTES), "bdc_lt": _rep(b["bdc"] - b["bdc_courant"], PART_DETTES), "emprunt_ic": [0.0, 0.0, pc.pret],
        "capital": _rep(b["capital"], PART_CAPITAL),
    }
    B["actif_courant"] = [B["encaisse"][i] + B["clients"][i] + B["creances_ic"][i] + B["stocks"][i] for i in range(3)]
    B["total_actif"] = [B["actif_courant"][i] + B["pret_ic"][i] + B["immobilisations"][i] for i in range(3)]
    B["passif_courant"] = [B["fournisseurs"][i] + B["dettes_ic"][i] + B["impots_a_payer"][i] + B["bdc_courant"][i] + B["marge"][i] for i in range(3)]
    B["total_passif"] = [B["passif_courant"][i] + B["bdc_lt"][i] + B["emprunt_ic"][i] for i in range(3)]
    B["bnr"] = [B["total_actif"][i] - B["total_passif"][i] - B["capital"][i] for i in range(3)]
    B["total_cp"] = [B["capital"][i] + B["bnr"][i] for i in range(3)]
    B["total_pcp"] = [B["total_passif"][i] + B["total_cp"][i] for i in range(3)]

    # --- 3. éliminations
    ER = {"ventes_ic": -sum(s_cession), "services_ic": -svc, "gestion_ic": -sum(gest), "achats_ic": -sum(s_cession), "svc_ch": -svc, "gest_ch": -sum(gest),
          "interets_ic_ch": -interet_ic, "prod_fin_ic": -interet_ic, "cpv_ext": nr_fin - nr_deb}
    EB = {"creances_ic": -creance_ic, "dettes_ic": -sum(dette_ic), "pret_ic": -pc.pret, "emprunt_ic": -pc.pret, "stocks": -nr_fin, "bnr": -nr_fin}
    agr_r, agr_b = {k: sum(v) for k, v in R.items()}, {k: sum(v) for k, v in B.items()}
    els_r, els_b = _cascade(ER, "r"), _cascade(EB, "b")
    cons_r = {k: agr_r[k] + els_r.get(k, 0.0) for k in agr_r}
    cons_b = {k: agr_b[k] + els_b.get(k, 0.0) for k in agr_b}

    s = round
    ecritures = [
        ("EC-1", "Élimination des ventes et des achats de pièces entre divisions", [("4110", "Ventes intercompagnies — pièces usinées", sum(s_cession), 0),
                                                                                  ("5110", "Achats intercompagnies", 0, sum(s_cession))]),
        ("EC-2", "Élimination du temps-machine refacturé", [("4120", "Produits de services intercompagnies", svc, 0),
                                                                     ("6800", "Services de temps-machine intercompagnies", 0, svc)]),
        ("EC-3", "Élimination des frais de gestion intercompagnies", [("4130", "Frais de gestion — produits", sum(gest), 0),
                                                                     ("7800", "Frais de gestion — charges", 0, sum(gest))]),
        ("EC-4", "Élimination des intérêts sur le prêt intercompagnies", [("4140", "Produits d'intérêts intercompagnies", interet_ic, 0),
                                                                       ("8110", "Intérêts intercompagnies", 0, interet_ic)]),
        ("EC-5", "Élimination des comptes à recevoir et à payer", [("2050", "Dettes intercompagnies", sum(dette_ic), 0),
                                                                  ("1150", "Créances intercompagnies", 0, creance_ic)]),
        ("EC-6", "Élimination du prêt intercompagnies", [("2550", "Emprunt intercompagnies", pc.pret, 0), ("1600", "Prêt intercompagnies à recevoir", 0, pc.pret)]),
        ("EC-7", "Élimination de la marge interne dans les stocks de fin", [("5010", "Coût des produits vendus", nr_fin, 0), ("1200", "Stocks de produits", 0, nr_fin)]),
        ("EC-8", "Marge interne des stocks de début, réalisée pendant l'exercice", [("3100", "Bénéfices non répartis au début", nr_deb, 0),
                                                                                  ("5010", "Coût des produits vendus", 0, nr_deb)]),
    ]
    journal = []
    for no, titre, lignes in ecritures:
        for compte, libelle, dt, ct in lignes:
            journal.append({"no": no, "titre": titre, "compte": compte, "libelle": libelle, "debit": dt, "credit": ct})
    return {
        "annee": annee, "parametres": pc, "divisions": R, "bilans": B, "agrege_r": agr_r, "agrege_b": agr_b, "elim_r": els_r, "elim_b": els_b,
        "consolide_r": cons_r, "consolide_b": cons_b, "journal": journal,
        "interco": {"ventes_produits": s_cession, "cout_transfere": p_cout, "services": svc, "gestion": gest, "interet": interet_ic, "pret": pc.pret,
                    "factures": factures, "creance": creance_ic, "dettes": dette_ic, "stock_cession_fin": [m * x for x in bc_fin], "nr_fin": nr_fin, "nr_deb": nr_deb,
                    "stock_ic_fin": bc_fin, "stock_ic_deb": bc_deb, "taux_impot_effectif": t_eff, "avant_impot_ext": avant_ext},
        "ext": e,
    }


def _cascade(elim: dict, _: str) -> dict:
    """Propage une élimination aux sous-totaux de l'état (les lignes de détail portent la valeur, les totaux la somme algébrique)."""
    e = dict(elim)
    g = e.get
    # état des résultats (signe : produits +, charges +)
    e["total_produits"] = g("ventes_ic", 0) + g("services_ic", 0) + g("gestion_ic", 0)
    e["cpv_total"] = g("cpv_ext", 0) + g("achats_ic", 0)
    e["marge_brute"] = e["total_produits"] - e["cpv_total"]
    e["baiia"] = e["marge_brute"] - g("svc_ch", 0) - g("gest_ch", 0)
    e["baii"] = e["baiia"]
    e["avant_impot"] = e["baii"] - g("interets_ic_ch", 0) + g("prod_fin_ic", 0)
    e["net"] = e["avant_impot"]
    # bilan
    e["actif_courant"] = g("creances_ic", 0) + g("stocks", 0)
    e["total_actif"] = e["actif_courant"] + g("pret_ic", 0)
    e["passif_courant"] = g("dettes_ic", 0)
    e["total_passif"] = e["passif_courant"] + g("emprunt_ic", 0)
    e["total_cp"] = g("bnr", 0)
    e["total_pcp"] = e["total_passif"] + e["total_cp"]
    return e


COMPTES_IC = [  # (compte, libellé, état, côté habituel)
    ("4110", "Ventes intercompagnies — pièces usinées", "Résultats", "Produit"), ("4120", "Produits de services intercompagnies", "Résultats", "Produit"),
    ("4130", "Frais de gestion — produits", "Résultats", "Produit"), ("4140", "Produits d'intérêts intercompagnies", "Résultats", "Produit"),
    ("5110", "Achats intercompagnies", "Résultats", "Charge"), ("6800", "Services de temps-machine intercompagnies", "Résultats", "Charge"),
    ("7800", "Frais de gestion — charges", "Résultats", "Charge"), ("8110", "Intérêts intercompagnies", "Résultats", "Charge"),
    ("1150", "Créances intercompagnies", "Bilan", "Actif"), ("1600", "Prêt intercompagnies à recevoir", "Bilan", "Actif"),
    ("2050", "Dettes intercompagnies", "Bilan", "Passif"), ("2550", "Emprunt intercompagnies", "Bilan", "Passif"),
]


def ecritures_divisions(c: dict) -> list[dict]:
    """Écritures que chaque division passe dans ses propres livres pour les opérations internes, AVANT la consolidation (dollars).
    Chaque opération est facturée à la division acheteuse ; la part non réglée à la clôture reste en créance (vendeur) et en dette (acheteur)."""
    ic, nom = c["interco"], DIVISIONS
    jours = c["parametres"].jours_ic / 365
    out: list[dict] = []

    def add(op, div, compte, lib, dt=0.0, ct=0.0):
        out.append({"operation": op, "division": nom[div], "compte": compte, "libelle": lib, "debit": dt, "credit": ct})

    for i, div in ((1, "PIE"), (2, "PRO")):
        s, p = ic["ventes_produits"][i], ic["cout_transfere"][i]
        add(f"Vente de pièces à {nom[div]}", "USI", "1150", "Créances intercompagnies", dt=s)
        add(f"Vente de pièces à {nom[div]}", "USI", "4110", "Ventes intercompagnies — pièces usinées", ct=s)
        add(f"Vente de pièces à {nom[div]}", "USI", "5010", "Coût des produits vendus", dt=p)
        add(f"Vente de pièces à {nom[div]}", "USI", "1200", "Stocks de produits", ct=p)
        add("Achat de pièces à l'Usinage de précision", div, "5110", "Achats intercompagnies", dt=s)
        add("Achat de pièces à l'Usinage de précision", div, "2050", "Dettes intercompagnies", ct=s)
    add("Temps-machine refacturé à Pièces de rechange", "USI", "1150", "Créances intercompagnies", dt=ic["services"])
    add("Temps-machine refacturé à Pièces de rechange", "USI", "4120", "Produits de services intercompagnies", ct=ic["services"])
    add("Temps-machine refacturé à Pièces de rechange", "PIE", "6800", "Services de temps-machine intercompagnies", dt=ic["services"])
    add("Temps-machine refacturé à Pièces de rechange", "PIE", "2050", "Dettes intercompagnies", ct=ic["services"])
    for i, div in ((1, "PIE"), (2, "PRO")):
        add(f"Frais de gestion facturés à {nom[div]}", "USI", "1150", "Créances intercompagnies", dt=ic["gestion"][i])
        add(f"Frais de gestion facturés à {nom[div]}", "USI", "4130", "Frais de gestion — produits", ct=ic["gestion"][i])
        add(f"Frais de gestion facturés à {nom[div]}", div, "7800", "Frais de gestion — charges", dt=ic["gestion"][i])
        add(f"Frais de gestion facturés à {nom[div]}", div, "2050", "Dettes intercompagnies", ct=ic["gestion"][i])
    reglees = [(i, f * (1 - jours)) for i, f in enumerate(ic["factures"])]
    for i, regl in reglees:
        if i:
            div = CODES[i]
            add(f"Règlement des factures de {nom[div]} (hors solde de clôture)", "USI", "1010", "Encaisse", dt=regl)
            add(f"Règlement des factures de {nom[div]} (hors solde de clôture)", "USI", "1150", "Créances intercompagnies", ct=regl)
            add(f"Règlement des factures de {nom[div]} (hors solde de clôture)", div, "2050", "Dettes intercompagnies", dt=regl)
            add(f"Règlement des factures de {nom[div]} (hors solde de clôture)", div, "1010", "Encaisse", ct=regl)
    add("Prêt de l'Usinage de précision au Prototypage", "USI", "1600", "Prêt intercompagnies à recevoir", dt=ic["pret"])
    add("Prêt de l'Usinage de précision au Prototypage", "USI", "1010", "Encaisse", ct=ic["pret"])
    add("Prêt de l'Usinage de précision au Prototypage", "PRO", "1010", "Encaisse", dt=ic["pret"])
    add("Prêt de l'Usinage de précision au Prototypage", "PRO", "2550", "Emprunt intercompagnies", ct=ic["pret"])
    add("Intérêts sur le prêt (réglés)", "USI", "1010", "Encaisse", dt=ic["interet"])
    add("Intérêts sur le prêt (réglés)", "USI", "4140", "Produits d'intérêts intercompagnies", ct=ic["interet"])
    add("Intérêts sur le prêt (réglés)", "PRO", "8110", "Intérêts intercompagnies", dt=ic["interet"])
    add("Intérêts sur le prêt (réglés)", "PRO", "1010", "Encaisse", ct=ic["interet"])
    return out


def controles(c: dict) -> list[dict]:
    """Identités vérifiées à chaque consolidation : [{controle, ok, ecart}]."""
    ext = c["ext"]
    r, b = ext["resultats"], ext["bilan"]
    cr, cb, ar, ab = c["consolide_r"], c["consolide_b"], c["agrege_r"], c["agrege_b"]
    ic = c["interco"]
    ctr: list[tuple[str, float]] = [
        ("Total des produits consolidé = états existants", cr["total_produits"] - r["revenus"]),
        ("Coût des produits vendus consolidé = états existants", cr["cpv_total"] - r["cout_produits"]),
        ("BAIIA consolidé = états existants", cr["baiia"] - r["baiia"]),
        ("Résultat avant impôts consolidé = états existants", cr["avant_impot"] - r["avant_impot"]),
        ("Résultat net consolidé = états existants", cr["net"] - r["net"]),
        ("Total de l'actif consolidé = états existants", cb["total_actif"] - ef.total_actif(b)),
        ("Stocks consolidés = états existants", cb["stocks"] - b["stocks"]),
        ("Passif consolidé = états existants", cb["total_passif"] - ef.total_passif(b)),
        ("Bénéfices non répartis consolidés = états existants", cb["bnr"] - b["bnr"]),
        ("Ventes interentreprises = achats interentreprises", ar["ventes_ic"] - ar["achats_ic"]),
        ("Services facturés = services comptabilisés en charges", ar["services_ic"] - ar["svc_ch"]),
        ("Frais de gestion facturés = frais comptabilisés", ar["gestion_ic"] - ar["gest_ch"]),
        ("Intérêts reçus = intérêts payés", ar["prod_fin_ic"] - ar["interets_ic_ch"]),
        ("Créances intercompagnies = dettes intercompagnies", ab["creances_ic"] - ab["dettes_ic"]),
        ("Prêt à recevoir = emprunt à rembourser", ab["pret_ic"] - ab["emprunt_ic"]),
        ("Écritures de consolidation : débits = crédits", sum(l["debit"] for l in c["journal"]) - sum(l["credit"] for l in c["journal"])),
        ("Résultats des divisions avant transactions internes = résultat de l'entreprise",
         sum(ic["avant_impot_ext"]) - r["avant_impot"]),
        ("Bilans des divisions équilibrés", sum(c["bilans"]["total_actif"]) - sum(c["bilans"]["total_pcp"])),
    ]
    return [{"controle": n, "ok": abs(v) < 0.5, "ecart": v} for n, v in ctr]


# --- Présentation : lignes (style, libellé, [USI, PIE, PRO, agrégé, éliminations, consolidé]) ---------------------------------------------------
def _ligne(c: dict, cle: str, style: str, libelle: str, etat: str) -> tuple:
    div, agr, el, con = ((c["divisions"], c["agrege_r"], c["elim_r"], c["consolide_r"]) if etat == "r" else (c["bilans"], c["agrege_b"], c["elim_b"], c["consolide_b"]))
    return (style, libelle, [*div[cle], agr[cle], el.get(cle, 0.0), con[cle]])


def presenter(c: dict) -> dict:
    L = lambda cle, st, lib: _ligne(c, cle, st, lib, "r")
    V = [None] * 6
    resultats = [
        ("titre", "Produits", V), L("ventes", "ligne", "Ventes externes"), L("ventes_ic", "ligne", "Ventes intercompagnies — pièces usinées (4110)"),
        L("services_ic", "ligne", "Services de temps-machine intercompagnies (4120)"), L("gestion_ic", "ligne", "Frais de gestion intercompagnies (4130)"),
        L("autres", "ligne", "Autres revenus (récupération de métaux)"), L("total_produits", "sous", "Total des produits"),
        ("titre", "Coût des produits vendus", V), L("cpv_ext", "ligne", "Coût des produits vendus"), L("achats_ic", "ligne", "Achats intercompagnies (5110)"),
        L("var_stock_ic", "ligne", "Variation des stocks — produits intercompagnies"), L("cpv_total", "sous", "Coût des produits vendus — total"),
        L("marge_brute", "total", "Marge brute"),
        ("titre", "Charges", V), L("ops", "ligne", "Charges d'exploitation"), L("svc_ch", "ligne", "Services de temps-machine intercompagnies (6800)"),
        L("adm", "ligne", "Frais de vente et d'administration"), L("gest_ch", "ligne", "Frais de gestion intercompagnies (7800)"),
        L("baiia", "total", "BAIIA"), L("amort", "ligne", "Amortissement des immobilisations"), L("baii", "sous", "Résultat d'exploitation (BAII)"),
        L("interets", "ligne", "Intérêts et frais bancaires"), L("interets_ic_ch", "ligne", "Intérêts intercompagnies — charge (8110)"),
        L("prod_fin_ic", "ligne", "Intérêts intercompagnies — produit (4140)"), L("subventions", "ligne", "Subventions et crédits"),
        L("avant_impot", "sous", "Résultat avant impôts"), L("impot", "ligne", "Impôts sur le résultat"), L("net", "total", "Résultat net"),
    ]
    B = lambda cle, st, lib: _ligne(c, cle, st, lib, "b")
    bilan = [
        ("titre", "Actif", V), B("encaisse", "ligne", "Encaisse"), B("clients", "ligne", "Comptes clients"), B("creances_ic", "ligne", "Créances intercompagnies (1150)"),
        B("stocks", "ligne", "Stocks de produits"), B("actif_courant", "sous", "Total de l'actif courant"),
        B("pret_ic", "ligne", "Prêt intercompagnies à recevoir (1600)"), B("immobilisations", "ligne", "Immobilisations corporelles nettes"),
        B("total_actif", "total", "Total de l'actif"),
        ("titre", "Passif", V), B("fournisseurs", "ligne", "Fournisseurs et charges à payer"), B("dettes_ic", "ligne", "Dettes intercompagnies (2050)"),
        B("impots_a_payer", "ligne", "Impôts à payer"), B("bdc_courant", "ligne", "Tranche à court terme de l'emprunt BDC"),
        B("marge", "ligne", "Marge de crédit d'exploitation"), B("passif_courant", "sous", "Total du passif courant"),
        B("bdc_lt", "ligne", "Emprunt BDC à long terme"), B("emprunt_ic", "ligne", "Emprunt intercompagnies (2550)"), B("total_passif", "sous", "Total du passif"),
        ("titre", "Capitaux propres", V), B("capital", "ligne", "Capital-actions"), B("bnr", "ligne", "Bénéfices non répartis"),
        B("total_cp", "sous", "Total des capitaux propres"), B("total_pcp", "total", "Total du passif et des capitaux propres"),
    ]
    return {"resultats": resultats, "bilan": bilan}


def classeur_excel(c: dict) -> bytes:
    """Chiffriers de consolidation (résultats, bilan) et journal des écritures dans un classeur Excel."""
    import io
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    wb = Workbook()
    wb.remove(wb.active)
    ent = ["", *DIVISIONS.values(), "Agrégé", "Éliminations", "Consolidé"]
    for nom, lignes in (("Chiffrier résultats", presenter(c)["resultats"]), ("Chiffrier bilan", presenter(c)["bilan"])):
        ws = wb.create_sheet(nom)
        ws.append([f"{nom} — FY{c['annee']}", *ent[1:]])
        for cell in ws[1]:
            cell.font, cell.fill = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="1F5F8B")
        for style, libelle, vals in lignes:
            ws.append([libelle, *[None if v is None else round(v, 2) for v in vals]])
            for cell in ws[ws.max_row]:
                if style in ("titre", "sous", "total"):
                    cell.font = Font(bold=True)
            for cell in ws[ws.max_row][1:]:
                cell.number_format = '#,##0;(#,##0);"—"'
                cell.alignment = Alignment(horizontal="right")
        ws.column_dimensions["A"].width = 58
        for col in "BCDEFG":
            ws.column_dimensions[col].width = 18
    ws = wb.create_sheet("Écritures de consolidation")
    ws.append(["N°", "Écriture", "Compte", "Libellé", "Débit", "Crédit"])
    for cell in ws[1]:
        cell.font, cell.fill = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="1F5F8B")
    for l in c["journal"]:
        ws.append([l["no"], l["titre"], l["compte"], l["libelle"], round(l["debit"], 2) or None, round(l["credit"], 2) or None])
        for cell in ws[ws.max_row][4:]:
            cell.number_format = '#,##0.00'
    for col, w in zip("ABCDEF", (8, 62, 10, 40, 16, 16)):
        ws.column_dimensions[col].width = w
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
