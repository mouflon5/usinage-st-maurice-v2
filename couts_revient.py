"""Calculs de la section « Coûts de revient » : méthodes de comptabilité de management appliquées à Groupe Usinage Saint-Maurice (cas fictif).

Fonctions pures (pas de Streamlit) pour qu'elles soient testées dans test_couts_revient.py ; l'affichage est dans demo_live/couts_ui.py.
Montants des charges en milliers de dollars (k$), volumes en milliers d'unités (pièces ou projets), prix en $ par unité.

Méthodes retenues pour une manufacture sur commande (voir METHODES : pourquoi chacune, et pourquoi d'autres sont écartées) :

  Coûts standards   écarts de prix et de quantité (matière), de taux et de rendement (main-d'œuvre), frais variables, frais fixes (budget et volume)
  Coût par commande devis contre réel : précision des soumissions, dépassements par élément de coût et par ligne
  Coût complet      centres d'analyse (taux par centre, répartition primaire puis secondaire) et ABC (inducteurs réels), sur les mêmes charges
  Coûts partiels    marge sur coûts variables, point mort, abandon d'une ligne (coûts spécifiques évitables), commande spéciale
  Capacité          imputation rationnelle des charges fixes (sous-activité hors du coût de la pièce) et théorie des contraintes (mix par heure-machine)
  Coûts cibles      prix de marché - marge visée = coût admissible ; feature costing : part du coût contre part de la valeur perçue
  ABM et qualité    activités classées selon leur valeur ; coût de la qualité
"""
from __future__ import annotations

import pandas as pd

# --- Données du cas ---------------------------------------------------------------------------------------------------------------------------
PRODUITS = {  # volume (milliers d'unités), prix de vente, matière, main-d'œuvre directe et frais variables ($ par unité)
    "Usinage sur mesure":    {"volume": 12.0, "prix": 860.00, "achat": 215.0, "mod": 175.0, "variable": 15.0, "unite": "pièce"},
    "Contrats aéro et rail": {"volume": 60.0, "prix": 80.67,  "achat": 27.0,  "mod": 12.0,  "variable": 2.5,  "unite": "pièce"},
    "Pièces de rechange":    {"volume": 18.0, "prix": 110.00, "achat": 36.0,  "mod": 22.0,  "variable": 4.0,  "unite": "pièce"},
    "Prototypage":           {"volume": 0.4,  "prix": 2500.0, "achat": 900.0, "mod": 700.0, "variable": 90.0, "unite": "projet"},
}
CENTRES_AUXILIAIRES = {"Administration": 900.0, "Entretien et maintenance": 600.0}
CENTRES_PRINCIPAUX = {"Usinage CNC": 2700.0, "Soudure et assemblage": 1000.0, "Contrôle et métrologie": 900.0, "Ingénierie et programmation": 1000.0}
CLES_SECONDAIRES = {
    "Administration":           {"Usinage CNC": .35, "Soudure et assemblage": .15, "Contrôle et métrologie": .20, "Ingénierie et programmation": .30},
    "Entretien et maintenance": {"Usinage CNC": .70, "Soudure et assemblage": .15, "Contrôle et métrologie": .10, "Ingénierie et programmation": .05},
}
UNITE_OEUVRE = {"Usinage CNC": "heures-machine", "Soudure et assemblage": "heures de soudage", "Contrôle et métrologie": "inspections", "Ingénierie et programmation": "heures d'ingénierie"}
INDUCTEURS = {  # consommation de chaque activité par produit
    "Usinage CNC":                 {"Usinage sur mesure": 20000, "Contrats aéro et rail": 12000, "Pièces de rechange": 3000, "Prototypage": 800},
    "Soudure et assemblage":       {"Usinage sur mesure": 3000, "Contrats aéro et rail": 5500, "Pièces de rechange": 600, "Prototypage": 100},
    "Contrôle et métrologie":      {"Usinage sur mesure": 2800, "Contrats aéro et rail": 6500, "Pièces de rechange": 1200, "Prototypage": 400},
    "Ingénierie et programmation": {"Usinage sur mesure": 3500, "Contrats aéro et rail": 1800, "Pièces de rechange": 700, "Prototypage": 4000},
}

FIXES_SPECIFIQUES = {"Usinage sur mesure": 1400.0, "Contrats aéro et rail": 800.0, "Pièces de rechange": 500.0, "Prototypage": 1050.0}   # k$ évitables si la ligne disparaît
FIXES_COMMUNES = 3000.0                                                                                                                # k$ non évitables par ligne

STANDARD = {"prix": 7.80, "kg_par_piece": 2.40, "heures_par_piece": 0.85, "taux": 58.0, "variable_par_piece": 3.20}


def direct_unitaire(p: str) -> float:
    d = PRODUITS[p]
    return d["achat"] + d["mod"] + d["variable"]


# --- Coût complet -----------------------------------------------------------------------------------------------------------------------------
def repartition_secondaire() -> pd.DataFrame:
    """Charges des centres auxiliaires reportées sur les centres principaux (k$). Colonnes : primaire, reçu, total."""
    lignes = []
    for centre, primaire in CENTRES_PRINCIPAUX.items():
        recu = sum(CENTRES_AUXILIAIRES[a] * CLES_SECONDAIRES[a][centre] for a in CENTRES_AUXILIAIRES)
        lignes.append({"Centre": centre, "Primaire": primaire, "Reçu des auxiliaires": recu, "Total": primaire + recu})
    return pd.DataFrame(lignes)


def _volumes() -> pd.Series:
    return pd.Series({p: d["volume"] for p, d in PRODUITS.items()}, dtype=float)


def cout_complet() -> pd.DataFrame:
    """Coût de revient par produit selon deux méthodes ($/unité) : centres d'analyse (taux par centre) et ABC (inducteurs réels). Elles absorbent les mêmes 7,1 M$."""
    pools = repartition_secondaire().set_index("Centre")["Total"]
    vol = _volumes()
    mod_total = pd.Series({p: d["volume"] * d["mod"] for p, d in PRODUITS.items()})          # k$ de main-d'œuvre directe par produit
    direct = pd.Series({p: direct_unitaire(p) for p in PRODUITS})
    prix = pd.Series({p: d["prix"] for p, d in PRODUITS.items()})
    heures_machine = pd.Series(INDUCTEURS["Usinage CNC"], dtype=float)
    # centres d'analyse : une seule unité d'œuvre par centre, la même pour tous les produits (heures-machine pour l'usinage, coût de la main-d'œuvre directe pour le reste)
    centres = pools["Usinage CNC"] * heures_machine / heures_machine.sum()
    for c in ("Soudure et assemblage", "Contrôle et métrologie", "Ingénierie et programmation"):
        centres = centres + pools[c] * mod_total / mod_total.sum()
    # ABC : chaque activité suit son inducteur réel
    abc = sum(pools[c] * pd.Series(INDUCTEURS[c], dtype=float) / sum(INDUCTEURS[c].values()) for c in pools.index)
    out = pd.DataFrame({"Volume (milliers)": vol, "Prix ($/unité)": prix, "Direct ($/unité)": direct})
    for nom, indirect in (("Centres d'analyse", centres), ("ABC", abc)):
        out[f"{nom} : indirect ($/unité)"] = indirect / vol
        out[f"{nom} : revient ($/unité)"] = direct + indirect / vol
        out[f"{nom} : marge ($/unité)"] = prix - (direct + indirect / vol)
    return out


# --- Coûts partiels ---------------------------------------------------------------------------------------------------------------------------
def contribution(var_volume: float = 0.0, var_prix: float = 0.0) -> pd.DataFrame:
    """Marge sur coûts variables par produit (k$), puis marge sur coûts spécifiques. Variations en pourcentage (0.05 = +5 %)."""
    lignes = []
    for p, d in PRODUITS.items():
        vol = d["volume"] * (1 + var_volume)
        prix = d["prix"] * (1 + var_prix)
        mcv = vol * (prix - direct_unitaire(p))                 # milliers d'unités x $/unité = k$
        lignes.append({"Produit": p, "Ventes (k$)": vol * prix, "Coûts variables (k$)": vol * direct_unitaire(p), "MCV (k$)": mcv,
                       "Taux de MCV": mcv / (vol * prix), "Fixes spécifiques (k$)": FIXES_SPECIFIQUES[p], "Marge spécifique (k$)": mcv - FIXES_SPECIFIQUES[p]})
    return pd.DataFrame(lignes)


def resultat_et_point_mort(df: pd.DataFrame) -> dict[str, float]:
    mcv, ventes = df["MCV (k$)"].sum(), df["Ventes (k$)"].sum()
    fixes = df["Fixes spécifiques (k$)"].sum() + FIXES_COMMUNES
    taux = mcv / ventes
    return {"mcv": mcv, "fixes": fixes, "resultat": mcv - fixes, "taux_mcv": taux, "point_mort": fixes / taux, "ventes": ventes,
            "marge_securite": (ventes - fixes / taux) / ventes}


def abandon(produit: str, df: pd.DataFrame) -> float:
    """Variation du résultat (k$) si la ligne est abandonnée : on perd sa MCV, on économise ses seuls fixes spécifiques ; les communs restent."""
    ligne = df.set_index("Produit").loc[produit]
    return -ligne["MCV (k$)"] + ligne["Fixes spécifiques (k$)"]


# --- Coûts standards et écarts ----------------------------------------------------------------------------------------------------------------
def ecarts(pieces: float, kg_achetes: float, prix_reel: float, heures_reelles: float, taux_reel: float, variable_reel: float,
           std: dict[str, float] = STANDARD) -> dict[str, float]:
    """Écarts d'une période ($). Positif = défavorable. La somme des écarts égale le coût réel moins le coût standard de la production réelle."""
    kg_std = pieces * std["kg_par_piece"]
    h_std = pieces * std["heures_par_piece"]
    cout_std = kg_std * std["prix"] + h_std * std["taux"] + pieces * std["variable_par_piece"]
    cout_reel = kg_achetes * prix_reel + heures_reelles * taux_reel + variable_reel
    e = {"Prix de la matière": (prix_reel - std["prix"]) * kg_achetes,
         "Quantité de matière (rebuts, copeaux)": (kg_achetes - kg_std) * std["prix"],
         "Taux horaire": (taux_reel - std["taux"]) * heures_reelles,
         "Rendement (heures)": (heures_reelles - h_std) * std["taux"],
         "Frais variables": variable_reel - pieces * std["variable_par_piece"]}
    e["_cout_standard"], e["_cout_reel"], e["_total"] = cout_std, cout_reel, cout_reel - cout_std
    return e


# --- Imputation rationnelle des charges fixes -------------------------------------------------------------------------------------------------
def ircf(charges_fixes_k: float, activite_normale: float, activite_reelle: float) -> dict[str, float]:
    """Coefficient d'imputation rationnelle, charges imputées au coût des produits et coût de sous-activité (k$, négatif = boni de suractivité).
    Les coûts unitaires sont en $ par unité d'activité (heure-machine) parce que k$ ÷ unité × 1000 = $ par unité."""
    coef = activite_reelle / activite_normale
    imputees = charges_fixes_k * coef
    return {"coefficient": coef, "imputees": imputees, "sous_activite": charges_fixes_k - imputees,
            "unitaire_ircf": charges_fixes_k * 1000 / activite_normale, "unitaire_complet": charges_fixes_k * 1000 / activite_reelle}


# --- Coût cible et feature costing ------------------------------------------------------------------------------------------------------------
CARACTERISTIQUES = pd.DataFrame({
    "Caractéristique": ["Certification AS9100 et traçabilité matière", "Contrôle dimensionnel à 100 % (MMT) et rapports", "Finition et traitement de surface",
                        "Livraison juste-à-temps (stock tampon)", "Gestion de configuration et des révisions", "Support d'ingénierie (conception pour la fabrication)"],
    "Coût estimé ($/pièce)": [20.0, 34.0, 20.0, 10.0, 6.0, 14.0],
    "Importance pour le client (%)": [30.0, 25.0, 15.0, 10.0, 8.0, 12.0],
})


def cout_cible(prix: float, marge_visee: float, cout_matiere: float, carac: pd.DataFrame) -> tuple[dict[str, float], pd.DataFrame]:
    """Coût admissible = prix x (1 - marge visée). Le solde après la matière se partage selon l'importance perçue des caractéristiques."""
    admissible = prix * (1 - marge_visee)
    enveloppe = admissible - cout_matiere
    t = carac.copy()
    imp = t["Importance pour le client (%)"] / t["Importance pour le client (%)"].sum()
    cout = t["Coût estimé ($/pièce)"]
    t["Part du coût"] = cout / cout.sum()
    t["Part de la valeur"] = imp
    t["Coût cible ($/pièce)"] = enveloppe * imp
    t["Écart à réduire ($)"] = cout - t["Coût cible ($/pièce)"]
    t["Ratio coût / valeur"] = t["Part du coût"] / t["Part de la valeur"]
    return {"admissible": admissible, "enveloppe": enveloppe, "estime": cout.sum(), "ecart": cout.sum() - enveloppe}, t


# --- ABM / PBM --------------------------------------------------------------------------------------------------------------------------------
ACTIVITES = pd.DataFrame([
    ("Soumission à la livraison", "Estimation et soumission", 180, "Nécessaire sans valeur ajoutée"),
    ("Soumission à la livraison", "Programmation FAO", 220, "Nécessaire sans valeur ajoutée"),
    ("Soumission à la livraison", "Réglage et préparation des machines", 310, "Nécessaire sans valeur ajoutée"),
    ("Soumission à la livraison", "Usinage — temps de coupe", 1150, "Valeur ajoutée"),
    ("Soumission à la livraison", "Attente entre opérations (encours)", 140, "Sans valeur"),
    ("Qualité et conformité", "Finition et traitement de surface", 260, "Valeur ajoutée"),
    ("Qualité et conformité", "Contrôle dimensionnel et rapports", 190, "Nécessaire sans valeur ajoutée"),
    ("Qualité et conformité", "Reprises, retouches et rebuts", 160, "Sans valeur"),
    ("Facturer et encaisser", "Facturation", 150, "Nécessaire sans valeur ajoutée"),
    ("Facturer et encaisser", "Corrections de factures", 120, "Sans valeur"),
    ("Facturer et encaisser", "Recouvrement", 190, "Nécessaire sans valeur ajoutée"),
], columns=["Processus", "Activité", "Coût (k$)", "Classe"])
CLASSES = ["Valeur ajoutée", "Nécessaire sans valeur ajoutée", "Sans valeur"]


def scenario_abm(reduction: dict[str, float]) -> pd.DataFrame:
    """Coût des activités après réduction (en %, 0 à 1) de certaines d'entre elles."""
    t = ACTIVITES.copy()
    t["Coût après (k$)"] = [c * (1 - reduction.get(a, 0.0)) for a, c in zip(t["Activité"], t["Coût (k$)"])]
    return t


# --- Imputation des charges directes et indirectes, avec les postes comptables ----------------------------------------------------------------
# Numéros du plan des états financiers (6000 + rang de catégorie × 10 pour les charges, 8010 amortissement, 5010 coût des produits vendus).
POSTES_INDIRECTS = [  # (compte, libellé, centre primaire, k$) : la somme par centre égale CENTRES_AUXILIAIRES / CENTRES_PRINCIPAUX
    ("7040", "Salaires et charges — administration", "Administration", 520.0), ("7140", "Honoraires professionnels (CPA, juridique)", "Administration", 140.0),
    ("6130", "Assurances (biens et responsabilité)", "Administration", 110.0), ("7150", "Télécoms, ERP, TI et logiciels", "Administration", 130.0),
    ("6100", "Entretien et réparation des machines", "Entretien et maintenance", 530.0), ("6050", "Sous-traitance (étalonnage, certification, réparations)", "Entretien et maintenance", 70.0),
    ("6030", "Salaires et charges — production (part indirecte)", "Usinage CNC", 900.0), ("6080", "Énergie — Hydro-Québec (usine)", "Usinage CNC", 420.0),
    ("6060", "Outillage et consommables d'atelier (part indirecte)", "Usinage CNC", 250.0), ("6090", "Loyer et taxes du bâtiment industriel", "Usinage CNC", 450.0),
    ("6110", "Location d'équipement (crédit-bail CNC)", "Usinage CNC", 280.0), ("8010", "Amortissement des immobilisations", "Usinage CNC", 400.0),
    ("6030", "Salaires et charges — production (part indirecte)", "Soudure et assemblage", 480.0), ("6060", "Outillage et consommables d'atelier (part indirecte)", "Soudure et assemblage", 150.0),
    ("6080", "Énergie — Hydro-Québec (usine)", "Soudure et assemblage", 120.0), ("8010", "Amortissement des immobilisations", "Soudure et assemblage", 250.0),
    ("6030", "Salaires et charges — production (part indirecte)", "Contrôle et métrologie", 470.0),
    ("6050", "Sous-traitance (étalonnage, certification, réparations)", "Contrôle et métrologie", 280.0), ("8010", "Amortissement des immobilisations", "Contrôle et métrologie", 150.0),
    ("6030", "Salaires et charges — production (part indirecte)", "Ingénierie et programmation", 640.0), ("7150", "Télécoms, ERP, TI et logiciels", "Ingénierie et programmation", 200.0),
    ("7170", "Formation, SST et équipements de protection", "Ingénierie et programmation", 90.0), ("7190", "Frais de déplacement et représentation", "Ingénierie et programmation", 70.0),
]
COMPTES_DIRECTS = {"5010": "Matières premières consommées (acier, aluminium, inox)", "6030": "Main-d'œuvre directe (salaires et charges — production)",
                   "5210": "Outillage et énergie machine imputables (frais variables)"}
CHAMP_DIRECT = {"5010": "achat", "6030": "mod", "5210": "variable"}


def postes_comptables() -> pd.DataFrame:
    """Tous les postes (k$) : directs par produit (affectation directe), indirects par centre. Colonnes : Compte, Poste, Nature, Imputé à, Mode."""
    lignes = []
    for p, d in PRODUITS.items():
        for compte, champ in CHAMP_DIRECT.items():
            lignes.append((compte, COMPTES_DIRECTS[compte], "Direct", p, "Affectation directe au produit", d["volume"] * d[champ]))
    for compte, poste, centre, montant in POSTES_INDIRECTS:
        mode = "Répartition secondaire vers les centres principaux" if centre in CENTRES_AUXILIAIRES else "Répartition primaire au centre, puis inducteur"
        lignes.append((compte, poste, "Indirect", centre, mode, montant))
    return pd.DataFrame(lignes, columns=["Compte", "Poste", "Nature", "Imputé à", "Mode", "Montant (k$)"])


def imputation_flux(famille: str = "Tout") -> pd.DataFrame:
    """Flux de l'imputation (k$) : poste comptable, nature, centre, produit. famille : « Tout », « Charges directes » ou « Charges indirectes »."""
    pools = repartition_secondaire().set_index("Centre")
    flux: list[tuple[str, str, float, str]] = []
    postes = postes_comptables()
    directs = postes[postes["Nature"] == "Direct"]
    for compte, g in directs.groupby("Compte"):
        flux.append((f"{compte} {COMPTES_DIRECTS[compte]}", "Charges directes", g["Montant (k$)"].sum(), "direct"))
    for p, g in directs.groupby("Imputé à"):
        flux.append(("Charges directes", p, g["Montant (k$)"].sum(), "direct"))
    ind = postes[postes["Nature"] == "Indirect"]
    for (compte, poste), g in ind.groupby(["Compte", "Poste"]):
        flux.append((f"{compte} {poste}", "Charges indirectes", g["Montant (k$)"].sum(), "indirect"))
    for centre, g in ind.groupby("Imputé à"):
        flux.append(("Charges indirectes", centre, g["Montant (k$)"].sum(), "indirect"))
    for aux, cles in CLES_SECONDAIRES.items():
        for centre, part in cles.items():
            if part:
                flux.append((aux, centre, CENTRES_AUXILIAIRES[aux] * part, "secondaire"))
    for centre, conso in INDUCTEURS.items():
        for p, q in conso.items():
            if q:
                flux.append((centre, p, pools.loc[centre, "Total"] * q / sum(conso.values()), "indirect"))
    df = pd.DataFrame(flux, columns=["Source", "Cible", "Montant (k$)", "Famille"])
    if famille == "Charges directes":
        df = df[df["Famille"] == "direct"]
    elif famille == "Charges indirectes":
        df = df[df["Famille"] != "direct"]
    return df.reset_index(drop=True)


def cout_complet_par_composante() -> pd.DataFrame:
    """Coût de revient complet par produit ($/unité) décomposé : charges directes par compte, charges indirectes par centre (inducteurs ABC)."""
    flux = imputation_flux()
    vol = _volumes()
    postes = postes_comptables()
    out = pd.DataFrame(index=vol.index)
    for compte, libelle in COMPTES_DIRECTS.items():
        out[f"{compte} {libelle}"] = pd.Series({p: g["Montant (k$)"].sum() for p, g in postes.query("Compte == @compte and Nature == 'Direct'").groupby("Imputé à")}) / vol
    for centre in INDUCTEURS:
        sel = flux[(flux["Source"] == centre) & flux["Cible"].isin(vol.index)].set_index("Cible")["Montant (k$)"]
        out[f"Indirect · {centre}"] = sel.reindex(vol.index).fillna(0.0) / vol
    return out


# =================================================================================================================================================
# Analyse de gestion (regard du CPA en comptabilité de management) : rentabilité, distorsion, prix, levier, capacité, qualité, écarts dans le temps
# =================================================================================================================================================
CAPACITE_NORMALE = {"Usinage CNC": 40000.0, "Soudure et assemblage": 10000.0, "Contrôle et métrologie": 12000.0, "Ingénierie et programmation": 11500.0}   # unités d'œuvre par an
PART_FIXE_CENTRES = 0.85          # part des charges d'un centre qui ne varie pas avec son activité à court terme


def rentabilite_produits() -> pd.DataFrame:
    """Compte de résultat par ligne de produits (k$) : ventes, marge sur coûts variables, charges indirectes ABC, marge complète ABC et marge selon les centres d'analyse.
    La distorsion est l'écart entre le coût ABC et le coût des centres d'analyse, en k$ : positive, la ligne est subventionnée par les autres ; négative, elle les subventionne."""
    d = cout_complet()
    c = contribution().set_index("Produit")
    out = pd.DataFrame(index=d.index)
    out["Ventes (k$)"] = d["Volume (milliers)"] * d["Prix ($/unité)"]
    out["Coûts directs (k$)"] = d["Volume (milliers)"] * d["Direct ($/unité)"]
    out["MCV (k$)"] = c["MCV (k$)"]
    out["Taux de MCV"] = out["MCV (k$)"] / out["Ventes (k$)"]
    out["Indirect ABC (k$)"] = d["Volume (milliers)"] * d["ABC : indirect ($/unité)"]
    out["Marge complète ABC (k$)"] = out["Ventes (k$)"] - out["Coûts directs (k$)"] - out["Indirect ABC (k$)"]
    out["Marge complète ABC (%)"] = out["Marge complète ABC (k$)"] / out["Ventes (k$)"]
    out["Marge selon centres (k$)"] = d["Volume (milliers)"] * d["Centres d'analyse : marge ($/unité)"]
    out["Distorsion (k$)"] = d["Volume (milliers)"] * (d["ABC : revient ($/unité)"] - d["Centres d'analyse : revient ($/unité)"])
    out["Rang ABC"] = out["Marge complète ABC (%)"].rank(ascending=False).astype(int)
    return out


def planchers_prix(marge_visee: float = 0.15) -> pd.DataFrame:
    """Trois planchers de prix par unité — variable (la vente ne perd pas d'argent à court terme), spécifique (elle couvre aussi les fixes de la ligne),
    complet ABC (elle couvre sa part de tous les frais) — et le prix cible qui donne la marge visée sur le coût ABC."""
    d = cout_complet()
    lignes = []
    for p, r in d.iterrows():
        direct = r["Direct ($/unité)"]
        specifique = direct + FIXES_SPECIFIQUES[p] / r["Volume (milliers)"]
        complet = r["ABC : revient ($/unité)"]
        cible = complet / (1 - marge_visee)
        prix = r["Prix ($/unité)"]
        lignes.append({"Produit": p, "Prix actuel ($)": prix, "Plancher variable ($)": direct, "Plancher spécifique ($)": specifique, "Plancher complet ABC ($)": complet,
                       "Prix cible ($)": cible, "Écart prix / cible (%)": prix / cible - 1,
                       "Position": "Sous le coût variable" if prix < direct else ("Sous le coût spécifique" if prix < specifique else ("Sous le coût complet" if prix < complet else
                                    ("Sous le prix cible" if prix < cible else "Au-dessus du prix cible")))})
    return pd.DataFrame(lignes)


def resultat_scenario(var_prix=0.0, var_volume=0.0, var_matiere=0.0, var_mod=0.0, var_variable=0.0, var_fixes=0.0) -> float:
    """Résultat d'exploitation (k$) quand les prix, les volumes, les coûts de matière, de main-d'œuvre directe, les frais variables ou les fixes varient (0,10 = +10 %)."""
    total = 0.0
    for p, d in PRODUITS.items():
        vol = d["volume"] * (1 + var_volume)
        total += vol * (d["prix"] * (1 + var_prix) - d["achat"] * (1 + var_matiere) - d["mod"] * (1 + var_mod) - d["variable"] * (1 + var_variable))
    return total - (sum(FIXES_SPECIFIQUES.values()) + FIXES_COMMUNES) * (1 + var_fixes)


def sensibilite_resultat(delta: float = 0.10) -> pd.DataFrame:
    """Tornado : effet sur le résultat d'exploitation (k$) d'une variation défavorable et favorable de chaque facteur."""
    base = resultat_scenario()
    facteurs = {"Prix de vente": ("var_prix", +1), "Volumes": ("var_volume", +1), "Coût de la matière": ("var_matiere", -1), "Main-d'œuvre directe": ("var_mod", -1),
                "Frais variables": ("var_variable", -1), "Charges fixes": ("var_fixes", -1)}
    lignes = []
    for nom, (cle, sens) in facteurs.items():
        fav = resultat_scenario(**{cle: sens * delta}) - base
        defav = resultat_scenario(**{cle: -sens * delta}) - base
        lignes.append({"Facteur": nom, "Défavorable (k$)": defav, "Favorable (k$)": fav, "Amplitude (k$)": fav - defav})
    return pd.DataFrame(lignes).sort_values("Amplitude (k$)", ascending=False).reset_index(drop=True)


def levier_exploitation() -> dict[str, float]:
    """Degré de levier d'exploitation = marge sur coûts variables ÷ résultat : de combien de % le résultat varie quand les volumes varient de 1 %."""
    df = contribution()
    r = resultat_et_point_mort(df)
    return {"degre_levier": r["mcv"] / r["resultat"], "mcv": r["mcv"], "resultat": r["resultat"], "marge_securite": r["marge_securite"], "point_mort": r["point_mort"]}


def point_mort_produits() -> pd.DataFrame:
    """Point mort de chaque ligne : volume qui couvre ses fixes spécifiques (milliers d'unités), part du volume actuel et marge de sécurité de la ligne."""
    lignes = []
    for p, d in PRODUITS.items():
        mc = d["prix"] - direct_unitaire(p)
        pm = FIXES_SPECIFIQUES[p] / mc if mc > 0 else float("inf")
        lignes.append({"Produit": p, "Marge unitaire ($)": mc, "Fixes spécifiques (k$)": FIXES_SPECIFIQUES[p], "Point mort (milliers)": pm, "Volume actuel (milliers)": d["volume"],
                       "Point mort / volume": pm / d["volume"], "Marge de sécurité": 1 - pm / d["volume"]})
    return pd.DataFrame(lignes)


def mix_capacite(capacite_heures: float = 40000.0, croissance_max: float = 0.20) -> pd.DataFrame:
    """Mix qui maximise la marge sur coûts variables quand les heures-machine sont rares (théorie des contraintes) : on sert d'abord les lignes qui rapportent
    le plus par heure-machine, chacune dans la limite de la demande (volume actuel × (1 + croissance_max)). Ne tient pas compte des fixes spécifiques : à ne pas
    utiliser pour abandonner une ligne sans les examiner."""
    h_total = INDUCTEURS["Usinage CNC"]
    lignes = []
    for p, d in PRODUITS.items():
        h_unite = h_total[p] / (d["volume"] * 1000)                      # heures-machine par pièce ou projet
        mcv_unite = d["prix"] - direct_unitaire(p)
        lignes.append({"Produit": p, "Heures par unité": h_unite, "MCV par unité ($)": mcv_unite, "MCV par heure-machine ($)": mcv_unite / h_unite,
                       "Heures actuelles": h_total[p], "Demande max (heures)": h_total[p] * (1 + croissance_max), "volume": d["volume"]})
    df = pd.DataFrame(lignes).sort_values("MCV par heure-machine ($)", ascending=False).reset_index(drop=True)
    reste, alloc = capacite_heures, []
    for _, r in df.iterrows():
        h = min(reste, r["Demande max (heures)"])
        alloc.append(h)
        reste -= h
    df["Heures allouées"] = alloc
    df["Volume optimal (milliers)"] = df["Heures allouées"] / (df["Heures actuelles"] / df["volume"])
    df["Variation vs actuel"] = df["Heures allouées"] / df["Heures actuelles"] - 1
    df["MCV optimale (k$)"] = df["Volume optimal (milliers)"] * df["MCV par unité ($)"]
    df["MCV actuelle (k$)"] = df["volume"] * df["MCV par unité ($)"]
    prix_ombre = 0.0
    if reste <= 1e-6:                                                         # contrainte active : valeur d'une heure de plus = MCV/h du dernier produit servi
        servis = df[df["Heures allouées"] > 1e-6]
        prix_ombre = float(servis.iloc[-1]["MCV par heure-machine ($)"])
    df.attrs.update(contrainte_active=bool(reste <= 1e-6), prix_ombre=prix_ombre, heures_inutilisees=max(reste, 0.0), mcv_optimale=float(df["MCV optimale (k$)"].sum()),
                    mcv_actuelle=float(df["MCV actuelle (k$)"].sum()))
    return df.drop(columns=["volume"])


def capacite_centres(capacites: dict[str, float] | None = None, part_fixe: float = PART_FIXE_CENTRES) -> pd.DataFrame:
    """Utilisation et coût de sous-activité de chaque centre principal (IRCF) : charges fixes = part fixe × charges du centre après répartition secondaire."""
    cap = capacites or CAPACITE_NORMALE
    pools = repartition_secondaire().set_index("Centre")["Total"]
    lignes = []
    for centre in CENTRES_PRINCIPAUX:
        reelle = float(sum(INDUCTEURS[centre].values()))
        fixes = pools[centre] * part_fixe
        r = ircf(fixes, cap[centre], reelle)
        lignes.append({"Centre": centre, "Unité d'œuvre": UNITE_OEUVRE[centre], "Activité réelle": reelle, "Capacité normale": cap[centre], "Utilisation": reelle / cap[centre],
                       "Charges du centre (k$)": pools[centre], "Charges fixes (k$)": fixes, "Taux fixe normal ($/unité)": r["unitaire_ircf"], "Taux fixe réel ($/unité)": r["unitaire_complet"],
                       "Coût de sous-activité (k$)": r["sous_activite"]})
    return pd.DataFrame(lignes)


COUT_QUALITE = [  # (catégorie, poste, k$)
    ("Prévention", "Certification AS9100 et audits", 130.0), ("Prévention", "Planification qualité et plans de contrôle", 90.0), ("Prévention", "Formation qualité et SST", 40.0),
    ("Évaluation", "Contrôle dimensionnel (MMT) et rapports", 190.0), ("Évaluation", "Étalonnage des instruments", 90.0), ("Évaluation", "Inspection à la réception de la matière", 60.0),
    ("Défaillance interne", "Reprises, retouches et rebuts", 160.0), ("Défaillance interne", "Matière perdue (pièces mises au rebut)", 70.0), ("Défaillance interne", "Attente et réordonnancement", 40.0),
    ("Défaillance externe", "Retours et réclamations de clients", 60.0), ("Défaillance externe", "Frais de garantie", 30.0),
]


def cout_qualite() -> dict:
    """Coût de la qualité : conformité (prévention + évaluation) contre non-conformité (défaillances internes et externes), en k$ et en % des ventes."""
    t = pd.DataFrame(COUT_QUALITE, columns=["Catégorie", "Poste", "Montant (k$)"])
    ventes = sum(d["volume"] * d["prix"] for d in PRODUITS.values())
    par_cat = t.groupby("Catégorie", sort=False)["Montant (k$)"].sum()
    conformite = par_cat[["Prévention", "Évaluation"]].sum()
    non_conf = par_cat[["Défaillance interne", "Défaillance externe"]].sum()
    return {"detail": t, "par_categorie": par_cat, "total": float(t["Montant (k$)"].sum()), "ventes": ventes, "pct_ventes": float(t["Montant (k$)"].sum() / ventes),
            "conformite": float(conformite), "non_conformite": float(non_conf), "ratio_non_conformite": float(non_conf / (conformite + non_conf))}


def investigation(ecart: float, base: float, seuil_pct: float = 0.05, seuil_dollars: float = 2500.0) -> bool:
    """Règle d'investigation d'un écart : il faut qu'il dépasse à la fois un pourcentage du coût standard et un montant minimal (sinon on s'épuise sur des riens)."""
    return abs(ecart) >= seuil_dollars and abs(ecart) >= seuil_pct * abs(base)


def historique_ecarts(mois: int = 12, courant: dict[str, float] | None = None, graine: int = 2026) -> pd.DataFrame:
    """Écarts mensuels sur standards (fictifs, reproductibles) : les onze premiers mois servent à fixer les limites de contrôle ; le dernier est le mois courant.
    Colonnes : une cause par colonne, index = mois."""
    import random
    rnd = random.Random(graine)
    moyennes = {"Prix de la matière": (900, 700), "Quantité de matière (rebuts, copeaux)": (1100, 500), "Taux horaire": (3500, 1100), "Rendement (heures)": (4800, 2200),
                "Frais variables": (350, 450)}
    periodes = [str(p) for p in pd.period_range(end="2026-09", periods=mois, freq="M")]
    data = {nom: [rnd.gauss(m, s) for _ in range(mois)] for nom, (m, s) in moyennes.items()}
    df = pd.DataFrame(data, index=periodes)
    if courant:
        for k, v in courant.items():
            if k in df.columns:
                df.loc[periodes[-1], k] = v
    return df


def limites_controle(hist: pd.DataFrame, k: float = 2.0) -> pd.DataFrame:
    """Moyenne et limites (± k écarts-types) calculées sur les mois qui précèdent le dernier ; indique si le mois courant sort des limites."""
    ref = hist.iloc[:-1]
    out = pd.DataFrame({"Moyenne": ref.mean(), "Écart-type": ref.std()})
    out["Limite haute"] = out["Moyenne"] + k * out["Écart-type"]
    out["Limite basse"] = out["Moyenne"] - k * out["Écart-type"]
    out["Mois courant"] = hist.iloc[-1]
    out["Hors limites"] = (out["Mois courant"] > out["Limite haute"]) | (out["Mois courant"] < out["Limite basse"])
    return out


FIXES_STANDARD = {"budget_mensuel": 30800.0, "volume_normal": 2200.0}     # frais généraux fixes de fabrication : budget du mois ($) et production normale (pièces)


def ecarts_frais_fixes(pieces: float, reel_fixe: float, std: dict[str, float] = FIXES_STANDARD) -> dict[str, float]:
    """Frais généraux fixes de fabrication, imputés à un taux prédéterminé (budget ÷ production normale). Positif = défavorable.
    Écart de budget = dépensé − budgété ; écart de volume = budgété − imputé (la production réelle a été inférieure ou supérieure à la normale).
    Leur somme est la sous-imputation (ou sur-imputation) de la période, soit les frais fixes réels moins ceux que les pièces produites ont absorbés."""
    taux = std["budget_mensuel"] / std["volume_normal"]
    imputes = pieces * taux
    ecart_budget = reel_fixe - std["budget_mensuel"]
    ecart_volume = std["budget_mensuel"] - imputes
    return {"taux": taux, "imputes": imputes, "budget": std["budget_mensuel"], "reel": reel_fixe, "ecart_budget": ecart_budget, "ecart_volume": ecart_volume,
            "sous_imputation": reel_fixe - imputes, "utilisation": pieces / std["volume_normal"]}


def taux_machine() -> float:
    """Taux horaire du centre d'usinage CNC ($ par heure-machine) : charges du centre après répartition secondaire ÷ heures-machine consommées."""
    pools = repartition_secondaire().set_index("Centre")["Total"]
    return float(pools["Usinage CNC"] * 1000 / sum(INDUCTEURS["Usinage CNC"].values()))


# --- Coût par commande : le devis contre le réel ----------------------------------------------------------------------------------------------
COMMANDES = pd.DataFrame([  # commande, ligne, marge soumise, matière (est, réel $), main-d'œuvre (h), machine (h), sous-traitance (est, réel $), reprises ($ réels)
    ("OF-2611 Brides de turbine (lot de 40)",          "Usinage sur mesure",    0.20, 4200, 4380, 120, 131, 150, 166, 1500, 1500,   0),
    ("OF-2614 Carter de réducteur",                    "Usinage sur mesure",    0.20, 2900, 2950,  85,  92, 110, 118,  800, 1100, 320),
    ("OF-2618 Supports de train d'atterrissage",       "Contrats aéro et rail", 0.18, 9800, 9870, 210, 214, 300, 306, 2600, 2600,   0),
    ("OF-2622 Essieux ferroviaires (série 300)",       "Contrats aéro et rail", 0.18, 7400, 7650, 160, 166, 240, 248, 1800, 1800,   0),
    ("OF-2625 Pièces de pompe (lot de 120)",           "Pièces de rechange",    0.22, 1900, 1860,  60,  78,  70,  95,  350,  350,   0),
    ("OF-2627 Engrenages de remplacement (lot de 60)", "Pièces de rechange",    0.22, 1350, 1400,  48,  59,  52,  66,    0,    0, 150),
    ("OF-2630 Prototype d'actionneur",                 "Prototypage",           0.12, 1600, 2150,  95, 140,  80, 118,  700,  900, 450),
    ("OF-2633 Prototype de support de capteur",        "Prototypage",           0.12,  900, 1100,  60,  86,  50,  71,  300,  400, 200),
], columns=["Commande", "Ligne", "Marge soumise", "Matière estimée", "Matière réelle", "MOD estimée (h)", "MOD réelle (h)", "Machine estimée (h)", "Machine réelle (h)",
            "Sous-traitance estimée", "Sous-traitance réelle", "Reprises"])
ELEMENTS_COMMANDE = ["Matière", "Main-d'œuvre directe", "Machine", "Sous-traitance", "Reprises"]


def commandes_detail() -> pd.DataFrame:
    """Chaque commande, élément par élément ($) : estimé au devis, réel, écart (positif = dépassement). Le coût estimé et le prix soumis (coût estimé ÷ (1 − marge soumise)) sont fixés au devis."""
    tm, tx = taux_machine(), STANDARD["taux"]
    lignes = []
    for _, r in COMMANDES.iterrows():
        est = {"Matière": r["Matière estimée"], "Main-d'œuvre directe": r["MOD estimée (h)"] * tx, "Machine": r["Machine estimée (h)"] * tm, "Sous-traitance": r["Sous-traitance estimée"], "Reprises": 0.0}
        reel = {"Matière": r["Matière réelle"], "Main-d'œuvre directe": r["MOD réelle (h)"] * tx, "Machine": r["Machine réelle (h)"] * tm, "Sous-traitance": r["Sous-traitance réelle"], "Reprises": float(r["Reprises"])}
        prix = sum(est.values()) / (1 - r["Marge soumise"])
        for el in ELEMENTS_COMMANDE:
            lignes.append({"Commande": r["Commande"], "Ligne": r["Ligne"], "Élément": el, "Estimé ($)": est[el], "Réel ($)": reel[el], "Écart ($)": reel[el] - est[el], "Prix soumis ($)": prix})
    return pd.DataFrame(lignes)


def commandes() -> pd.DataFrame:
    """Une ligne par commande : prix soumis, coût estimé et réel, marge prévue et réelle. Écart > 0 = dépassement du devis."""
    d = commandes_detail()
    g = d.groupby(["Commande", "Ligne"], sort=False).agg(prix=("Prix soumis ($)", "first"), estime=("Estimé ($)", "sum"), reel=("Réel ($)", "sum")).reset_index()
    out = pd.DataFrame({"Commande": g["Commande"], "Ligne": g["Ligne"], "Prix soumis ($)": g["prix"], "Coût estimé ($)": g["estime"], "Coût réel ($)": g["reel"]})
    out["Écart ($)"] = out["Coût réel ($)"] - out["Coût estimé ($)"]
    out["Écart (%)"] = out["Écart ($)"] / out["Coût estimé ($)"]
    out["Marge prévue (%)"] = 1 - out["Coût estimé ($)"] / out["Prix soumis ($)"]
    out["Marge réelle (%)"] = 1 - out["Coût réel ($)"] / out["Prix soumis ($)"]
    out["Marge perdue (pts)"] = out["Marge prévue (%)"] - out["Marge réelle (%)"]
    return out


def precision_soumissions(seuil: float = 0.05) -> pd.DataFrame:
    """Précision de l'estimation par ligne : écart moyen pondéré (en % du coût estimé), part des commandes qui dépassent le seuil, marge prévue contre réelle, et poste qui dérive le plus."""
    c, d = commandes(), commandes_detail()
    lignes = []
    for ligne, g in c.groupby("Ligne", sort=False):
        el = d[d["Ligne"] == ligne].groupby("Élément")["Écart ($)"].sum()
        prix = g["Prix soumis ($)"].sum()
        lignes.append({"Ligne": ligne, "Commandes": len(g), "Écart moyen pondéré": g["Écart ($)"].sum() / g["Coût estimé ($)"].sum(), "Commandes au-delà du seuil": int((g["Écart (%)"] > seuil).sum()),
                       "Marge prévue (%)": 1 - g["Coût estimé ($)"].sum() / prix, "Marge réelle (%)": 1 - g["Coût réel ($)"].sum() / prix, "Poste qui dérive": el.idxmax(), "Dérive du poste ($)": float(el.max())})
    return pd.DataFrame(lignes)


# --- Commande spéciale (coûts pertinents) -----------------------------------------------------------------------------------------------------
def commande_speciale(produit: str, quantite: float, prix: float, capacite_libre: bool = True, heures_machine_unite: float | None = None) -> dict[str, float]:
    """Accepter une commande hors catalogue, à un prix inférieur ? Seuls comptent les coûts qui diffèrent : coûts variables et, si la capacité est pleine, la marge sacrifiée sur les heures-machine prises.
    Montants en $ (quantité en unités) ; `plancher` est le prix en dessous duquel il ne faut pas accepter la commande."""
    d = PRODUITS[produit]
    mc = prix - direct_unitaire(produit)
    h = heures_machine_unite if heures_machine_unite is not None else INDUCTEURS["Usinage CNC"][produit] / (d["volume"] * 1000)
    mcv_h = (d["prix"] - direct_unitaire(produit)) / h if h else 0.0
    cout_opportunite = 0.0 if capacite_libre else h * mcv_h
    return {"marge_unitaire": mc, "contribution": quantite * mc, "heures": quantite * h, "cout_opportunite": quantite * cout_opportunite, "contribution_nette": quantite * (mc - cout_opportunite),
            "plancher": direct_unitaire(produit) + cout_opportunite, "accepter": (mc - cout_opportunite) > 0}


# --- Registre des méthodes : retenues et écartées ---------------------------------------------------------------------------------------------
METHODES = pd.DataFrame([
    ("Coûts standards et écarts", "Pilier", "Le coût réel est-il celui qu'il devrait être, et qui doit répondre de l'écart ?", "Contrôle, responsabilisation, budget flexible", "Assise du contrôle de gestion d'une manufacture : chaque écart a une cause et un responsable."),
    ("Frais généraux imputés à un taux prédéterminé", "Pilier", "Combien de frais fixes les pièces produites ont-elles absorbé ?", "Valorisation des stocks, sous-imputation", "Un taux fixé au budget et à la production normale évite que le coût d'une pièce varie avec le volume du mois."),
    ("Coût par commande (devis contre réel)", "Pilier", "Le prix soumis était-il le bon ?", "Soumissions et prix", "En production sur commande, le coût se forme commande par commande : c'est là qu'on apprend à mieux estimer."),
    ("Coût complet par ABC", "Pilier", "Quelles lignes gagnent vraiment de l'argent une fois les frais indirects attribués ?", "Rentabilité, portefeuille, prix", "Les inducteurs réels (heures-machine, inspections, ingénierie) rattachent les frais à ce qui les cause."),
    ("Coûts variables et point mort", "Pilier", "Que gagne-t-on si le volume, le prix ou l'offre changent ?", "Décisions à court terme, commandes spéciales", "Seuls les coûts qui diffèrent entre les options sont pertinents pour une décision."),
    ("Théorie des contraintes (marge par heure-machine)", "Pilier", "Quand les machines sont rares, que faut-il faire passer en premier ?", "Mix, ordonnancement, soumissions", "Le goulot d'étranglement fixe le débit de l'atelier : c'est la marge par heure du goulot qui compte."),
    ("Coûts par centre d'analyse (taux horaire)", "Complément", "Quelle valeur donner aux stocks et aux encours ?", "Valorisation comptable", "Conforme au coût de fabrication normal ; gardé pour les états financiers et comme référence de comparaison de l'ABC, pas pour fixer les prix."),
    ("Imputation rationnelle et coût de sous-activité", "Complément", "Quelle part des frais fixes est un coût de capacité inutilisée ?", "Capacité et investissement", "Sépare le coût de la pièce du coût de la machine vide."),
    ("Coût cible et feature costing", "Complément", "Combien peut-on dépenser pour une offre, vu le prix que le marché accepte ?", "Nouveaux contrats et conception", "Pertinent pour les contrats aéro et rail où le client impose un prix."),
    ("Coût de la qualité et ABM", "Complément", "Où dépense-t-on sans créer de valeur ?", "Amélioration continue", "Rend visible le coût des reprises et des attentes, pour agir sur les activités plutôt que sur les budgets."),
    ("Unités de valeur ajoutée (UVA)", "Écartée", "—", "—", "Un seul inducteur composite aux coefficients arbitraires, peu répandu en Amérique du Nord ; l'ABC, avec des inducteurs observables, le remplace avec plus de transparence."),
    ("Frais répartis sur la seule main-d'œuvre directe", "Écartée", "—", "—", "La main-d'œuvre n'est plus qu'une part du coût dans un atelier à machines CNC : la clé trompe, comme l'ABC le montre sur les lignes de contrôle et d'ingénierie."),
    ("Coûts réels seuls (sans standard)", "Écartée", "—", "—", "Tardifs, volatils, sans repère : ils mélangent l'inefficacité d'un mois et la saisonnalité des frais."),
    ("Coût de revient par processus continu (unités équivalentes)", "Écartée", "—", "—", "Fait pour la production en continu ; l'atelier fabrique sur commande, où le coût par commande est la bonne unité."),
    ("Budget base zéro et coût de transfert entre divisions", "Écartée", "—", "—", "Utiles ailleurs ; hors du périmètre du coût de revient de l'atelier. Le prix de cession interne est traité par la consolidation."),
], columns=["Méthode", "Statut", "Question à laquelle elle répond", "Décision éclairée", "Pourquoi"])


def decomposer_ecart_prix(ecart_prix: float, var_marche: float, part_matiere: float, prix_standard: float, kg: float) -> dict[str, float]:
    """Sépare l'écart de prix de la matière entre ce que le marché explique (variation du prix du métal depuis la fixation du standard × part du prix qui suit le marché)
    et le reste (négociation, surcharges, quantités commandées, délais de paiement) — le seul que l'acheteur contrôle."""
    marche = prix_standard * part_matiere * var_marche * kg
    return {"ecart_total": ecart_prix, "effet_marche": marche, "effet_achat": ecart_prix - marche}