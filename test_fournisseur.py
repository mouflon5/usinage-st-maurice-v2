"""Test du fournisseur de LLM : choix Claude / Ollama / simulé, traçage complet, coût nul en local.

Le chemin Claude est testé avec un faux modèle (aucun appel réseau). Le chemin Ollama est testé pour de vrai si le serveur
local répond (sinon ce volet est ignoré et le dit).
"""
import os, sqlite3, sys, tempfile, types

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
tmp = tempfile.mkdtemp()
db = os.path.join(tmp, "x.db")
os.environ.pop("LLM_MODE", None)
os.environ.update(SUIVI_DB=db, SUIVI_RUN="t")
os.environ.pop("ANTHROPIC_API_KEY", None)

import llm_fournisseur as lf
import llm_outils as llm
import suivi_llm as suivi

# 1. résolution du fournisseur et du modèle
os.environ.pop("LLM_FOURNISSEUR", None)
assert lf.fournisseur() == "simule" and llm.mode_llm() == "simule", "sans clé ni choix : simulé"
lf.appliquer("claude", "claude-opus-5-5")
assert lf.fournisseur() == "claude" and llm.mode_llm() == "reel"
assert lf.nom_modele("A3", "claude-haiku-5-5") == "claude-opus-5-5", "le choix explicite l'emporte sur le défaut de l'agent"
lf.appliquer("claude", "")
assert lf.nom_modele("A3", "claude-haiku-5-5") == "claude-haiku-5-5", "sans choix : défaut de l'agent"
lf.appliquer("ollama", "")
assert lf.nom_modele("A3", "claude-haiku-5-5") == lf.OLLAMA_MODELE_DEFAUT
lf.appliquer("simule")
assert lf.fournisseur() == "simule" and llm.mode_llm() == "simule"
try:
    lf.invoquer("A3", "x")
    raise SystemExit("invoquer doit refuser le fournisseur simulé")
except RuntimeError:
    pass
print("1 OK choix du fournisseur et du modèle")


# 2. chemin Claude avec un faux modèle : trace complète + décision
class Msg:
    def __init__(s, c):
        s.content = c
        s.usage_metadata = {"input_tokens": 50, "output_tokens": 10, "total_tokens": 60}
        s.additional_kwargs = {}


class Faux:
    def __init__(s, **k): s.k = k
    def invoke(s, p, *a, **k): return Msg("Réponse <think>je réfléchis</think>finale")
    def with_structured_output(s, c): return types.SimpleNamespace(invoke=lambda p: c(categorie="Fret et transport", confiance=0.9, justification="faux"))


sys.modules["langchain_anthropic"] = types.SimpleNamespace(ChatAnthropic=Faux)
lf.appliquer("claude", "claude-sonnet-5-5")
r = lf.invoquer("A7", [("system", "Consigne"), ("human", "Question")], max_tokens=50)
assert r.texte == "Réponse finale" and r.raisonnement == "je réfléchis" and r.jetons == (50, 10), r
suivi.decider(r.trace_id, "acceptée", "ok")
r2 = lf.invoquer("A3", "classe", schema=llm.Classement)
assert r2.parse.categorie == "Fret et transport"
c = sqlite3.connect(db)
lignes = c.execute("SELECT agent, fournisseur, modele, prompt, reponse, raisonnement, decision FROM llm_traces ORDER BY id").fetchall()
assert lignes[0][:3] == ("A7", "claude", "claude-sonnet-5-5") and "[system]" in lignes[0][3] and lignes[0][6] == "acceptée", lignes
assert lignes[0][5] == "je réfléchis", "le raisonnement du modèle doit être conservé"
assert lignes[1][0] == "A3" and "Fret et transport" in lignes[1][4], lignes
print("2 OK appel tracé : prompt, réponse, raisonnement et décision conservés")

# 3. modèle local : aucun coût
suivi.noter("A3", "llama3.2", "reel", 5.0, entree="x" * 4000, sortie="y" * 400, fournisseur="ollama")
suivi.noter("A3", "claude-sonnet-5-5", "reel", 5.0, entree="x" * 4000, sortie="y" * 400, fournisseur="claude")
couts = [x[0] for x in c.execute("SELECT cout FROM llm_appels ORDER BY id")]
assert couts[0] == 0 and couts[1] > 0, couts
print("3 OK Ollama gratuit, Claude facturé")

# 4. erreur : consignée puis relancée
class Panne(Faux):
    def invoke(s, p, *a, **k): raise ConnectionError("réseau coupé")


sys.modules["langchain_anthropic"] = types.SimpleNamespace(ChatAnthropic=Panne)
try:
    lf.invoquer("A7", "x")
    raise SystemExit("l'erreur doit être relancée")
except ConnectionError:
    pass
ligne = c.execute("SELECT statut, erreur FROM llm_traces ORDER BY id DESC LIMIT 1").fetchone()
assert ligne[0] == "erreur" and "réseau coupé" in ligne[1], ligne
print("4 OK panne consignée dans la trace")

# 5. Ollama réel (si le serveur local répond)
modeles = lf.lister_ollama()
if not modeles:
    print("5 IGNORÉ Ollama ne répond pas sur", lf.url_ollama())
else:
    petit = min(modeles, key=lambda m: m["taille_go"])["nom"]
    t = lf.tester("ollama", petit)
    assert t["ok"], t
    lf.appliquer("ollama", petit)
    cl = llm.classer({"description": "FACTURE USINAGE MARMEN", "montant": -1200.0, "date": "2026-10-03"},
                     {"Fret et transport": "Variable", "Matières premières (acier, alu, inox)": "Variable"}, [], "reel")
    assert 0 <= cl.confiance <= 1 and cl.categorie, cl
    print(f"5 OK Ollama réel ({petit}) : {t['ms']} ms ; classement → {cl.categorie} ({cl.confiance})")
