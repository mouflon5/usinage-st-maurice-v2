"""Outils de données maîtres et de chargement (DMBOK : Master Data & Reference Data).

- normaliser_libelle      : nettoyage commun des libellés bancaires
- categoriser_libelle     : libellé -> catégorie de flux via ref_mapping_libelle
- resoudre_contrepartie   : libellé -> contrepartie (alias exact, approximatif ou nouvelle à valider)
- fusionner_contreparties : fusion de deux contreparties (survivante + repointage)
- charger_mouvement       : insertion idempotente dans core_mouvement (hash anti-doublon)

Aucune fonction ne fait de commit : l'appelant contrôle la transaction.
"""
import difflib
import hashlib
import json
import re
import unicodedata
from datetime import date

_SUFFIXES_JURIDIQUES = {"INC", "LTEE", "LTD", "LIMITEE", "CIE", "ENR", "SENC", "CORP", "INCORPORATED"}
SEUIL_APPROX_DEFAUT = 0.88
CATEGORIES_SANS_CONTREPARTIE = {"TRF_INTERNE", "DEC_FRAIS_BANCAIRES"}


# ---------------------------------------------------------------- Normalisation
def normaliser_libelle(texte):
    """Majuscules, sans accent, sans ponctuation, sans numéros de 3 chiffres ou plus, sans suffixe juridique.

    "Hydro-Québec inc. #4432" -> "HYDRO QUEBEC"
    """
    if texte is None:
        return ""
    t = unicodedata.normalize("NFKD", str(texte))
    t = "".join(c for c in t if not unicodedata.combining(c)).upper()
    t = re.sub(r"[^A-Z0-9 ]", " ", t)
    t = re.sub(r"\b\d{3,}\b", " ", t)
    return " ".join(m for m in t.split() if m not in _SUFFIXES_JURIDIQUES)


def masquer_compte(numero):
    """Numéro de compte masqué pour affichage : ****1234."""
    chiffres = re.sub(r"\D", "", str(numero))
    return "****" + chiffres[-4:] if chiffres else "****"


def hash_numero_compte(numero, sel):
    """Empreinte salée du numéro de compte. Le sel doit être gardé hors du code (variable d'environnement)."""
    chiffres = re.sub(r"\D", "", str(numero))
    return hashlib.sha256(f"{sel}|{chiffres}".encode("utf-8")).hexdigest()


def hash_transaction(compte_id, date_operation, montant_cents, libelle_normalise, occurrence=1):
    """Empreinte d'un mouvement. 'occurrence' distingue deux opérations identiques le même jour
    dans un même fichier (1 pour la première, 2 pour la deuxième, etc.)."""
    brut = f"{compte_id}|{date_operation}|{montant_cents}|{libelle_normalise}|{occurrence}"
    return hashlib.sha256(brut.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- Catégorisation
def categoriser_libelle(conn, libelle_normalise):
    """Retourne le code de catégorie de la première règle applicable, sinon 'NON_CLASSE'."""
    regles = conn.execute(
        "SELECT motif, type_motif, categorie_code FROM ref_mapping_libelle "
        "WHERE actif = 1 ORDER BY priorite, mapping_id"
    ).fetchall()
    for motif, type_motif, categorie in regles:
        if type_motif == "regex":
            if re.search(motif, libelle_normalise):
                return categorie
            continue
        m = normaliser_libelle(motif)
        if not m:
            continue
        if type_motif == "contient" and m in libelle_normalise:
            return categorie
        if type_motif == "commence" and libelle_normalise.startswith(m):
            return categorie
    return "NON_CLASSE"


# ---------------------------------------------------------------- Contreparties
def _suivre_fusion(conn, contrepartie_id):
    """Suit la chaîne fusionne_vers_id jusqu'à la contrepartie survivante."""
    vus = set()
    courant = contrepartie_id
    while courant is not None and courant not in vus:
        vus.add(courant)
        ligne = conn.execute(
            "SELECT fusionne_vers_id FROM mdm_contrepartie WHERE contrepartie_id = ?", (courant,)
        ).fetchone()
        if ligne is None or ligne[0] is None:
            return courant
        courant = ligne[0]
    return courant


def resoudre_contrepartie(conn, libelle_brut, *, seuil=SEUIL_APPROX_DEFAUT, creer=True, source="auto"):
    """Associe un libellé à une contrepartie.

    Retourne (contrepartie_id, methode, confiance) où méthode vaut :
      'exact'   alias déjà connu
      'approx'  alias proche (similarité >= seuil) : un nouvel alias est enregistré
      'nouveau' aucune correspondance : contrepartie créée avec statut 'a_valider'
      'inconnu' aucune correspondance et creer=False
    Un cas ambigu (similarité sous le seuil) devient une nouvelle contrepartie à valider :
    mieux vaut deux doublons visibles dans la file de revue qu'une fusion erronée silencieuse.
    """
    norm = normaliser_libelle(libelle_brut)
    if not norm:
        return None, "inconnu", 0.0

    ligne = conn.execute(
        "SELECT contrepartie_id FROM mdm_contrepartie_alias WHERE alias_normalise = ?", (norm,)
    ).fetchone()
    if ligne:
        return _suivre_fusion(conn, ligne[0]), "exact", 1.0

    meilleur_ratio, meilleur_id = 0.0, None
    for alias, cid in conn.execute("SELECT alias_normalise, contrepartie_id FROM mdm_contrepartie_alias"):
        sm = difflib.SequenceMatcher(None, norm, alias)
        if sm.real_quick_ratio() < seuil or sm.quick_ratio() < seuil:
            continue
        ratio = sm.ratio()
        if ratio > meilleur_ratio:
            meilleur_ratio, meilleur_id = ratio, cid
    if meilleur_id is not None and meilleur_ratio >= seuil:
        conn.execute(
            "INSERT OR IGNORE INTO mdm_contrepartie_alias "
            "(contrepartie_id, alias_normalise, alias_brut, source, confiance) VALUES (?, ?, ?, ?, ?)",
            (meilleur_id, norm, libelle_brut, source, round(meilleur_ratio, 4)),
        )
        return _suivre_fusion(conn, meilleur_id), "approx", round(meilleur_ratio, 4)

    if not creer:
        return None, "inconnu", 0.0
    curseur = conn.execute(
        "INSERT INTO mdm_contrepartie (nom_canonique, statut_validation, source_creation) "
        "VALUES (?, 'a_valider', ?)", (norm, source),
    )
    cid = curseur.lastrowid
    conn.execute(
        "INSERT INTO mdm_contrepartie_alias (contrepartie_id, alias_normalise, alias_brut, source, confiance) "
        "VALUES (?, ?, ?, ?, 1.0)", (cid, norm, libelle_brut, source),
    )
    return cid, "nouveau", 1.0


def valider_contrepartie(conn, contrepartie_id, nom_canonique=None, type_contrepartie=None):
    """Confirme une contrepartie après revue humaine, avec nom et type optionnels."""
    conn.execute(
        "UPDATE mdm_contrepartie SET statut_validation = 'valide', "
        "nom_canonique = COALESCE(?, nom_canonique), type_contrepartie = COALESCE(?, type_contrepartie) "
        "WHERE contrepartie_id = ?",
        (nom_canonique, type_contrepartie, contrepartie_id),
    )


def fusionner_contreparties(conn, source_id, cible_id):
    """Fusionne 'source' dans 'cible' : alias et mouvements sont repointés, la source devient inactive.
    Retourne le nombre de mouvements repointés."""
    cible = _suivre_fusion(conn, cible_id)
    if source_id == cible:
        raise ValueError("Impossible de fusionner une contrepartie avec elle-même.")
    conn.execute("UPDATE mdm_contrepartie_alias SET contrepartie_id = ? WHERE contrepartie_id = ?", (cible, source_id))
    curseur = conn.execute("UPDATE core_mouvement SET contrepartie_id = ? WHERE contrepartie_id = ?", (cible, source_id))
    conn.execute("UPDATE mdm_contrepartie SET fusionne_vers_id = ? WHERE fusionne_vers_id = ?", (cible, source_id))
    conn.execute(
        "UPDATE mdm_contrepartie SET fusionne_vers_id = ?, actif = 0 WHERE contrepartie_id = ?", (cible, source_id)
    )
    return curseur.rowcount


# ---------------------------------------------------------------- Chargement
def _rejeter_entree(conn, run_id, motif, payload):
    conn.execute(
        "INSERT INTO stg_rejet (run_id, table_source, cle_source, regle_id, motif, payload_json) "
        "VALUES (?, 'charger_mouvement', NULL, 'PRE-FORMAT', ?, ?)",
        (run_id, motif, json.dumps(payload, ensure_ascii=False, default=str)),
    )


def charger_mouvement(conn, *, compte_id, date_operation, libelle_brut, montant_cents,
                      devise_code=None, date_valeur=None, type_transaction_code="AUTRE",
                      categorie_code=None, run_id=None, fichier_id=None, stg_id=None, occurrence=1,
                      resoudre_la_contrepartie=True):
    """Insère un mouvement de façon idempotente.

    Retourne un dict {'statut': 'insere' | 'doublon' | 'rejete', 'mouvement_id', 'categorie_code',
    'contrepartie_id'}. Une entrée au format invalide (date inexistante, montant non entier) n'entre pas
    dans core : elle est placée dans stg_rejet avec la règle 'PRE-FORMAT'.
    Si categorie_code n'est pas fourni, il est déduit de ref_mapping_libelle.
    """
    payload = {"compte_id": compte_id, "date_operation": date_operation, "date_valeur": date_valeur,
               "libelle_brut": libelle_brut, "montant_cents": montant_cents}
    try:
        date.fromisoformat(str(date_operation))
        if date_valeur is not None:
            date.fromisoformat(str(date_valeur))
    except ValueError:
        _rejeter_entree(conn, run_id, "Date invalide ou format non ISO (AAAA-MM-JJ attendu)", payload)
        return {"statut": "rejete", "mouvement_id": None, "categorie_code": None, "contrepartie_id": None}
    if isinstance(montant_cents, bool) or not isinstance(montant_cents, int):
        _rejeter_entree(conn, run_id, "Montant non entier : convertir en cents avant le chargement", payload)
        return {"statut": "rejete", "mouvement_id": None, "categorie_code": None, "contrepartie_id": None}

    libelle_brut = "" if libelle_brut is None else str(libelle_brut)
    norm = normaliser_libelle(libelle_brut)
    if devise_code is None:
        devise_code = conn.execute("SELECT devise_code FROM mdm_compte WHERE compte_id = ?", (compte_id,)).fetchone()[0]
    if categorie_code is None:
        categorie_code = categoriser_libelle(conn, norm)

    contrepartie_id = None
    if resoudre_la_contrepartie and norm and categorie_code not in CATEGORIES_SANS_CONTREPARTIE:
        contrepartie_id, _, _ = resoudre_contrepartie(conn, libelle_brut)

    h = hash_transaction(compte_id, date_operation, montant_cents, norm, occurrence)
    curseur = conn.execute(
        "INSERT OR IGNORE INTO core_mouvement "
        "(compte_id, date_operation, date_valeur, libelle_brut, libelle_normalise, montant_cents, devise_code, "
        " type_transaction_code, categorie_code, contrepartie_id, hash_transaction, run_id, fichier_id, stg_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (compte_id, date_operation, date_valeur, libelle_brut, norm, montant_cents, devise_code,
         type_transaction_code, categorie_code, contrepartie_id, h, run_id, fichier_id, stg_id),
    )
    if curseur.rowcount == 0:
        mid = conn.execute("SELECT mouvement_id FROM core_mouvement WHERE hash_transaction = ?", (h,)).fetchone()[0]
        return {"statut": "doublon", "mouvement_id": mid, "categorie_code": categorie_code,
                "contrepartie_id": contrepartie_id}
    return {"statut": "insere", "mouvement_id": curseur.lastrowid, "categorie_code": categorie_code,
            "contrepartie_id": contrepartie_id}
