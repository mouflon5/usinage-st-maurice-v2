"""Tests d'intégration : approbation humaine (interrupt) et chemin « LLM réel » avec un faux modèle."""
import os, shutil, sys, types
os.environ["LLM_MODE"] = "simule"
os.environ["SORTIES_DIR"] = "sorties_tests"
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command
import scenarios as sc
from db_outils import reinitialiser_demo

SRC = sys.argv[1] if len(sys.argv) > 1 else "tresorerie.db"
DB = "tresorerie_test_pipeline.db"
scn = [s for s in sc.generer(5, 10, SRC, racine="releves_tests") if s.nom.endswith("normal")][0]
entree = {"compte": sc.COMPTE, "dossier_releves": scn.dossier, "periode_debut": scn.periode_debut,
          "periode_fin": scn.periode, "db_path": DB, "approbation_humaine": True}

import graph as g
app = g.builder.compile(checkpointer=MemorySaver())

# 1. interruption puis approbation
reinitialiser_demo(SRC, DB)
cfg = {"configurable": {"thread_id": "t1"}}
r = app.invoke(entree, cfg)
assert "__interrupt__" in r, "le graphe aurait dû s'interrompre"
print("1a OK interruption :", r["__interrupt__"][0].value["demande"], "| verdict A6 =", r["__interrupt__"][0].value["verdict_a6"])
r = app.invoke(Command(resume={"decision": "approuver", "commentaire": "OK pour diffusion"}), cfg)
assert r["statut_pipeline"] in ("complet", "complet_avec_reserves") and r["fichiers_a7"], r["statut_pipeline"]
assert "OK pour diffusion" in open(r["fichiers_a7"][1], encoding="utf-8").read()
print("1b OK approuvé →", r["statut_pipeline"], r["fichiers_a7"])

# 2. rejet humain : A7 ne doit rien produire
reinitialiser_demo(SRC, DB)
cfg = {"configurable": {"thread_id": "t2"}}
app.invoke(entree, cfg)
r = app.invoke(Command(resume={"decision": "rejeter", "commentaire": "chiffres à revoir"}), cfg)
assert r["statut_pipeline"] == "rejete_humain" and not r.get("fichiers_a7"), r["statut_pipeline"]
print("2 OK rejet humain →", r["message_pipeline"])

# 3. chemin « réel » avec un faux modèle Claude (aucun appel réseau)
class FauxModele:
    def __init__(self, **kw): self.schema = None
    def with_structured_output(self, schema): self.schema = schema; return self
    def invoke(self, prompt):
        if self.schema is not None:
            return self.schema(**({"categorie": "Fret et transport", "confiance": 0.95, "justification": "faux"} if "categorie" in self.schema.model_fields
                                  else {"resume": "Flux net conforme. Revenus de 999 999 $ !", "points": []}))
        return types.SimpleNamespace(content="Synthèse avec un chiffre inventé : 123 456 $.")
fake = types.ModuleType("langchain_anthropic"); fake.ChatAnthropic = FauxModele
sys.modules["langchain_anthropic"] = fake
os.environ["LLM_MODE"] = "reel"
reinitialiser_demo(SRC, DB)
entree2 = {k: v for k, v in entree.items() if k != "approbation_humaine"}
r = g.graph.invoke(entree2)
assert r["commentaire_a5"]["origine"] == "modele", r["commentaire_a5"]
assert r["statut_pipeline"] == "complet_avec_reserves", r["statut_pipeline"]
assert any("rejeté" in a for a in r["alertes_a5"]), r["alertes_a5"]
print("3 OK chiffre inventé par le LLM rejeté →", r["statut_pipeline"], "|", r["alertes_a5"][0][:90])
for d in ("releves_tests", "sorties_tests"): shutil.rmtree(d, ignore_errors=True)
os.remove(DB)
print("TOUS LES TESTS D'INTÉGRATION OK")
