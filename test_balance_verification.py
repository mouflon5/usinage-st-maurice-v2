"""Test de la balance de vérification du journal et de son intégration aux rapports A7 (classeur Excel et brouillon R0)."""
import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["LLM_MODE"] = "simule"
import balance_verification as bv

DB = "tresorerie.db"

# 1. identités sur une période réelle
b = bv.balance_journal(DB, "2026-09")
assert b["lignes"] and all(c["ok"] for c in b["controles"]), b["controles"]
t = b["totaux"]
net_db = sqlite3.connect(DB).execute("SELECT SUM(montant) FROM journal_general WHERE substr(date_ecriture,1,7)='2026-09'").fetchone()[0]
assert abs(t["net"] - net_db) < 0.01 and abs((t["credit"] - t["debit"]) - net_db) < 0.01
assert t["nb"] == sqlite3.connect(DB).execute("SELECT COUNT(*) FROM journal_general WHERE substr(date_ecriture,1,7)='2026-09'").fetchone()[0]
assert abs(t["net_cumul"] - sqlite3.connect(DB).execute(
    "SELECT SUM(montant) FROM journal_general WHERE substr(date_ecriture,1,7)<='2026-09' AND substr(date_ecriture,1,4)='2026'").fetchone()[0]) < 0.01
print(f"1 OK balance 2026-09 : {len(b['lignes'])} comptes, débits {t['debit']:,.0f} $, crédits {t['credit']:,.0f} $, net {t['net']:,.0f} $ ; contrôles OK")

# 2. une période sans écriture → balance vide mais valide
vide = bv.balance_journal(DB, "2019-01")
assert vide["lignes"] == [] and all(c["ok"] for c in vide["controles"])
print("2 OK période sans écriture")

# 3. intégration au rapport A7 : feuille Excel + section du brouillon R0
import a7_nodes
from openpyxl import load_workbook
sortie = tempfile.mkdtemp()
dossier = {"verdict": "approuve", "empreinte": "x", "controles": [], "ecarts": [], "commentaire": {}, "previsions": {}, "flux_net_prevu": {},
           "resume_a3": {}, "transactions": [], "mode_llm": "simule", "decision_humaine": {}, "alertes": [], "statut_pipeline": "complet",
           "db_path": DB}
etat = {"periode": "2026-09", "dossier": dossier, "dossier_sortie": sortie, "synthese": {"texte": "ok", "origine": "simule"}}
fichiers = a7_nodes.construire_excel_node(etat)["fichiers"]
wb = load_workbook(fichiers[0])
assert "Balance de vérification" in wb.sheetnames, wb.sheetnames
ws = wb["Balance de vérification"]
valeurs = [[c.value for c in row] for row in ws.iter_rows()]
total = next(r for r in valeurs if r[0] == "TOTAL")
assert abs(total[3] - t["debit"]) < 0.01 and abs(total[4] - t["credit"]) < 0.01
assert any(r[0] and "Débits − crédits" in str(r[0]) and r[1] == "OK" for r in valeurs)
a7_nodes.construire_r0_node({**etat, "fichiers": fichiers})
r0 = open(os.path.join(sortie, "R0_2026-09.md"), encoding="utf-8").read()
assert "## Balance de vérification du journal" in r0 and "tous OK" in r0
# sans base : la feuille le dit, le rapport ne plante pas
etat2 = {**etat, "dossier": {**dossier, "db_path": None}, "dossier_sortie": tempfile.mkdtemp()}
wb2 = load_workbook(a7_nodes.construire_excel_node(etat2)["fichiers"][0])
assert "indisponible" in wb2["Balance de vérification"]["A1"].value
print("3 OK rapport A7 : feuille « Balance de vérification » dans le classeur et section dans R0 ; dégradation propre sans base")
print("TOUS LES TESTS BALANCE DE VÉRIFICATION OK")
