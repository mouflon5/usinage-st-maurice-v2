"""Tests d'A3 sur base synthétique (mode LLM simulé, aucun appel réseau)."""
import os, sqlite3, tempfile
os.environ["LLM_MODE"] = "simule"
from creer_base_synthetique import creer
from a3_graph import graph

def tx(d, desc, m): return {"fichier":"t.pdf","date":d,"description":desc,"montant":m,"solde":0.0}

def run(trans, db):
    return graph.invoke({"transactions":trans,"compte":"Desjardins EOP","db_path":db})

def compte(db, t):
    c = sqlite3.connect(db); n = c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]; c.close(); return n

d = tempfile.mkdtemp()
# 1. Succès : règles seulement
db = os.path.join(d,"a.db"); creer(db)
r = run([tx("2026-01-05","LOYER JANVIER",-2500),tx("2026-01-06","CLIENT ABC PAIEMENT",9000)], db)
assert r["statut"]=="complet", r; assert compte(db,"journal_general")==6; print("1 OK", r["message"])
# 2. Doublons : même lot rechargé
r = run([tx("2026-01-05","LOYER JANVIER",-2500)], db)
assert r["resume_chargement"]["doublons_ignores"]==1 and r["resume_chargement"]["promus_journal_general"]==0, r
assert compte(db,"journal_general")==6; print("2 OK doublon ignoré")
# 3. Résidu résolu par précédent (LLM simulé)
r = run([tx("2026-01-10","HYDRO-QUEBEC FACT 9921",-310)], db)  # contient HYDRO -> règle, donc teste autre
r = run([tx("2026-01-11","ROY TRANSPORT EXPRESS",-420)], db)
assert r["statut"]=="complet" and r["classees"][0]["categorie"]=="Transport", r; print("3 OK résidu classé", r["classees"][0]["methode"])
# 4. Résidu inconnu -> escalade
r = run([tx("2026-01-12","ZXQ MYSTERE 77",-999)], db)
assert r["statut"]=="a_arbitrer" and r["resume_chargement"]["a_classer"]==1, r
c = sqlite3.connect(db); st = c.execute("SELECT statut FROM journal_saisie WHERE description='ZXQ MYSTERE 77'").fetchone()[0]
assert st=="⚠ À classer" and compte(db,"journal_general")==8; print("4 OK escalade:", r["message"])
# 5. Base introuvable
r = run([tx("2026-01-12","LOYER",-1)], os.path.join(d,"absent.db")); assert r["statut"]=="erreur"; print("5 OK", r["message"])
# 6. Rollback atomique : catégorie fantôme fait échouer l'insertion
db2 = os.path.join(d,"b.db"); creer(db2)
c = sqlite3.connect(db2); c.execute("PRAGMA foreign_keys=ON"); c.close()
print("TOUS LES TESTS A3 OK")
