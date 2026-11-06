"""Tests du cycle achats-décaissements (cycle_achats.py) : exemple cohérent, appariement, contrôles et séparation des tâches.

    python -m unittest test_cycle_achats
"""
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import date, timedelta

RACINE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, RACINE)
sys.path.insert(0, os.path.join(RACINE, "tresorerie_gouvernance"))

import cycle_achats as A  # noqa: E402
import dq_runner  # noqa: E402
import init_db  # noqa: E402

REF = date(2026, 10, 28)


class TestCalculs(unittest.TestCase):
    def test_taxes(self):
        tps, tvq, total = A.taxes(100000)
        self.assertEqual((tps, tvq, total), (5000, 9975, 114975))

    def test_niveau_approbation(self):
        self.assertEqual([A.niveau_approbation(v) for v in (2500000, 2500001, 10000000, 10000001)], [1, 2, 2, 3])

    def test_appariement_dans_les_tolerances(self):
        r = A.simuler_appariement(120000, 138, 118400, 118400, 138.0)
        self.assertTrue(r["conforme"])
        self.assertEqual(r["ecart_cents"], 0)

    def test_appariement_prix_hors_tolerance(self):
        r = A.simuler_appariement(120000, 138, 120000, 120000, 138 * 1.024)
        self.assertFalse(r["conforme"])
        self.assertAlmostEqual(r["ecart_prix_pct"], 2.4, places=1)
        self.assertGreater(r["ecart_cents"], 0)

    def test_appariement_facture_sur_la_quantite_commandee(self):
        r = A.simuler_appariement(120000, 138, 118000, 120000, 138)           # reçu 118 000 L, facturé 120 000 L
        self.assertFalse(r["conforme"])
        self.assertAlmostEqual(r["ecart_quantite_pct"], 1.69, places=1)

    def test_escompte_2_10_net_30(self):
        self.assertAlmostEqual(A.escompte_annualise_pct(2, 10, 30), 37.2, places=1)
        self.assertEqual(A.escompte_annualise_pct(0, 10, 30), 0.0)

    def test_ecritures_facture_equilibrees(self):
        f = {"montant_ht_cents": 1000000, "tps_cents": 50000, "tvq_cents": 99750, "total_cents": 1149750}
        for recu in (None, 980000, 1020000):
            lignes = A.ecritures_facture(f, recu)
            self.assertEqual(sum(d for _, d, _, _ in lignes), sum(c for _, _, c, _ in lignes), recu)


class TestExemple(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dossier = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        cls.db = os.path.join(cls.dossier.name, "cycle.db")
        conn, cls.stats = init_db.initialiser(cls.db)
        conn.close()
        c = A.connecter(cls.db)
        cls.compteurs = A.generer(c, ref=REF)
        c.close()

    @classmethod
    def tearDownClass(cls):
        cls.dossier.cleanup()

    def setUp(self):
        self.c = A.connecter(self.db)

    def tearDown(self):
        self.c.close()

    def un(self, sql, *p):
        return self.c.execute(sql, p).fetchone()[0]

    def test_dictionnaire_complet(self):
        self.assertEqual(self.stats["a_documenter"], [], "toute colonne du cycle doit être documentée")
        self.assertGreater(self.un("SELECT COUNT(*) FROM meta_champ WHERE table_nom = 'core_facture_fournisseur'"), 15)

    def test_volumes(self):
        self.assertEqual(self.compteurs["mdm_fournisseur"], len(A.FOURNISSEURS))
        self.assertGreater(self.compteurs["core_facture_fournisseur"], 100)
        self.assertGreater(self.compteurs["core_paiement_fournisseur"], 50)

    def test_ecritures_equilibrees(self):
        self.assertEqual(self.un("SELECT COUNT(*) FROM (SELECT no_ecriture FROM core_ecriture_achat GROUP BY no_ecriture HAVING SUM(debit_cents) <> SUM(credit_cents))"), 0)

    def test_totaux_de_facture(self):
        self.assertEqual(self.un("SELECT COUNT(*) FROM core_facture_fournisseur WHERE total_cents <> montant_ht_cents + tps_cents + tvq_cents"), 0)

    def test_integrite_referentielle(self):
        self.assertEqual(self.c.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_aucune_facture_payee_sans_paiement(self):
        self.assertEqual(self.un("SELECT COUNT(*) FROM core_facture_fournisseur f WHERE f.statut = 'payee' AND NOT EXISTS (SELECT 1 FROM core_paiement_fournisseur p WHERE p.facture_id = f.facture_id)"), 0)

    def test_paiement_jamais_avant_la_facture(self):
        self.assertEqual(self.un("SELECT COUNT(*) FROM core_paiement_fournisseur p JOIN core_facture_fournisseur f ON f.facture_id = p.facture_id "
                                 "JOIN core_lot_paiement l ON l.lot_id = p.lot_id WHERE l.date_paiement < f.date_facture"), 0)

    def test_exemple_phare(self):
        cid = A.exemple_phare(self.c)
        self.assertIsNotNone(cid)
        f = self.c.execute("SELECT f.ecart_prix_pct, f.statut, p.escompte_pris_cents FROM core_facture_fournisseur f JOIN core_paiement_fournisseur p ON p.facture_id = f.facture_id "
                           "WHERE f.commande_id = ?", (cid,)).fetchone()
        self.assertGreater(f[0], 2)
        self.assertEqual(f[1], "payee")
        self.assertGreater(f[2], 0)

    def test_regles_qualite_du_cycle(self):
        r = {x["regle_id"]: x for x in dq_runner.executer(self.c, quarantaine=False)["resultats"]}
        for regle in ("DQ-COH-010", "DQ-EXA-010", "DQ-INT-010", "DQ-VAL-010"):
            self.assertEqual(r[regle]["nb_violation"], 0, regle)
        self.assertEqual(r["DQ-UNI-010"]["nb_violation"], 1)               # le doublon de l'exemple
        self.assertEqual(r["DQ-COH-011"]["nb_violation"], 1)               # la facture sans commande de l'exemple


class TestActions(unittest.TestCase):
    def setUp(self):
        self.dossier = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db = os.path.join(self.dossier.name, "actions.db")
        conn, _ = init_db.initialiser(self.db)
        conn.close()
        c = A.connecter(self.db)
        A.generer(c, ref=REF)
        self.c = c

    def tearDown(self):
        self.c.close()
        self.dossier.cleanup()

    def ids(self, sql):
        return [r[0] for r in self.c.execute(sql)]

    def test_ecart_exige_un_motif(self):
        f = self.ids("SELECT facture_id FROM core_facture_fournisseur WHERE statut = 'ecart' AND commande_id IS NOT NULL")[0]
        with self.assertRaises(A.ErreurCycle):
            A.approuver_facture(self.db, f, "Contrôleur financier", "")
        A.approuver_facture(self.db, f, "Contrôleur financier", "Prix du jour confirmé")
        self.assertEqual(self.c.execute("SELECT statut FROM core_facture_fournisseur WHERE facture_id = ?", (f,)).fetchone()[0], "approuvee")

    def test_le_demandeur_n_approuve_pas_la_facture(self):
        f = self.ids("SELECT facture_id FROM core_facture_fournisseur WHERE statut = 'ecart' AND commande_id IS NOT NULL")[0]
        dem = self.c.execute("SELECT c.demandeur FROM core_facture_fournisseur f JOIN core_commande_achat c ON c.commande_id = f.commande_id WHERE f.facture_id = ?", (f,)).fetchone()[0]
        with self.assertRaises(A.ErreurCycle):
            A.approuver_facture(self.db, f, dem, "ok")

    def test_fournisseur_suspendu_non_payable(self):
        f = self.ids("SELECT f.facture_id FROM core_facture_fournisseur f JOIN mdm_fournisseur o ON o.fournisseur_id = f.fournisseur_id WHERE o.statut = 'suspendu' AND f.statut = 'approuvee'")[0]
        with self.assertRaises(A.ErreurCycle):
            A.creer_lot(self.db, [f], REF)

    def test_facture_non_approuvee_non_payable(self):
        f = self.ids("SELECT facture_id FROM core_facture_fournisseur WHERE statut IN ('recue', 'ecart') LIMIT 1")[0]
        with self.assertRaises(A.ErreurCycle):
            A.creer_lot(self.db, [f], REF)

    def test_double_approbation_et_execution(self):
        fs = self.ids("SELECT f.facture_id FROM core_facture_fournisseur f JOIN mdm_fournisseur o ON o.fournisseur_id = f.fournisseur_id WHERE f.statut = 'approuvee' AND o.statut = 'actif' LIMIT 4")
        lot = A.creer_lot(self.db, fs, REF + timedelta(days=3))
        self.assertGreater(A.total_lot(self.c, lot), A.parametres(self.c)["seuil_double_approbation"] * 100)
        with self.assertRaises(A.ErreurCycle):
            A.approuver_lot(self.db, lot, A.PREPARATEUR)                  # le préparateur ne l'approuve pas
        self.assertEqual(A.approuver_lot(self.db, lot, "Contrôleur financier"), "approuve_1")
        with self.assertRaises(A.ErreurCycle):
            A.approuver_lot(self.db, lot, "Contrôleur financier")         # pas deux fois la même personne
        with self.assertRaises(A.ErreurCycle):
            A.executer_lot(self.db, lot)                                  # pas avant la seconde approbation
        self.assertEqual(A.approuver_lot(self.db, lot, "Direction générale"), "approuve")
        self.assertEqual(A.executer_lot(self.db, lot), len(fs))
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM core_facture_fournisseur WHERE facture_id IN (%s) AND statut = 'payee'" % ",".join(map(str, fs))).fetchone()[0], len(fs))
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM (SELECT no_ecriture FROM core_ecriture_achat GROUP BY no_ecriture HAVING SUM(debit_cents) <> SUM(credit_cents))").fetchone()[0], 0)

    def test_levee_de_suspension(self):
        fid = self.c.execute("SELECT fournisseur_id FROM mdm_fournisseur WHERE statut = 'suspendu'").fetchone()[0]
        A.lever_suspension(self.db, fid, "Contrôleur financier")
        self.assertEqual(self.c.execute("SELECT statut, rappel_verifie FROM mdm_fournisseur WHERE fournisseur_id = ?", (fid,)).fetchone(), ("actif", 1))

    def test_validation_fournisseur_par_un_demandeur_refusee(self):
        fid = self.c.execute("SELECT fournisseur_id FROM mdm_fournisseur WHERE statut = 'a_valider'").fetchone()[0]
        with self.assertRaises(A.ErreurCycle):
            A.valider_fournisseur(self.db, fid, A.DEMANDEURS[0])
        A.valider_fournisseur(self.db, fid, "Contrôleur financier")
        self.assertEqual(self.c.execute("SELECT statut FROM mdm_fournisseur WHERE fournisseur_id = ?", (fid,)).fetchone()[0], "actif")


if __name__ == "__main__":
    unittest.main()
