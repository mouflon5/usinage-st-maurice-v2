"""Crée une base SQLite de test avec le schéma exact de tresorerie.db (données synthétiques).
Sert aux tests automatiques d'A3 ; ta vraie base reste la source pour la démo."""
import sqlite3, sys, random

SCHEMA = """
CREATE TABLE parametres (domaine TEXT NOT NULL, cle TEXT NOT NULL, valeur TEXT NOT NULL, type_valeur TEXT NOT NULL, libelle TEXT, PRIMARY KEY (domaine, cle));
CREATE TABLE categories (categorie TEXT PRIMARY KEY, nature TEXT NOT NULL CHECK (nature IN ('Fixe','Variable','Financement','Revenu')), ordre INTEGER NOT NULL);
CREATE TABLE mots_cles (id INTEGER PRIMARY KEY AUTOINCREMENT, categorie TEXT NOT NULL REFERENCES categories(categorie), mot_cle TEXT NOT NULL, ordre INTEGER NOT NULL);
CREATE TABLE journal_general (no_ecriture TEXT PRIMARY KEY, date_ecriture TEXT NOT NULL, description TEXT NOT NULL, montant REAL NOT NULL, categorie TEXT NOT NULL REFERENCES categories(categorie), nature TEXT NOT NULL, mois INTEGER NOT NULL, annee INTEGER NOT NULL, compte_source TEXT NOT NULL, exercice TEXT NOT NULL);
CREATE TABLE journal_saisie (id INTEGER PRIMARY KEY AUTOINCREMENT, date_brute TEXT, description TEXT, montant_brut REAL, compte_source TEXT, date_valide TEXT, categorie TEXT, nature TEXT, mois INTEGER, cle_doublon TEXT, est_doublon INTEGER DEFAULT 0, statut TEXT);
"""
CATS = [("Loyer","Fixe"),("Électricité","Fixe"),("Salaires","Fixe"),("Matières premières","Variable"),
        ("Transport","Variable"),("Intérêts prêt","Financement"),("Ventes","Revenu"),("Services","Revenu")]
MOTS = [("Loyer","LOYER"),("Électricité","HYDRO"),("Salaires","PAIE"),("Matières premières","ACIER"),
        ("Matières premières","ALUMINIUM"),("Transport","FEDEX"),("Intérêts prêt","INTERETS"),
        ("Ventes","CLIENT"),("Services","CONSULTATION")]
HIST = [("HYDRO-QUEBEC FACT 8841","Électricité"),("LOGISTIQUE ROY TRANSPORT","Transport"),
        ("ROY TRANSPORT LIVRAISON","Transport"),("FOURNITURES BUREAU STAPLES","Matières premières")]

def creer(path):
    conn = sqlite3.connect(path); conn.executescript(SCHEMA)
    for i,(c,n) in enumerate(CATS,1): conn.execute("INSERT INTO categories VALUES (?,?,?)",(c,n,i))
    for i,(c,m) in enumerate(MOTS,1): conn.execute("INSERT INTO mots_cles (categorie,mot_cle,ordre) VALUES (?,?,?)",(c,m,i))
    nat = dict(CATS)
    for i,(d,c) in enumerate(HIST,1):
        conn.execute("INSERT INTO journal_general VALUES (?,?,?,?,?,?,?,?,?,?)",
                     (f"JG-2025-{i:05d}","2025-12-01",d,-100.0,c,nat[c],12,2025,"Desjardins EOP","FY2025"))
    conn.commit(); conn.close()

if __name__ == "__main__":
    creer(sys.argv[1] if len(sys.argv)>1 else "tresorerie_synth.db")
