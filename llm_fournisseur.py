"""Fournisseur de LLM unique pour tous les agents (A3, A5, A7, A8 et l'assistant RAG).

Trois fournisseurs, choisis par variables d'environnement (l'interface les positionne) :

    LLM_FOURNISSEUR = claude | ollama | simule      (absent : compatibilité avec LLM_MODE / ANTHROPIC_API_KEY)
    LLM_MODELE      = identifiant du modèle choisi (vide : le défaut de chaque agent, ex. A5_MODELE)
    OLLAMA_URL      = http://localhost:11434        OLLAMA_NUM_CTX = 8192

Chaque appel passe par `invoquer()` : il est chronométré, et — quand SUIVI_DB est défini (moteur de démo) — son prompt,
sa réponse brute, le raisonnement éventuel du modèle et, plus tard, la décision des garde-fous sont conservés dans la
table `llm_traces` (voir suivi_llm.tracer). C'est la matière de l'onglet « Raisonnement ».
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from dotenv import load_dotenv

import suivi_llm as suivi

load_dotenv()

RACINE = os.path.dirname(os.path.abspath(__file__))
FICHIER_CONFIG = os.path.join(RACINE, "demo_live", "donnees", "config_llm.json")

FOURNISSEURS = ("simule", "claude", "ollama")
CLAUDE_MODELES = ["claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5", "claude-fable-5-1"]
OLLAMA_URL_DEFAUT = "http://localhost:11434"
OLLAMA_MODELE_DEFAUT = "qwen2.5:7b"

_RE_PENSEE = re.compile(r"<think>(.*?)</think>", re.S | re.I)


# --------------------------------------------------------------------------- #
# Choix du fournisseur et du modèle
# --------------------------------------------------------------------------- #
def fournisseur() -> str:
    f = os.getenv("LLM_FOURNISSEUR", "").lower()
    if f in FOURNISSEURS:
        return f
    mode = os.getenv("LLM_MODE", "auto").lower()          # compatibilité avec l'ancien réglage
    if mode == "simule":
        return "simule"
    if mode == "reel":
        return "claude"
    return "claude" if os.getenv("ANTHROPIC_API_KEY") else "simule"


def url_ollama() -> str:
    return os.getenv("OLLAMA_URL", OLLAMA_URL_DEFAUT).rstrip("/")


def nom_modele(agent: str, defaut: str) -> str:
    """Modèle effectivement utilisé par un agent. `defaut` = son modèle Claude habituel (A3_MODELE, A5_MODELE…)."""
    f = fournisseur()
    if f == "simule":
        return "simulé"
    choisi = os.getenv("LLM_MODELE", "").strip()
    if choisi:
        return choisi
    return os.getenv("OLLAMA_MODELE", OLLAMA_MODELE_DEFAUT) if f == "ollama" else defaut


def libelle() -> str:
    f = fournisseur()
    return "simulé (règles, aucun appel)" if f == "simule" else f"{f} · {os.getenv('LLM_MODELE', '').strip() or 'modèle par défaut de chaque agent'}"


def _construire(prov: str, modele: str, max_tokens: int, url: str | None = None):
    if prov == "ollama":
        from langchain_ollama import ChatOllama
        return ChatOllama(model=modele, base_url=url or url_ollama(), temperature=0, num_predict=max_tokens,
                          num_ctx=int(os.getenv("OLLAMA_NUM_CTX", "8192")))
    from langchain_anthropic import ChatAnthropic
    return ChatAnthropic(model=modele, max_tokens=max_tokens)


# --------------------------------------------------------------------------- #
# Appel tracé
# --------------------------------------------------------------------------- #
@dataclass
class Reponse:
    texte: str = ""
    parse: Any = None
    modele: str = ""
    fournisseur: str = ""
    duree_ms: float = 0.0
    jetons: tuple[int, int] | None = None
    raisonnement: str = ""
    trace_id: int | None = None
    message: Any = field(default=None, repr=False)


_dernier: dict = {"id": None}


def dernier_trace_id() -> int | None:
    """Identifiant de la trace du dernier appel : permet à l'agent d'y consigner sa décision (acceptée, rejetée…)."""
    return _dernier["id"]


def _rendre_prompt(prompt) -> str:
    if isinstance(prompt, str):
        return prompt
    try:
        return "\n\n".join(f"[{role}]\n{texte}" for role, texte in prompt)
    except Exception:
        return str(prompt)


def _texte_et_pensee(msg) -> tuple[str, str]:
    contenu = getattr(msg, "content", msg)
    pensee = []
    if isinstance(contenu, list):
        morceaux = []
        for b in contenu:
            if isinstance(b, dict):
                if b.get("type") == "thinking":
                    pensee.append(b.get("thinking", ""))
                else:
                    morceaux.append(b.get("text", ""))
            else:
                morceaux.append(str(b))
        texte = "".join(morceaux)
    else:
        texte = str(contenu or "")
    extra = getattr(msg, "additional_kwargs", None) or {}
    if extra.get("reasoning_content"):
        pensee.append(str(extra["reasoning_content"]))
    pensee += _RE_PENSEE.findall(texte)                       # modèles de raisonnement locaux (deepseek-r1, qwen3…)
    texte = _RE_PENSEE.sub("", texte).strip()
    return texte, "\n".join(p.strip() for p in pensee if p and p.strip())


def invoquer(agent: str, prompt, *, schema=None, max_tokens: int = 500, defaut: str = "claude-sonnet-5-5",
             meta: dict | None = None) -> Reponse:
    """Appelle le modèle choisi. Avec `schema` (classe pydantic) la réponse est structurée (`.parse`).
    Toute erreur est consignée puis relancée : l'agent décide de son repli."""
    prov = fournisseur()
    if prov == "simule":
        raise RuntimeError("Aucun LLM sélectionné (fournisseur « simulé »)")
    modele = nom_modele(agent, defaut)
    r = Reponse(modele=modele, fournisseur=prov)
    texte_prompt = _rendre_prompt(prompt)
    t0 = time.perf_counter()
    try:
        llm = _construire(prov, modele, max_tokens)
        if schema is not None:
            r.parse = llm.with_structured_output(schema).invoke(prompt)
            r.texte = r.parse.model_dump_json(indent=1) if hasattr(r.parse, "model_dump_json") else str(r.parse)
        else:
            r.message = llm.invoke(prompt)
            r.jetons = suivi.jetons_api(r.message)
            r.texte, r.raisonnement = _texte_et_pensee(r.message)
        r.duree_ms = (time.perf_counter() - t0) * 1000
        r.trace_id = suivi.tracer(agent, modele, prov, texte_prompt, r.texte, r.duree_ms, raisonnement=r.raisonnement,
                                  tokens=r.jetons, meta=meta)
        _dernier["id"] = r.trace_id
        return r
    except Exception as e:
        duree = (time.perf_counter() - t0) * 1000
        _dernier["id"] = suivi.tracer(agent, modele, prov, texte_prompt, "", duree, statut="erreur",
                                      erreur=f"{type(e).__name__}: {e}", meta=meta)
        raise


def rejouer(prov: str, modele: str, prompt, schema=None, max_tokens: int = 800, url: str | None = None) -> Reponse:
    """Rejoue un prompt déjà consigné sur un autre modèle, pour comparer. Ne consigne rien et ne touche pas à l'environnement."""
    r = Reponse(modele=modele, fournisseur=prov)
    t0 = time.perf_counter()
    llm = _construire(prov, modele, max_tokens, url)
    if schema is not None:
        r.parse = llm.with_structured_output(schema).invoke(prompt)
        r.texte = r.parse.model_dump_json(indent=1)
    else:
        r.message = llm.invoke(prompt)
        r.texte, r.raisonnement = _texte_et_pensee(r.message)
    r.duree_ms = (time.perf_counter() - t0) * 1000
    return r


def tracer_regle(agent: str, entree: str, sortie: str, meta: dict | None = None, decision: str | None = None,
                 detail: str | None = None) -> None:
    """Consigne un raisonnement SANS LLM (règles, gabarit) dans le même journal, pour que l'onglet couvre aussi le mode simulé."""
    tid = suivi.tracer(agent, "règles", "simule", entree, sortie, 0.0, meta=meta)
    _dernier["id"] = tid
    if decision:
        suivi.decider(tid, decision, detail)


# --------------------------------------------------------------------------- #
# Outils pour l'interface
# --------------------------------------------------------------------------- #
def lister_ollama(url: str | None = None, delai: float = 3.0) -> list[dict]:
    """Modèles installés dans Ollama : [{nom, taille_go}]. Liste vide si le serveur ne répond pas."""
    try:
        with urllib.request.urlopen((url or url_ollama()).rstrip("/") + "/api/tags", timeout=delai) as rep:
            data = json.load(rep)
        return [{"nom": m["name"], "taille_go": round(m.get("size", 0) / 1e9, 1)} for m in data.get("models", [])]
    except Exception:
        return []


def tester(prov: str, modele: str, url: str | None = None) -> dict:
    """Appel minimal pour vérifier la connexion : {ok, ms, reponse | erreur}."""
    t0 = time.perf_counter()
    try:
        if prov == "claude" and not os.getenv("ANTHROPIC_API_KEY"):
            return {"ok": False, "erreur": "ANTHROPIC_API_KEY absente (fichier .env ou variable d'environnement)."}
        msg = _construire(prov, modele, 60, url).invoke("Réponds uniquement par le mot : OK")
        texte, _ = _texte_et_pensee(msg)
        return {"ok": True, "ms": round((time.perf_counter() - t0) * 1000), "reponse": texte[:200]}
    except Exception as e:
        return {"ok": False, "erreur": f"{type(e).__name__}: {e}"[:400]}


def lire_config() -> dict:
    try:
        with open(FICHIER_CONFIG, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def ecrire_config(cfg: dict) -> None:
    os.makedirs(os.path.dirname(FICHIER_CONFIG), exist_ok=True)
    with open(FICHIER_CONFIG, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=1)


def appliquer(prov: str, modele: str = "", url: str = "") -> None:
    """Positionne l'environnement du processus courant (les processus lancés ensuite en héritent)."""
    os.environ["LLM_FOURNISSEUR"] = prov
    os.environ["LLM_MODELE"] = modele or ""
    if url:
        os.environ["OLLAMA_URL"] = url
    os.environ["LLM_MODE"] = "simule" if prov == "simule" else "reel"
