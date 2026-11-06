"""
Chargeur — classe et insère les transactions d'A2 dans tresorerie.db.

Logique :
    1. Détection de doublon (par date + montant + description) → ignoré si déjà présent
    2. Classification par mots-clés (table mots_cles) → categorie + nature
    3. Insertion dans journal_saisie (toujours — c'est la zone de staging)
    4. Si classifiée avec succès : promotion aussi dans journal_general
       (c'est la table que R8/SARIMAX interroge en direct)
       Si non classifiée : reste seulement dans journal_saisie, statut "⚠ À classer",
       exactement comme les lignes "À classer" qu'on voit déjà dans R6.

Le format de no_ecriture (JG-<année>-NNNNN) et d'exercice (FY<année>) suit
exactement la convention déjà utilisée dans tresorerie.db.
"""

import sqlite3


def _charger_classification(conn: sqlite3.Connection):
    cur = conn.cursor()
    cur.execute("SELECT mot_cle, categorie FROM mots_cles")
    mots_cles = cur.fetchall()
    cur.execute("SELECT categorie, nature FROM categories")
    nature_par_categorie = dict(cur.fetchall())
    return mots_cles, nature_par_categorie


def _classifier(description: str, mots_cles, nature_par_categorie):
    desc_maj = description.upper()
    for mot_cle, categorie in mots_cles:
        if mot_cle in desc_maj:
            return categorie, nature_par_categorie.get(categorie)
    return None, None


def _prochain_no_ecriture(cur: sqlite3.Cursor, annee: int) -> str:
    cur.execute(
        "SELECT no_ecriture FROM journal_general WHERE no_ecriture LIKE ? ORDER BY no_ecriture DESC LIMIT 1",
        (f"JG-{annee}-%",),
    )
    row = cur.fetchone()
    if row:
        dernier = int(row[0].split("-")[-1])
        return f"JG-{annee}-{dernier + 1:05d}"
    return f"JG-{annee}-00001"


def charger_transactions(transactions: list[dict], compte: str, db_path: str = "tresorerie.db") -> dict:
    """
    transactions : liste de dict au format de sortie d'A2 (date, description, montant, ...)
    compte       : identifiant du compte source (ex. "Desjardins EOP")
    db_path      : chemin vers tresorerie.db

    Retourne un résumé des insertions.
    """
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    mots_cles, nature_par_categorie = _charger_classification(conn)

    resume = {
        "inseres_staging": 0,
        "promus_journal_general": 0,
        "doublons_ignores": 0,
        "a_classer": 0,
        "details_a_classer": [],
    }

    for t in transactions:
        date_str = t["date"]
        montant = t["montant"]
        description = t["description"]
        annee, mois = int(date_str[:4]), int(date_str[5:7])

        cle_doublon = f"{date_str}|{round(montant, 2)}|{description}"
        cur.execute("SELECT 1 FROM journal_saisie WHERE cle_doublon=?", (cle_doublon,))
        if cur.fetchone():
            resume["doublons_ignores"] += 1
            continue

        categorie, nature = _classifier(description, mots_cles, nature_par_categorie)
        statut = "✓ Valide" if categorie else "⚠ À classer"

        cur.execute(
            """
            INSERT INTO journal_saisie
                (date_brute, description, montant_brut, compte_source, date_valide,
                 categorie, nature, mois, cle_doublon, est_doublon, statut)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
            """,
            (date_str, description, montant, compte, date_str,
             categorie or "À classer", nature or "À classer", mois, cle_doublon, statut),
        )
        resume["inseres_staging"] += 1

        if categorie:
            no_ecriture = _prochain_no_ecriture(cur, annee)
            cur.execute(
                """
                INSERT INTO journal_general
                    (no_ecriture, date_ecriture, description, montant, categorie, nature,
                     mois, annee, compte_source, exercice)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (no_ecriture, date_str, description, montant, categorie, nature,
                 mois, annee, compte, f"FY{annee}"),
            )
            resume["promus_journal_general"] += 1
        else:
            resume["a_classer"] += 1
            resume["details_a_classer"].append({"date": date_str, "description": description})

    conn.commit()
    conn.close()
    return resume
