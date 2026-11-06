"""Consolidation juridique du Groupe Saint-Maurice : cas intégrateur du cours (NCECF, Partie II), exercice clos le 31 décembre 2025.

Le groupe : Gestion Saint-Maurice (société mère) détient Usinage Saint-Maurice (100 %) et Immeubles Saint-Maurice (100 %) ; Usinage Saint-Maurice détient
Soudure Bécancour (80 %, acquise le 1er avril 2025, d'où une participation ne donnant pas le contrôle — PNDC — de 20 %) et USM Precision Inc. (100 %, filiale
américaine tenue en dollars US, établissement autonome). Les montants viennent du classeur Chiffrier_consolidation_Groupe_Saint-Maurice.xlsx et se
recalculent quand on change une hypothèse. Neuf étapes, comme dans le classeur :

  01 Hypothèses  ·  02 Balances de vérification  ·  03 Conversion USD (cours de clôture)  ·  04 Acquisition et répartition du prix  ·  05 Les 19 écritures
  06 Chiffrier  ·  07 PNDC  ·  08 États financiers consolidés  ·  09 Les 8 contrôles

Convention du grand livre : un débit est positif, un crédit est négatif. Chaque balance de vérification (une par entité) totalise zéro. Le consolidé de
chaque compte est la somme des cinq entités, plus les débits et moins les crédits des écritures de consolidation ; ces écritures n'existent que dans le chiffrier.
Fonctions pures, testées par test_consolidation_groupe.py ; l'affichage est dans demo_live/groupe_ui.py.
"""
from __future__ import annotations

from dataclasses import dataclass, fields, replace

import pandas as pd

from consolidation_groupe_textes import EXPLICATIONS

ENTITES = ("GSM", "USM", "ISM", "SBE", "USP")
NOMS = {"GSM": "Gestion Saint-Maurice", "USM": "Usinage Saint-Maurice", "ISM": "Immeubles Saint-Maurice", "SBE": "Soudure Bécancour", "USP": "USM Precision"}
ROLES = {"GSM": "Société mère. Facture des honoraires de gestion aux filiales et détient un billet à recevoir de Soudure Bécancour.",
         "USM": "Opérante manufacturière, détenue à 100 %. Détient Soudure Bécancour (80 %) et USM Precision (100 %).",
         "ISM": "Détient l'usine et la loue à l'opérante, 100 %.",
         "SBE": "Acquise à 80 % le 1er avril 2025 — d'où une PNDC de 20 % et neuf mois de résultats seulement.",
         "USP": "Filiale américaine à 100 %, tenue en dollars US, jugée établissement autonome."}

# (compte, section) dans l'ordre du chiffrier
COMPTES: list[tuple[str, str]] = [
    ("Encaisse", "ACTIF"), ("Débiteurs clients", "ACTIF"), ("Débiteurs intersociétés", "ACTIF"), ("Billet à recevoir — Soudure Bécancour", "ACTIF"), ("Stocks", "ACTIF"),
    ("Frais payés d'avance", "ACTIF"), ("Immobilisations nettes", "ACTIF"), ("Relations clients", "ACTIF"), ("Carnet de commandes", "ACTIF"), ("Écart d'acquisition", "ACTIF"),
    ("Placement dans Usinage SM", "ACTIF"), ("Placement dans Immeubles SM", "ACTIF"), ("Placement dans Soudure Bécancour", "ACTIF"), ("Placement dans USM Precision", "ACTIF"),
    ("Créditeurs et charges à payer", "PASSIF"), ("Créditeurs intersociétés", "PASSIF"), ("Impôts à payer", "PASSIF"), ("Provision environnementale", "PASSIF"),
    ("Dette à long terme", "PASSIF"), ("Billet à payer — Gestion SM", "PASSIF"), ("Emprunt hypothécaire", "PASSIF"), ("Impôts différés", "PASSIF"),
    ("Capital-actions", "CAPITAUX PROPRES"), ("Bénéfices non répartis — ouverture", "CAPITAUX PROPRES"), ("Dividendes déclarés", "CAPITAUX PROPRES"),
    ("Écart de conversion cumulé", "CAPITAUX PROPRES"), ("Participation ne donnant pas le contrôle", "CAPITAUX PROPRES"),
    ("Ventes", "PRODUITS"), ("Produits de location", "PRODUITS"), ("Honoraires de gestion — produits", "PRODUITS"), ("Dividendes reçus", "PRODUITS"), ("Produits d'intérêts", "PRODUITS"),
    ("Coût des ventes", "CHARGES"), ("Frais de vente et d'administration", "CHARGES"), ("Frais de gestion — intragroupe", "CHARGES"), ("Charges de loyer", "CHARGES"),
    ("Amortissement", "CHARGES"), ("Charges d'intérêts", "CHARGES"), ("Charge d'impôts", "CHARGES"), ("Résultat attribuable à la PNDC", "CHARGES"),
]
NOMS_COMPTES = [c for c, _ in COMPTES]
PLACEMENTS = ("Placement dans Usinage SM", "Placement dans Immeubles SM", "Placement dans Soudure Bécancour", "Placement dans USM Precision")

# Balances de vérification en dollars canadiens (débit +, crédit −) ; USM Precision vient de la conversion
BV_CAD: dict[str, dict[str, float]] = {
    "GSM": {"Encaisse": 260000, "Billet à recevoir — Soudure Bécancour": 1500000, "Placement dans Usinage SM": 100000, "Placement dans Immeubles SM": 50000,
            "Créditeurs et charges à payer": -90000, "Impôts à payer": -30000, "Capital-actions": -10000, "Bénéfices non répartis — ouverture": -1054000,
            "Honoraires de gestion — produits": -480000, "Dividendes reçus": -600000, "Produits d'intérêts": -84375, "Frais de vente et d'administration": 390375, "Charge d'impôts": 48000},
    "USM": {"Encaisse": 470000, "Débiteurs clients": 3900000, "Débiteurs intersociétés": 420000, "Stocks": 4200000, "Frais payés d'avance": 120000, "Immobilisations nettes": 5800000,
            "Placement dans Soudure Bécancour": 4800000, "Placement dans USM Precision": 660000, "Créditeurs et charges à payer": -3100000, "Créditeurs intersociétés": -820000,
            "Dette à long terme": -3200000, "Impôts différés": -480000, "Capital-actions": -100000, "Bénéfices non répartis — ouverture": -11445000, "Dividendes déclarés": 600000,
            "Ventes": -24500000, "Dividendes reçus": -120000, "Coût des ventes": 17640000, "Frais de vente et d'administration": 3320000, "Frais de gestion — intragroupe": 300000,
            "Charges de loyer": 216000, "Amortissement": 620000, "Charges d'intérêts": 84000, "Charge d'impôts": 615000},
    "ISM": {"Encaisse": 40000, "Débiteurs intersociétés": 180000, "Immobilisations nettes": 2600000, "Créditeurs et charges à payer": -40000, "Emprunt hypothécaire": -900000,
            "Impôts différés": -250000, "Capital-actions": -50000, "Bénéfices non répartis — ouverture": -1502000, "Produits de location": -216000, "Frais de gestion — intragroupe": 20000,
            "Amortissement": 50000, "Charges d'intérêts": 40000, "Charge d'impôts": 28000},
    "SBE": {"Encaisse": 180000, "Débiteurs clients": 1350000, "Débiteurs intersociétés": 640000, "Stocks": 1100000, "Immobilisations nettes": 2900000, "Créditeurs et charges à payer": -780000,
            "Dette à long terme": -220000, "Billet à payer — Gestion SM": -1500000, "Impôts différés": -100000, "Capital-actions": -500000, "Bénéfices non répartis — ouverture": -2600000,
            "Dividendes déclarés": 150000, "Ventes": -6200000, "Coût des ventes": 4100000, "Frais de vente et d'administration": 780000, "Frais de gestion — intragroupe": 100000,
            "Amortissement": 215625, "Charges d'intérêts": 84375, "Charge d'impôts": 300000},
}
# USM Precision en dollars US : (compte, solde USD, base de conversion) ; certains soldes sont définis en dollars canadiens dans l'entente (None = calculé)
USD_BV: list[tuple[str, float | None, str]] = [
    ("Encaisse", 293000, "cloture"), ("Débiteurs clients", 957000, "cloture"), ("Stocks", 980000, "cloture"), ("Immobilisations nettes", 1620000, "cloture"),
    ("Créditeurs intersociétés", None, "cloture"), ("Créditeurs et charges à payer", None, "cloture"), ("Capital-actions", -500000, "historique"),
    ("Bénéfices non répartis — ouverture", None, "report"), ("Ventes", -4100000, "moyen"), ("Coût des ventes", 2900000, "moyen"),
    ("Frais de vente et d'administration", 640000, "moyen"), ("Frais de gestion — intragroupe", None, "moyen"), ("Amortissement", None, "moyen"), ("Charge d'impôts", 100000, "moyen"),
]
BASES = {"cloture": "Cours de clôture", "moyen": "Cours moyen", "historique": "Cours historique", "report": "Report de l'exercice précédent"}


@dataclass
class Hypotheses:
    # détention et fiscalité
    detention_sbe: float = 0.80
    taux_impot: float = 0.265
    # cours de change (CAD par USD)
    cours_cloture: float = 1.365
    cours_moyen: float = 1.40
    cours_historique: float = 1.32
    bnr_converti_ouverture: float = 1_315_000.0
    # acquisition de Soudure Bécancour (la contrepartie versée est le placement inscrit chez l'opérante : 4 800 000 $, lu dans la balance)
    jv_pndc: float = 1_080_000.0
    jv_immobilisations: float = 850_000.0
    jv_relations: float = 1_200_000.0
    jv_carnet: float = 250_000.0
    passif_repris: float = -100_000.0
    duree_immobilisations: float = 15.0
    duree_relations: float = 8.0
    duree_carnet: float = 1.0
    mois_exercice: float = 9.0
    # opérations intragroupe de l'exercice
    honoraires: float = 480_000.0
    loyer: float = 216_000.0
    ventes_aval: float = 1_800_000.0
    ventes_amont: float = 950_000.0
    interets_billet: float = 84_375.0
    dividende_usinage: float = 600_000.0
    dividende_sbe: float = 150_000.0
    soldes_interco: float = 1_240_000.0
    billet: float = 1_500_000.0
    # profit non réalisé dans les stocks
    stocks_sbe: float = 350_000.0
    marge_sbe: float = 0.24
    stocks_usinage_chez_usp: float = 0.0
    marge_usinage: float = 0.30

    def modifie(self, **kw) -> "Hypotheses":
        return replace(self, **kw)


def hypotheses_par_defaut() -> Hypotheses:
    return Hypotheses()


# --- 03 Conversion de USM Precision ----------------------------------------------------------------------------------------------------------
def conversion(h: Hypotheses) -> pd.DataFrame:
    """Conversion en dollars canadiens : actifs et passifs au cours de clôture, produits et charges au cours moyen, capital au cours historique,
    bénéfices non répartis d'ouverture reportés. L'écart de conversion est le résidu qui boucle la balance."""
    taux = {"cloture": h.cours_cloture, "moyen": h.cours_moyen, "historique": h.cours_historique}
    interco_usd = -420_000 / h.cours_cloture                      # libellé en dollars canadiens dans l'entente : se concilie à 420 000 $
    fixes_cad = {"Frais de gestion — intragroupe": 60_000 / h.cours_moyen, "Amortissement": 220_000 / h.cours_moyen}
    lignes = []
    for compte, usd, base in USD_BV:
        if compte == "Créditeurs intersociétés":
            usd = interco_usd
        elif compte == "Créditeurs et charges à payer":
            usd = -1_940_000 - interco_usd
        elif compte in fixes_cad:
            usd = fixes_cad[compte]
        if base == "report":
            lignes.append({"Compte": compte, "Solde (USD)": None, "Cours appliqué": BASES[base], "Taux": None, "Solde (CAD)": -h.bnr_converti_ouverture})
        else:
            lignes.append({"Compte": compte, "Solde (USD)": usd, "Cours appliqué": BASES[base], "Taux": taux[base], "Solde (CAD)": usd * taux[base]})
    ecart = -sum(l["Solde (CAD)"] for l in lignes)
    lignes.append({"Compte": "Écart de conversion cumulé", "Solde (USD)": None, "Cours appliqué": "Résidu de bouclage", "Taux": None, "Solde (CAD)": ecart})
    return pd.DataFrame(lignes)


# --- 02 Balances de vérification ------------------------------------------------------------------------------------------------------------------
def balances(h: Hypotheses) -> pd.DataFrame:
    """Une ligne par compte, une colonne par entité (USM Precision en dollars canadiens), plus le total agrégé."""
    conv = conversion(h).set_index("Compte")["Solde (CAD)"]
    df = pd.DataFrame(0.0, index=NOMS_COMPTES, columns=list(ENTITES))
    for e, comptes in BV_CAD.items():
        for c, v in comptes.items():
            df.loc[c, e] = v
    for c in conv.index:
        df.loc[c, "USP"] = conv[c]
    df["Total agrégé"] = df[list(ENTITES)].sum(axis=1)
    return df


# --- 04 Acquisition de Soudure Bécancour et répartition du prix ------------------------------------------------------------------------------------
def acquisition(h: Hypotheses, bv: pd.DataFrame | None = None) -> dict:
    bv = balances(h) if bv is None else bv
    actif_net = -(bv.loc["Capital-actions", "SBE"] + bv.loc["Bénéfices non répartis — ouverture", "SBE"])     # capitaux propres de la filiale à l'acquisition
    ecarts = h.jv_immobilisations + h.jv_relations + h.jv_carnet + h.passif_repris
    impots_diff = ecarts * h.taux_impot
    jv_actif_net = actif_net + ecarts - impots_diff
    contrepartie = bv.loc["Placement dans Soudure Bécancour", "USM"]
    a_repartir = contrepartie + h.jv_pndc
    goodwill = a_repartir - jv_actif_net
    pndc_qp = jv_actif_net * (1 - h.detention_sbe)
    elements = [("Immeuble et équipements", h.jv_immobilisations, h.duree_immobilisations), ("Relations clients", h.jv_relations, h.duree_relations),
                ("Carnet de commandes", h.jv_carnet, h.duree_carnet)]
    amort = [{"Élément": n, "Montant": m, "Durée (ans)": d, "Charge annuelle": m / d, "Charge de l'exercice": m / d * h.mois_exercice / 12} for n, m, d in elements]
    amort_total = sum(a["Charge de l'exercice"] for a in amort)
    reprise = amort_total * h.taux_impot
    return {"actif_net_comptable": actif_net, "ecarts_jv": ecarts, "impots_differes": impots_diff, "jv_actif_net": jv_actif_net, "contrepartie": contrepartie,
            "jv_pndc": h.jv_pndc, "a_repartir": a_repartir, "goodwill": goodwill, "pndc_quote_part": pndc_qp, "goodwill_quote_part": contrepartie + pndc_qp - jv_actif_net,
            "diff_goodwill": goodwill - (contrepartie + pndc_qp - jv_actif_net), "amortissements": amort, "amort_total": amort_total, "reprise_impots": reprise,
            "reduction_nette": amort_total - reprise}


# --- 05 Les dix-neuf écritures --------------------------------------------------------------------------------------------------------------------
def ecritures(h: Hypotheses, bv: pd.DataFrame, acq: dict, pndc_min: float) -> list[dict]:
    """Journal de consolidation : [{no, famille, operation, pourquoi, lignes: [{compte, debit, credit}]}]. Total des débits = total des crédits."""
    L = lambda compte, debit=0.0, credit=0.0: {"compte": compte, "debit": float(debit), "credit": float(credit)}
    nr = h.stocks_sbe * h.marge_sbe + h.stocks_usinage_chez_usp * h.marge_usinage
    d = h.detention_sbe
    donnees = [
        ("E1", [L("Honoraires de gestion — produits", h.honoraires), L("Frais de gestion — intragroupe", 0, h.honoraires)]),
        ("E2", [L("Produits de location", h.loyer), L("Charges de loyer", 0, h.loyer)]),
        ("E3", [L("Ventes", h.ventes_aval), L("Coût des ventes", 0, h.ventes_aval)]),
        ("E4", [L("Ventes", h.ventes_amont), L("Coût des ventes", 0, h.ventes_amont)]),
        ("E5", [L("Coût des ventes", nr), L("Stocks", 0, nr)]),
        ("E6", [L("Impôts différés", nr * h.taux_impot), L("Charge d'impôts", 0, nr * h.taux_impot)]),
        ("E7", [L("Créditeurs intersociétés", h.soldes_interco), L("Débiteurs intersociétés", 0, h.soldes_interco)]),
        ("E8", [L("Billet à payer — Gestion SM", h.billet), L("Billet à recevoir — Soudure Bécancour", 0, h.billet)]),
        ("E9", [L("Produits d'intérêts", h.interets_billet), L("Charges d'intérêts", 0, h.interets_billet)]),
        ("E10", [L("Dividendes reçus", h.dividende_usinage), L("Dividendes déclarés", 0, h.dividende_usinage)]),
        ("E11", [L("Dividendes reçus", h.dividende_sbe * d), L("Dividendes déclarés", 0, h.dividende_sbe * d)]),
        ("E12", [L("Participation ne donnant pas le contrôle", h.dividende_sbe * (1 - d)), L("Dividendes déclarés", 0, h.dividende_sbe * (1 - d))]),
        ("E13", [L("Capital-actions", -bv.loc["Capital-actions", "USM"]), L("Placement dans Usinage SM", 0, bv.loc["Placement dans Usinage SM", "GSM"])]),
        ("E14", [L("Capital-actions", -bv.loc["Capital-actions", "ISM"]), L("Placement dans Immeubles SM", 0, bv.loc["Placement dans Immeubles SM", "GSM"])]),
        ("E15", [L("Capital-actions", -bv.loc["Capital-actions", "USP"]), L("Placement dans USM Precision", 0, bv.loc["Placement dans USM Precision", "USM"])]),
        ("E16", [L("Capital-actions", -bv.loc["Capital-actions", "SBE"]), L("Bénéfices non répartis — ouverture", -bv.loc["Bénéfices non répartis — ouverture", "SBE"]),
                 L("Immobilisations nettes", h.jv_immobilisations), L("Relations clients", h.jv_relations), L("Carnet de commandes", h.jv_carnet),
                 L("Écart d'acquisition", acq["goodwill"]), L("Provision environnementale", 0, -h.passif_repris), L("Impôts différés", 0, acq["impots_differes"]),
                 L("Placement dans Soudure Bécancour", 0, bv.loc["Placement dans Soudure Bécancour", "USM"]), L("Participation ne donnant pas le contrôle", 0, h.jv_pndc)]),
        ("E17", [L("Amortissement", acq["amort_total"])] + [L(n, 0, a["Charge de l'exercice"]) for n, a in zip(("Immobilisations nettes", "Relations clients", "Carnet de commandes"), acq["amortissements"])]),
        ("E18", [L("Impôts différés", acq["reprise_impots"]), L("Charge d'impôts", 0, acq["reprise_impots"])]),
        ("E19", [L("Résultat attribuable à la PNDC", pndc_min), L("Participation ne donnant pas le contrôle", 0, pndc_min)]),
    ]
    operations = {"E3": "Ventes de Usinage SM à USM Precision — vente aval", "E4": "Ventes de Soudure Bécancour à Usinage SM — vente amont"}
    return [{"no": no, "famille": EXPLICATIONS[no]["famille"], "operation": operations.get(no, EXPLICATIONS[no]["operation"]), "pourquoi": EXPLICATIONS[no]["pourquoi"], "lignes": lignes}
            for no, lignes in donnees]


# --- 07 Participation ne donnant pas le contrôle ---------------------------------------------------------------------------------------------------
def pndc(h: Hypotheses, bv: pd.DataFrame, acq: dict) -> dict:
    sbe = bv["SBE"]
    resultat = -sum(sbe[c] for c, s in COMPTES if s in ("PRODUITS", "CHARGES"))                            # produits (crédits) moins charges (débits)
    amort_net = -acq["reduction_nette"]
    nr_amont = h.stocks_sbe * h.marge_sbe
    nr_net = -nr_amont * (1 - h.taux_impot)                                                                  # vente montante : le profit se partage
    ajuste = resultat + amort_net + nr_net
    min_ = ajuste * (1 - h.detention_sbe)
    div_min = h.dividende_sbe * (1 - h.detention_sbe)
    return {"resultat_sbe": resultat, "amort_net": amort_net, "nr_net": nr_net, "resultat_ajuste": ajuste, "quote_part_pndc": min_, "quote_part_mere": ajuste - min_,
            "solde_acquisition": h.jv_pndc, "dividendes_min": -div_min, "solde_cloture": h.jv_pndc + min_ - div_min}


# --- 06 Chiffrier -----------------------------------------------------------------------------------------------------------------------------------
def chiffrier(bv: pd.DataFrame, journal: list[dict]) -> pd.DataFrame:
    """Un compte par ligne : les cinq entités, le total, les éliminations (débit, crédit) tirées du journal, et le consolidé."""
    df = bv[list(ENTITES)].copy()
    df["Agrégé"] = df.sum(axis=1)
    deb = pd.Series(0.0, index=df.index)
    cre = pd.Series(0.0, index=df.index)
    for e in journal:
        for l in e["lignes"]:
            deb[l["compte"]] += l["debit"]
            cre[l["compte"]] += l["credit"]
    df["Élim. débit"], df["Élim. crédit"] = deb, cre
    df["Consolidé"] = df["Agrégé"] + deb - cre
    df.insert(0, "Section", [s for _, s in COMPTES])
    return df


# --- 08 États financiers consolidés ---------------------------------------------------------------------------------------------------------------
def etats(ch: pd.DataFrame, pn: dict) -> dict:
    J = ch["Consolidé"]
    ventes = -J["Ventes"]
    autres_produits = -(J["Produits de location"] + J["Honoraires de gestion — produits"] + J["Dividendes reçus"] + J["Produits d'intérêts"])
    charges = [("Coût des ventes", J["Coût des ventes"]), ("Frais de vente et d'administration", J["Frais de vente et d'administration"]),
               ("Frais de gestion — intragroupe", J["Frais de gestion — intragroupe"]), ("Charges de loyer", J["Charges de loyer"]),
               ("Amortissement", J["Amortissement"]), ("Charges d'intérêts", J["Charges d'intérêts"])]
    total_produits = ventes + autres_produits
    total_charges = sum(v for _, v in charges)
    avant_impots = total_produits - total_charges
    impots = -J["Charge d'impôts"]
    net = avant_impots + impots
    min_ = J["Résultat attribuable à la PNDC"]
    mere = net - min_
    bnr_debut = -J["Bénéfices non répartis — ouverture"]
    bnr_fin = bnr_debut + mere - J["Dividendes déclarés"]
    actif = {"Encaisse": J["Encaisse"], "Débiteurs clients": J["Débiteurs clients"], "Stocks": J["Stocks"], "Frais payés d'avance": J["Frais payés d'avance"],
             "Immobilisations nettes": J["Immobilisations nettes"], "Relations clients": J["Relations clients"], "Carnet de commandes": J["Carnet de commandes"],
             "Écart d'acquisition": J["Écart d'acquisition"]}
    passif = {"Créditeurs et charges à payer": -J["Créditeurs et charges à payer"], "Impôts à payer": -J["Impôts à payer"], "Provision environnementale": -J["Provision environnementale"],
              "Dette à long terme": -J["Dette à long terme"], "Emprunt hypothécaire": -J["Emprunt hypothécaire"], "Impôts différés": -J["Impôts différés"]}
    cp = {"Capital-actions": -J["Capital-actions"], "Bénéfices non répartis": bnr_fin, "Écart de conversion cumulé": -J["Écart de conversion cumulé"],
          "Participation ne donnant pas le contrôle": -J["Participation ne donnant pas le contrôle"]}
    residuels_actif = {c: J[c] for c in ("Débiteurs intersociétés", "Billet à recevoir — Soudure Bécancour", *PLACEMENTS) if abs(J[c]) > 0.5}
    residuels_passif = {c: -J[c] for c in ("Créditeurs intersociétés", "Billet à payer — Gestion SM") if abs(J[c]) > 0.5}
    return {"actif": actif, "passif": passif, "cp": cp, "total_actif": sum(actif.values()), "total_passif": sum(passif.values()), "total_cp": sum(cp.values()),
            "residuels_actif": residuels_actif, "residuels_passif": residuels_passif,
            "resultats": {"ventes": ventes, "autres_produits": autres_produits, "total_produits": total_produits, "charges": charges, "total_charges": total_charges,
                          "avant_impots": avant_impots, "impots": impots, "net": net, "min": min_, "mere": mere},
            "bnr": {"debut": bnr_debut, "resultat_mere": mere, "dividendes": -J["Dividendes déclarés"], "fin": bnr_fin}}


# --- 09 Contrôles -----------------------------------------------------------------------------------------------------------------------------------
def controles(res: dict) -> list[dict]:
    J, jr, et, pn = res["chiffrier"]["Consolidé"], res["journal"], res["etats"], res["pndc"]
    deb = sum(l["debit"] for e in jr for l in e["lignes"])
    cre = sum(l["credit"] for e in jr for l in e["lignes"])
    tests = [
        ("Total des débits égal au total des crédits au journal", deb - cre, "Une écriture déséquilibrée fausse tout ce qui suit."),
        ("Colonne consolidée du chiffrier — total nul", J.sum(), "La preuve arithmétique que l'actif égale le passif plus les capitaux propres."),
        # le classeur additionne les deux côtés ; on additionne leurs valeurs absolues, ce qui détecte aussi une erreur symétrique (même montant des deux côtés)
        ("Solde net des comptes intersociétés", abs(J["Débiteurs intersociétés"]) + abs(J["Créditeurs intersociétés"]),
         "Doit être exactement nul, de chaque côté. Un résidu signale un décalage de coupure ou une refacturation traitée d'un seul côté."),
        ("Billet intersociétés éliminé au complet", abs(J["Billet à recevoir — Soudure Bécancour"]) + abs(J["Billet à payer — Gestion SM"]),
         "Le groupe ne peut pas se devoir de l'argent à lui-même."),
        ("Placements dans les filiales éliminés au complet", sum(abs(J[c]) for c in PLACEMENTS), "Aucun placement dans une entité consolidée ne subsiste au bilan du groupe."),
        ("Bilan consolidé équilibré", et["total_actif"] - (et["total_passif"] + et["total_cp"]), "Actif moins passif et capitaux propres."),
        ("Continuité de la PNDC concordante avec le chiffrier", pn["solde_cloture"] + J["Participation ne donnant pas le contrôle"],
         "Solde d'ouverture, plus quote-part, moins dividendes : le calcul indépendant doit retomber sur le chiffrier."),
        ("Dividendes intragroupe entièrement neutralisés", J["Dividendes déclarés"], "Seuls les dividendes versés hors du groupe subsistent — ici, aucun : la société mère n'a rien distribué."),
    ]
    return [{"controle": n, "ecart": float(v), "ok": abs(v) < 0.5, "signification": s} for n, v, s in tests]


def consolider(h: Hypotheses | None = None) -> dict:
    """Les neuf étapes, calculées dans l'ordre. Retourne un dictionnaire d'objets prêts à afficher."""
    h = h or Hypotheses()
    conv = conversion(h)
    bv = balances(h)
    acq = acquisition(h, bv)
    pn = pndc(h, bv, acq)
    jr = ecritures(h, bv, acq, pn["quote_part_pndc"])
    ch = chiffrier(bv, jr)
    et = etats(ch, pn)
    res = {"hypotheses": h, "conversion": conv, "balances": bv, "acquisition": acq, "pndc": pn, "journal": jr, "chiffrier": ch, "etats": et}
    res["controles"] = controles(res)
    et_ = et["resultats"]
    res["chiffres_cles"] = {"Produits consolidés": et_["total_produits"], "Résultat net consolidé": et_["net"], "dont attribuable aux minoritaires": et_["min"],
                            "dont attribuable à la société mère": et_["mere"], "Total de l'actif consolidé": et["total_actif"], "Écart d'acquisition": ch.loc["Écart d'acquisition", "Consolidé"],
                            "Participation ne donnant pas le contrôle": -ch.loc["Participation ne donnant pas le contrôle", "Consolidé"],
                            "Écart de conversion cumulé": -ch.loc["Écart de conversion cumulé", "Consolidé"]}
    return res


def journal_plat(res: dict) -> pd.DataFrame:
    lignes = []
    for e in res["journal"]:
        for l in e["lignes"]:
            lignes.append({"No": e["no"], "Famille": e["famille"], "Opération": e["operation"], "Compte touché": l["compte"], "Débit": l["debit"] or None, "Crédit": l["credit"] or None})
    return pd.DataFrame(lignes)


def classeur_excel(res: dict) -> bytes:
    """Chiffrier, journal des écritures, états consolidés et contrôles dans un classeur Excel."""
    import io
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    wb = Workbook()
    wb.remove(wb.active)
    entete = lambda ws: [setattr(c, "font", Font(bold=True, color="FFFFFF")) or setattr(c, "fill", PatternFill("solid", fgColor="1F5F8B")) for c in ws[1]]
    ws = wb.create_sheet("Chiffrier")
    ws.append(["Compte", *ENTITES, "Agrégé", "Élim. débit", "Élim. crédit", "Consolidé"])
    entete(ws)
    ch = res["chiffrier"]
    for compte, r in ch.iterrows():
        ws.append([compte, *[round(float(r[c]), 2) for c in (*ENTITES, "Agrégé", "Élim. débit", "Élim. crédit", "Consolidé")]])
    for row in ws.iter_rows(min_row=2, min_col=2):
        for c in row:
            c.number_format = '#,##0;(#,##0);"—"'
            c.alignment = Alignment(horizontal="right")
    ws.column_dimensions["A"].width = 44
    for col in "BCDEFGHIJ":
        ws.column_dimensions[col].width = 15
    ws = wb.create_sheet("Écritures")
    ws.append(["No", "Famille", "Opération", "Compte touché", "Débit", "Crédit"])
    entete(ws)
    for _, r in journal_plat(res).iterrows():
        ws.append([r["No"], r["Famille"], r["Opération"], r["Compte touché"], None if pd.isna(r["Débit"]) else round(r["Débit"], 2), None if pd.isna(r["Crédit"]) else round(r["Crédit"], 2)])
    for col, w in zip("ABCDEF", (6, 24, 70, 42, 14, 14)):
        ws.column_dimensions[col].width = w
    ws = wb.create_sheet("Contrôles")
    ws.append(["Contrôle", "Écart", "Résultat"])
    entete(ws)
    for c in res["controles"]:
        ws.append([c["controle"], round(c["ecart"], 2), "CONFORME" if c["ok"] else "À CORRIGER"])
    ws.column_dimensions["A"].width = 62
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
