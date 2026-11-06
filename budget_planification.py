"""Calculs de la section « Planification budgétaire » : trois approches du budget de Groupe Usinage Saint-Maurice (cas fictif) et leur réconciliation.

  Top-down      la direction fixe la cible (croissance, marge) ; on en déduit l'enveloppe de coûts, puis on la répartit par ligne et par centre.
  Bottom-up     les gestionnaires bâtissent leurs budgets (volumes, prix, coûts unitaires, capacité) ; on additionne.
  Base zéro     chaque centre justifie ses frais indirects par des paquets de décision classés selon leur valeur ; la ligne de coupure tombe où l'enveloppe s'épuise.
  Réconciliation les trois approches se rejoignent : leviers chiffrés de l'écart entre la cible et le ascendant, puis budget retenu.

Les données de base (volumes, prix, coûts unitaires, centres) viennent de couts_revient.py : le budget et le coût de revient parlent des mêmes chiffres.
Montants en k$ sauf indication contraire ; aucune écriture en base.
"""
from __future__ import annotations

from datetime import date

import pandas as pd

import couts_revient as C

EXERCICE = 2027
BASE_ANNEE = 2026
LIGNES = list(C.PRODUITS)
CENTRES = list(C.CENTRES_AUXILIAIRES) + list(C.CENTRES_PRINCIPAUX)
CHARGES_CENTRES = {**C.CENTRES_AUXILIAIRES, **C.CENTRES_PRINCIPAUX}
CAPACITE_HEURES_MACHINE = C.CAPACITE_NORMALE["Usinage CNC"]
PART_SALAIRES_INDIRECT = 0.65           # part des frais indirects qui suit l'inflation salariale (le reste suit l'inflation générale)

# --- Hypothèses des gestionnaires (bottom-up) ------------------------------------------------------------------------------------------------------
HYP_LIGNES = pd.DataFrame({  # croissance du volume, variation de prix, productivité de la main-d'œuvre directe (gain), par ligne
    "Volume (%)":        [4.0, 9.0, 3.0, 12.0],
    "Prix (%)":          [2.0, 1.5, 2.0, 2.0],
    "Productivité (%)":  [1.0, 1.5, 0.5, 0.0],
}, index=LIGNES)
HYP_GENERALES = {"inflation_matiere": 3.5, "inflation_salaires": 3.8, "inflation_generale": 2.4, "prudence": 3.0}   # en %, la prudence est la marge de sécurité des gestionnaires

CIBLES_DEFAUT = {"croissance_ventes": 6.0, "marge_cible": 13.0, "productivite_directe": 1.5}      # en %
POIDS_STRATEGIQUES = {"Usinage sur mesure": 1.00, "Contrats aéro et rail": 1.06, "Pièces de rechange": 1.00, "Prototypage": 0.96}


# --- Base de l'exercice courant ---------------------------------------------------------------------------------------------------------------------
def base() -> pd.DataFrame:
    """Ventes, coûts directs et contribution par ligne pour l'exercice de référence (k$)."""
    lignes = []
    for p, d in C.PRODUITS.items():
        v = d["volume"]
        lignes.append({"Ligne": p, "Ventes": v * d["prix"], "Matière": v * d["achat"], "Main-d'œuvre directe": v * d["mod"], "Frais variables": v * d["variable"]})
    df = pd.DataFrame(lignes).set_index("Ligne")
    df["Coûts directs"] = df[["Matière", "Main-d'œuvre directe", "Frais variables"]].sum(axis=1)
    df["Contribution"] = df["Ventes"] - df["Coûts directs"]
    return df


def resultat_base() -> dict[str, float]:
    b = base()
    indirects = sum(CHARGES_CENTRES.values())
    return {"ventes": float(b["Ventes"].sum()), "directs": float(b["Coûts directs"].sum()), "indirects": indirects,
            "resultat": float(b["Contribution"].sum() - indirects)}


# --- Approche 1 : top-down --------------------------------------------------------------------------------------------------------------------------
def top_down(croissance_ventes: float = CIBLES_DEFAUT["croissance_ventes"], marge_cible: float = CIBLES_DEFAUT["marge_cible"],
             productivite_directe: float = CIBLES_DEFAUT["productivite_directe"], poids: dict[str, float] | None = None) -> dict:
    """La direction fixe la croissance, la marge et la productivité ; l'enveloppe des frais indirects en découle (résidu).

    Retourne les totaux, la répartition par ligne (ventes et coûts directs cibles) et par centre (enveloppe au prorata de la base).
    """
    poids = poids or POIDS_STRATEGIQUES
    b = base()
    ventes = float(b["Ventes"].sum()) * (1 + croissance_ventes / 100)
    brut = b["Ventes"] * pd.Series(poids)
    ventes_ligne = brut / brut.sum() * ventes
    ratio_direct = (b["Coûts directs"] / b["Ventes"]) * (1 - productivite_directe / 100)
    directs_ligne = ventes_ligne * ratio_direct
    resultat = ventes * marge_cible / 100
    enveloppe = ventes - directs_ligne.sum() - resultat
    base_ind = pd.Series(CHARGES_CENTRES)
    enveloppe_centre = base_ind / base_ind.sum() * enveloppe
    par_ligne = pd.DataFrame({"Ventes base": b["Ventes"], "Ventes cibles": ventes_ligne, "Croissance (%)": (ventes_ligne / b["Ventes"] - 1) * 100,
                              "Coûts directs cibles": directs_ligne, "Contribution cible": ventes_ligne - directs_ligne})
    par_centre = pd.DataFrame({"Base": base_ind, "Enveloppe cible": enveloppe_centre, "Variation (%)": (enveloppe_centre / base_ind - 1) * 100})
    return {"ventes": ventes, "resultat": resultat, "directs": float(directs_ligne.sum()), "enveloppe": float(enveloppe), "par_ligne": par_ligne, "par_centre": par_centre,
            "marge": marge_cible, "croissance": croissance_ventes}


# --- Approche 2 : bottom-up -------------------------------------------------------------------------------------------------------------------------
def _facteur_indirect(infl_salaires: float, infl_generale: float) -> float:
    return 1 + (PART_SALAIRES_INDIRECT * infl_salaires + (1 - PART_SALAIRES_INDIRECT) * infl_generale) / 100


def heures_machine(hyp: pd.DataFrame | None = None) -> dict[str, float]:
    """Heures-machine requises par le programme des gestionnaires, contre la capacité normale du centre d'usinage."""
    hyp = HYP_LIGNES if hyp is None else hyp
    requises = sum(C.INDUCTEURS["Usinage CNC"][p] * (1 + hyp.loc[p, "Volume (%)"] / 100) for p in LIGNES)
    base_h = sum(C.INDUCTEURS["Usinage CNC"].values())
    return {"base": float(base_h), "requises": float(requises), "capacite": CAPACITE_HEURES_MACHINE, "utilisation": float(requises / CAPACITE_HEURES_MACHINE)}


def bottom_up(hyp: pd.DataFrame | None = None, generales: dict[str, float] | None = None) -> dict:
    """Budget bâti par les gestionnaires : volume x prix par ligne, coûts unitaires indexés, frais indirects qui suivent l'activité de leur centre."""
    hyp = HYP_LIGNES if hyp is None else hyp
    g = {**HYP_GENERALES, **(generales or {})}
    lignes = []
    for p, d in C.PRODUITS.items():
        h = hyp.loc[p]
        vol = d["volume"] * (1 + h["Volume (%)"] / 100)
        prix = d["prix"] * (1 + h["Prix (%)"] / 100)
        mat = d["achat"] * (1 + g["inflation_matiere"] / 100)
        mod = d["mod"] * (1 + g["inflation_salaires"] / 100) / (1 + h["Productivité (%)"] / 100)
        var = d["variable"] * (1 + g["inflation_generale"] / 100)
        lignes.append({"Ligne": p, "Volume (milliers)": vol, "Prix ($)": prix, "Ventes": vol * prix, "Matière": vol * mat,
                       "Main-d'œuvre directe": vol * mod, "Frais variables": vol * var})
    df = pd.DataFrame(lignes).set_index("Ligne")
    df["Coûts directs"] = df[["Matière", "Main-d'œuvre directe", "Frais variables"]].sum(axis=1)
    df["Contribution"] = df["Ventes"] - df["Coûts directs"]
    idx = _facteur_indirect(g["inflation_salaires"], g["inflation_generale"])
    centres = []
    indice = {c: sum(C.INDUCTEURS[c][p] * (1 + hyp.loc[p, "Volume (%)"] / 100) for p in LIGNES) / sum(C.INDUCTEURS[c].values()) for c in C.CENTRES_PRINCIPAUX}
    indice_aux = sum(CHARGES_CENTRES[c] * indice[c] for c in indice) / sum(CHARGES_CENTRES[c] for c in indice)   # les auxiliaires suivent les centres qu'ils servent
    for c, charge in CHARGES_CENTRES.items():
        activite = indice.get(c, indice_aux)
        variable = 1 - C.PART_FIXE_CENTRES
        montant = charge * idx * (C.PART_FIXE_CENTRES + variable * activite)
        centres.append({"Centre": c, "Base": charge, "Activité (indice)": activite, "Budget sans prudence": montant,
                        "Prudence": montant * g["prudence"] / 100, "Budget demandé": montant * (1 + g["prudence"] / 100)})
    ind = pd.DataFrame(centres).set_index("Centre")
    ventes = float(df["Ventes"].sum())
    directs = float(df["Coûts directs"].sum())
    indirects = float(ind["Budget demandé"].sum())
    return {"ventes": ventes, "directs": directs, "indirects": indirects, "indirects_sans_prudence": float(ind["Budget sans prudence"].sum()),
            "prudence": float(ind["Prudence"].sum()), "resultat": ventes - directs - indirects, "par_ligne": df, "par_centre": ind, "heures": heures_machine(hyp),
            "indexation_indirect": idx}


def pont_ascendant(bu: dict) -> list[tuple[str, float]]:
    """Du résultat de base au résultat ascendant : volume, prix, coûts unitaires (inflation nette de la productivité) et frais indirects. La somme est exacte."""
    effets = {"Volume": 0.0, "Prix": 0.0, "Coûts unitaires": 0.0}
    for p, d in C.PRODUITS.items():
        r = bu["par_ligne"].loc[p]
        v1, v0 = r["Volume (milliers)"], d["volume"]
        c0 = C.direct_unitaire(p)
        c1 = r["Coûts directs"] / v1
        effets["Volume"] += (v1 - v0) * (d["prix"] - c0)
        effets["Prix"] += v1 * (r["Prix ($)"] - d["prix"])
        effets["Coûts unitaires"] -= v1 * (c1 - c0)
    return list(effets.items()) + [("Frais indirects", -(bu["indirects"] - sum(CHARGES_CENTRES.values())))]


# --- Approche 3 : base zéro -------------------------------------------------------------------------------------------------------------------------
CRITERES = {"Conformité et sécurité": 30, "Valeur pour le client": 30, "Productivité": 25, "Maîtrise du risque": 15}
_P = []   # (centre, paquet, niveau, k$, obligatoire, [conformité, client, productivité, risque] sur 5)


def _p(centre, paquet, niveau, cout, obligatoire, notes):
    _P.append((centre, paquet, niveau, cout, obligatoire, notes))


_p("Administration", "Paie, comptabilité et conformité fiscale", "Minimum", 560, True, [5, 1, 2, 5])
_p("Administration", "Gestion des fournisseurs et comptes payables", "Actuel", 120, False, [3, 2, 3, 3])
_p("Administration", "Rapports de gestion détaillés", "Actuel", 90, False, [2, 2, 3, 2])
_p("Administration", "Abonnements et cotisations professionnelles", "Actuel", 70, False, [2, 1, 1, 1])
_p("Administration", "Déplacements et représentation", "Actuel", 60, False, [1, 3, 1, 1])
_p("Administration", "Module budgétaire de l'ERP", "Amélioré", 110, False, [2, 2, 4, 3])
_p("Administration", "Programme de formation en leadership", "Amélioré", 40, False, [1, 1, 3, 2])
_p("Entretien et maintenance", "Inspections réglementaires et sécurité", "Minimum", 260, True, [5, 2, 1, 5])
_p("Entretien et maintenance", "Maintenance préventive des centres CNC", "Actuel", 190, False, [4, 5, 5, 5])   # le centre CNC tourne près de sa capacité : un arrêt coûte plus que l'entretien
_p("Entretien et maintenance", "Maintenance corrective sous contrat", "Actuel", 80, False, [2, 3, 2, 3])
_p("Entretien et maintenance", "Stock de pièces d'entretien critiques", "Actuel", 40, False, [2, 3, 3, 4])
_p("Entretien et maintenance", "Entretien du bâtiment non critique", "Actuel", 30, False, [1, 1, 1, 1])
_p("Entretien et maintenance", "Maintenance prédictive (capteurs)", "Amélioré", 140, False, [2, 4, 5, 4])
_p("Usinage CNC", "Amortissement, énergie et loyer des machines", "Minimum", 1500, True, [3, 5, 3, 3])
_p("Usinage CNC", "Outils de coupe et inserts", "Minimum", 520, True, [2, 5, 4, 3])                       # sans outils, aucune pièce : plancher d'exploitation
_p("Usinage CNC", "Quart de soir (capacité de base)", "Minimum", 380, True, [1, 5, 4, 2])             # la capacité normale de 40 000 h suppose le quart de soir
_p("Usinage CNC", "Étalonnage et montages spéciaux", "Actuel", 160, False, [3, 4, 3, 3])
_p("Usinage CNC", "Contrat de service des machines", "Actuel", 140, False, [2, 3, 3, 4])
_p("Usinage CNC", "Quart de fin de semaine", "Amélioré", 220, False, [1, 4, 3, 1])
_p("Usinage CNC", "Machine cinq axes (location)", "Amélioré", 300, False, [1, 5, 4, 2])
_p("Soudure et assemblage", "Postes de soudure, énergie et gaz", "Minimum", 640, True, [3, 4, 3, 3])
_p("Soudure et assemblage", "Certification des soudeurs", "Minimum", 90, True, [5, 4, 1, 5])
_p("Soudure et assemblage", "Consommables de qualité supérieure", "Actuel", 120, False, [2, 3, 2, 2])
_p("Soudure et assemblage", "Gabarits et préparation des pièces", "Actuel", 100, False, [1, 3, 4, 2])
_p("Soudure et assemblage", "Nettoyage et finition manuelle", "Actuel", 50, False, [1, 3, 2, 1])
_p("Soudure et assemblage", "Cellule de soudure robotisée", "Amélioré", 180, False, [1, 3, 5, 2])
_p("Contrôle et métrologie", "Audits AS9100 et étalonnage des instruments", "Minimum", 480, True, [5, 5, 1, 5])
_p("Contrôle et métrologie", "Inspection à 100 % des pièces non critiques", "Actuel", 160, False, [1, 2, 1, 2])
_p("Contrôle et métrologie", "Temps additionnel de la machine à mesurer", "Actuel", 110, False, [2, 4, 3, 3])
_p("Contrôle et métrologie", "Rapports de première pièce détaillés", "Actuel", 90, False, [3, 4, 2, 3])
_p("Contrôle et métrologie", "Archivage des dossiers qualité", "Actuel", 60, False, [3, 1, 1, 3])
_p("Contrôle et métrologie", "Inspection automatisée par vision", "Amélioré", 150, False, [2, 4, 5, 4])
_p("Ingénierie et programmation", "Logiciels de FAO et licences", "Minimum", 420, True, [2, 4, 4, 3])
_p("Ingénierie et programmation", "Soutien aux soumissions", "Actuel", 190, False, [1, 5, 5, 5])      # des soumissions dérivent (voir Coûts de revient, Devis contre réel) : on garde l'estimation
_p("Ingénierie et programmation", "Développement de procédés", "Actuel", 150, False, [1, 4, 5, 3])
_p("Ingénierie et programmation", "Programmation hors ligne", "Actuel", 140, False, [1, 3, 5, 2])
_p("Ingénierie et programmation", "Veille technologique", "Actuel", 100, False, [1, 2, 2, 2])
_p("Ingénierie et programmation", "Jumeau numérique de l'atelier", "Amélioré", 200, False, [1, 3, 4, 3])
PAQUETS_BASE = pd.DataFrame(_P, columns=["Centre", "Paquet", "Niveau", "Coût (k$)", "Obligatoire", "Notes"])
PAQUET_PM = "Appariement automatisé des factures (issu du process mining)"


def paquets(economie_process_mining: float | None = None) -> pd.DataFrame:
    """Les paquets de décision. Les montants de base sont indexés par le budget ascendant ; le paquet issu du process mining est ajouté s'il est fourni."""
    d = PAQUETS_BASE.copy()
    if economie_process_mining is not None:
        d.loc[len(d)] = ["Administration", PAQUET_PM, "Amélioré", 45.0, False, [2, 2, 5, 4]]
    d["Notes"] = d["Notes"].apply(list)
    return d


def zbb(enveloppe: float, poids: dict[str, float] | None = None, indexation: float = 1.0, economie_process_mining: float | None = None) -> dict:
    """Classe les paquets par valeur par k$ ; finance d'abord les paquets obligatoires, puis les mieux classés jusqu'à l'épuisement de l'enveloppe.

    La valeur d'un paquet est la moyenne pondérée de ses notes (0 à 5) selon les critères choisis ; l'efficience est la valeur par k$ (x100).
    Un paquet dont la valeur dépasse le coût indexé (l'économie du process mining) se finance par ses gains, il ne consomme donc que son coût net.
    """
    poids = poids or CRITERES
    somme = sum(poids.values()) or 1.0
    d = paquets(economie_process_mining)
    d["Coût (k$)"] = d["Coût (k$)"] * indexation
    d["Valeur"] = d["Notes"].apply(lambda n: sum(n[i] * w for i, w in enumerate(poids.values())) / somme)
    d["Coût net (k$)"] = d["Coût (k$)"]
    if economie_process_mining is not None:
        masque = d["Paquet"] == PAQUET_PM
        d.loc[masque, "Coût net (k$)"] = (d.loc[masque, "Coût (k$)"] - economie_process_mining).clip(lower=0)
    d["Efficience"] = d["Valeur"] / d["Coût net (k$)"].clip(lower=20.0) * 100                       # plancher de 20 k$ : un paquet quasi gratuit n'écrase pas le classement
    # les obligatoires d'abord ; ensuite, par efficience décroissante (à efficience égale, la valeur la plus haute)
    d = d.sort_values(["Obligatoire", "Efficience", "Valeur"], ascending=[False, False, False]).reset_index(drop=True)
    d["Rang"] = d.index + 1
    d["Cumul (k$)"] = d["Coût net (k$)"].cumsum()
    financé = []
    cumul = 0.0
    for _, r in d.iterrows():
        if r["Obligatoire"] or cumul + r["Coût net (k$)"] <= enveloppe + 1e-9:
            financé.append(True)
            cumul += r["Coût net (k$)"]
        else:
            financé.append(False)
    d["Financé"] = financé
    d["Décision"] = d.apply(lambda r: "Obligatoire" if r["Obligatoire"] else ("Financé" if r["Financé"] else "Non financé"), axis=1)
    f = d[d["Financé"]]
    par_centre = pd.DataFrame({
        "Base indexée": d[d["Niveau"] != "Amélioré"].groupby("Centre")["Coût (k$)"].sum(),
        "Budget base zéro": f.groupby("Centre")["Coût net (k$)"].sum(),
        "Coupé (paquets actuels)": d[(d["Niveau"] == "Actuel") & (~d["Financé"])].groupby("Centre")["Coût (k$)"].sum(),
        "Ajouté (améliorations)": d[(d["Niveau"] == "Amélioré") & d["Financé"]].groupby("Centre")["Coût net (k$)"].sum(),
    }).reindex(CENTRES).fillna(0.0).rename_axis("Centre")
    obligatoire = float(d.loc[d["Obligatoire"], "Coût net (k$)"].sum())
    return {"paquets": d, "total": float(f["Coût net (k$)"].sum()), "obligatoire": obligatoire, "enveloppe": enveloppe, "par_centre": par_centre,
            "coupe": float(d[(d["Niveau"] == "Actuel") & (~d["Financé"])]["Coût (k$)"].sum()),
            "ajoute": float(d[(d["Niveau"] == "Amélioré") & d["Financé"]]["Coût net (k$)"].sum()),
            "obligatoire_depasse": obligatoire > enveloppe + 1e-9}


# --- Réconciliation ---------------------------------------------------------------------------------------------------------------------------------
def reconciliation(td: dict, bu: dict, bz: dict, productivite_supplementaire: float = 0.5, hausse_prix: float = 0.1) -> dict:
    """Du résultat ascendant au budget retenu, par leviers chiffrés ; l'écart restant par rapport à la cible est à arbitrer par la direction.

    Leviers : retirer la prudence des gestionnaires, adopter le budget base zéro des frais indirects, gain de productivité de la main-d'œuvre directe
    au-delà de celui des gestionnaires, discipline de prix (hausse additionnelle en % des ventes).
    """
    mod = float(bu["par_ligne"]["Main-d'œuvre directe"].sum())
    leviers = [
        ("Retirer la prudence des gestionnaires", bu["prudence"]),
        ("Budget base zéro des frais indirects", bu["indirects_sans_prudence"] - bz["total"]),
        ("Productivité de la main-d'œuvre directe", mod * productivite_supplementaire / 100),
        ("Discipline de prix", bu["ventes"] * hausse_prix / 100),
    ]
    retenu = bu["resultat"] + sum(v for _, v in leviers)
    ventes = bu["ventes"] * (1 + hausse_prix / 100)
    directs = bu["directs"] - mod * productivite_supplementaire / 100
    return {"leviers": leviers, "resultat_bu": bu["resultat"], "resultat_retenu": retenu, "cible": td["resultat"], "ecart_initial": td["resultat"] - bu["resultat"],
            "ecart_residuel": td["resultat"] - retenu, "ventes": ventes, "directs": directs, "indirects": bz["total"],
            "marge_retenue": retenu / ventes * 100, "marge_cible": td["marge"]}


def iterations(ecart_initial: float, part_direction: float = 0.4, tours: int = 4) -> pd.DataFrame:
    """Les tours de négociation : chaque tour, la direction assouplit sa cible et les gestionnaires resserrent la leur, chacun d'une part de l'écart restant."""
    lignes = [{"Tour": 0, "Écart restant": ecart_initial, "Concession direction": 0.0, "Effort gestionnaires": 0.0}]
    reste = ecart_initial
    for t in range(1, tours + 1):
        conc = reste * part_direction * 0.5
        effort = reste * (1 - part_direction) * 0.5
        reste = reste - conc - effort
        lignes.append({"Tour": t, "Écart restant": reste, "Concession direction": conc, "Effort gestionnaires": effort})
    return pd.DataFrame(lignes)


# --- Phasage mensuel --------------------------------------------------------------------------------------------------------------------------------
SAISONNALITE = [0.075, 0.080, 0.088, 0.086, 0.088, 0.084, 0.070, 0.062, 0.092, 0.095, 0.090, 0.090]   # part des ventes annuelles par mois (somme 1) : creux de l'été et des fêtes
MOIS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]


def phasage(rec: dict) -> pd.DataFrame:
    """Répartit le budget retenu sur 12 mois : les ventes suivent la saisonnalité, les coûts directs les ventes, les frais indirects sont linéaires."""
    s = pd.Series(SAISONNALITE, index=MOIS)
    s = s / s.sum()
    df = pd.DataFrame({"Ventes": s * rec["ventes"], "Coûts directs": s * rec["directs"], "Frais indirects": rec["indirects"] / 12})
    df["Résultat"] = df["Ventes"] - df["Coûts directs"] - df["Frais indirects"]
    df["Résultat cumulé"] = df["Résultat"].cumsum()
    return df


# --- Calendrier du processus ------------------------------------------------------------------------------------------------------------------------
ETAPES = pd.DataFrame([  # (étape, acteur, approche, début, fin)
    ("Orientations stratégiques et hypothèses macro", "Direction", "Top-down", date(2026, 8, 17), date(2026, 8, 28)),
    ("Cibles de ventes, de marge et enveloppes", "Direction", "Top-down", date(2026, 8, 31), date(2026, 9, 11)),
    ("Budgets détaillés par ligne et par centre", "Gestionnaires", "Bottom-up", date(2026, 9, 14), date(2026, 10, 2)),
    ("Paquets de décision à trois niveaux", "Gestionnaires", "Base zéro", date(2026, 9, 21), date(2026, 10, 9)),
    ("Consolidation et validation de la capacité", "Contrôle de gestion", "Bottom-up", date(2026, 10, 5), date(2026, 10, 16)),
    ("Classement des paquets et ligne de coupure", "Contrôle de gestion", "Base zéro", date(2026, 10, 12), date(2026, 10, 23)),
    ("Analyse de l'écart entre la cible et l'ascendant", "Contrôle de gestion", "Réconciliation", date(2026, 10, 19), date(2026, 10, 30)),
    ("Arbitrage et tours de négociation", "Comité de budget", "Réconciliation", date(2026, 11, 2), date(2026, 11, 20)),
    ("Approbation du budget maître", "Conseil d'administration", "Approbation", date(2026, 11, 23), date(2026, 12, 4)),
    ("Diffusion et ouverture du suivi mensuel", "Contrôle de gestion", "Suivi", date(2026, 12, 7), date(2026, 12, 18)),
], columns=["Étape", "Acteur", "Approche", "Début", "Fin"])


METHODES_BUDGET = pd.DataFrame([
    ("Top-down", "Direction fixe la cible, les gestionnaires la répartissent",
     "Alignement sur la stratégie, rapide, cible exigeante", "Cible déconnectée du terrain, peu d'adhésion, hypothèses irréalistes",
     "Fixer le cap et les enveloppes, en début de cycle"),
    ("Bottom-up", "Les gestionnaires bâtissent chaque budget à partir de leurs volumes et de leurs coûts",
     "Réalisme, engagement des responsables, capacité validée", "Marge de sécurité, budget qui reproduit le passé, long à consolider",
     "Bâtir les ventes, les coûts directs et la capacité"),
    ("Base zéro", "Chaque dépense se justifie à partir de zéro par des paquets de décision classés",
     "Élimine les dépenses sans valeur, rend visibles les arbitrages", "Lourd en temps, scores subjectifs, risque de couper l'invisible",
     "Les frais indirects, tous les trois ans ou quand la marge s'érode"),
], columns=["Approche", "Principe", "Avantages", "Risques", "Quand l'utiliser"])
