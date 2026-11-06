"""Suivi de la performance des modèles LLM (observabilité) — silencieux et sans effet sur la logique des agents.

Chaque appel LLM (réel OU simulé) et chaque contrôle de garde-fou est noté dans la table `llm_appels` de la base de
démonstration, uniquement si la variable SUIVI_DB est définie (le moteur de démo la définit). Hors démo : aucune écriture.

    suivi_llm.noter(agent, modele, mode, duree_ms, entree="...", sortie="...", statut="ok", tokens=(in, out), **meta)
    suivi_llm.noter_garde(agent, garde, ok, **meta)

Jetons : l'API les fournit quand l'appel est direct ; sinon (sortie structurée, mode simulé) ils sont ESTIMÉS à 1 jeton
pour 4 caractères et marqués `estime`. En mode simulé le coût est donc un coût « équivalent si le mode réel était actif ».
Les tarifs ci-dessous sont indicatifs (USD par million de jetons) : ajustez-les dans PRIX ou via SUIVI_PRIX_JSON.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from contextlib import contextmanager

PRIX = {"haiku": (1.0, 5.0), "sonnet": (3.0, 15.0), "opus": (5.0, 25.0)}     # (entrée, sortie) $/M jetons — indicatif
if os.getenv("SUIVI_PRIX_JSON"):
    try:
        PRIX.update({k: tuple(v) for k, v in json.loads(os.environ["SUIVI_PRIX_JSON"]).items()})
    except Exception:
        pass

_SCHEMA = """CREATE TABLE IF NOT EXISTS llm_appels(
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, run_id TEXT, type TEXT, agent TEXT, modele TEXT, mode TEXT,
    duree_ms REAL, tok_in INTEGER, tok_out INTEGER, estime INTEGER, cout REAL, statut TEXT, meta TEXT)"""


def actif() -> bool:
    return bool(os.getenv("SUIVI_DB"))


def tarif(modele: str) -> tuple[float, float]:
    m = (modele or "").lower()
    for cle, p in PRIX.items():
        if cle in m:
            return p
    return PRIX["sonnet"]            # modèle inconnu (ex. « simulé ») : on projette au tarif Sonnet


def _ecrire(ligne: tuple) -> None:
    chemin = os.getenv("SUIVI_DB")
    if not chemin:
        return
    for essai in range(4):
        try:
            c = sqlite3.connect(chemin, timeout=5)
            try:
                c.execute(_SCHEMA)
                c.execute("INSERT INTO llm_appels(ts, run_id, type, agent, modele, mode, duree_ms, tok_in, tok_out, estime, cout, statut, meta) "
                          "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", ligne)
                c.commit()
            finally:
                c.close()
            return
        except Exception:
            time.sleep(0.15)


def noter(agent: str, modele: str, mode: str, duree_ms: float, entree: str = "", sortie: str = "", statut: str = "ok",
          tokens: tuple[int, int] | None = None, entree_chars: int | None = None, **meta) -> None:
    try:
        estime = tokens is None
        if estime:
            tokens = (max(1, (entree_chars if entree_chars is not None else len(entree)) // 4), max(1, len(sortie) // 4))
        p_in, p_out = (0.0, 0.0) if meta.get("fournisseur") == "ollama" else tarif(modele)     # modèle local : gratuit
        cout = (tokens[0] * p_in + tokens[1] * p_out) / 1_000_000
        _ecrire((time.strftime("%Y-%m-%dT%H:%M:%S"), os.getenv("SUIVI_RUN", ""), "appel", agent, modele, mode,
                 round(duree_ms, 2), tokens[0], tokens[1], int(estime), cout, statut, json.dumps(meta, ensure_ascii=False, default=str)))
    except Exception:
        pass


def noter_garde(agent: str, garde: str, ok: bool, **meta) -> None:
    """Un garde-fou a-t-il laissé passer (ok) ou rejeté (non ok) la production du LLM ?"""
    try:
        _ecrire((time.strftime("%Y-%m-%dT%H:%M:%S"), os.getenv("SUIVI_RUN", ""), "garde", agent, garde, "", 0, 0, 0, 0, 0,
                 "ok" if ok else "rejete", json.dumps(meta, ensure_ascii=False, default=str)))
    except Exception:
        pass


_SCHEMA_TRACES = """CREATE TABLE IF NOT EXISTS llm_traces(
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, run_id TEXT, agent TEXT, fournisseur TEXT, modele TEXT, prompt TEXT,
    reponse TEXT, raisonnement TEXT, duree_ms REAL, tok_in INTEGER, tok_out INTEGER, statut TEXT, erreur TEXT,
    decision TEXT, decision_detail TEXT, meta TEXT)"""


def _executer(sql: str, params: tuple) -> int | None:
    chemin = os.getenv("SUIVI_DB")
    if not chemin:
        return None
    for _ in range(4):
        try:
            c = sqlite3.connect(chemin, timeout=5)
            try:
                c.execute(_SCHEMA_TRACES)
                cur = c.execute(sql, params)
                c.commit()
                return cur.lastrowid
            finally:
                c.close()
        except Exception:
            time.sleep(0.15)
    return None


def tracer(agent: str, modele: str, fournisseur: str, prompt: str, reponse: str, duree_ms: float, raisonnement: str = "",
           tokens: tuple[int, int] | None = None, statut: str = "ok", erreur: str | None = None, meta: dict | None = None) -> int | None:
    """Conserve l'échange COMPLET avec le modèle (prompt, réponse brute, raisonnement) pour l'onglet « Raisonnement ».
    Retourne l'identifiant de la trace (None hors démo) afin d'y consigner ensuite la décision de l'agent."""
    try:
        t_in, t_out = tokens if tokens else (max(1, len(prompt) // 4), max(1, len(reponse) // 4))
        return _executer(
            "INSERT INTO llm_traces(ts, run_id, agent, fournisseur, modele, prompt, reponse, raisonnement, duree_ms, tok_in, tok_out, "
            "statut, erreur, meta) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (time.strftime("%Y-%m-%dT%H:%M:%S"), os.getenv("SUIVI_RUN", ""), agent, fournisseur, modele, prompt, reponse,
             raisonnement, round(duree_ms, 2), t_in, t_out, statut, erreur, json.dumps(meta or {}, ensure_ascii=False, default=str)))
    except Exception:
        return None


def decider(trace_id: int | None, decision: str, detail: str | None = None) -> None:
    """Ce que l'agent a fait de la réponse : « acceptée », « escaladée », « rejetée par garde-fou »… et pourquoi."""
    if trace_id is None:
        return
    try:
        _executer("UPDATE llm_traces SET decision=?, decision_detail=? WHERE id=?", (decision, detail, trace_id))
    except Exception:
        pass


@contextmanager
def chrono():
    """with chrono() as t: ... ; t[0] contient la durée en ms."""
    t = [0.0]
    t0 = time.perf_counter()
    try:
        yield t
    finally:
        t[0] = (time.perf_counter() - t0) * 1000


def jetons_api(reponse) -> tuple[int, int] | None:
    """Jetons réels d'une réponse LangChain (usage_metadata), sinon None."""
    try:
        u = getattr(reponse, "usage_metadata", None)
        if u:
            return int(u["input_tokens"]), int(u["output_tokens"])
    except Exception:
        pass
    return None
