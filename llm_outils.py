"""
Outils LLM d'A3 — classement du résidu « À classer ».

Principe d'architecture : le LLM ne calcule jamais. Il choisit UNE catégorie dans
la liste fermée de la table `categories`, avec une confiance et une justification,
à partir de précédents tirés de journal_general. Si la confiance est sous le seuil
ou si la catégorie n'existe pas, la ligne reste « À classer » (escalade).

Deux modes :
    - "reel"   : un vrai LLM — Claude (ANTHROPIC_API_KEY requis) ou un modèle local Ollama (voir llm_fournisseur.py)
    - "simule" : aucun appel réseau, déterministe, basé sur la similarité aux précédents
Variables d'environnement : LLM_FOURNISSEUR = claude | ollama | simule  (ou l'ancien LLM_MODE = auto | reel | simule)
"""

import os
import re
import unicodedata

from dotenv import load_dotenv
from pydantic import BaseModel, Field

import llm_fournisseur as llm_f

load_dotenv()

SEUIL_CONFIANCE = float(os.getenv("A3_SEUIL_CONFIANCE", "0.8"))
MODELE_DEFAUT = os.getenv("A3_MODELE", "claude-haiku-5-5")

_MOTS_VIDES = {"FACT", "INC", "LTEE", "LES", "DES", "POUR", "PAR", "AVEC"}


class Classement(BaseModel):
    categorie: str = Field(description="Une catégorie de la liste fournie, ou 'À classer'")
    confiance: float = Field(ge=0, le=1)
    justification: str


def mode_llm() -> str:
    return "simule" if llm_f.fournisseur() == "simule" else "reel"


def _jetons(description: str) -> frozenset:
    texte = unicodedata.normalize("NFD", description.upper())
    texte = "".join(c for c in texte if unicodedata.category(c) != "Mn")
    return frozenset(m for m in re.findall(r"[A-Z]{3,}", texte) if m not in _MOTS_VIDES)


def charger_precedents(conn) -> list:
    """Descriptions distinctes de journal_general avec leur catégorie."""
    lignes = conn.execute(
        "SELECT description, categorie FROM journal_general GROUP BY description, categorie"
    ).fetchall()
    return [(_jetons(d), cat, d) for d, cat in lignes]


def top_precedents(description: str, precedents: list, k: int = 5) -> list:
    """Retourne [(score, catégorie, description)] triés, score > 0.

    Score = part du « poids » (IDF) des mots de la transaction retrouvée dans le précédent : un nom de
    fournisseur rare (MARMEN) pèse plus qu'un mot courant. Mesurer la couverture de la transaction
    (et non le Jaccard) évite de pénaliser les précédents plus longs (« FACTURE USINAGE - MARMEN INC »).
    """
    import math
    cible = _jetons(description)
    if not cible or not precedents:
        return []
    n = len(precedents)
    df = {}
    for jetons, _, _ in precedents:
        for j in jetons:
            df[j] = df.get(j, 0) + 1
    idf = lambda j: math.log((n + 1) / (df.get(j, 0) + 1)) + 1.0
    total = sum(idf(j) for j in cible)
    notes = []
    for jetons, cat, desc in precedents:
        commun = cible & jetons
        if commun:
            notes.append((sum(idf(j) for j in commun) / total, cat, desc))
    notes.sort(key=lambda x: x[0], reverse=True)
    return notes[:k]


def _simule(prec: list) -> Classement:
    if not prec:
        return Classement(categorie="À classer", confiance=0.0, justification="Aucun précédent similaire.")
    s, cat, desc = prec[0]
    if s >= 0.5:
        return Classement(categorie=cat, confiance=0.85, justification=f"[simulé] Précédent similaire : {desc}")
    return Classement(categorie=cat, confiance=round(s, 2), justification=f"[simulé] Précédent faible : {desc}")


def prompt_classement(t: dict, categories: dict, prec: list) -> str:
    """Le prompt exact envoyé au LLM pour classer une ligne (aussi utilisé pour rejouer une décision sur un autre modèle)."""
    liste = "\n".join(f"- {c} ({n})" for c, n in sorted(categories.items()))
    exemples = "\n".join(f"- « {d} » → {c}" for _, c, d in prec) or "(aucun précédent)"
    sens = "sortie de fonds" if t["montant"] < 0 else "entrée de fonds"
    return (
        "Tu classes une transaction bancaire dans le plan de classement de Groupe Usinage Saint-Maurice, "
        "PME manufacturière d'usinage de précision (usinage sur mesure, contrats récurrents aéro et rail, pièces de rechange, prototypage).\n"
        "Choisis EXACTEMENT UNE catégorie dans la liste, telle qu'écrite. "
        "Si aucune ne convient avec confiance, réponds « À classer » avec une confiance faible.\n"
        "Tu ne calcules rien et n'inventes aucune catégorie.\n\n"
        f"Catégories (nature) :\n{liste}\n\n"
        f"Précédents les plus proches :\n{exemples}\n\n"
        f"Transaction : « {t['description']} » — {t['montant']:.2f} $ ({sens})\n"
        "Donne la catégorie, une confiance entre 0 et 1, et une justification d'une phrase."
    )


def _reel(t: dict, categories: dict, prec: list) -> Classement:
    return llm_f.invoquer("A3", prompt_classement(t, categories, prec), schema=Classement, max_tokens=300, defaut=MODELE_DEFAUT,
                          meta=_contexte_trace(t, prec)).parse


def _contexte_trace(t: dict, prec: list) -> dict:
    """Les éléments sur lesquels repose la décision : on les garde pour pouvoir l'expliquer ensuite."""
    return {"description": t["description"], "montant": t["montant"], "date": t.get("date"), "seuil": SEUIL_CONFIANCE,
            "precedents": [{"score": round(s, 2), "categorie": c, "description": d} for s, c, d in prec]}


def classer(t: dict, categories: dict, precedents: list, mode: str) -> Classement:
    prec = top_precedents(t["description"], precedents)
    if mode == "simule":
        res = _simule(prec)
        llm_f.tracer_regle("A3", f"Transaction : « {t['description']} » ({t['montant']:.2f} $)\nPrécédents : "
                           + (" ; ".join(f"« {d} » → {c} ({s:.2f})" for s, c, d in prec) or "aucun"),
                           res.model_dump_json(indent=1), meta=_contexte_trace(t, prec))
        return res
    return _reel(t, categories, prec)
