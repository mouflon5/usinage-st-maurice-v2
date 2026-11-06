"""Données de trésorerie pour la vue « Architecture d'affaires » de la démonstration.

Lit la base (journal général, paramètres, facilités, tables de gouvernance si elles existent) et produit un dictionnaire
JSON-sérialisable que la page injecte sous `window.USM_DATA`. Lecture seule : aucune écriture dans la base.
"""
import json
import os
import re
import sqlite3
from datetime import date

RE_CONTREPARTIE = re.compile(r"^(.*?) - (.*?) FACT")


def _existe(c, nom):
    return c.execute("SELECT 1 FROM sqlite_master WHERE name = ?", (nom,)).fetchone() is not None


def donnees(db_path):
    if not db_path or not os.path.isfile(db_path):
        return {"disponible": False}
    c = sqlite3.connect(db_path, timeout=10)
    try:
        par = {k: v for k, v in c.execute("SELECT cle, valeur FROM parametres WHERE domaine = 'general'")}
        annees = [r[0] for r in c.execute("SELECT DISTINCT annee FROM journal_general ORDER BY annee")]
        cats = {}
        for cat, nature, an, tot, nb in c.execute(
                "SELECT categorie, nature, annee, ROUND(SUM(montant), 0), COUNT(*) FROM journal_general GROUP BY 1, 2, 3"):
            e = cats.setdefault(cat, {"categorie": cat, "nature": nature, "par_annee": {}, "nb": 0})
            e["par_annee"][str(an)] = tot
            e["nb"] += nb
        contre = {}
        for desc, mont, cat in c.execute("SELECT description, montant, categorie FROM journal_general"):
            m = RE_CONTREPARTIE.match(desc or "")
            if not m:
                continue
            e = contre.setdefault((m.group(1), m.group(2)), {"type": m.group(1), "nom": m.group(2), "nb": 0, "total": 0.0, "categorie": cat})
            e["nb"] += 1
            e["total"] += mont
        ventes = {k: v["par_annee"].get(str(annees[-1]), 0) for k, v in cats.items() if k.startswith("Ventes")}
        tot_ventes = sum(ventes.values()) or 1
        rec = sum(v for k, v in ventes.items() if "récurrents" in k or "recurrents" in k)
        out = {
            "disponible": True, "genere_le": date.today().isoformat(),
            "entreprise": par.get("entreprise", "Groupe Usinage Saint-Maurice inc."), "secteur": par.get("secteur", ""),
            "exercice": int(par.get("exercice", annees[-1] if annees else 0)),
            "solde_initial": float(par.get("solde_initial", 0)), "seuil": float(par.get("seuil_securite", 0)),
            "facilites": [{"nom": n, "solde": s, "limite": l} for n, s, l in c.execute("SELECT facilite, solde, limite FROM facilites_credit")],
            "annees": annees, "categories": list(cats.values()),
            "contreparties": sorted(({**e, "total": round(e["total"])} for e in contre.values()), key=lambda e: -abs(e["total"])),
            "nb_mouvements": c.execute("SELECT COUNT(*) FROM journal_general").fetchone()[0],
            "part_recurrents": round(100 * rec / tot_ventes, 1),
            "gouvernance": {"initialisee": False},
        }
        if _existe(c, "meta_champ"):
            g = out["gouvernance"]
            g["initialisee"] = True
            g["nb_champs"] = c.execute("SELECT COUNT(*) FROM meta_champ").fetchone()[0]
            g["nb_regles"] = c.execute("SELECT COUNT(*) FROM dq_regle WHERE actif = 1").fetchone()[0]
            g["nb_runs"] = c.execute("SELECT COUNT(*) FROM meta_run").fetchone()[0]
            g["nb_fichiers"] = c.execute("SELECT COUNT(*) FROM meta_fichier_source").fetchone()[0]
            g["nb_mouvements_core"] = c.execute("SELECT COUNT(*) FROM core_mouvement").fetchone()[0]
            g["nb_quarantaine"] = c.execute("SELECT COUNT(*) FROM core_mouvement WHERE statut_dq = 'quarantaine'").fetchone()[0]
            g["nb_contreparties"] = c.execute("SELECT COUNT(*) FROM mdm_contrepartie").fetchone()[0]
            ex = c.execute("SELECT score_global, execute_le, nb_echecs, nb_bloquants_echec FROM dq_execution ORDER BY rowid DESC LIMIT 1").fetchone()
            if ex:
                g.update({"dq_score": ex[0], "dq_le": ex[1], "dq_echecs": ex[2], "dq_bloquants": ex[3]})
        out["achats"] = _achats(c)
        return out
    finally:
        c.close()


def _achats(c):
    """Cycle achats-décaissements : indicateurs lus dans les tables core_ du cycle (absentes ou vides : {"disponible": False})."""
    if not (_existe(c, "core_facture_fournisseur") and _existe(c, "mdm_fournisseur")):
        return {"disponible": False}
    if not c.execute("SELECT COUNT(*) FROM mdm_fournisseur").fetchone()[0]:
        return {"disponible": False}
    un = lambda sql, par=(): c.execute(sql, par).fetchone()[0]
    ref = un("SELECT valeur FROM parametres WHERE domaine = 'achats' AND cle = 'date_reference'") if _existe(c, "parametres") else None
    ref = ref or date.today().isoformat()
    tol_p = float(un("SELECT valeur FROM parametres WHERE domaine = 'achats' AND cle = 'tolerance_prix_pct'") or 2)
    tol_q = float(un("SELECT valeur FROM parametres WHERE domaine = 'achats' AND cle = 'tolerance_quantite_pct'") or 1)
    sur_cmd = un("SELECT COUNT(*) FROM core_facture_fournisseur WHERE commande_id IS NOT NULL AND statut <> 'contestee'")
    hors = un("SELECT COUNT(*) FROM core_facture_fournisseur WHERE commande_id IS NOT NULL AND statut <> 'contestee' "
              "AND (ABS(COALESCE(ecart_prix_pct, 0)) > ? OR ABS(COALESCE(ecart_quantite_pct, 0)) > ?)", (tol_p, tol_q))
    dispo = un("SELECT COALESCE(SUM(escompte_cents), 0) FROM core_facture_fournisseur WHERE escompte_cents > 0 AND statut = 'payee'")
    pris = un("SELECT COALESCE(SUM(escompte_pris_cents), 0) FROM core_paiement_fournisseur")
    dpo = un("SELECT AVG(julianday(l.date_paiement) - julianday(f.date_facture)) FROM core_paiement_fournisseur p JOIN core_facture_fournisseur f ON f.facture_id = p.facture_id "
             "JOIN core_lot_paiement l ON l.lot_id = p.lot_id WHERE l.statut = 'execute'")
    total_pp = un("SELECT COALESCE(SUM(f.montant_ht_cents), 0) FROM core_facture_fournisseur f JOIN mdm_fournisseur o ON o.fournisseur_id = f.fournisseur_id WHERE o.famille_achat = 'matiere_premiere' AND f.statut <> 'contestee'")
    top = c.execute("SELECT o.nom_legal, SUM(f.montant_ht_cents) s FROM core_facture_fournisseur f JOIN mdm_fournisseur o ON o.fournisseur_id = f.fournisseur_id "
                    "WHERE o.famille_achat = 'matiere_premiere' AND f.statut <> 'contestee' GROUP BY 1 ORDER BY s DESC LIMIT 1").fetchone()
    statuts = dict(c.execute("SELECT statut, COUNT(*) FROM core_facture_fournisseur GROUP BY statut").fetchall())
    return {
        "disponible": True, "date_reference": ref,
        "fournisseurs": un("SELECT COUNT(*) FROM mdm_fournisseur"),
        "fournisseurs_actifs": un("SELECT COUNT(*) FROM mdm_fournisseur WHERE statut = 'actif'"),
        "fournisseurs_a_valider": un("SELECT COUNT(*) FROM mdm_fournisseur WHERE statut = 'a_valider'"),
        "fournisseurs_suspendus": un("SELECT COUNT(*) FROM mdm_fournisseur WHERE statut = 'suspendu'"),
        "commandes": un("SELECT COUNT(*) FROM core_commande_achat"),
        "commandes_en_attente": un("SELECT COUNT(*) FROM core_commande_achat WHERE statut = 'attente_approbation'"),
        "factures": un("SELECT COUNT(*) FROM core_facture_fournisseur"), "factures_par_statut": statuts,
        "solde_ouvert_cents": un("SELECT COALESCE(SUM(total_cents), 0) FROM core_facture_fournisseur WHERE statut NOT IN ('payee', 'contestee')"),
        "echu_cents": un("SELECT COALESCE(SUM(total_cents), 0) FROM core_facture_fournisseur WHERE statut NOT IN ('payee', 'contestee') AND date_echeance < ?", (ref,)),
        "paye_cents": un("SELECT COALESCE(SUM(montant_cents), 0) FROM core_paiement_fournisseur p JOIN core_lot_paiement l ON l.lot_id = p.lot_id WHERE l.statut = 'execute'"),
        "dpo": round(dpo, 1) if dpo is not None else None,
        "premiere": round(100 * (1 - hors / sur_cmd), 1) if sur_cmd else None,
        "ecarts_ouverts": statuts.get("ecart", 0),
        "escompte_capte_pct": round(100 * pris / dispo, 1) if dispo else None, "escompte_pris_cents": pris,
        "top_source": {"nom": top[0], "part": round(100 * top[1] / total_pp, 1)} if top and total_pp else None,
        "doublons": un("SELECT COUNT(*) FROM core_facture_fournisseur f WHERE EXISTS (SELECT 1 FROM core_facture_fournisseur g WHERE g.fournisseur_id = f.fournisseur_id AND g.no_facture = f.no_facture AND g.facture_id < f.facture_id)"),
        "lots_en_cours": un("SELECT COUNT(*) FROM core_lot_paiement WHERE statut IN ('prepare', 'approuve_1', 'approuve')"),
        "ecritures": un("SELECT COUNT(DISTINCT no_ecriture) FROM core_ecriture_achat"),
    }


def en_script(db_path):
    """Balise <script> à placer avant les scripts de l'application."""
    return "<script>window.USM_DATA = " + json.dumps(donnees(db_path), ensure_ascii=False).replace("</", "<\\/") + ";</script>"


if __name__ == "__main__":
    import sys
    base = sys.argv[1] if len(sys.argv) > 1 else "tresorerie.db"
    sortie = sys.argv[2] if len(sys.argv) > 2 else None
    s = en_script(base)
    if sortie:
        with open(sortie, "w", encoding="utf-8") as f:
            f.write(s[len("<script>"):-len("</script>")])
        print("écrit", sortie)
    else:
        print(s[:400])
