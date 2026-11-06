"""
Classement des documents que la convention de nom ne reconnaît pas (agent A1).

Un fichier comme « releve_bnc_nov.pdf » ne passe pas la convention « Compte_AAAA-MM ». Au lieu de l'ignorer,
le LLM lit le début du document et répond :
    - s'il s'agit d'un relevé de compte bancaire ou non ;
    - le compte (nom, banque, type, 4 derniers chiffres) et le mois couvert.

Règles (même prudence que le reste du pipeline) :
    * le LLM ne calcule rien : il classe seulement ;
    * une réponse n'est retenue que si c'est un relevé, si le mois est lisible et si la confiance atteint le seuil ;
    * sinon le fichier reste non reconnu et A1 le signale ;
    * sans LLM configuré (fournisseur « simulé »), rien n'est classé : aucun document n'est deviné ;
    * chaque classement est mis en cache par nom + empreinte SHA-256 (table classement_documents) : un fichier
      n'est soumis au LLM qu'une fois, tant que son contenu ne change pas ;
    * un compte nouveau est créé dans mdm_compte ; un compte connu (même banque et mêmes 4 derniers chiffres,
      ou même nom) est réutilisé.
"""

import hashlib
import json
import os
import re
import sqlite3
from typing import Optional

from pydantic import BaseModel, Field

import llm_fournisseur as llm_f
import suivi_llm as suivi
from formats_releves import DOSSIER_LECTURES_LLM, EXTENSIONS, analyser_nom_fichier, lire_releve, normaliser_compte

SEUIL_CLASSEMENT = float(os.getenv("A1_SEUIL_CLASSEMENT", "0.8"))
MODELE_CLASSEMENT = os.getenv("A1_MODELE", "claude-haiku-5-5")
MAX_CARACTERES = 3000
PAGES_PDF = 2
LIGNES_TABLEAU = 15

_RE_PERIODE = re.compile(r"^(\d{4})-(\d{2})$")

_SCHEMA_TABLE = """
CREATE TABLE IF NOT EXISTS classement_documents (
    nom_fichier   TEXT PRIMARY KEY,
    sha256        TEXT NOT NULL,
    est_releve    INTEGER NOT NULL,
    compte        TEXT,
    banque_code   TEXT,
    type_code     TEXT,
    numero_masque TEXT,
    periode       TEXT,
    confiance     REAL NOT NULL,
    justification TEXT,
    raison        TEXT,
    classe_le     TEXT NOT NULL DEFAULT (datetime('now'))
)
"""


class ClassementDocument(BaseModel):
    est_releve: bool = Field(description="Vrai seulement si le document est un relevé de compte bancaire "
                                         "(liste d'opérations avec des soldes). Faux pour une facture, un contrat, etc.")
    compte: str = Field(description="Nom du compte tel qu'il apparaît sur le document. Réutilise un nom de la "
                                    "liste des comptes connus si c'est le même compte. Vide si introuvable.")
    banque_code: str = Field(description="Code de la banque, parmi la liste fournie. AUTRE si aucune ne convient.")
    type_code: str = Field(description="Type de compte, parmi la liste fournie. EXPLOITATION par défaut.")
    numero_masque: str = Field(description="Les 4 derniers chiffres du numéro de compte seulement, sinon vide.")
    periode: str = Field(description="Mois couvert par le relevé, au format AAAA-MM. Si le relevé couvre "
                                     "plusieurs mois, le premier mois. Vide si illisible.")
    confiance: float = Field(ge=0, le=1, description="Ta certitude sur l'ensemble de la réponse, entre 0 et 1.")
    justification: str = Field(description="Une phrase : les indices qui fondent la réponse.")


# --------------------------------------------------------------------------- #
# Base : table de classement et registre des comptes
# --------------------------------------------------------------------------- #
def _connexion(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute(_SCHEMA_TABLE)
    return conn


def _empreinte(chemin: str) -> str:
    with open(chemin, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _referentiel(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r[0] for r in conn.execute(f"SELECT code FROM {table}")}


def _nom_entreprise(conn: sqlite3.Connection) -> str:
    row = conn.execute("SELECT valeur FROM parametres WHERE domaine='general' AND cle='entreprise'").fetchone()
    return row[0] if row else "Entreprise"


def _hash_compte(banque: str, numero_masque: str, compte: str) -> str:
    cle = f"{banque}|{numero_masque}" if numero_masque else f"{banque}|{normaliser_compte(compte)}"
    return hashlib.sha256(cle.encode("utf-8")).hexdigest()


def assurer_compte(conn: sqlite3.Connection, compte: str, banque: str, type_code: str, numero_masque: str) -> int:
    """Retourne l'identifiant mdm_compte du compte ; le crée s'il n'existe pas.
    Reconnu par banque + 4 derniers chiffres, ou à défaut par nom."""
    numero_hash = _hash_compte(banque, numero_masque, compte)
    row = conn.execute("SELECT compte_id FROM mdm_compte WHERE banque_code=? AND numero_hash=?",
                       (banque, numero_hash)).fetchone()
    if row:
        return row[0]
    # Le nom du compte sert d'identifiant dans le journal (compte_source) : deux comptes ne le partagent pas,
    # même si le LLM a répondu une autre banque d'un mois à l'autre.
    for cid, libelle in conn.execute("SELECT compte_id, libelle FROM mdm_compte"):
        if libelle and normaliser_compte(libelle) == normaliser_compte(compte):
            return cid

    entite = conn.execute("SELECT entite_id FROM mdm_entite_juridique ORDER BY entite_id LIMIT 1").fetchone()
    if entite is None:
        conn.execute("INSERT INTO mdm_entite_juridique (nom_legal, nom_court) VALUES (?, ?)",
                     (_nom_entreprise(conn), _nom_entreprise(conn)))
        entite = conn.execute("SELECT entite_id FROM mdm_entite_juridique ORDER BY entite_id LIMIT 1").fetchone()
    cur = conn.execute(
        "INSERT INTO mdm_compte (entite_id, banque_code, type_code, devise_code, numero_masque, numero_hash, libelle, actif) "
        "VALUES (?, ?, ?, 'CAD', ?, ?, ?, 1)",
        (entite[0], banque, type_code, f"****{numero_masque}" if numero_masque else "non précisé", numero_hash, compte))
    return cur.lastrowid


def comptes_connus(conn: sqlite3.Connection) -> list[str]:
    return [f"« {libelle} » ({banque}, se termine par {num or '?'})"
            for libelle, banque, num in conn.execute(
                "SELECT libelle, banque_code, numero_masque FROM mdm_compte WHERE actif=1 ORDER BY libelle")]


# --------------------------------------------------------------------------- #
# Lecture du début du document
# --------------------------------------------------------------------------- #
def texte_document(chemin: str) -> str:
    """Premières lignes lisibles du document : texte des premières pages (PDF) ou en-tête et premières lignes (CSV/Excel)."""
    ext = os.path.splitext(chemin)[1].lower()
    if ext == ".pdf":
        import pdfplumber
        with pdfplumber.open(chemin) as pdf:
            texte = "\n".join((p.extract_text() or "") for p in pdf.pages[:PAGES_PDF])
    else:
        import pandas as pd
        if ext == ".csv":
            df = pd.read_csv(chemin, sep=None, engine="python", header=None, dtype=str, nrows=LIGNES_TABLEAU,
                             keep_default_na=False, encoding_errors="replace")
        else:
            df = pd.read_excel(chemin, header=None, dtype=str, nrows=LIGNES_TABLEAU, keep_default_na=False)
        texte = df.to_string(header=False, index=False)
    return texte[:MAX_CARACTERES]


# --------------------------------------------------------------------------- #
# Appel au LLM
# --------------------------------------------------------------------------- #
def _consigne(comptes: list[str], banques: set[str], types: set[str]) -> str:
    return (
        "Tu classes un document financier reçu par une entreprise.\n"
        "Dis seulement s'il s'agit d'un relevé de compte bancaire, identifie le compte et le mois couvert.\n"
        "Ne calcule rien. En cas de doute, mets une confiance basse.\n"
        f"Codes de banque possibles : {', '.join(sorted(banques))}.\n"
        f"Types de compte possibles : {', '.join(sorted(types))}.\n"
        f"Comptes déjà connus de l'entreprise : {'; '.join(comptes) or 'aucun'}."
    )


def classer_document(chemin: str, conn: sqlite3.Connection) -> tuple[Optional[ClassementDocument], str]:
    """Interroge le LLM sur un document. Retourne (classement ou None, raison)."""
    try:
        texte = texte_document(chemin)
    except Exception as e:
        return None, f"document illisible ({type(e).__name__})"
    if not texte.strip():
        return None, "aucun texte lisible (scan sans OCR ?)"

    prompt = (f"{_consigne(comptes_connus(conn), _referentiel(conn, 'ref_banque'), _referentiel(conn, 'ref_compte_type'))}\n\n"
              f"Nom du fichier : {os.path.basename(chemin)}\n\nDébut du document :\n{texte}")
    try:
        rep = llm_f.invoquer("A1", prompt, schema=ClassementDocument, max_tokens=400, defaut=MODELE_CLASSEMENT)
    except Exception as e:
        return None, f"appel au LLM en échec ({type(e).__name__})"
    return rep.parse, "ok"


_MOIS_NOMS = {1: ("JANVIER", "JANUARY"), 2: ("FEVRIER", "FEBRUARY"), 3: ("MARS", "MARCH"), 4: ("AVRIL", "APRIL"), 5: ("MAI", "MAY"),
              6: ("JUIN", "JUNE"), 7: ("JUILLET", "JULY"), 8: ("AOUT", "AUGUST"), 9: ("SEPTEMBRE", "SEPTEMBER"),
              10: ("OCTOBRE", "OCTOBER"), 11: ("NOVEMBRE", "NOVEMBER"), 12: ("DECEMBRE", "DECEMBER")}
DOSSIER_IDENTIFICATIONS = os.path.join(os.path.dirname(DOSSIER_LECTURES_LLM), "identification_llm")


def _periode_dans_texte(periode: str, texte: str) -> bool:
    """Le mois annoncé par le LLM figure-t-il dans le document ? (AAAA-MM, ou nom du mois + année)"""
    annee, mois = periode[:4], int(periode[5:])
    t = _sans_accents(texte)
    return periode in texte or (annee in t and any(nom in t for nom in _MOIS_NOMS[mois]))


def _sans_accents(s: str) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", s.upper()) if unicodedata.category(c) != "Mn")


def identifier_document(chemin: str, connus: Optional[list] = None) -> dict:
    """Compte et mois d'un document au nom non reconnu, SANS exiger que sa mise en page soit lisible par le lecteur natif.
    Retourne {ok, compte, periode, confiance, raison}. Le LLM propose ; le mois doit figurer dans le texte du document
    (ou, si le lecteur natif lit le document, coïncider avec le mois de ses opérations). Résultat mis en cache par empreinte."""
    empreinte = _empreinte(chemin)
    fichier = os.path.join(DOSSIER_IDENTIFICATIONS, empreinte + ".json")
    if os.path.isfile(fichier):
        with open(fichier, encoding="utf-8") as f:
            return json.load(f)

    def fin(ok, compte="", periode="", confiance=0.0, raison=""):
        res = {"ok": ok, "compte": compte, "periode": periode, "confiance": confiance, "raison": raison}
        if confiance:                   # une panne d'appel (confiance 0) n'est pas mise en cache : elle sera retentée
            os.makedirs(DOSSIER_IDENTIFICATIONS, exist_ok=True)
            with open(fichier, "w", encoding="utf-8") as f:
                json.dump(res, f, ensure_ascii=False, indent=1)
        return res

    if llm_f.fournisseur() == "simule":
        return fin(False, raison="aucun LLM sélectionné")
    try:
        texte = texte_document(chemin)
    except Exception as e:                                                      # noqa: BLE001
        return fin(False, raison=f"document illisible ({type(e).__name__})")
    if not texte.strip():
        return fin(False, raison="aucun texte lisible (scan sans OCR ?)")
    prompt = ("Tu classes un document financier reçu par une entreprise.\n"
              "Dis s'il s'agit d'un relevé de compte bancaire, donne l'intitulé du compte principal tel qu'imprimé "
              "(sans adresse ni nom de client) et le mois couvert au format AAAA-MM. Ne calcule rien ; "
              "en cas de doute, confiance basse. Codes de banque possibles : DESJ, BNC, RBC, TD, BMO, SCOTIA, CIBC, AUTRE. "
              "Types possibles : EXPLOITATION, PAIE, DEVISES, EPARGNE, MARGE, CARTE_CREDIT, PLACEMENT.\n"
              f"Comptes déjà connus (réutilise le même nom pour le même compte) : {'; '.join(connus or []) or 'aucun'}.\n\n"
              f"Nom du fichier : {os.path.basename(chemin)}\n\nDébut du document :\n{texte}")
    try:
        res = llm_f.invoquer("A1", prompt, schema=ClassementDocument, max_tokens=400, defaut=MODELE_CLASSEMENT).parse
    except Exception as e:                                                      # noqa: BLE001
        return fin(False, raison=f"appel au LLM en échec ({type(e).__name__})")

    def decider(ok, raison):
        suivi.decider(llm_f.dernier_trace_id(), "acceptée" if ok else "escaladée", raison)
        return fin(ok, (res.compte or "").strip() if ok else "", res.periode if ok else "", max(res.confiance, 0.01), raison)

    if not res.est_releve:
        return decider(False, "le document n'est pas un relevé de compte")
    if res.confiance < SEUIL_CLASSEMENT:
        return decider(False, f"confiance {res.confiance:.2f} < seuil {SEUIL_CLASSEMENT:.2f}")
    if not (res.compte or "").strip():
        return decider(False, "nom du compte introuvable")
    if not _RE_PERIODE.match(res.periode or "") or not 1 <= int(res.periode[5:]) <= 12:
        return decider(False, f"mois illisible « {res.periode} »")
    try:
        lec = lire_releve(chemin)
    except Exception:                                                           # noqa: BLE001
        lec = None
    if lec is not None and lec.format and lec.transactions:
        mois = {t["date"][:7] for t in lec.transactions}
        if mois != {res.periode}:
            return decider(False, f"mois du LLM ({res.periode}) ≠ mois des opérations ({', '.join(sorted(mois))})")
    elif not _periode_dans_texte(res.periode, texte):
        return decider(False, f"le mois {res.periode} ne figure pas dans le document")
    return decider(True, f"relevé de « {res.compte.strip()} », {res.periode}, confiance {res.confiance:.2f}")


def _decision(chemin: str, res: Optional[ClassementDocument], raison: str) -> tuple[bool, str, str]:
    """Accepte ou refuse un classement. Retourne (accepté, raison lisible, mois AAAA-MM).

    Le LLM propose ; le parseur déterministe vérifie. Un document n'est retenu que si ses opérations
    se lisent dans une mise en page de relevé et tombent toutes dans le même mois."""
    if res is None:
        return False, raison, ""
    if not res.est_releve:
        return False, "le document n'est pas un relevé de compte", ""
    if res.confiance < SEUIL_CLASSEMENT:
        return False, f"confiance {res.confiance:.2f} < seuil {SEUIL_CLASSEMENT:.2f}", ""
    if not (res.compte or "").strip():
        return False, "nom du compte introuvable", ""
    try:
        lec = lire_releve(chemin)
    except Exception as e:
        return False, f"relevé illisible ({type(e).__name__})", ""
    if lec.format is None or not lec.transactions:
        return False, "aucune opération lue dans une mise en page de relevé (le LLM s'est trompé ?)", ""
    mois = {t["date"][:7] for t in lec.transactions}
    if len(mois) > 1:
        return False, f"opérations sur plusieurs mois ({', '.join(sorted(mois))}) : un document par mois", ""
    mois_doc = mois.pop()
    if _RE_PERIODE.match(res.periode or "") and res.periode != mois_doc:
        return False, f"mois du LLM ({res.periode}) ≠ mois des opérations ({mois_doc})", ""
    return True, (f"relevé de « {res.compte} », {mois_doc}, {len(lec.transactions)} opération(s) lues, "
                  f"confiance {res.confiance:.2f}"), mois_doc


# --------------------------------------------------------------------------- #
# Point d'entrée : classer le dossier, puis résoudre un nom de fichier
# --------------------------------------------------------------------------- #
def classer_dossier(dossier: str, db_path: str) -> dict:
    """Classe les documents du dossier que la convention de nom ne reconnaît pas.
    Retourne {classes, refuses, ignores_sans_llm, comptes_crees}. Sans LLM configuré, rien n'est classé."""
    resume = {"classes": [], "refuses": [], "deja_classes": 0, "sans_llm": False}
    if not os.path.isdir(dossier):
        return resume
    conn = _connexion(db_path)
    try:
        for nom in sorted(os.listdir(dossier)):
            chemin = os.path.join(dossier, nom)
            if os.path.splitext(nom)[1].lower() not in EXTENSIONS or analyser_nom_fichier(nom):
                continue
            empreinte = _empreinte(chemin)
            deja = conn.execute("SELECT sha256, est_releve FROM classement_documents WHERE nom_fichier=?", (nom,)).fetchone()
            if deja and deja[0] == empreinte:
                resume["deja_classes"] += 1
                continue
            if llm_f.fournisseur() == "simule":
                resume["sans_llm"] = True
                continue

            res, raison_appel = classer_document(chemin, conn)
            accepte, raison, mois = _decision(chemin, res, raison_appel)
            suivi.decider(llm_f.dernier_trace_id(), "acceptée" if accepte else "escaladée", raison)

            if accepte:
                banque = res.banque_code if res.banque_code in _referentiel(conn, "ref_banque") else "AUTRE"
                type_code = res.type_code if res.type_code in _referentiel(conn, "ref_compte_type") else "EXPLOITATION"
                numero = re.sub(r"\D", "", res.numero_masque or "")[-4:]
                compte_id = assurer_compte(conn, res.compte.strip(), banque, type_code, numero)
                libelle = conn.execute("SELECT libelle FROM mdm_compte WHERE compte_id=?", (compte_id,)).fetchone()[0]
                _enregistrer(conn, nom, empreinte, True, libelle, banque, type_code, numero, mois, res.confiance,
                             res.justification, raison)
                resume["classes"].append({"fichier": nom, "compte": libelle, "periode": mois})
            else:
                if res is not None:     # un refus motivé est mis en cache ; une panne d'appel sera retentée au prochain passage
                    _enregistrer(conn, nom, empreinte, False, None, None, None, None, None,
                                 res.confiance, res.justification, raison)
                resume["refuses"].append({"fichier": nom, "raison": raison})
        conn.commit()
    finally:
        conn.close()
    return resume


def _enregistrer(conn, nom, empreinte, est_releve, compte, banque, type_code, numero, periode, confiance,
                 justification, raison):
    conn.execute(
        "INSERT OR REPLACE INTO classement_documents (nom_fichier, sha256, est_releve, compte, banque_code, type_code, "
        "numero_masque, periode, confiance, justification, raison) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (nom, empreinte, int(est_releve), compte, banque, type_code, numero, periode, confiance, justification, raison))


def analyser_document(nom: str, db_path: Optional[str]) -> Optional[tuple[str, str, str]]:
    """Compte, mois et convention d'un fichier. D'abord la convention de nom, puis le classement LLM accepté.
    Retourne (compte, 'AAAA-MM', convention) ou None. Convention « llm » pour un fichier classé par le modèle."""
    info = analyser_nom_fichier(nom)
    if info or not db_path or not os.path.isfile(db_path):
        return info
    conn = _connexion(db_path)
    try:
        row = conn.execute("SELECT compte, periode, confiance FROM classement_documents "
                           "WHERE nom_fichier=? AND est_releve=1", (nom,)).fetchone()
    finally:
        conn.close()
    if row and row[2] >= SEUIL_CLASSEMENT and row[0] and row[1]:
        return row[0], row[1], "llm"
    return None
