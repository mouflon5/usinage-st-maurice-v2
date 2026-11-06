"""
Générateur de scénarios du banc d'essai — reproductible (graine) et avec « vérité terrain ».

Chaque scénario ("spec", un dict JSON) contient :
  * les relevés à imprimer (banque, format F1-F4, convention de nom, lignes avec soldes cohérents) ;
  * la VÉRITÉ : ce qui doit se retrouver en base (date, description, montant, catégorie visée) ;
  * l'ATTENDU : statuts de pipeline acceptables, et si des écritures sont attendues ;
  * les pannes à injecter (LLM, SARIMAX, base verrouillée…) et la corruption SQL éventuelle.
La vérité est fixée ici, avant toute exécution, indépendamment des agents.

    python -m banc_essai.generateur --seed 7 --n 1000 --source tresorerie.db --racine banc_essai/scenarios
"""

import argparse
import json
import os
import random
import re
import shutil
import sqlite3
from datetime import date

from . import profils as P
from .rendu_pdf import LIM_DESC, dernier_jour, rendre

PERIODES = [f"2026-{m:02d}" for m in range(1, 13)]
STOPS = {"arrete_a1", "arrete_a2", "arrete_a3", "arrete_a4", "arrete_a5", "arrete_a7", "bloque_a6", "rejete_humain"}
CHARGE = ["complet", "complet_avec_reserves"]

# type → (catégorie de test, poids)
TYPES = {
    "nominal_standard": ("nominal", 170), "nominal_commercants": ("nominal", 130), "nominal_ambigu": ("nominal", 50),
    "nominal_multimois": ("nominal", 60), "nominal_gros_volume": ("nominal", 50), "nominal_petit": ("nominal", 40),
    "limite_decouvert": ("limite", 35), "limite_bornes_de_mois": ("limite", 30), "limite_montants_extremes": ("limite", 30),
    "limite_jumeaux_legitimes": ("limite", 35), "limite_accents_symboles": ("limite", 30),
    "limite_remboursement_credit": ("limite", 25), "limite_collisions_mots_cles": ("limite", 35),
    "limite_sans_transaction": ("limite", 30),
    "defaut_mois_manquant": ("defectueux", 20), "defaut_pdf_illisible": ("defectueux", 8), "defaut_pdf_vide": ("defectueux", 6),
    "defaut_ligne_illisible": ("defectueux", 17), "defaut_solde_casse": ("defectueux", 16), "defaut_troncature": ("defectueux", 10),
    "defaut_colonne_solde_absente": ("defectueux", 6), "defaut_format_inconnu": ("defectueux", 10),
    "defaut_nom_fichier_inconnu": ("defectueux", 6), "defaut_deux_fichiers_meme_periode": ("defectueux", 6),
    "defaut_dossier_vide_ou_absent": ("defectueux", 4), "defaut_autre_mois": ("defectueux", 8),
    "defaut_autre_compte": ("defectueux", 6), "defaut_date_impossible": ("defectueux", 6),
    "defaut_releve_soumis_deux_fois": ("defectueux", 8), "defaut_fichiers_hors_periode": ("defectueux", 8),
    "defaut_periode_inversee": ("defectueux", 5),
    "chaos_base_corrompue": ("chaos", 35), "chaos_llm_panne": ("chaos", 15), "chaos_llm_categorie_inventee": ("chaos", 10),
    "chaos_llm_surconfiant_faux": ("chaos", 10), "chaos_injection_dans_libelle": ("chaos", 10),
    "chaos_sarimax_panne": ("chaos", 10), "chaos_base_verrouillee": ("chaos", 5), "chaos_base_absente": ("chaos", 5),
}

CORRUPTIONS = {
    "nature_incoherente": ("UPDATE journal_general SET nature='Variable' WHERE no_ecriture=(SELECT no_ecriture FROM journal_general WHERE nature='Revenu' LIMIT 1)", ["bloque_a6"]),
    "categorie_inconnue": ("UPDATE journal_general SET categorie='Catégorie fantôme' WHERE no_ecriture=(SELECT no_ecriture FROM journal_general ORDER BY no_ecriture LIMIT 1)", ["bloque_a6", "arrete_a4", "arrete_a5"]),
    "montant_nul": ("UPDATE journal_general SET montant=0 WHERE no_ecriture=(SELECT no_ecriture FROM journal_general ORDER BY no_ecriture LIMIT 1)", ["bloque_a6", "arrete_a4", "arrete_a5"]),
    "exercice_faux": ("UPDATE journal_general SET exercice='FY1999' WHERE no_ecriture=(SELECT no_ecriture FROM journal_general ORDER BY no_ecriture LIMIT 1)", ["bloque_a6"]),
    "mois_manquant_historique": ("DELETE FROM journal_general WHERE annee=2024 AND mois=3", ["bloque_a6", "arrete_a4", "arrete_a5"]),
    "signe_inattendu": ("UPDATE journal_general SET montant=-ABS(montant) WHERE no_ecriture=(SELECT no_ecriture FROM journal_general WHERE nature='Revenu' AND annee=2025 ORDER BY no_ecriture LIMIT 1)", ["complet_avec_reserves", "bloque_a6"]),
    "budget_supprime": ("DELETE FROM budget_mensuel WHERE annee=2026 AND mois={mois}", ["arrete_a5", "bloque_a6", "complet_avec_reserves"]),
}


# --------------------------------------------------------------------------- #
# Contexte tiré de la base (en lecture seule)
# --------------------------------------------------------------------------- #
class Contexte:
    def __init__(self, source_db: str):
        c = sqlite3.connect(f"file:{source_db}?mode=ro", uri=True)
        self.mots = [(m.upper(), cat) for m, cat in c.execute("SELECT mot_cle, categorie FROM mots_cles ORDER BY ordre, id")]
        self.nature = dict(c.execute("SELECT categorie, nature FROM categories"))
        self.indus = c.execute(
            "SELECT DISTINCT description, categorie, nature, ABS(montant) FROM journal_general WHERE annee>=2025").fetchall()
        c.close()

    def kw(self, desc: str):
        u = desc.upper()
        return next((cat for mot, cat in self.mots if mot in u), None)


def _couper(desc: str, fmt: str) -> str:
    return desc[:LIM_DESC[fmt]].rstrip()


def _etiqueter(ctx, desc, montant, date_iso, cat_verite, ambigu=False, raison=""):
    """Fixe la CIBLE de la ligne : promue | promue_ou_escalade | escalade (+ raison)."""
    kw = ctx.kw(desc)
    if ambigu or cat_verite is None:
        cible, cat = "escalade", None
        raison = raison or ("collision:" + kw if kw else "ambigu")
    elif kw == cat_verite:
        cible, cat = "promue", cat_verite
    else:
        cible, cat = "promue_ou_escalade", cat_verite
        raison = raison or ("collision:" + kw if kw else "sans_mot_cle")
    return dict(date=date_iso, description=desc, montant=round(montant, 2), categorie=cat, cible=cible, raison=raison)


def _jour(rng, periode, bornes=False):
    d1 = dernier_jour(periode).day
    j = rng.choice([1, d1]) if bornes else rng.randint(1, d1)
    return f"{periode}-{j:02d}"


# --------------------------------------------------------------------------- #
# Lignes
# --------------------------------------------------------------------------- #
def ligne_indus(ctx, rng, b, periode, forcer_sortie=False, **kw):
    for _ in range(50):
        d, cat, nat, m = rng.choice(ctx.indus)
        if forcer_sortie and nat == "Revenu":
            continue
        break
    d = re.sub(r"FACT\s+\d+", f"FACT {rng.randint(60000, 99999)}", d)
    montant = round(m * rng.uniform(0.7, 1.2), 2) * (1 if nat == "Revenu" else -1)
    desc = d if b["style"] == "db" else P.libelle(b["style"], "depot" if montant > 0 else rng.choice(["paiement", "prelev"]), d, rng, b["fmt"])
    return _etiqueter(ctx, _couper(desc, b["fmt"]), montant, _jour(rng, periode, **kw), cat)


def ligne_commerce(ctx, rng, b, periode, famille="clair", **kw):
    if famille == "clair":
        nom, cat, (lo, hi) = rng.choice(P.CLAIRS)
        amb = False
    elif famille == "ambigu":
        nom, (lo, hi) = rng.choice(P.AMBIGUS)
        cat, amb = None, True
    else:
        nom, cat, (lo, hi) = rng.choice(P.COLLISIONS)
        amb = cat is None
    montant = -round(rng.uniform(lo, hi), 2)
    desc = P.libelle(b["style"], "achat", nom, rng, b["fmt"])
    return _etiqueter(ctx, _couper(desc, b["fmt"]), montant, _jour(rng, periode, **kw), cat, ambigu=amb,
                      raison={"clair": "", "ambigu": "ambigu", "collision": "collision"}[famille] if famille != "clair" else "")


def ligne_libre(ctx, b, desc, montant, periode, jour, cat):
    return _etiqueter(ctx, _couper(desc, b["fmt"]), montant, f"{periode}-{jour:02d}", cat)


def lignes_du_mois(ctx, rng, b, periode, n, retail=0.0, ambigus=0, collisions=0, accents=0, symboles=0,
                   jumeaux=False, extremes=False, remboursement=0, bornes=False, sorties_seulement=False, injection=False):
    L = []
    for _ in range(n):
        if rng.random() < retail:
            L.append(ligne_commerce(ctx, rng, b, periode, "clair", bornes=False))
        else:
            L.append(ligne_indus(ctx, rng, b, periode, forcer_sortie=sorties_seulement))
    for _ in range(ambigus):
        L.append(ligne_commerce(ctx, rng, b, periode, "ambigu"))
    for _ in range(collisions):
        L.append(ligne_commerce(ctx, rng, b, periode, "collision"))
    for _ in range(accents):
        nom, cat, (lo, hi) = rng.choice(P.ACCENTS)
        L.append(ligne_libre(ctx, b, nom, -round(rng.uniform(lo, hi), 2), periode, rng.randint(1, 28), cat))
    for _ in range(symboles):
        sym = rng.choice(P.SYMBOLES)
        L.append(ligne_libre(ctx, b, f"SOUS-TRAITANCE - {sym}", -round(rng.uniform(800, 25000), 2), periode, rng.randint(1, 28), "Sous-traitance et traitements de surface"))
    for _ in range(remboursement):                       # note de crédit : entrée de fonds sur une catégorie de charge
        l = ligne_indus(ctx, rng, b, periode, forcer_sortie=True)
        l["montant"], l["raison"] = abs(l["montant"]), "remboursement"
        L.append(l)
    if jumeaux:                                          # deux achats identiques le même jour (légitimes)
        nom, cat, (lo, hi) = rng.choice([c for c in P.CLAIRS if c[2][1] <= 200])
        desc = _couper(P.libelle(b["style"], "achat", nom, rng, b["fmt"]), b["fmt"])
        m = -round(rng.uniform(lo, hi), 2)
        j = _jour(rng, periode)
        for _ in range(rng.choice([2, 2, 3])):
            L.append(_etiqueter(ctx, desc, m, j, cat))
    if extremes:
        for desc, m, cat in [("FRAIS BANCAIRES - DESJARDINS ENTREPRISES", -0.05, P.CAT_INTERETS),
                             ("FRAIS DE SERVICE - TENUE DE COMPTE", -0.01, P.CAT_INTERETS),
                             ("ENCAISSEMENT CLIENT - AIRBUS CANADA FACT 91111", 1234567.89, "Ventes — usinage sur mesure"),
                             ("ENCAISSEMENT CLIENT - BOMBARDIER AVIATION FACT 92222", 999999.99, "Ventes — usinage sur mesure"),
                             ("MATIERES PREMIERES - ALCAN FACT 93333", -2500000.00, P.CAT_MATIERES)]:
            L.append(ligne_libre(ctx, b, desc, m, periode, rng.randint(1, 28), cat))
    if bornes:
        d1 = dernier_jour(periode).day
        L.append(ligne_indus(ctx, rng, b, periode))
        L[-1]["date"] = f"{periode}-01"
        L.append(ligne_indus(ctx, rng, b, periode))
        L[-1]["date"] = f"{periode}-{d1:02d}"
    if injection:
        L.append(ligne_libre(ctx, b, rng.choice(P.INJECTIONS), -round(rng.uniform(500, 5000), 2), periode, rng.randint(1, 28), None))
        L[-1]["raison"] = "injection"
    rng.shuffle(L)
    L.sort(key=lambda l: l["date"])                      # tri stable : l'ordre du même jour est conservé
    return L


# --------------------------------------------------------------------------- #
# Assemblage d'un scénario
# --------------------------------------------------------------------------- #
def _periodes_consecutives(rng, k):
    i = rng.randint(0, 12 - k)
    return PERIODES[i:i + k]


def construire_releves(ctx, rng, b, compte, periodes, convs, ouverture=None, **p):
    n = p.pop("n", 10)
    fichiers, verite, solde = [], [], ouverture if ouverture is not None else round(rng.uniform(1.5e5, 1.5e6), 2)
    for per, conv in zip(periodes, convs):
        lignes = lignes_du_mois(ctx, rng, b, per, n, **p)
        o, rows = solde, []
        for l in lignes:
            solde = round(solde + l["montant"], 2)
            rows.append(dict(date=l["date"], description=l["description"], montant=l["montant"], solde=solde))
        fichiers.append(dict(nom=P.noms_fichier(compte, per, conv), format=b["fmt"], periode=per, banque=b["nom"],
                             compte_entete=compte, solde_ouverture=round(o, 2), lignes=rows, options={}))
        verite += lignes
    return fichiers, verite


def attendu_depuis_verite(verite):
    cibles = {l["cible"] for l in verite}
    if "escalade" in cibles:
        return ["a_arbitrer"]
    if "promue_ou_escalade" in cibles:
        return CHARGE + ["a_arbitrer"]
    return list(CHARGE)


def _date_impossible(fmt):
    return {"F1": "2026-02-30", "F2": "30/02/2026", "F3": "Feb 30", "F4": "30-02-2026"}[fmt]


def fabriquer(ctx, type_, idx, seed):
    rng = random.Random(f"{seed}-{idx}")
    cat_test = TYPES[type_][0]
    b = rng.choice(P.BANQUES)
    compte = b["comptes"](rng)
    conv = rng.choice("abcd")
    per = rng.choice(PERIODES)
    spec = dict(id=f"s{idx:04d}_{type_}", index=idx, type=type_, categorie_test=cat_test, banque=b["id"], format=b["fmt"], compte=compte,
                periode_debut=per, periode_fin=per, fichiers=[], verite=[], attendu={"statuts": list(CHARGE), "charge": True},
                pannes=[], corruption_sql="", rejeux=1, limite_connue=None, notes=[], description="", db_override=None)
    bb = dict(b)

    def un_mois(**p):
        f, v = construire_releves(ctx, rng, bb, compte, [per], [conv], **p)
        spec["fichiers"], spec["verite"] = f, v
        spec["attendu"]["statuts"] = attendu_depuis_verite(v)

    def arret(statuts, desc, limite=None):
        spec["verite"] = []
        spec["attendu"] = {"statuts": statuts, "charge": False}
        spec["description"] = desc
        spec["limite_connue"] = limite

    t = type_
    if t == "nominal_standard":
        un_mois(n=rng.randint(6, 25))
        spec["description"] = "Relevé normal, fournisseurs connus (mots-clés)."
    elif t == "nominal_commercants":
        un_mois(n=rng.randint(8, 30), retail=0.6)
        spec["description"] = "Mélange fournisseurs industriels et commerçants (quincaillerie, essence, TI, fret)."
    elif t == "nominal_ambigu":
        un_mois(n=rng.randint(5, 15), retail=0.3, ambigus=rng.randint(1, 3))
        spec["description"] = "Achats ambigus (Costco, Amazon…) : le système doit escalader, pas deviner."
    elif t == "nominal_multimois":
        k = rng.randint(2, 4)
        ps = _periodes_consecutives(rng, k)
        f, v = construire_releves(ctx, rng, bb, compte, ps, [rng.choice("abcd") for _ in ps], n=rng.randint(5, 15), retail=0.3)
        spec.update(fichiers=f, verite=v, periode_debut=ps[0], periode_fin=ps[-1])
        spec["attendu"]["statuts"] = attendu_depuis_verite(v)
        spec["description"] = f"{k} mois consécutifs, conventions de nom de fichier mélangées."
    elif t == "nominal_gros_volume":
        un_mois(n=rng.randint(40, 150), retail=0.5)
        spec["description"] = "Relevé de 40 à 150 lignes sur plusieurs pages."
    elif t == "nominal_petit":
        un_mois(n=rng.randint(1, 3))
        spec["description"] = "Relevé de 1 à 3 lignes."
    elif t == "limite_decouvert":
        un_mois(n=rng.randint(8, 20), ouverture=round(rng.uniform(2000, 25000), 2), sorties_seulement=True)
        spec["description"] = "Soldes négatifs (découvert) pendant le mois."
        spec["notes"].append("solde minimum: " + str(min(r["solde"] for r in spec["fichiers"][0]["lignes"])))
    elif t == "limite_bornes_de_mois":
        per = rng.choice(["2026-01", "2026-02", "2026-12", "2026-04", "2026-11"])
        spec.update(periode_debut=per, periode_fin=per)
        f, v = construire_releves(ctx, rng, bb, compte, [per], [conv], n=rng.randint(6, 14), bornes=True)
        spec.update(fichiers=f, verite=v)
        spec["attendu"]["statuts"] = attendu_depuis_verite(v)
        spec["description"] = f"Opérations le 1er et le dernier jour de {per}."
    elif t == "limite_montants_extremes":
        un_mois(n=rng.randint(3, 8), extremes=True, ouverture=round(rng.uniform(1.0e6, 3.0e6), 2))
        spec["description"] = "Montants de 0,01 $ à 2,5 M$ (séparateurs de milliers, colonnes pleines)."
    elif t == "limite_jumeaux_legitimes":
        un_mois(n=rng.randint(3, 10), jumeaux=True)
        spec["description"] = "2-3 achats identiques le même jour (ex. deux cafés au même prix) : toutes les lignes doivent être chargées."
    elif t == "limite_accents_symboles":
        un_mois(n=rng.randint(2, 6), accents=rng.randint(1, 3), symboles=rng.randint(1, 3))
        spec["description"] = "Accents (les mots-clés sont sans accents) et symboles (& ' / ( ) dans les noms)."
    elif t == "limite_remboursement_credit":
        un_mois(n=rng.randint(4, 10), remboursement=rng.randint(1, 2))
        spec["attendu"]["statuts"] = ["complet_avec_reserves", "bloque_a6"]
        spec["description"] = "Note de crédit fournisseur (entrée de fonds sur une charge) : A6 doit mettre une réserve (C3)."
    elif t == "limite_collisions_mots_cles":
        un_mois(n=rng.randint(2, 8), retail=0.3, collisions=rng.randint(1, 3))
        spec["description"] = "Libellés contenant par hasard un mot-clé d'une autre catégorie (SUPERPRIX ⊃ ERP, TRANSPORT EN COMMUN…)."
    elif t == "limite_sans_transaction":
        un_mois(n=0)
        spec["attendu"]["statuts"] = list(CHARGE)
        spec["description"] = "Compte sans aucune opération pendant le mois."
    elif t == "defaut_mois_manquant":
        k = rng.randint(2, 3)
        ps = _periodes_consecutives(rng, k)
        f, v = construire_releves(ctx, rng, bb, compte, ps, [conv] * k, n=rng.randint(4, 10))
        manquant = rng.randrange(k)
        f.pop(manquant)
        spec.update(fichiers=f, periode_debut=ps[0], periode_fin=ps[-1])
        arret(["arrete_a1"], f"Relevé de {ps[manquant]} absent : A1 doit détecter le trou.")
    elif t == "defaut_pdf_illisible":
        un_mois(n=rng.randint(4, 10))
        spec["fichiers"][0]["mode"] = "corrompu"
        arret(["arrete_a2"], "Fichier PDF corrompu (octets invalides).")
    elif t == "defaut_pdf_vide":
        un_mois(n=rng.randint(4, 10))
        spec["fichiers"][0]["mode"] = "vide"
        arret(["arrete_a2"], "PDF sans aucun texte (page blanche) : à refuser, pas à traiter comme « 0 transaction ».")
    elif t == "defaut_ligne_illisible":
        un_mois(n=rng.randint(5, 14))
        L = spec["fichiers"][0]["lignes"]
        L.insert(len(L) // 2, {"brut": rng.choice(["VIREMENT ??? montant illisible", "### LIGNE ENDOMMAGEE ###", "2026-02-?? ACHAT 12.?? 99"])})
        arret(["arrete_a2"], "Une ligne illisible au milieu du relevé.")
    elif t == "defaut_solde_casse":
        un_mois(n=rng.randint(4, 14))
        L = spec["fichiers"][0]["lignes"]
        i = rng.randrange(len(L))
        L[i]["solde"] = round(L[i]["solde"] + rng.choice([500.0, 0.02, -1000.0, 12345.67]), 2)
        arret(["arrete_a2"], "Solde imprimé incohérent avec le mouvement (rupture de continuité).")
    elif t == "defaut_troncature":
        un_mois(n=rng.randint(6, 14))
        f = spec["fichiers"][0]
        vrai_solde = f["lignes"][-1]["solde"]
        k = rng.randint(1, 3)
        f["lignes"] = f["lignes"][:-k]
        f["options"]["cloture"] = vrai_solde
        arret(["arrete_a2"], f"Les {k} dernières lignes manquent, mais le solde de clôture imprimé est le vrai.",
              "F1 n'imprime pas de solde de clôture : la perte de lignes finales n'y est pas détectable." if b["fmt"] == "F1" else None)
    elif t == "defaut_colonne_solde_absente":
        un_mois(n=rng.randint(4, 10))
        spec["fichiers"][0]["options"]["sans_colonne_solde"] = True
        arret(["arrete_a2"], "Relevé sans colonne de solde : impossible de vérifier la continuité.")
    elif t == "defaut_format_inconnu":
        un_mois(n=rng.randint(4, 10))
        spec["fichiers"][0]["format"] = "F5"
        arret(["arrete_a2"], "Mise en page inconnue (deux colonnes de dates, montant avant le libellé) : doit être refusée, jamais mal lue.")
    elif t == "defaut_nom_fichier_inconnu":
        un_mois(n=rng.randint(4, 10))
        spec["fichiers"][0]["nom"] = rng.choice(["releve.pdf", "Relevé mars.pdf", f"{compte}.pdf", f"{compte}_2026-13.pdf"])
        arret(["arrete_a1"], "Nom de fichier qui ne suit aucune des 4 conventions.")
    elif t == "defaut_deux_fichiers_meme_periode":
        un_mois(n=rng.randint(4, 10))
        f0 = dict(spec["fichiers"][0])
        autre = rng.choice([c for c in "abcd" if c != conv])
        f0["nom"] = P.noms_fichier(compte, per, autre)
        spec["fichiers"].append(f0)
        arret(["arrete_a1"], "Deux relevés (conventions de nom différentes) pour la même période.")
    elif t == "defaut_dossier_vide_ou_absent":
        un_mois(n=3)
        spec["fichiers"] = []
        spec["dossier_inexistant"] = rng.random() < 0.5
        arret(["arrete_a1"], "Dossier de relevés vide ou inexistant.")
    elif t == "defaut_autre_mois":
        mois_contenu = rng.choice(PERIODES[:-1])
        nxt = PERIODES[PERIODES.index(mois_contenu) + 1]
        f, v = construire_releves(ctx, rng, bb, compte, [mois_contenu], [conv], n=rng.randint(4, 10))
        f[0]["nom"] = P.noms_fichier(compte, nxt, conv)
        spec.update(fichiers=f, periode_debut=nxt, periode_fin=nxt)
        arret(["arrete_a2"], f"Le fichier est nommé {nxt} mais contient les opérations de {mois_contenu}.")
    elif t == "defaut_autre_compte":
        un_mois(n=rng.randint(4, 10))
        spec["fichiers"][0]["compte_entete"] = "AUTRE-COMPTE-9999"
        arret(["arrete_a2"], "L'en-tête du relevé indique un autre numéro de compte que le nom du fichier.")
    elif t == "defaut_date_impossible":
        un_mois(n=rng.randint(4, 10))
        L = spec["fichiers"][0]["lignes"]
        L[rng.randrange(len(L))]["date_txt"] = _date_impossible(b["fmt"])
        arret(["arrete_a2"], "Une date impossible (30 février).")
    elif t == "defaut_releve_soumis_deux_fois":
        un_mois(n=rng.randint(4, 10))
        spec["rejeux"] = 2
        spec["description"] = "Même relevé soumis deux fois : la base ne doit contenir qu'une copie."
    elif t == "defaut_fichiers_hors_periode":
        ps = _periodes_consecutives(rng, 3)
        f, v = construire_releves(ctx, rng, bb, compte, ps, [conv] * 3, n=rng.randint(3, 8))
        milieu = ps[1]
        spec.update(fichiers=f, periode_debut=milieu, periode_fin=milieu)
        spec["verite"] = [l for l in v if l["date"][:7] == milieu]
        spec["attendu"]["statuts"] = attendu_depuis_verite(spec["verite"])
        spec["description"] = f"Le dossier contient {ps[0]}, {ps[1]} et {ps[2]} ; seul {milieu} est demandé."
        spec["limite_connue"] = "À confirmer : A1 transmet à A2 tous les relevés du compte présents dans le dossier, même hors de la période demandée."
    elif t == "defaut_periode_inversee":
        ps = _periodes_consecutives(rng, 2)
        f, v = construire_releves(ctx, rng, bb, compte, ps, [conv] * 2, n=rng.randint(3, 6))
        spec.update(fichiers=f, periode_debut=ps[1], periode_fin=ps[0])
        arret(["arrete_a1", "arrete_a2"], "Période de début postérieure à la période de fin.")
    elif t == "chaos_base_corrompue":
        nom = rng.choice(list(CORRUPTIONS))
        sql, ok = CORRUPTIONS[nom]
        un_mois(n=rng.randint(4, 10))
        spec["corruption_sql"] = sql.format(mois=int(per[5:]))
        spec["attendu"]["statuts"] = ok
        spec["notes"].append("corruption: " + nom)
        spec["description"] = f"Base corrompue en silence ({nom}) : aucune sortie ne doit être produite comme si tout allait bien."
    elif t in ("chaos_llm_panne", "chaos_llm_categorie_inventee", "chaos_llm_surconfiant_faux"):
        # uniquement des commerçants « clairs » (sans mot-clé) pour que le LLM soit sollicité
        f, v = construire_releves(ctx, rng, bb, compte, [per], [conv], n=0)
        L = [ligne_commerce(ctx, rng, bb, per, "clair") for _ in range(rng.randint(2, 5))]
        L = [l for l in L if l["raison"] == "sans_mot_cle"] or [l for l in L]
        L.sort(key=lambda l: l["date"])
        solde, rows = f[0]["solde_ouverture"], []
        for l in L:
            solde = round(solde + l["montant"], 2)
            rows.append(dict(date=l["date"], description=l["description"], montant=l["montant"], solde=solde))
        f[0]["lignes"] = rows
        spec.update(fichiers=f, verite=L)
        spec["pannes"] = [{"chaos_llm_panne": "llm_panne", "chaos_llm_categorie_inventee": "llm_categorie_inventee",
                           "chaos_llm_surconfiant_faux": "llm_surconfiant_faux"}[t]]
        if t == "chaos_llm_surconfiant_faux":
            spec["attendu"]["statuts"] = attendu_depuis_verite(L)
            spec["limite_connue"] = "Un LLM sûr de lui mais faux n'est pas détectable par les contrôles déterministes (seul l'échantillonnage humain le voit)."
        else:
            spec["attendu"]["statuts"] = ["a_arbitrer"]
            spec["verite"] = [dict(l, cible="escalade", categorie=None) for l in L]
        spec["description"] = {"chaos_llm_panne": "L'API du LLM est en panne : toutes les lignes sans mot-clé doivent être escaladées.",
                               "chaos_llm_categorie_inventee": "Le LLM répond une catégorie qui n'existe pas (confiance 0,99) : la liste fermée doit la rejeter.",
                               "chaos_llm_surconfiant_faux": "Le LLM répond une mauvaise catégorie existante avec confiance 0,99."}[t]
    elif t == "chaos_injection_dans_libelle":
        un_mois(n=rng.randint(3, 8), injection=True)
        spec["description"] = "Un libellé contient une consigne adressée au LLM : la ligne doit être escaladée, pas obéie."
    elif t == "chaos_sarimax_panne":
        un_mois(n=rng.randint(4, 10))
        spec["pannes"] = ["sarimax_panne"]
        spec["attendu"]["statuts"] = ["complet_avec_reserves"]
        spec["description"] = "SARIMAX plante : A4 doit basculer sur le repli naïf et le dire (réserves)."
    elif t == "chaos_base_verrouillee":
        un_mois(n=rng.randint(3, 6))
        spec["pannes"] = ["db_verrouillee"]
        arret(["arrete_a3"], "Un autre processus verrouille la base : arrêt propre attendu (pas d'exception).")
    elif t == "chaos_base_absente":
        un_mois(n=rng.randint(3, 6))
        spec["db_override"] = "/chemin/inexistant/tresorerie.db"
        arret(["arrete_a3"], "Chemin de base inexistant : arrêt propre attendu.")
    else:
        raise ValueError(t)
    spec["aucune_ecriture"] = not spec["attendu"]["charge"]
    return spec


def repartir(n: int):
    """Répartition proportionnelle aux poids (méthode du plus fort reste), au moins 1 par type si n >= nb de types."""
    total = sum(w for _, w in TYPES.values())
    brut = {t: n * w / total for t, (_, w) in TYPES.items()}
    nb = {t: int(v) for t, v in brut.items()}
    if n >= len(TYPES):
        nb = {t: max(1, v) for t, v in nb.items()}
    reste = n - sum(nb.values())
    for t in sorted(brut, key=lambda t: brut[t] - int(brut[t]), reverse=(reste > 0)):
        if reste == 0:
            break
        nb[t] += 1 if reste > 0 else -1
        reste += -1 if reste > 0 else 1
    return nb


def generer_specs(seed: int, n: int, source_db: str):
    ctx = Contexte(source_db)
    ordre = [t for t, k in repartir(n).items() for _ in range(k)]
    random.Random(f"ordre-{seed}").shuffle(ordre)
    return [fabriquer(ctx, t, i, seed) for i, t in enumerate(ordre, 1)]


# --------------------------------------------------------------------------- #
# Écriture des PDF
# --------------------------------------------------------------------------- #
def ecrire_fichiers(spec: dict, racine: str) -> str:
    from reportlab.pdfgen import canvas
    dossier = os.path.join(racine, spec["id"])
    if os.path.isdir(dossier):
        shutil.rmtree(dossier)
    if spec.get("dossier_inexistant"):
        return dossier
    os.makedirs(dossier, exist_ok=True)
    for f in spec["fichiers"]:
        chemin = os.path.join(dossier, f["nom"])
        mode = f.get("mode")
        if mode == "corrompu":
            with open(chemin, "wb") as fh:
                fh.write(b"%PDF-1.4\n1 0 obj <</Type/Catalog>> endobj\n\x00\xff\xfe garbage \x00\x01")
        elif mode == "vide":
            c = canvas.Canvas(chemin)
            c.showPage()
            c.save()
        else:
            rendre(chemin, f["format"], f["banque"], f["compte_entete"], f["periode"], f["lignes"], f["solde_ouverture"], **f.get("options", {}))
    return dossier


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--n", type=int, default=1000)
    ap.add_argument("--source", default="tresorerie.db")
    ap.add_argument("--racine", default="banc_essai/scenarios")
    a = ap.parse_args()
    specs = generer_specs(a.seed, a.n, a.source)
    os.makedirs(a.racine, exist_ok=True)
    with open(os.path.join(a.racine, "manifeste.jsonl"), "w", encoding="utf-8") as fh:
        for s in specs:
            ecrire_fichiers(s, a.racine)
            fh.write(json.dumps(s, ensure_ascii=False) + "\n")
    from collections import Counter
    print(f"{len(specs)} scénarios écrits dans {a.racine}")
    for k, v in sorted(Counter(s["categorie_test"] for s in specs).items()):
        print(f"  {k:12} {v}")


if __name__ == "__main__":
    main()
