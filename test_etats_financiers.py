"""Tests des états financiers dynamiques : identités comptables, sensibilité aux paramètres, présentation et export Excel."""
import io
import os
import random
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import etats_financiers as ef

DB = "tresorerie.db"
j = ef.lire_journal(DB)
p0 = ef.parametres_par_defaut(j)
res0 = ef.calculer(j, p0)
AN = j.annees[-1]

# 1. identités comptables avec les paramètres par défaut, tous les exercices
bad = [v for v in ef.verifications(res0) if not v["ok"]]
assert not bad, bad
assert j.annees == [2023, 2024, 2025, 2026], j.annees
print(f"1 OK {len(ef.verifications(res0))} contrôles comptables sur {len(j.annees)} exercices (écart max {max(abs(v['ecart']) for v in ef.verifications(res0)):.6f} $)")

# 2. les identités tiennent pour n'importe quelle combinaison de paramètres (200 tirages aléatoires)
rng = random.Random(7)
for _ in range(200):
    p = p0.modifie(var_ventes=rng.uniform(-.3, .3), var_cout_produits=rng.uniform(-.3, .3), var_charges=rng.uniform(-.3, .3),
                   var_taux=rng.uniform(-.5, .5), annee_scenario=rng.choice(j.annees), dso=rng.uniform(0, 120), dio=rng.uniform(0, 90),
                   dpo=rng.uniform(0, 120), capex=rng.uniform(0, 2e6), taux_amort=rng.uniform(0, .4), taux_impot=rng.uniform(0, .5),
                   impot_impaye=rng.uniform(0, 1), dividendes_pct=rng.uniform(0, 1), emission_actions=rng.choice([0, 1e5, 5e5]),
                   tirages_marge_pct=rng.uniform(0, 1.5), part_interets_bdc=rng.uniform(0, .6), bdc_ouverture=rng.choice([0, 2e5, 1e6, 5e6]),
                   encaisse_ouverture=rng.uniform(0, 2e6))
    mauvais = [v for v in ef.verifications(ef.calculer(j, p)) if not v["ok"]]
    assert not mauvais, (p, mauvais[:2])
print("2 OK 200 combinaisons aléatoires de paramètres : le bilan s'équilibre et les trois états restent liés")

# 3. le résultat reflète le journal, et le scénario ne touche que les exercices visés
ventes_db = sqlite3.connect(DB).execute("SELECT SUM(montant) FROM journal_general WHERE annee=? AND nature='Revenu' AND categorie IN "
                                        "(SELECT categorie FROM categories WHERE ordre BETWEEN 20 AND 23)", (AN,)).fetchone()[0]
assert abs(res0["annees"][AN]["resultats"]["total_ventes"] - ventes_db) < 0.01
plus = ef.calculer(j, p0.modifie(var_ventes=0.10))
assert abs(plus["annees"][AN]["resultats"]["total_ventes"] - 1.10 * ventes_db) < 0.01
assert plus["annees"][AN - 1]["resultats"] == res0["annees"][AN - 1]["resultats"], "l'exercice précédent ne doit pas changer"
tout = ef.calculer(j, p0.modifie(var_ventes=0.10, annee_scenario=j.annees[0]))
assert tout["annees"][2023]["resultats"]["total_ventes"] > res0["annees"][2023]["resultats"]["total_ventes"]
assert plus["annees"][AN]["resultats"]["net"] > res0["annees"][AN]["resultats"]["net"]
print("3 OK ventes = journal ; +10 % de ventes touche l'exercice du scénario seulement (ou tous si on le demande)")

# 4. effets attendus des hypothèses
lent = ef.calculer(j, p0.modifie(dso=90))
assert abs(lent["annees"][AN]["resultats"]["net"] - res0["annees"][AN]["resultats"]["net"]) < 0.01, "les jours de créances ne changent pas le résultat"
assert lent["annees"][AN]["flux"]["exploitation"] < res0["annees"][AN]["flux"]["exploitation"], "…mais ils absorbent de la trésorerie"
assert lent["annees"][AN]["bilan"]["clients"] > res0["annees"][AN]["bilan"]["clients"]
sans_div = ef.calculer(j, p0.modifie(dividendes_pct=0.0))
assert sans_div["annees"][AN]["bilan"]["bnr"] > res0["annees"][AN]["bilan"]["bnr"]
assert sans_div["annees"][AN]["bilan"]["encaisse"] > res0["annees"][AN]["bilan"]["encaisse"]
gros_capex = ef.calculer(j, p0.modifie(capex=2_000_000))
assert gros_capex["annees"][AN]["resultats"]["amortissement"] > res0["annees"][AN]["resultats"]["amortissement"]
assert gros_capex["annees"][AN]["bilan"]["immobilisations"] > res0["annees"][AN]["bilan"]["immobilisations"]
exo = ef.calculer(j, p0.modifie(taux_impot=0.0))
assert exo["annees"][AN]["resultats"]["impot"] == 0 and exo["annees"][AN]["resultats"]["net"] > res0["annees"][AN]["resultats"]["net"]
print("4 OK créances, dividendes, investissements et impôts jouent dans le bon sens")

# 5. alertes (marge au-delà de la limite, perte)
alertes = ef.calculer(j, p0.modifie(tirages_marge_pct=1.5))
assert any("limite" in a for e in alertes["annees"].values() for a in e["alertes"])
perte = ef.calculer(j, p0.modifie(var_ventes=-0.5))
assert any("perte" in a for a in perte["annees"][AN]["alertes"]) and not [v for v in ef.verifications(perte) if not v["ok"]]
print("5 OK alertes : dépassement de la marge, perte sans impôt")

# 6. présentation et export Excel
pres = ef.presenter(res0, j, AN)
assert set(pres) == {"resultats", "bilan", "flux", "capitaux"} and all(len(v) > 8 for v in pres.values())
total_actif = next(v for s, l, v in pres["bilan"] if l == "Total de l'actif")
total_pc = next(v for s, l, v in pres["bilan"] if l == "Total du passif et des capitaux propres")
assert all(abs(a - b) < 0.01 for a, b in zip(total_actif, total_pc))
premier = ef.presenter(res0, j, j.annees[0])
assert next(v for s, l, v in premier["bilan"] if l == "Encaisse")[1] == res0["ouverture"]["encaisse"], "comparatif du 1er exercice = bilan d'ouverture"
from openpyxl import load_workbook
wb = load_workbook(io.BytesIO(ef.classeur_excel(res0, j, AN)))
assert wb.sheetnames == ["Résultats", "Bilan", "Flux de trésorerie", "Capitaux propres", "Balance de vérification", "Hypothèses"], wb.sheetnames
print("6 OK présentation (comparatif, bilan d'ouverture) et classeur Excel")

# 7. balance de vérification comptable : équilibrée pour tous les exercices et toutes les hypothèses, avec un compte par poste
for an in j.annees:
    bv = ef.balance_de_verification(res0, j, an)
    assert bv["equilibre"] and abs(bv["total_debit"] - bv["total_credit"]) < 0.01, (an, bv["ecart"])
    assert len({l["numero"] for l in bv["lignes"]}) == len(bv["lignes"]), "numéros de compte uniques"
    assert {"Actif", "Passif", "Capitaux propres", "Produits", "Charges"} == {l["groupe"] for l in bv["lignes"]}
dividende = next(l for l in ef.balance_de_verification(res0, j, AN)["lignes"] if l["numero"] == "3200")
assert dividende["debit"] > 0 and dividende["credit"] == 0, "les dividendes sont un débit"
rng2 = random.Random(11)
for _ in range(100):
    p = p0.modifie(var_ventes=rng2.uniform(-.4, .4), dso=rng2.uniform(0, 120), capex=rng2.uniform(0, 2e6), dividendes_pct=rng2.uniform(0, 1),
                   taux_impot=rng2.uniform(0, .5), emission_actions=rng2.choice([0, 3e5]), tirages_marge_pct=rng2.uniform(0, 1.5))
    rr = ef.calculer(j, p)
    assert all(ef.balance_de_verification(rr, j, an)["equilibre"] for an in j.annees)
print("7 OK balance de vérification équilibrée (4 exercices, 100 combinaisons de paramètres)")

ind = ef.indicateurs(res0["annees"][AN])
print(f"   FY{AN} : produits {res0['annees'][AN]['resultats']['revenus']:,.0f} $, BAIIA {ind['BAIIA (%)']:.1f} %, résultat net "
      f"{res0['annees'][AN]['resultats']['net']:,.0f} $, encaisse {res0['annees'][AN]['bilan']['encaisse']:,.0f} $, liquidité {ind['Liquidité générale (x)']:.2f}")
print("TOUS LES TESTS ÉTATS FINANCIERS OK")
