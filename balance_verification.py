"""Balance de vérification du journal général (pour les rapports A7).

Chaque catégorie du journal est un compte : les sorties de fonds sont des DÉBITS, les entrées des CRÉDITS. Pour une période (AAAA-MM) et
pour le cumul de l'exercice jusqu'à cette période, la balance donne les débits, les crédits et le solde net par catégorie, puis les totaux.
Contrôles : le total des débits moins celui des crédits égale le flux net opposé (identité), le flux net de la balance égale la somme
du journal, et les écritures au signe inattendu (revenu en sortie, charge en entrée) sont comptées pour relecture.

La balance de vérification COMPTABLE (bilan, produits, charges, capitaux propres) vit dans etats_financiers.py : elle porte sur le modèle
d'états financiers, pas sur le journal bancaire.
"""
from __future__ import annotations

import sqlite3


def balance_journal(db_path: str, periode: str) -> dict:
    annee = periode[:4]
    c = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        cats = c.execute("SELECT categorie, nature, ordre FROM categories ORDER BY ordre").fetchall()
        def agg(clause, params):
            return {cat: (nb, deb or 0.0, cre or 0.0) for cat, nb, deb, cre in c.execute(
                "SELECT categorie, COUNT(*), SUM(CASE WHEN montant < 0 THEN -montant END), SUM(CASE WHEN montant > 0 THEN montant END) "
                f"FROM journal_general WHERE {clause} GROUP BY categorie", params)}
        mois = agg("substr(date_ecriture, 1, 7) = ?", (periode,))
        cumul = agg("substr(date_ecriture, 1, 4) = ? AND substr(date_ecriture, 1, 7) <= ?", (annee, periode))
        total_journal = c.execute("SELECT COALESCE(SUM(montant), 0) FROM journal_general WHERE substr(date_ecriture, 1, 7) = ?", (periode,)).fetchone()[0]
        inattendus = c.execute(
            "SELECT COUNT(*) FROM journal_general WHERE substr(date_ecriture, 1, 7) = ? AND "
            "((nature = 'Revenu' AND montant < 0) OR (nature <> 'Revenu' AND montant > 0))", (periode,)).fetchone()[0]
    finally:
        c.close()
    lignes = []
    for cat, nature, ordre in cats:
        nb, deb, cre = mois.get(cat, (0, 0.0, 0.0))
        _, deb_c, cre_c = cumul.get(cat, (0, 0.0, 0.0))
        if nb or deb_c or cre_c:
            lignes.append({"ordre": ordre, "categorie": cat, "nature": nature, "nb": nb, "debit": deb, "credit": cre, "net": cre - deb,
                           "debit_cumul": deb_c, "credit_cumul": cre_c, "net_cumul": cre_c - deb_c})
    tot = {k: sum(l[k] for l in lignes) for k in ("nb", "debit", "credit", "net", "debit_cumul", "credit_cumul", "net_cumul")}
    controles = [
        {"controle": "Débits − crédits = − flux net (période)", "ok": abs((tot["debit"] - tot["credit"]) + tot["net"]) < 0.01},
        {"controle": "Flux net de la balance = somme du journal (période)", "ok": abs(tot["net"] - total_journal) < 0.01},
        {"controle": "Flux net cumulé = cumul des crédits − cumul des débits", "ok": abs(tot["net_cumul"] - (tot["credit_cumul"] - tot["debit_cumul"])) < 0.01},
    ]
    return {"periode": periode, "annee": annee, "lignes": lignes, "totaux": tot, "controles": controles, "signes_inattendus": inattendus}
