"""Test du suivi de performance LLM (module suivi_llm) avec un faux modèle : jetons réels, rejet par garde-fou, aucune écriture hors démo."""
import os, sqlite3, sys, tempfile, types

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
tmp = tempfile.mkdtemp()
db = os.path.join(tmp, "x.db")
os.environ.update(SUIVI_DB=db, SUIVI_RUN="t", LLM_MODE="reel", ANTHROPIC_API_KEY="x")


class Msg:
    def __init__(s, c):
        s.content = c
        s.usage_metadata = {"input_tokens": 120, "output_tokens": 40, "total_tokens": 160}


class Fake:
    def __init__(s, **k): pass
    def invoke(s, p, *a, **k): return Msg("Le solde est 1 000 $ et 999 inventé.")
    def with_structured_output(s, c): return s


sys.modules["langchain_anthropic"] = types.SimpleNamespace(ChatAnthropic=Fake)
import a7_nodes as a7
import suivi_llm as s

a7._faits = lambda st: "solde 1 000"
a7._synthese_modele = lambda st: "modele"
r = a7.rediger_node({})
assert r["synthese"]["origine"] == "modele" and "rejet" in r["synthese"], r
c = sqlite3.connect(db)
rows = c.execute("SELECT type,agent,modele,mode,tok_in,tok_out,estime,statut FROM llm_appels ORDER BY id").fetchall()
assert rows[0][0] == "appel" and rows[0][4:7] == (120, 40, 0), rows
assert rows[1][0] == "garde" and rows[1][7] == "rejete", rows
del os.environ["SUIVI_DB"]
s.noter("A3", "x", "simule", 1.0, entree="abc")
assert len(c.execute("SELECT * FROM llm_appels").fetchall()) == 2
print("OK suivi LLM : jetons réels lus, nombre inventé rejeté, aucune écriture hors démo")
