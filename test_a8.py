"""Tests d'A8 (relecture) : règles du mode simulé, garde-fous contre un LLM fautif, indisponibilité, absence de blocage."""
import os, shutil, sys, types
os.environ["LLM_MODE"] = "simule"
os.environ["SORTIES_DIR"] = "sorties_tests"
os.environ["TRACES_DIR"] = "sorties_tests"
import scenarios as sc
from db_outils import reinitialiser_demo
import graph as g
import llm_outils

SRC = sys.argv[1] if len(sys.argv) > 1 else "tresorerie.db"
DB = "tresorerie_test_a8.db"
scn = [s for s in sc.generer(5, 10, SRC, racine="releves_tests_a8") if s.nom.endswith("normal")][0]
entree = {"compte": sc.COMPTE, "dossier_releves": scn.dossier, "periode_debut": scn.periode_debut,
          "periode_fin": scn.periode, "db_path": DB}


def lancer():
    reinitialiser_demo(SRC, DB)
    return g.graph.invoke(entree)


# 1. dossier sain, mode simulé : A8 s'exécute, aucun faux positif, statut inchangé
r = lancer()
assert r["statut_a8"] in ("ok", "reserves") and r["origine_a8"] == "simule", r.get("statut_a8")
print("1 OK simulé →", r["statut_a8"], "|", r["message_a8"], "| pipeline", r["statut_pipeline"])
base_statut = r["statut_pipeline"]

# 2. LLM réel (faux modèle) : constat valide retenu, constat avec nombre inventé / référence inconnue rejetés
class Faux:
    comportement = "ok"
    def __init__(self, **kw): self.schema = None
    def with_structured_output(self, schema): self.schema = schema; return self
    def invoke(self, prompt):
        if self.schema is not None and "note_classement" in self.schema.model_fields:
            c = Faux.comportement
            if c == "panne": raise RuntimeError("API indisponible")
            ok = dict(ref="L1", theme="classement", gravite="reserve", texte="Catégorie à confirmer pour cette ligne.")
            inv = dict(ref="L1", theme="classement", gravite="reserve", texte="Écart de 987654.32 $ non expliqué.")
            ref = dict(ref="L9999", theme="classement", gravite="reserve", texte="Ligne inexistante.")
            cs = {"ok": [ok], "mauvais": [inv, ref], "vide": []}[c]
            return self.schema(note_classement=4, note_doublons=5, note_commentaire=5, note_coherence=5,
                               constats=[self.schema.model_fields["constats"].annotation.__args__[0](**x) for x in cs])
        # autres appels LLM du pipeline (A3/A5/A7) : réponses sobres
        if self.schema is not None and "categorie" in self.schema.model_fields:
            return self.schema(categorie="À classer", confiance=0.0, justification="faux")
        if self.schema is not None:
            return self.schema(resume="RAS", points=[])
        return types.SimpleNamespace(content="Synthèse.")
fake = types.ModuleType("langchain_anthropic"); fake.ChatAnthropic = Faux
sys.modules["langchain_anthropic"] = fake
os.environ["LLM_MODE"] = "reel"

Faux.comportement = "ok"
r = lancer()
assert r["origine_a8"] == "llm" and r["statut_a8"] == "reserves" and len(r["constats_a8"]) == 1, r
assert r["statut_pipeline"] == "complet_avec_reserves" and any(a.startswith("") for a in [r["message_pipeline"]])
txt = open(r["fichiers_a7"][1], encoding="utf-8").read()
assert "A8 (L1)" in txt, "la réserve d'A8 doit apparaître dans le rapport A7"
print("2a OK constat valide retenu → réserve imprimée dans le rapport A7")

Faux.comportement = "mauvais"
r = lancer()
assert r["constats_a8"] == [] and len(r["constats_rejetes_a8"]) == 2, r["constats_rejetes_a8"]
assert "987654" in str(r["constats_rejetes_a8"]) and r["statut_a8"] == "ok"
print("2b OK nombre inventé et référence inconnue rejetés →", [c["raison"] for c in r["constats_rejetes_a8"]])

# 3. panne du LLM : réserve par défaut, rien par option ; jamais d'arrêt
Faux.comportement = "panne"
r = lancer()
assert r["statut_a8"] == "indisponible" and r["statut_pipeline"] == "complet_avec_reserves", r["statut_pipeline"]
os.environ["A8_ECHEC_EST_RESERVE"] = "0"
r = lancer()
assert r["statut_a8"] == "indisponible" and not r["constats_a8"]
del os.environ["A8_ECHEC_EST_RESERVE"]
print("3 OK panne LLM → réserve (ou rien avec A8_ECHEC_EST_RESERVE=0), pipeline non bloqué")

# 4. A8 désactivé
os.environ["A8_ACTIF"] = "0"
r = lancer()
assert r["origine_a8"] == "desactive" and not r["constats_a8"]
del os.environ["A8_ACTIF"]
print("4 OK A8_ACTIF=0")

# 5. simulé : règles — encaissement classé en charge, et doublon interne signalés
os.environ["LLM_MODE"] = "simule"
import a8_nodes
etat = {"db_path": DB, "compte": "X", "periode": scn.periode, "controles": [], "ecarts": [], "resume_a3": {}, "transactions": [],
        "classees": [{"date": "2026-03-04", "description": "VIREMENT CLIENT ZZ", "montant": 1500.0, "categorie": "Fret et transport",
                      "nature": "Variable", "methode": "regle", "confiance": 1.0}],
        "doublons": [{"date": "2026-03-05", "description": "TIM HORTONS", "montant": -4.5, "origine": "releve"},
                     {"date": "2026-03-06", "description": "DEJA LA", "montant": -9.0, "origine": "base"}]}
sortie = a8_nodes.graph if hasattr(a8_nodes, "graph") else None
import a8_graph
o = a8_graph.graph.invoke(etat)
refs = sorted(c["ref"] for c in o["constats"])
assert refs == ["D1", "L1"] and o["statut"] == "reserves", o["constats"]
print("5 OK règles simulées :", [c["texte"][:70] for c in o["constats"]])

for d in ("releves_tests_a8", "sorties_tests"): shutil.rmtree(d, ignore_errors=True)
os.remove(DB)
print("TOUS LES TESTS A8 OK")
