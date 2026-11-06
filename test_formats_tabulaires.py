"""Test de la lecture des relevés CSV / Excel : formats de nombres FR et EN, débit+crédit, rejet prudent, passage dans A2."""
import os, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pandas as pd

import a2_nodes
from formats_releves import analyser_nom_fichier, lire_releve, _nombre

d = tempfile.mkdtemp()

# 0. nombres
assert _nombre("1 234,50") == 1234.5 and _nombre("1,234.50") == 1234.5 and _nombre("(45.00)") == -45.0
assert _nombre("-45,00 $") == -45.0 and _nombre("1.234,50") == 1234.5 and _nombre("abc") is None and _nombre("") is None
assert analyser_nom_fichier("Desjardins EOP - 2026-10.csv") == ("Desjardins EOP", "2026-10", "b")
assert analyser_nom_fichier("Compte_202610.xlsx")[1] == "2026-10"
print("0 OK nombres et noms de fichier")

# 1. CSV français : point-virgule, virgule décimale, titre avant l'en-tête, montant signé
p1 = os.path.join(d, "Desjardins EOP - 2026-10.csv")
open(p1, "w", encoding="cp1252").write(
    "Relevé de compte;;;\n"
    "Date;Libellé;Montant;Solde\n"
    "2026-10-03;FACTURE USINAGE MARMEN;-1 200,00;8 800,00\n"
    "05/10/2026;DEPOT CLIENT ABC;2 500,50;11 300,50\n")
lec = lire_releve(p1)
assert lec.format == "CSV" and len(lec.transactions) == 2 and not lec.rejetees, (lec.format, lec.rejetees)
assert lec.transactions[1] == {"date": "2026-10-05", "description": "DEPOT CLIENT ABC", "montant": 2500.5, "solde": 11300.5}
print("1 OK CSV français")

# 2. Excel : colonnes Débit / Crédit
p2 = os.path.join(d, "Desjardins EOP_2026-10.xlsx")
pd.DataFrame({"Date": ["2026-10-03", "2026-10-07"], "Description": ["ACHAT QUINCAILLERIE", "VIREMENT CLIENT"],
              "Débit": ["120.00", ""], "Crédit": ["", "900.00"], "Solde": ["880.00", "1780.00"]}).to_excel(p2, index=False)
lec = lire_releve(p2)
assert lec.format == "XLSX" and [t["montant"] for t in lec.transactions] == [-120.0, 900.0], lec
print("2 OK Excel débit/crédit")

# 3. prudence : ligne illisible rejetée, colonne solde absente refusée, en-tête inconnu refusé
p3 = os.path.join(d, "Desjardins EOP - 2026-11.csv")
open(p3, "w", encoding="utf-8").write("Date,Description,Montant,Solde\n2026-11-02,OK,-10.00,90.00\nn'importe quoi,,,\n")
lec = lire_releve(p3)
assert len(lec.transactions) == 1 and len(lec.rejetees) == 1, lec
p4 = os.path.join(d, "Sans solde - 2026-10.csv")
open(p4, "w", encoding="utf-8").write("Date,Description,Montant\n2026-10-02,OK,-10.00\n")
lec = lire_releve(p4)
assert lec.format is None and "solde" in lec.rejetees[0], lec
p5 = os.path.join(d, "Inconnu - 2026-10.csv")
open(p5, "w", encoding="utf-8").write("a,b,c\n1,2,3\n")
assert lire_releve(p5).format is None
print("3 OK rejet prudent (ligne illisible, solde absent, en-tête inconnu)")

# 4. A2 : continuité des soldes vérifiée sur un CSV, anomalie détectée si elle est rompue
etat = {"fichiers_a_traiter": [p1]}
r = a2_nodes.extraire_node(etat)
assert len(r["transactions"]) == 2 and not r["anomalies_structure"] and not r["lignes_rejetees"], r
assert not a2_nodes.valider_coherence_node({"transactions": r["transactions"]})["anomalies_solde"]
cass = os.path.join(d, "Desjardins EOP - 2026-12.csv")
open(cass, "w", encoding="utf-8").write("Date,Description,Montant,Solde\n2026-12-02,A,-10.00,90.00\n2026-12-03,B,-10.00,500.00\n")
r = a2_nodes.extraire_node({"fichiers_a_traiter": [cass]})
assert a2_nodes.valider_coherence_node({"transactions": r["transactions"]})["anomalies_solde"], "le saut de solde doit être détecté"
print("4 OK A2 vérifie la continuité des soldes sur CSV")
