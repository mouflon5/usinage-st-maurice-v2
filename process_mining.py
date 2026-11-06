"""Process mining de Groupe Usinage Saint-Maurice : du journal d'événements à la carte du processus, aux goulots et aux écarts de conformité.

Deux processus : le cycle achats-décaissements (celui de cycle_achats.py) et la commande de fabrication (de la commande reçue à la facturation).
Le journal est SYNTHÉTIQUE (graine fixe, donc reproductible) : un vrai journal viendrait de l'ERP, une ligne par événement (cas, activité, horodatage, ressource).

Outils : carte des suivis directs (fréquence et attente), variantes, goulots, conformité au modèle de référence (alignement), séparation des tâches,
coût des reprises. Le coût des reprises alimente un paquet de décision de la planification budgétaire (base zéro).
"""
from __future__ import annotations

import math
import random
from datetime import datetime, timedelta

import pandas as pd

DEBUT_PERIODE = datetime(2026, 4, 1)
JOURS_PERIODE = 183                                  # avril à septembre 2026 : le journal couvre six mois, on annualise par 365 / 183


class _Processus:
    def __init__(self, nom, chemin, courts, optionnelles, ressources, attente, positions, extras, cout_evenement, sod, cas_par_periode):
        self.nom, self.chemin, self.courts, self.optionnelles = nom, chemin, courts, set(optionnelles)
        self.ressources, self.attente, self.positions, self.extras = ressources, attente, positions, extras
        self.cout_evenement, self.sod, self.cas_par_periode = cout_evenement, sod, cas_par_periode


ACHATS = _Processus(
    "Achats et paiements",
    ["Besoin d'achat", "Commande d'achat", "Approbation de la commande", "Réception et contrôle", "Facture du fournisseur", "Appariement à trois voies",
     "Approbation de la facture", "Lot de paiement", "Rapprochement bancaire"],
    ["Besoin", "Commande", "Appro. commande", "Réception", "Facture", "Appariement", "Appro. facture", "Paiement", "Rapproch."],
    [],
    {"Besoin d'achat": ["Planificateur de production", "Responsable de l'usine", "Responsable de la finition"],
     "Commande d'achat": ["Chef des approvisionnements", "Acheteuse 1", "Acheteur 2"],
     "Approbation de la commande": ["Chef des approvisionnements", "Contrôleur financier"],
     "Réception et contrôle": ["Magasinier 1", "Magasinier 2"],
     "Facture du fournisseur": ["Commis comptes fournisseurs 1", "Commis comptes fournisseurs 2"],
     "Appariement à trois voies": ["Système"],
     "Approbation de la facture": ["Contrôleur financier", "Contrôleur adjoint"],
     "Lot de paiement": ["Commis comptes fournisseurs 1", "Trésorier"],
     "Rapprochement bancaire": ["Trésorier"],
     "Retenue pour écart": ["Système"], "Correction de la facture": ["Commis comptes fournisseurs 1", "Commis comptes fournisseurs 2", "Acheteuse 1"]},
    {"Commande d'achat": 20, "Approbation de la commande": 14, "Réception et contrôle": 96, "Facture du fournisseur": 40, "Appariement à trois voies": 6,
     "Approbation de la facture": 62, "Lot de paiement": 118, "Rapprochement bancaire": 30, "Retenue pour écart": 2, "Correction de la facture": 54},
    {"Besoin d'achat": (0, 0), "Commande d'achat": (1, 0), "Approbation de la commande": (2, 0), "Réception et contrôle": (3, 0), "Facture du fournisseur": (4, 0),
     "Appariement à trois voies": (5, 0), "Approbation de la facture": (6, 0), "Lot de paiement": (7, 0), "Rapprochement bancaire": (8, 0),
     "Retenue pour écart": (5.7, -1.15), "Correction de la facture": (4.3, -1.15)},
    ["Retenue pour écart", "Correction de la facture"],
    {"Retenue pour écart": 65.0, "Correction de la facture": 40.0},
    ("Facture du fournisseur", "Approbation de la facture"),
    600)
ACHATS.cas_annuels = 4200                           # le journal est un échantillon de 600 factures sur six mois ; le groupe en traite environ 4 200 par an

FABRICATION = _Processus(
    "Commande de fabrication",
    ["Commande reçue", "Revue technique", "Programmation CNC", "Approvisionnement matière", "Usinage", "Soudure et assemblage", "Contrôle qualité", "Expédition",
     "Facturation client"],
    ["Commande", "Revue tech.", "Programmation", "Matière", "Usinage", "Soudure", "Contrôle", "Expédition", "Facturation"],
    ["Soudure et assemblage"],
    {"Commande reçue": ["Représentante aux ventes", "Représentant aux ventes"], "Revue technique": ["Ingénieur 1", "Ingénieure 2"],
     "Programmation CNC": ["Programmeur 1", "Programmeuse 2", "Programmeur 3"], "Approvisionnement matière": ["Acheteuse 1", "Acheteur 2"],
     "Usinage": ["Centre CNC 1", "Centre CNC 2", "Centre CNC 3", "Centre CNC 4"], "Soudure et assemblage": ["Poste de soudure 1", "Poste de soudure 2"],
     "Contrôle qualité": ["Inspectrice 1", "Inspecteur 2"], "Expédition": ["Magasinier 1", "Magasinier 2"], "Facturation client": ["Commis facturation"],
     "Reprise": ["Centre CNC 1", "Centre CNC 2", "Poste de soudure 1"]},
    {"Revue technique": 12, "Programmation CNC": 30, "Approvisionnement matière": 118, "Usinage": 58, "Soudure et assemblage": 30, "Contrôle qualité": 18,
     "Expédition": 22, "Facturation client": 46, "Reprise": 12},
    {"Commande reçue": (0, 0), "Revue technique": (1, 0), "Programmation CNC": (2, 0), "Approvisionnement matière": (3, 0), "Usinage": (4, 0), "Soudure et assemblage": (5, 0),
     "Contrôle qualité": (6, 0), "Expédition": (7, 0), "Facturation client": (8, 0), "Reprise": (5, -1.15)},
    ["Reprise"],
    {"Reprise": 650.0},
    None,
    260)
FABRICATION.cas_annuels = 520                       # le journal couvre toutes les commandes de six mois

PROCESSUS = {ACHATS.nom: ACHATS, FABRICATION.nom: FABRICATION}


def _duree(rnd: random.Random, moyenne: float, sigma: float = 0.55) -> float:
    """Délai en heures, loi log-normale de moyenne donnée (la queue épaisse des vrais délais)."""
    return rnd.lognormvariate(math.log(moyenne) - sigma ** 2 / 2, sigma)


def _sequence(rnd: random.Random, p: _Processus) -> list[str]:
    s = list(p.chemin)
    if p is ACHATS:
        if rnd.random() < 0.05:
            s.remove("Approbation de la commande")
        elif rnd.random() < 0.07:                                   # approbation après coup : donnée après la réception
            s.remove("Approbation de la commande")
            s.insert(s.index("Réception et contrôle") + 1, "Approbation de la commande")
        if rnd.random() < 0.04:
            s.remove("Réception et contrôle")
        if rnd.random() < 0.03:
            s.remove("Approbation de la facture")
        i = s.index("Appariement à trois voies")
        while rnd.random() < 0.17:                                   # écart hors tolérance : retenue, correction, nouvel appariement
            s[i + 1:i + 1] = ["Retenue pour écart", "Correction de la facture", "Appariement à trois voies"]
            i += 3
    else:
        if rnd.random() < 0.45:
            s.remove("Soudure et assemblage")
        if rnd.random() < 0.05:
            s.remove("Revue technique")
        elif rnd.random() < 0.08:                                    # programmation lancée avant la fin de la revue technique
            i, j = s.index("Revue technique"), s.index("Programmation CNC")
            s[i], s[j] = s[j], s[i]
        if rnd.random() < 0.03:
            s.remove("Contrôle qualité")
        else:
            i = s.index("Contrôle qualité")
            while rnd.random() < 0.15:                               # non-conformité : reprise, nouvel usinage, nouveau contrôle
                s[i + 1:i + 1] = ["Reprise", "Usinage", "Contrôle qualité"]
                i += 3
    return s


def journal(processus: str = ACHATS.nom, graine: int = 20261101) -> pd.DataFrame:
    """Journal d'événements synthétique : une ligne par événement (Cas, Activité, Horodatage, Ressource, Montant)."""
    p = PROCESSUS[processus]
    rnd = random.Random(graine + len(p.nom))
    lignes = []
    for n in range(p.cas_par_periode):
        cas = f"{'ACH' if p is ACHATS else 'OF'}-{n + 1:04d}"
        t = DEBUT_PERIODE + timedelta(days=rnd.uniform(0, JOURS_PERIODE - 30), hours=rnd.uniform(7, 16))
        montant = round(rnd.lognormvariate(math.log(7500 if p is ACHATS else 21000), 0.9), 2)
        seq = _sequence(rnd, p)
        qui_facture = None
        for k, act in enumerate(seq):
            if k:
                t += timedelta(hours=_duree(rnd, p.attente.get(act, 24.0) * (1 + 0.35 * (montant > 40000))))
            res = rnd.choice(p.ressources[act])
            if p.sod and act == p.sod[0]:
                qui_facture = res
            if p.sod and act == p.sod[1] and qui_facture and rnd.random() < 0.04:
                res = qui_facture                                    # la même personne enregistre et approuve la facture
            lignes.append({"Cas": cas, "Activité": act, "Horodatage": t, "Ressource": res, "Montant ($)": montant})
    return pd.DataFrame(lignes).sort_values(["Cas", "Horodatage"], kind="stable").reset_index(drop=True)


# --- Analyses ---------------------------------------------------------------------------------------------------------------------------------------
def traces(log: pd.DataFrame) -> pd.Series:
    return log.groupby("Cas", sort=False)["Activité"].apply(tuple)


def durees_cas(log: pd.DataFrame) -> pd.DataFrame:
    g = log.groupby("Cas", sort=False)["Horodatage"]
    d = pd.DataFrame({"Début": g.min(), "Fin": g.max(), "Événements": log.groupby("Cas", sort=False).size()})
    d["Durée (j)"] = (d["Fin"] - d["Début"]).dt.total_seconds() / 86400
    d["Montant ($)"] = log.groupby("Cas", sort=False)["Montant ($)"].first()
    return d


def suivis_directs(log: pd.DataFrame) -> pd.DataFrame:
    """Les arcs de la carte : pour chaque paire (A puis B) dans un même cas, la fréquence et l'attente entre A et B (heures)."""
    l = log.sort_values(["Cas", "Horodatage"], kind="stable").copy()
    l["Vers"] = l.groupby("Cas")["Activité"].shift(-1)
    l["Attente (h)"] = (l.groupby("Cas")["Horodatage"].shift(-1) - l["Horodatage"]).dt.total_seconds() / 3600
    a = l.dropna(subset=["Vers"]).groupby(["Activité", "Vers"])["Attente (h)"].agg(["size", "mean", "median"]).reset_index()
    a.columns = ["De", "Vers", "Fréquence", "Attente moyenne (h)", "Attente médiane (h)"]
    a["Attente totale (h)"] = a["Fréquence"] * a["Attente moyenne (h)"]
    return a.sort_values("Fréquence", ascending=False).reset_index(drop=True)


def activites(log: pd.DataFrame) -> pd.DataFrame:
    g = log.groupby("Activité")
    return pd.DataFrame({"Événements": g.size(), "Cas": g["Cas"].nunique()})


def variantes(log: pd.DataFrame, processus: str = ACHATS.nom) -> pd.DataFrame:
    p = PROCESSUS[processus]
    t = traces(log)
    d = durees_cas(log)
    v = pd.DataFrame({"Trace": t, "Durée (j)": d["Durée (j)"]})
    g = v.groupby("Trace")
    r = pd.DataFrame({"Cas": g.size(), "Durée médiane (j)": g["Durée (j)"].median()}).reset_index().sort_values("Cas", ascending=False).reset_index(drop=True)
    r["Variante"] = [f"V{i + 1}" for i in range(len(r))]
    r["Part (%)"] = r["Cas"] / r["Cas"].sum() * 100
    r["Cumul (%)"] = r["Part (%)"].cumsum()
    r["Conforme"] = r["Trace"].apply(lambda s: tuple(a for a in p.chemin if a in s or a not in p.optionnelles) == s)
    return r[["Variante", "Trace", "Cas", "Part (%)", "Cumul (%)", "Durée médiane (j)", "Conforme"]]


def _plus_longue_sous_sequence(a: tuple, b: tuple) -> int:
    m = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i in range(len(a)):
        for j in range(len(b)):
            m[i + 1][j + 1] = m[i][j] + 1 if a[i] == b[j] else max(m[i][j + 1], m[i + 1][j])
    return m[-1][-1]


def conformite(log: pd.DataFrame, processus: str = ACHATS.nom) -> pd.DataFrame:
    """Compare chaque cas au modèle de référence par alignement (plus longue sous-séquence commune). Aptitude de 0 à 1 ; 1 = trace conforme.

    Écarts : étape sautée (activité obligatoire absente), reprise (activité répétée ou hors modèle), ordre inversé (activités du modèle dans un autre ordre).
    """
    p = PROCESSUS[processus]
    ref = tuple(p.chemin)
    lignes = []
    for cas, tr in traces(log).items():
        sautees = [a for a in ref if a not in tr and a not in p.optionnelles]
        modele_eff = tuple(a for a in ref if a in tr or a not in p.optionnelles)
        lcs = _plus_longue_sous_sequence(tr, ref)
        fitness = 1 - ((len(tr) - lcs) + (len(modele_eff) - lcs)) / (len(tr) + len(modele_eff))
        extras = [a for a in tr if a not in ref]
        repetees = sorted({a for a in tr if tr.count(a) > 1 and a in ref} | set(extras))
        premieres = [tr.index(a) for a in ref if a in tr]
        inverse = premieres != sorted(premieres)
        types = (["Étape sautée"] if sautees else []) + (["Reprise"] if repetees or extras else []) + (["Ordre inversé"] if inverse else [])
        lignes.append({"Cas": cas, "Aptitude": fitness, "Étapes sautées": sautees, "Reprises": repetees, "Ordre inversé": inverse,
                       "Écarts": types, "Conforme": not types})
    return pd.DataFrame(lignes).set_index("Cas")


def resume_ecarts(conf: pd.DataFrame) -> pd.DataFrame:
    """Nombre de cas par type d'écart, et détail des étapes sautées et des reprises."""
    lignes = [("Étape sautée", int(conf["Écarts"].apply(lambda e: "Étape sautée" in e).sum())), ("Reprise", int(conf["Écarts"].apply(lambda e: "Reprise" in e).sum())),
              ("Ordre inversé", int(conf["Écarts"].apply(lambda e: "Ordre inversé" in e).sum()))]
    return pd.DataFrame(lignes, columns=["Écart", "Cas"])


def detail_sautees(conf: pd.DataFrame) -> pd.Series:
    from collections import Counter
    return pd.Series(Counter(a for l in conf["Étapes sautées"] for a in l)).sort_values(ascending=False)


def goulots(arcs: pd.DataFrame, n: int = 5) -> pd.DataFrame:
    """Les transitions qui consomment le plus d'attente : fréquence x attente moyenne, hors arcs de reprise très rares."""
    a = arcs[arcs["Fréquence"] >= 5].copy()
    a["Part de l'attente (%)"] = a["Attente totale (h)"] / a["Attente totale (h)"].sum() * 100
    return a.sort_values("Attente totale (h)", ascending=False).head(n).reset_index(drop=True)


def separation_taches(log: pd.DataFrame, processus: str = ACHATS.nom) -> pd.DataFrame:
    """Cas où la même ressource a exécuté deux activités qui devraient être séparées (enregistrer puis approuver la facture)."""
    p = PROCESSUS[processus]
    if not p.sod:
        return pd.DataFrame(columns=["Cas", "Ressource", "Montant ($)"])
    a, b = p.sod
    x = log[log["Activité"] == a][["Cas", "Ressource"]].merge(log[log["Activité"] == b][["Cas", "Ressource", "Montant ($)"]], on=["Cas", "Ressource"])
    return x.drop_duplicates("Cas").reset_index(drop=True)


def cout_reprises(log: pd.DataFrame, processus: str = ACHATS.nom) -> dict:
    """Coût des événements de reprise du journal, puis annualisé ; la moitié évitable est l'économie visée d'un paquet d'automatisation."""
    p = PROCESSUS[processus]
    n = log["Activité"].value_counts()
    detail = pd.DataFrame([(a, int(n.get(a, 0)), c, n.get(a, 0) * c) for a, c in p.cout_evenement.items()], columns=["Événement de reprise", "Nombre", "Coût unitaire ($)", "Coût ($)"])
    periode = float(detail["Coût ($)"].sum())
    annuel = periode / log["Cas"].nunique() * p.cas_annuels          # coût de reprise par cas du journal x cas traités en un an
    return {"detail": detail, "periode": periode, "annuel": annuel, "annuel_k": annuel / 1000, "evitable_k": annuel / 2000}


def statistiques(log: pd.DataFrame, processus: str = ACHATS.nom) -> dict:
    d = durees_cas(log)
    c = conformite(log, processus)
    v = variantes(log, processus)
    return {"cas": int(len(d)), "evenements": int(len(log)), "activites": int(log["Activité"].nunique()), "variantes": int(len(v)),
            "duree_mediane": float(d["Durée (j)"].median()), "duree_p90": float(d["Durée (j)"].quantile(0.9)), "conformes": float(c["Conforme"].mean() * 100),
            "aptitude": float(c["Aptitude"].mean()), "top3": float(v["Part (%)"].head(3).sum())}
