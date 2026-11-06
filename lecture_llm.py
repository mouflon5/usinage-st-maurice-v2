"""
Lecture d'un relevé par le LLM quand le lecteur déterministe ne reconnaît pas sa mise en page (bouton de l'interface).

Principe : le LLM TRANSCRIT, il ne calcule rien. Chaque ligne qu'il rapporte est ensuite vérifiée contre le texte du document :
    * la ligne existe (le solde et le libellé annoncés se retrouvent sur une même ligne du document, dans l'ordre) ;
    * le montant n'est pas celui du LLM : il est recalculé = solde de la ligne − solde précédent, et ce montant doit
      figurer sur la ligne du document (donc le signe vient de l'arithmétique, jamais du modèle) ;
    * la date est cohérente avec la ligne (jour, et mois s'il est écrit en lettres) ;
    * une ligne omise ou inventée casse la continuité des soldes : la ligne suivante est refusée.
Une section (un compte du relevé) n'est utilisable que si TOUTES ses lignes passent. L'utilisateur la valide alors
explicitement ; la lecture est enregistrée par empreinte du fichier et reprise par formats_releves.lire_releve.
"""

import json
import os
import re
import unicodedata
from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field

import llm_fournisseur as llm_f
import suivi_llm as suivi
from formats_releves import DOSSIER_LECTURES_LLM, empreinte_fichier

MODELE_LECTURE = os.getenv("A2_MODELE_LECTURE", "claude-sonnet-5-5")
MAX_CARACTERES = 14000

_MOIS = {"JAN": 1, "FEV": 2, "MAR": 3, "AVR": 4, "MAI": 5, "JUN": 6, "JUI": 6, "JUL": 7, "AOU": 8, "SEP": 9, "OCT": 10,
         "NOV": 11, "DEC": 12, "APR": 4, "AUG": 8, "MAY": 5}


class LigneLue(BaseModel):
    date: str = Field(description="Date de l'opération au format AAAA-MM-JJ. L'année est dans l'en-tête du relevé.")
    description: str = Field(description="Libellé tel qu'imprimé sur la ligne (code d'opération compris).")
    solde: float = Field(description="Solde imprimé sur cette ligne, après l'opération. Recopié, jamais calculé.")


class SectionLue(BaseModel):
    nom: str = Field(description="Intitulé du compte ou de la section, tel qu'imprimé.")
    solde_ouverture: Optional[float] = Field(default=None, description="Solde reporté / précédent imprimé au début de la section, sinon null.")
    lignes: list[LigneLue]


class LectureLLM(BaseModel):
    sections: list[SectionLue]


# --------------------------------------------------------------------------- #
# Texte du document
# --------------------------------------------------------------------------- #
def texte_integral(chemin: str) -> str:
    ext = os.path.splitext(chemin)[1].lower()
    if ext == ".pdf":
        import pdfplumber
        with pdfplumber.open(chemin) as pdf:
            return "\n".join((p.extract_text() or "") for p in pdf.pages)
    import pandas as pd
    df = (pd.read_csv(chemin, sep=None, engine="python", header=None, dtype=str, keep_default_na=False, encoding_errors="replace")
          if ext == ".csv" else pd.read_excel(chemin, header=None, dtype=str, keep_default_na=False))
    return df.to_csv(index=False, header=False)


def _sans_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s.upper()) if unicodedata.category(c) != "Mn")


# --------------------------------------------------------------------------- #
# Vérification déterministe
# --------------------------------------------------------------------------- #
def _formes(x: float) -> list[str]:
    """Façons d'imprimer |x| : 1660.36, 1 660.36, 1 660,36 (espace ordinaire ou insécable)."""
    ent, dec = f"{abs(x):.2f}".split(".")
    groupes = f"{int(ent):,}"
    formes = {f"{ent}.{dec}", f"{ent},{dec}"}
    for sep in (" ", " ", " "):
        g = groupes.replace(",", sep)
        formes |= {f"{g}.{dec}", f"{g},{dec}"}
    return sorted(formes, key=len, reverse=True)


def _contient_nombre(ligne: str, x: float) -> bool:
    return any(re.search(r"(?<![\d.,])" + re.escape(f) + r"(?!\d)", ligne) for f in _formes(x))


def _mots(s: str) -> list[str]:
    return re.findall(r"[A-Z0-9]{3,}", _sans_accents(s))


def _libelle_coherent(description: str, ligne_norm: str) -> bool:
    mots = _mots(description)
    if not mots:
        return False
    return sum(m in ligne_norm for m in mots) / len(mots) >= 0.7


def _date_coherente(iso: str, ligne_norm: str) -> tuple[bool, str]:
    try:
        d = date.fromisoformat(iso)
    except ValueError:
        return False, f"date illisible « {iso} »"
    formes_numeriques = (d.isoformat(), f"{d.day:02d}/{d.month:02d}/{d.year}", f"{d.day:02d}-{d.month:02d}-{d.year}")
    if any(f in ligne_norm for f in formes_numeriques):
        return True, ""
    m = re.match(r"^\s*0?(\d{1,2})\s+([A-Z]{3,})", ligne_norm)
    if not m:
        return False, f"date {iso} introuvable sur la ligne"
    if int(m.group(1)) != d.day:
        return False, f"jour {d.day} ≠ jour imprimé {m.group(1)}"
    mois = _MOIS.get(m.group(2)[:3])
    if mois is not None and mois != d.month:
        return False, f"mois {d.month} ≠ mois imprimé « {m.group(2)} »"
    return True, ""


def verifier_section(section: SectionLue, lignes_source: list[str]) -> dict:
    """Vérifie une section contre les lignes du document. Retourne
    {nom, solde_ouverture, transactions, rejetees, ignorees}. Aucune ligne n'est corrigée en silence."""
    norm = [_sans_accents(l) for l in lignes_source]
    curseur = 0
    prec = section.solde_ouverture if (section.solde_ouverture is not None and any(_contient_nombre(l, section.solde_ouverture) for l in norm)) else None
    res = {"nom": section.nom, "solde_ouverture": prec, "transactions": [], "rejetees": [], "ignorees": []}
    if section.solde_ouverture is not None and prec is None:
        res["rejetees"].append({"ligne": f"solde d'ouverture {section.solde_ouverture:.2f}", "raison": "ce solde ne figure pas dans le document"})

    for lg in section.lignes:
        j = next((i for i in range(curseur, len(norm))
                  if _contient_nombre(norm[i], lg.solde) and _libelle_coherent(lg.description, norm[i])), None)
        if j is None:
            res["rejetees"].append({"ligne": f"{lg.date} {lg.description} (solde {lg.solde:.2f})",
                                    "raison": "introuvable dans le document (solde ou libellé inexact)"})
            continue
        ancien, prec, curseur = prec, lg.solde, j + 1       # le solde est vérifié dans le texte : la chaîne continue
        ok_date, raison_date = _date_coherente(lg.date, norm[j])
        if not ok_date:
            res["rejetees"].append({"ligne": lignes_source[j], "raison": raison_date})
            continue
        if ancien is None:
            res["rejetees"].append({"ligne": lignes_source[j], "raison": "pas de solde précédent vérifié : montant impossible à établir"})
            continue
        montant = round(lg.solde - ancien, 2)
        if abs(montant) < 0.005:
            res["ignorees"].append({"ligne": lignes_source[j], "raison": "montant nul"})
            continue
        if not _contient_nombre(norm[j], montant):
            res["rejetees"].append({"ligne": lignes_source[j],
                                    "raison": f"variation de solde {montant:+.2f} absente de la ligne (ligne omise avant elle ?)"})
            continue
        res["transactions"].append({"date": lg.date, "description": re.sub(r"\s+", " ", lg.description).strip(),
                                    "montant": montant, "solde": round(lg.solde, 2)})
    return res


# --------------------------------------------------------------------------- #
# Appel au LLM
# --------------------------------------------------------------------------- #
_CONSIGNE = (
    "Tu transcris un relevé bancaire. Recopie chaque opération (ligne qui commence par une date) dans l'ordre du document.\n"
    "Règles : ne calcule rien, ne corrige rien, n'invente aucune ligne. Le solde est celui IMPRIMÉ sur la ligne.\n"
    "Ignore les adresses, sommaires de frais, totaux et mentions légales.\n"
    "S'il y a plusieurs comptes ou sections (chèques, épargne, parts…), fais une section par compte avec son intitulé.\n"
    "L'année des dates est indiquée dans l'en-tête de période ; écris chaque date en AAAA-MM-JJ.\n"
    "Pour chaque section, solde_ouverture = le « solde reporté » / « solde précédent » imprimé au début, sinon null."
)


def lire_avec_llm(chemin: str) -> dict:
    """Lit un document avec le LLM puis vérifie chaque ligne. Retourne
    {sha256, sections: [verifier_section(...)], erreur}. Lève RuntimeError si aucun LLM n'est configuré."""
    if llm_f.fournisseur() == "simule":
        raise RuntimeError("Aucun LLM sélectionné : choisissez Claude ou Ollama dans la barre latérale.")
    texte = texte_integral(chemin)
    if not texte.strip():
        return {"sha256": empreinte_fichier(chemin), "sections": [], "erreur": "aucun texte lisible (scan sans OCR ?)"}
    if len(texte) > MAX_CARACTERES:
        return {"sha256": empreinte_fichier(chemin), "sections": [],
                "erreur": f"document trop long pour une lecture ({len(texte)} caractères > {MAX_CARACTERES}) : le découper par mois"}

    lignes = [re.sub(r"\s+", " ", l).strip() for l in texte.splitlines() if l.strip()]
    try:
        rep = llm_f.invoquer("A2", f"{_CONSIGNE}\n\nDocument :\n{texte}", schema=LectureLLM, max_tokens=6000,
                             defaut=MODELE_LECTURE)
    except Exception as e:                                        # noqa: BLE001
        return {"sha256": empreinte_fichier(chemin), "sections": [], "erreur": f"appel au LLM en échec ({type(e).__name__}: {e})"[:300]}

    sections = [verifier_section(s, lignes) for s in rep.parse.sections if s.lignes]
    nb_ok = sum(len(s["transactions"]) for s in sections)
    nb_ko = sum(len(s["rejetees"]) for s in sections)
    suivi.decider(llm_f.dernier_trace_id(), "à valider" if nb_ko == 0 and nb_ok else "escaladée",
                  f"{nb_ok} ligne(s) vérifiée(s), {nb_ko} rejetée(s) sur {len(sections)} section(s)")
    return {"sha256": empreinte_fichier(chemin), "sections": sections, "erreur": None}


# --------------------------------------------------------------------------- #
# Validation par l'utilisateur
# --------------------------------------------------------------------------- #
def section_utilisable(section: dict) -> bool:
    return bool(section["transactions"]) and not section["rejetees"]


def enregistrer_lecture(chemin: str, section: dict) -> str:
    """Enregistre la section validée par l'utilisateur ; lire_releve la reprend ensuite pour ce document."""
    if not section_utilisable(section):
        raise ValueError("Section non utilisable : lignes rejetées ou aucune opération.")
    os.makedirs(DOSSIER_LECTURES_LLM, exist_ok=True)
    sha = empreinte_fichier(chemin)
    fichier = os.path.join(DOSSIER_LECTURES_LLM, sha + ".json")
    with open(fichier, "w", encoding="utf-8") as f:
        json.dump({"sha256": sha, "nom_fichier": os.path.basename(chemin), "section": section["nom"],
                   "solde_ouverture": section["solde_ouverture"], "transactions": section["transactions"],
                   "valide_le": datetime.now().isoformat(timespec="seconds"),
                   "modele": llm_f.nom_modele("A2", MODELE_LECTURE)}, f, ensure_ascii=False, indent=1)
    return fichier


def retirer_lecture(chemin: str) -> bool:
    fichier = os.path.join(DOSSIER_LECTURES_LLM, empreinte_fichier(chemin) + ".json")
    if os.path.isfile(fichier):
        os.remove(fichier)
        return True
    return False
