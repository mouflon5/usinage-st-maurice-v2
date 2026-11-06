"""
Lecture des relevés bancaires — 4 mises en page PDF, plus les exports tabulaires CSV / Excel.

    F1  « Signé »          2026-05-14  DESCRIPTION            -1234.50     9876.54      (format d'origine, ex. Desjardins EOP)
    F2  « Débit / Crédit » 14/05/2026  DESCRIPTION   [débit] [crédit]   solde (1 234,50)  → sens selon la colonne
    F3  « Date courte »    May 14      DESCRIPTION      1,234.50 DR     9,876.54 CR       → année tirée de « Statement period »
    F4  « Parenthèses »    14-05-2026  DESCRIPTION        (1 234,50)     9 876,54         → négatif entre parenthèses
    CSV / XLSX  en-têtes lus par NOM (date, description/libellé, montant ou débit+crédit, solde) — voir _lire_tabulaire

Principes (identiques à l'A2 d'origine) :
  * Prudence : une ligne du corps du relevé qui n'est pas reconnue est REJETÉE (jamais devinée, jamais ignorée).
  * Les colonnes des formats F2 à F4 sont lues par POSITION (x) à partir de la ligne d'en-tête du tableau,
    pas par découpage de texte : « FACT 123 456,78 » reste lisible sans ambiguïté.
  * Un format est retenu par fichier, d'après l'en-tête du tableau puis le nombre de lignes lues.

Ce module ne dépend pas du générateur de tests : les dimensions sont déduites de la ligne d'en-tête du PDF.
"""

import hashlib
import io
import json
import os
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

import pdfplumber

# --------------------------------------------------------------------------- #
# Noms de fichier (utilisé par A1 et A2) — 4 conventions, extensions .pdf / .csv / .xlsx
# --------------------------------------------------------------------------- #
EXTENSIONS = (".pdf", ".csv", ".xlsx")
_EXT = r"\.(?:pdf|csv|xlsx)$"
_NOMS = [
    (re.compile(r"^(?P<compte>.+?)_(?P<a>\d{4})-(?P<m>\d{2})" + _EXT, re.I), "a"),          # Compte_2026-05.pdf
    (re.compile(r"^(?P<compte>.+?)\s+-\s+(?P<a>\d{4})-(?P<m>\d{2})" + _EXT, re.I), "b"),    # Compte - 2026-05.pdf
    (re.compile(r"^(?P<compte>.+?)_(?P<a>\d{4})(?P<m>\d{2})" + _EXT, re.I), "c"),           # Compte_202605.pdf
    (re.compile(r"^(?P<compte>.+?)_(?P<m>\d{2})-(?P<a>\d{4})" + _EXT, re.I), "d"),          # Compte_05-2026.pdf
]


def analyser_nom_fichier(nom: str):
    """Retourne (compte, 'AAAA-MM', convention) ou None si le nom n'est pas reconnu."""
    for rx, conv in _NOMS:
        m = rx.match(nom)
        if m and 1 <= int(m.group("m")) <= 12:
            return m.group("compte"), f"{m.group('a')}-{m.group('m')}", conv
    return None


def normaliser_compte(s: Optional[str]) -> str:
    return re.sub(r"\s+", " ", (s or "").replace(" ", " ")).strip().casefold()


# --------------------------------------------------------------------------- #
# Résultat de lecture
# --------------------------------------------------------------------------- #
@dataclass
class Lecture:
    format: Optional[str] = None
    transactions: list = field(default_factory=list)
    rejetees: list = field(default_factory=list)
    solde_ouverture: Optional[float] = None
    solde_cloture: Optional[float] = None
    compte_entete: Optional[str] = None
    periode_entete: Optional[tuple] = None        # (debut ISO, fin ISO)


# --------------------------------------------------------------------------- #
# Utilitaires
# --------------------------------------------------------------------------- #
RE_PAGE = re.compile(r"^(page|p\.)\s*\d+\s*(de|of|/|sur)\s*\d+$", re.I)
RE_OUVERTURE = re.compile(r"^(solde\s+(pr[ée]c[ée]dent|report[ée]|d['’]ouverture|initial)|opening balance|balance forward)$", re.I)
RE_CLOTURE = re.compile(r"^(solde\s+(final|de\s+fermeture|de\s+cl[ôo]ture)|closing balance)$", re.I)

MOIS_EN = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def _nettoyer(s: str) -> str:
    return s.replace(" ", " ").replace(" ", " ").strip()


def _date_valide(a: int, m: int, j: int) -> Optional[str]:
    try:
        return date(a, m, j).isoformat()
    except ValueError:
        return None


def _lignes_mots(page, tol=2.5):
    """Regroupe les mots d'une page en lignes (haut → bas), chaque ligne triée de gauche à droite."""
    mots = page.extract_words(x_tolerance=3, y_tolerance=3, keep_blank_chars=False)
    mots.sort(key=lambda w: (w["top"], w["x0"]))
    lignes, courant, y = [], [], None
    for w in mots:
        if y is None or abs(w["top"] - y) <= tol:
            courant.append(w)
            y = w["top"] if y is None else y
        else:
            lignes.append(sorted(courant, key=lambda t: t["x0"]))
            courant, y = [w], w["top"]
    if courant:
        lignes.append(sorted(courant, key=lambda t: t["x0"]))
    return lignes


def _texte(ligne) -> str:
    return _nettoyer(" ".join(w["text"] for w in ligne))


def _clusters(mots, ecart=8.0):
    """Regroupe des mots contigus (espace de milliers inclus) en cellules."""
    out = []
    for w in sorted(mots, key=lambda t: t["x0"]):
        if out and w["x0"] - out[-1][-1]["x1"] <= ecart:
            out[-1].append(w)
        else:
            out.append([w])
    return out


# --------------------------------------------------------------------------- #
# F1 — format d'origine (ligne de texte signée). Comportement conservé tel quel.
# --------------------------------------------------------------------------- #
LIGNE_F1 = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})\s+(?P<description>.+?)\s+"
    r"(?P<montant>-?\d+\.\d{2})\s+(?P<solde>-?\d+\.\d{2})\s*$"
)
RE_ENTETE_F1 = re.compile(r"^Relev[ée] de compte\s+(?P<compte>.+)$", re.I)


def _lire_f1(pdf) -> Lecture:
    lec = Lecture(format="F1")
    for page in pdf.pages:
        for brut in (page.extract_text() or "").splitlines():
            t = _nettoyer(brut)
            if not t:
                continue
            m_ent = RE_ENTETE_F1.match(t)
            if m_ent:
                lec.compte_entete = lec.compte_entete or m_ent.group("compte").strip()
                continue
            if RE_PAGE.match(t):
                continue
            m = LIGNE_F1.match(t)
            d = m and _date_valide(int(m.group("date")[:4]), int(m.group("date")[5:7]), int(m.group("date")[8:]))
            if m and d:
                lec.transactions.append({"date": d, "description": m.group("description").strip(),
                                         "montant": float(m.group("montant")), "solde": float(m.group("solde"))})
            else:
                lec.rejetees.append(t)
    return lec


# --------------------------------------------------------------------------- #
# F2 à F4 — tableaux lus par colonnes
# --------------------------------------------------------------------------- #
_FR_PLAIN = r"\d{1,3}(?: \d{3})*,\d{2}|\d+,\d{2}"
_EN_PLAIN = r"\d{1,3}(?:,\d{3})*\.\d{2}|\d+\.\d{2}"


def _montant_f2(s: str):
    m = re.fullmatch(rf"(-?)({_FR_PLAIN})", s)
    return None if not m else (-1 if m.group(1) else 1) * float(m.group(2).replace(" ", "").replace(",", "."))


def _montant_f3(s: str):
    m = re.fullmatch(rf"({_EN_PLAIN}) (DR|CR)", s)
    if not m:
        return None
    v = float(m.group(1).replace(",", ""))
    return -v if m.group(2) == "DR" else v


def _montant_f4(s: str):
    m = re.fullmatch(rf"(\()?({_FR_PLAIN})(\))?", s)
    if not m or bool(m.group(1)) != bool(m.group(3)):
        return None
    v = float(m.group(2).replace(" ", "").replace(",", "."))
    return -v if m.group(1) else v


def _date_f2(s, ctx):
    m = re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})", s)
    return m and _date_valide(int(m.group(3)), int(m.group(2)), int(m.group(1)))


def _date_f4(s, ctx):
    m = re.fullmatch(r"(\d{2})-(\d{2})-(\d{4})", s)
    return m and _date_valide(int(m.group(3)), int(m.group(2)), int(m.group(1)))


def _date_f3(s, ctx):
    """« May 14 » : l'année vient de la période du relevé ; hors période → rejet."""
    m = re.fullmatch(r"([A-Za-z]{3}) (\d{1,2})", s)
    per = ctx.get("periode")
    if not m or m.group(1).lower() not in MOIS_EN or not per:
        return None
    mois, jour = MOIS_EN[m.group(1).lower()], int(m.group(2))
    d0, d1 = date.fromisoformat(per[0]), date.fromisoformat(per[1])
    for a in sorted({d0.year, d1.year}):
        iso = _date_valide(a, mois, jour)
        if iso and per[0] <= iso <= per[1]:
            return iso
    return None


_RE_PER_F2 = re.compile(r"P[ée]riode\s*:?\s*(\d{2})/(\d{2})/(\d{4})\s+au\s+(\d{2})/(\d{2})/(\d{4})", re.I)
_RE_PER_F4 = re.compile(r"P[ée]riode du\s+(\d{2})-(\d{2})-(\d{4})\s+au\s+(\d{2})-(\d{2})-(\d{4})", re.I)
_RE_PER_F3 = re.compile(r"Statement period:?\s*([A-Za-z]{3}) (\d{1,2}), (\d{4})\s*-\s*([A-Za-z]{3}) (\d{1,2}), (\d{4})", re.I)


def _per_jma(m):
    return _date_valide(int(m.group(3)), int(m.group(2)), int(m.group(1))), _date_valide(int(m.group(6)), int(m.group(5)), int(m.group(4)))


def _per_f3(m):
    a, b = m.group(1).lower(), m.group(4).lower()
    if a not in MOIS_EN or b not in MOIS_EN:
        return None, None
    return (_date_valide(int(m.group(3)), MOIS_EN[a], int(m.group(2))), _date_valide(int(m.group(6)), MOIS_EN[b], int(m.group(5))))


TABLEAUX = {
    "F2": dict(montants=("débit", "crédit"), alias={"debit": "débit", "credit": "crédit"}, solde=("solde",),
               parse=_montant_f2, date=_date_f2, rx_per=_RE_PER_F2, per=_per_jma,
               rx_compte=re.compile(r"^Compte\s*:\s*(?P<c>.+)$", re.I), mode="colonnes"),
    "F3": dict(montants=("amount",), alias={}, solde=("balance",),
               parse=_montant_f3, date=_date_f3, rx_per=_RE_PER_F3, per=_per_f3,
               rx_compte=re.compile(r"^Account\s*:\s*(?P<c>.+)$", re.I), mode="unique"),
    "F4": dict(montants=("montant",), alias={}, solde=("solde",),
               parse=_montant_f4, date=_date_f4, rx_per=_RE_PER_F4, per=_per_jma,
               rx_compte=re.compile(r"^Compte n[°o]\s*(?P<c>.+)$", re.I), mode="unique"),
}


def _entete_tableau(lignes, cfg):
    """Repère la ligne d'en-tête (Date / Description / colonnes de montant / Solde) et en déduit les colonnes."""
    for i, ln in enumerate(lignes):
        noms = {w["text"].lower(): w for w in ln}
        noms = {cfg["alias"].get(k, k): v for k, v in noms.items()}
        if "description" in noms and any(s in noms for s in cfg["solde"]) and all(m in noms for m in cfg["montants"]):
            return i, {
                "desc_x0": noms["description"]["x0"],
                "montants": {m: noms[m]["x1"] for m in cfg["montants"]},
                "solde_x1": next(noms[s]["x1"] for s in cfg["solde"] if s in noms),
            }
    return None, None


def _lire_tableau(pdf, nom_fmt: str) -> Lecture:
    cfg = TABLEAUX[nom_fmt]
    lec = Lecture(format=None)
    pages = [_lignes_mots(p) for p in pdf.pages]
    colonnes = None
    ctx = {}
    # 1) en-têtes (compte, période) : toutes pages, avant et pendant le tableau
    for lignes in pages:
        for ln in lignes:
            t = _texte(ln)
            mp = cfg["rx_per"].search(t)
            if mp and not lec.periode_entete:
                d0, d1 = cfg["per"](mp)
                if d0 and d1:
                    lec.periode_entete = (d0, d1)
                    ctx["periode"] = (d0, d1)
            mc = cfg["rx_compte"].match(t)
            if mc and not lec.compte_entete:
                lec.compte_entete = mc.group("c").strip()
    # 2) corps
    for lignes in pages:
        h, cols = _entete_tableau(lignes, cfg)
        if cols:
            colonnes, debut = cols, h + 1
            lec.format = nom_fmt
        else:
            debut = 0 if colonnes else len(lignes)       # page sans en-tête : on réutilise les colonnes connues
        if not colonnes:
            continue
        for ln in lignes[debut:]:
            t = _texte(ln)
            if not t or RE_PAGE.match(t):
                continue
            ok = _ligne_tableau(ln, t, cfg, colonnes, ctx, lec)
            if not ok:
                lec.rejetees.append(t)
    return lec


def _ligne_tableau(ln, texte, cfg, col, ctx, lec) -> bool:
    mots_date = [w for w in ln if w["x1"] <= col["desc_x0"] - 2.0]
    reste = [w for w in ln if all(w is not d for d in mots_date)]

    # Cellules de montant : lues de DROITE à GAUCHE, tant qu'un groupe de mots est aligné sur une colonne de l'en-tête.
    # Le premier groupe qui n'est sur aucune colonne marque le début de la description.
    cibles = {**col["montants"], "_solde": col["solde_x1"]}
    groupes = _clusters(reste, ecart=7.5)
    cellules, k = {}, len(groupes)
    while k > 0:
        cl = groupes[k - 1]
        nom, dist = min(((n, abs(cl[-1]["x1"] - x)) for n, x in cibles.items()), key=lambda a: a[1])
        if dist > 20:
            break
        if nom in cellules:
            return False
        cellules[nom] = _nettoyer(" ".join(w["text"] for w in cl))
        k -= 1
    desc = _nettoyer(" ".join(w["text"] for g in groupes[:k] for w in g))

    if not mots_date:                                    # ligne de solde d'ouverture / de clôture
        if set(cellules) == {"_solde"} and desc:
            v = cfg["parse"](cellules["_solde"]) if cfg["mode"] == "unique" else _montant_f2(cellules["_solde"])
            if v is not None and RE_OUVERTURE.match(desc):
                lec.solde_ouverture = v
                return True
            if v is not None and RE_CLOTURE.match(desc):
                lec.solde_cloture = v
                return True
        return False

    iso = cfg["date"](_nettoyer(" ".join(w["text"] for w in mots_date)), ctx)
    if not iso or not desc or "_solde" not in cellules:
        return False
    solde = cfg["parse"](cellules["_solde"]) if cfg["mode"] == "unique" else _montant_f2(cellules["_solde"])
    montants = [n for n in cellules if n != "_solde"]
    if solde is None or len(montants) != 1:
        return False
    if cfg["mode"] == "colonnes":
        v = _montant_f2(cellules[montants[0]])
        if v is None or v < 0:
            return False
        montant = -v if montants[0] == "débit" else v
    else:
        montant = cfg["parse"](cellules[montants[0]])
        if montant is None:
            return False
    lec.transactions.append({"date": iso, "description": desc, "montant": round(montant, 2), "solde": round(solde, 2)})
    return True


# --------------------------------------------------------------------------- #
# CSV / Excel — en-têtes lus par NOM
# --------------------------------------------------------------------------- #
_COLONNES = {
    "date": {"date", "date de transaction", "date operation", "date de l operation", "transaction date", "date valeur"},
    "description": {"description", "libelle", "details", "detail", "memo", "transaction", "nom", "description de la transaction"},
    "montant": {"montant", "amount", "montant net"},
    "debit": {"debit", "retrait", "retraits", "withdrawal", "withdrawals"},
    "credit": {"credit", "depot", "depots", "deposit", "deposits"},
    "solde": {"solde", "balance", "solde courant", "solde apres"},
}


def _cle_colonne(s) -> str:
    t = unicodedata.normalize("NFD", str(s).lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9 ]+", " ", t).strip()


def _nombre(s) -> Optional[float]:
    """« 1 234,50 », « 1,234.50 », « (45.00) », « -45,00 $ » → float ; None si ce n'est pas un nombre sans ambiguïté."""
    t = _nettoyer(str(s)).replace("$", "").replace(" ", "").strip()
    if not t:
        return None
    neg = t.startswith("(") and t.endswith(")")
    t = t.strip("()")
    if t.endswith("-"):
        neg, t = True, t[:-1]
    if "," in t and "." in t:
        t = t.replace(",", "") if t.rfind(".") > t.rfind(",") else t.replace(".", "").replace(",", ".")
    elif "," in t:
        t = t.replace(",", ".") if re.fullmatch(r"-?\d+,\d{1,2}", t) else t.replace(",", "")
    if not re.fullmatch(r"[+-]?\d+(\.\d+)?", t):
        return None
    v = float(t)
    return round(-abs(v) if neg else v, 2)


def _date_tabulaire(s) -> Optional[str]:
    t = _nettoyer(str(s))
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})(?:[ T].*)?$", t)
    if m:
        return _date_valide(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.fullmatch(r"(\d{2})[/-](\d{2})[/-](\d{4})", t)           # jour/mois/année (convention canadienne-française)
    return _date_valide(int(m.group(3)), int(m.group(2)), int(m.group(1))) if m else None


def _lire_tabulaire(chemin: str) -> Lecture:
    import pandas as pd
    ext = os.path.splitext(chemin)[1].lower()
    if ext == ".csv":
        brut = open(chemin, "rb").read()
        texte = None
        for enc in ("utf-8-sig", "cp1252"):
            try:
                texte = brut.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        if not texte or not texte.strip():
            return Lecture(format=None)
        df = pd.read_csv(io.StringIO(texte), sep=None, engine="python", header=None, dtype=str, keep_default_na=False)
        fmt = "CSV"
    else:
        df = pd.read_excel(chemin, header=None, dtype=str, keep_default_na=False)
        fmt = "XLSX"
    if df.empty:
        return Lecture(format=None)

    entete, col = None, {}
    for i in range(min(25, len(df))):                              # des lignes de titre peuvent précéder l'en-tête
        cles = [_cle_colonne(c) for c in df.iloc[i]]
        trouve = {nom: cles.index(a) for nom, alias in _COLONNES.items() for a in alias if a in cles}
        if "date" in trouve and "description" in trouve:
            entete, col = i, trouve
            break
    inconnu = Lecture(format=None)
    if entete is None:
        inconnu.rejetees.append("En-tête non reconnu : colonnes « date » et « description » (ou « libellé ») introuvables")
        return inconnu
    manque = []
    if "montant" not in col and not ("debit" in col and "credit" in col):
        manque.append("« montant » (ou « débit » et « crédit »)")
    if "solde" not in col:
        manque.append("« solde » (sans lui, la continuité des soldes ne peut pas être vérifiée)")
    if manque:
        inconnu.rejetees.append("Colonne(s) obligatoire(s) absente(s) : " + ", ".join(manque))
        return inconnu

    lec = Lecture(format=fmt)
    for _, ligne in df.iloc[entete + 1:].iterrows():
        v = [str(x) for x in ligne]
        if not any(x.strip() for x in v):
            continue
        brut = " | ".join(x.strip() for x in v if x.strip())
        iso = _date_tabulaire(v[col["date"]])
        desc = _nettoyer(v[col["description"]])
        solde = _nombre(v[col["solde"]])
        if "montant" in col:
            montant = _nombre(v[col["montant"]])
        else:
            deb, cre = _nombre(v[col["debit"]]), _nombre(v[col["credit"]])
            montant = None if (deb is None) == (cre is None) else (-abs(deb) if deb is not None else abs(cre))
        if not iso or not desc or montant is None or solde is None:
            lec.rejetees.append(brut)
            continue
        lec.transactions.append({"date": iso, "description": desc, "montant": round(montant, 2), "solde": round(solde, 2)})
    return lec


# --------------------------------------------------------------------------- #
# Point d'entrée
# --------------------------------------------------------------------------- #
DOSSIER_LECTURES_LLM = os.path.join(os.path.dirname(os.path.abspath(__file__)), "demo_live", "donnees", "lecture_llm")


def empreinte_fichier(chemin: str) -> str:
    with open(chemin, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _lecture_validee(chemin: str) -> Optional[Lecture]:
    """Lecture faite par le LLM puis VALIDÉE par l'utilisateur (voir lecture_llm.py), retrouvée par l'empreinte du contenu :
    elle suit le fichier même renommé ou recopié. None si le document n'a pas de lecture validée."""
    fichier = os.path.join(DOSSIER_LECTURES_LLM, empreinte_fichier(chemin) + ".json")
    if not os.path.isfile(fichier):
        return None
    with open(fichier, encoding="utf-8") as f:
        data = json.load(f)
    trans = data.get("transactions") or []
    return Lecture(format="LLM", transactions=trans, solde_ouverture=data.get("solde_ouverture"),
                   solde_cloture=trans[-1]["solde"] if trans else None)


def lire_releve(chemin: str) -> Lecture:
    """Lit un relevé (PDF, CSV ou Excel). Lève une exception si le fichier est illisible.
    `format` = None si aucune mise en page n'est reconnue (le fichier est alors à refuser).
    Si le lecteur déterministe échoue (format inconnu ou lignes rejetées) et que l'utilisateur a validé une lecture
    par le LLM de ce document, c'est cette lecture qui est retournée (format « LLM »)."""
    lec = _lire_releve_natif(chemin)
    if lec.format is None or lec.rejetees:
        validee = _lecture_validee(chemin)
        if validee:
            return validee
    return lec


def _lire_releve_natif(chemin: str) -> Lecture:
    if os.path.splitext(chemin)[1].lower() in (".csv", ".xlsx"):
        return _lire_tabulaire(chemin)
    with pdfplumber.open(chemin) as pdf:
        candidats = []
        for nom in ("F2", "F3", "F4"):
            lec = _lire_tableau(pdf, nom)
            if lec.format:
                candidats.append((1000 + len(lec.transactions), lec))     # en-tête de tableau trouvé : très fort indice
        lec1 = _lire_f1(pdf)
        if lec1.transactions or lec1.compte_entete:       # en-tête « Relevé de compte » seul = relevé sans opération
            candidats.append((len(lec1.transactions), lec1))
        if candidats:
            candidats.sort(key=lambda c: -c[0])
            return candidats[0][1]
        # aucun format reconnu : on remonte les lignes de texte comme « non reconnues »
        inconnu = Lecture(format=None)
        for page in pdf.pages:
            for brut in (page.extract_text() or "").splitlines():
                t = _nettoyer(brut)
                if t and not RE_PAGE.match(t) and not RE_ENTETE_F1.match(t):
                    inconnu.rejetees.append(t)
        return inconnu
