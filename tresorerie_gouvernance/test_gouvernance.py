"""Tests du socle de gouvernance. Lancer :  python -m unittest test_gouvernance -v

Chaque test part d'une base vide et temporaire. Les anomalies de qualité sont injectées en SQL direct
(en contournant charger_mouvement) pour vérifier que chaque règle détecte exactement ce qu'elle doit.
"""
import os
import tempfile
import unittest
from datetime import date, timedelta

import dq_runner
import init_db
import lineage
import mdm_utils
from dictionnaire import construire_dictionnaire, exporter_markdown, exporter_xlsx


def jour(n):
    """Date ISO d'il y a n jours."""
    return (date.today() - timedelta(days=n)).isoformat()


class BaseTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "test.db")
        self.conn, self.stats = init_db.initialiser(self.db)
        c = self.conn
        c.execute("INSERT INTO mdm_entite_juridique (nom_legal, nom_court) VALUES ('Entreprise Test inc.', 'Test')")
        self.entite = c.execute("SELECT entite_id FROM mdm_entite_juridique").fetchone()[0]
        self.c1 = self._compte("DESJ", "1111")
        self.c2 = self._compte("BNC", "2222")
        self.run = lineage.demarrer_run(c, "TEST")
        c.commit()
        self._n = 0

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def _compte(self, banque, fin):
        cur = self.conn.execute(
            "INSERT INTO mdm_compte (entite_id, banque_code, type_code, numero_masque, numero_hash) "
            "VALUES (?, ?, 'EXPLOITATION', ?, ?)",
            (self.entite, banque, mdm_utils.masquer_compte(fin), mdm_utils.hash_numero_compte(fin, "sel-test")))
        return cur.lastrowid

    def _ins(self, compte, date_op, montant, libelle, categorie="DEC_AUTRES", devise="CAD", date_valeur=None,
             contrepartie=None, fichier=None):
        """Insertion directe (sans validation) pour fabriquer des anomalies."""
        self._n += 1
        cur = self.conn.execute(
            "INSERT INTO core_mouvement (compte_id, date_operation, date_valeur, libelle_brut, libelle_normalise, "
            "montant_cents, devise_code, categorie_code, contrepartie_id, hash_transaction, run_id, fichier_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (compte, date_op, date_valeur, libelle, mdm_utils.normaliser_libelle(libelle), montant, devise,
             categorie, contrepartie, f"hash-test-{self._n}", self.run, fichier))
        return cur.lastrowid

    def _resultats(self, resume):
        return {r["regle_id"]: r for r in resume["resultats"]}


class TestSchemaEtReferences(BaseTest):
    def test_cles_etrangeres_actives_et_references(self):
        self.assertEqual(self.conn.execute("PRAGMA foreign_keys").fetchone()[0], 1)
        n = lambda t: self.conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        self.assertEqual(n("ref_format_releve"), 4)
        self.assertGreaterEqual(n("ref_banque"), 7)
        self.assertEqual(n("ref_scenario"), 4)
        self.assertEqual(self.conn.execute(
            "SELECT famille FROM ref_categorie_flux WHERE code = 'NON_CLASSE'").fetchone()[0], "neutre")
        self.assertEqual(n("dq_regle"), len(dq_runner.REGLES))

    def test_cle_etrangere_refusee(self):
        with self.assertRaises(Exception):
            self.conn.execute("INSERT INTO mdm_compte (entite_id, banque_code, type_code, numero_masque, "
                              "numero_hash) VALUES (?, 'BANQUE_INCONNUE', 'EXPLOITATION', '****0000', 'x')",
                              (self.entite,))

    def test_dim_date(self):
        attendu = (date(2035, 12, 31) - date(2020, 1, 1)).days + 1
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM dim_date").fetchone()[0], attendu)
        ligne = self.conn.execute(
            "SELECT jour_semaine, est_ouvrable, trimestre, fin_de_mois FROM dim_date WHERE date_id = '2026-10-22'"
        ).fetchone()
        self.assertEqual(ligne, (4, 1, 4, 0))  # jeudi
        self.assertEqual(self.conn.execute(
            "SELECT fin_de_mois FROM dim_date WHERE date_id = '2028-02-29'").fetchone()[0], 1)

    def test_idempotence_de_init(self):
        avant = self.conn.execute("SELECT COUNT(*) FROM meta_champ").fetchone()[0]
        self.conn.close()
        self.conn, stats = init_db.initialiser(self.db)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM meta_champ").fetchone()[0], avant)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM dq_regle").fetchone()[0], len(dq_runner.REGLES))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM meta_version_schema").fetchone()[0], 1)


class TestDictionnaire(BaseTest):
    def test_couverture_complete(self):
        self.assertEqual(self.stats["a_documenter"], [])
        self.assertEqual(self.stats["documentes"], self.stats["total"])
        self.assertGreater(self.stats["total"], 200)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM meta_champ").fetchone()[0], self.stats["total"])
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM meta_champ WHERE definition_metier = 'À DOCUMENTER'").fetchone()[0], 0)

    def test_classification_et_obligatoire(self):
        q = lambda t, c, col: self.conn.execute(
            f"SELECT {col} FROM meta_champ WHERE table_nom = ? AND champ_nom = ?", (t, c)).fetchone()[0]
        self.assertEqual(q("core_mouvement", "montant_cents", "sensibilite"), "confidentiel")
        self.assertEqual(q("mdm_compte", "numero_hash", "sensibilite"), "restreint")
        self.assertEqual(q("core_mouvement", "montant_cents", "nullable"), 0)
        self.assertEqual(q("core_mouvement", "date_valeur", "nullable"), 1)

    def test_detecte_un_champ_non_documente_et_les_obsoletes(self):
        self.conn.execute("ALTER TABLE ref_banque ADD COLUMN nouveau_champ TEXT")
        stats = construire_dictionnaire(self.conn)
        self.assertEqual(stats["a_documenter"], ["ref_banque.nouveau_champ"])
        self.conn.execute("ALTER TABLE ref_banque DROP COLUMN nouveau_champ")
        stats = construire_dictionnaire(self.conn)
        self.assertEqual(stats["a_documenter"], [])
        self.assertEqual(stats["obsoletes_supprimes"], 1)

    def test_exports(self):
        md, xlsx = os.path.join(self.tmp.name, "d.md"), os.path.join(self.tmp.name, "d.xlsx")
        exporter_markdown(self.conn, md)
        exporter_xlsx(self.conn, xlsx)
        with open(md, encoding="utf-8") as f:
            texte = f.read()
        self.assertIn("## core_mouvement", texte)
        self.assertIn("## Glossaire métier", texte)
        from openpyxl import load_workbook
        wb = load_workbook(xlsx)
        self.assertEqual(wb.sheetnames, ["Dictionnaire", "Glossaire", "Regles_DQ"])
        self.assertEqual(wb["Dictionnaire"].max_row - 1, self.stats["total"])


class TestMDM(BaseTest):
    def test_normalisation(self):
        self.assertEqual(mdm_utils.normaliser_libelle("Hydro-Québec inc. #4432"), "HYDRO QUEBEC")
        self.assertEqual(mdm_utils.normaliser_libelle("ACHAT  Tim Hortons 0123"), "ACHAT TIM HORTONS")
        self.assertEqual(mdm_utils.normaliser_libelle(None), "")
        self.assertEqual(mdm_utils.masquer_compte("0123-456-7890"), "****7890")

    def test_categorisation(self):
        cat = lambda s: mdm_utils.categoriser_libelle(self.conn, mdm_utils.normaliser_libelle(s))
        self.assertEqual(cat("PAIEMENT FACTURE 123"), "NON_CLASSE")  # la regex évite PAIE -> salaires
        self.assertEqual(cat("PAIE 2026-10-15"), "DEC_SALAIRES")
        self.assertEqual(cat("Hydro-Québec facture"), "DEC_SERVICES_PUBLICS")
        self.assertEqual(cat("Virement entre comptes"), "TRF_INTERNE")
        self.assertEqual(cat("quelque chose d'inconnu"), "NON_CLASSE")

    def test_resolution_contrepartie(self):
        r = lambda s: mdm_utils.resoudre_contrepartie(self.conn, s)
        id1, m1, _ = r("Tim Hortons #123")
        self.assertEqual(m1, "nouveau")
        id2, m2, _ = r("TIM HORTONS 456")
        self.assertEqual((id2, m2), (id1, "exact"))
        id3, m3, conf = r("Tim Horton")
        self.assertEqual((id3, m3), (id1, "approx"))
        self.assertGreaterEqual(conf, 0.88)
        id4, m4, _ = r("Hydro-Québec")
        self.assertEqual(m4, "nouveau")
        self.assertNotEqual(id4, id1)
        # Cas ambigu : 'HYDRO QC' est trop différent de 'HYDRO QUEBEC' -> nouvelle contrepartie à valider
        id5, m5, _ = r("HYDRO QC")
        self.assertEqual(m5, "nouveau")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM mart_contreparties_a_valider").fetchone()[0], 3)
        self.assertEqual(mdm_utils.resoudre_contrepartie(self.conn, "Inconnu SA", creer=False)[1], "inconnu")

    def test_fusion_et_validation(self):
        hydro, _, _ = mdm_utils.resoudre_contrepartie(self.conn, "Hydro-Québec")
        hydro_qc, _, _ = mdm_utils.resoudre_contrepartie(self.conn, "HYDRO QC")
        mid = self._ins(self.c1, jour(3), -1000, "HYDRO QC", "DEC_SERVICES_PUBLICS", contrepartie=hydro_qc)
        nb = mdm_utils.fusionner_contreparties(self.conn, hydro_qc, hydro)
        self.assertEqual(nb, 1)
        self.assertEqual(self.conn.execute(
            "SELECT contrepartie_id FROM core_mouvement WHERE mouvement_id = ?", (mid,)).fetchone()[0], hydro)
        self.assertEqual(mdm_utils.resoudre_contrepartie(self.conn, "HYDRO QC")[0], hydro)
        self.assertEqual(self.conn.execute(
            "SELECT actif FROM mdm_contrepartie WHERE contrepartie_id = ?", (hydro_qc,)).fetchone()[0], 0)
        with self.assertRaises(ValueError):
            mdm_utils.fusionner_contreparties(self.conn, hydro, hydro)
        mdm_utils.valider_contrepartie(self.conn, hydro, "Hydro-Québec", "fournisseur")
        self.assertEqual(self.conn.execute(
            "SELECT statut_validation, type_contrepartie FROM mdm_contrepartie WHERE contrepartie_id = ?",
            (hydro,)).fetchone(), ("valide", "fournisseur"))

    def test_chargement_idempotent_et_rejets(self):
        args = dict(compte_id=self.c1, date_operation=jour(3), libelle_brut="HYDRO QUEBEC FACTURE",
                    montant_cents=-12345, run_id=self.run)
        r1 = mdm_utils.charger_mouvement(self.conn, **args)
        self.assertEqual((r1["statut"], r1["categorie_code"]), ("insere", "DEC_SERVICES_PUBLICS"))
        self.assertIsNotNone(r1["contrepartie_id"])
        r2 = mdm_utils.charger_mouvement(self.conn, **args)
        self.assertEqual((r2["statut"], r2["mouvement_id"]), ("doublon", r1["mouvement_id"]))
        r3 = mdm_utils.charger_mouvement(self.conn, **args, occurrence=2)
        self.assertEqual(r3["statut"], "insere")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM core_mouvement").fetchone()[0], 2)

        bad_date = mdm_utils.charger_mouvement(self.conn, compte_id=self.c1, date_operation="2026-02-30",
                                               libelle_brut="X", montant_cents=-100, run_id=self.run)
        bad_montant = mdm_utils.charger_mouvement(self.conn, compte_id=self.c1, date_operation=jour(2),
                                                  libelle_brut="X", montant_cents=-12.5, run_id=self.run)
        self.assertEqual((bad_date["statut"], bad_montant["statut"]), ("rejete", "rejete"))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM core_mouvement").fetchone()[0], 2)
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM stg_rejet WHERE regle_id = 'PRE-FORMAT'").fetchone()[0], 2)

    def test_pas_de_contrepartie_pour_virement_interne(self):
        r = mdm_utils.charger_mouvement(self.conn, compte_id=self.c1, date_operation=jour(3),
                                        libelle_brut="VIREMENT ENTRE COMPTES", montant_cents=-500, run_id=self.run)
        self.assertEqual(r["categorie_code"], "TRF_INTERNE")
        self.assertIsNone(r["contrepartie_id"])


class TestLineage(BaseTest):
    def test_run_et_fichier(self):
        lineage.terminer_run(self.conn, self.run, "succes")
        self.assertEqual(self.conn.execute("SELECT statut FROM meta_run WHERE run_id = ?", (self.run,)).fetchone()[0],
                         "succes")
        chemin = os.path.join(self.tmp.name, "releve.csv")
        with open(chemin, "w") as f:
            f.write("date;libelle;montant\n2026-10-01;TEST;-10,00\n")
        fid, vu = lineage.enregistrer_fichier(self.conn, chemin, format_code="CSV", banque_code="DESJ", run_id=self.run)
        fid2, vu2 = lineage.enregistrer_fichier(self.conn, chemin, format_code="CSV", banque_code="DESJ")
        self.assertEqual((vu, vu2, fid2), (False, True, fid))


class TestQualite(BaseTest):
    def test_donnees_propres(self):
        """Jeu de données cohérent : aucune règle ne doit échouer."""
        c = self.conn
        # Soldes de relevé cohérents avec les mouvements entre les deux dates
        for compte, s0, s1 in ((self.c1, 100000, 115000), (self.c2, 0, 10000)):
            c.execute("INSERT INTO core_solde_releve (compte_id, date_solde, solde_cents) VALUES (?, ?, ?)",
                      (compte, jour(10), s0))
            c.execute("INSERT INTO core_solde_releve (compte_id, date_solde, solde_cents) VALUES (?, ?, ?)",
                      (compte, jour(3), s1))
        L = lambda **k: mdm_utils.charger_mouvement(c, run_id=self.run, **k)
        L(compte_id=self.c1, date_operation=jour(8), libelle_brut="Hydro-Québec facture", montant_cents=-25000)
        L(compte_id=self.c1, date_operation=jour(6), libelle_brut="Client ABC", montant_cents=50000,
          categorie_code="ENC_CLIENTS")
        L(compte_id=self.c1, date_operation=jour(5), libelle_brut="Virement entre comptes", montant_cents=-10000)
        L(compte_id=self.c2, date_operation=jour(5), libelle_brut="Virement entre comptes", montant_cents=10000)
        c.commit()
        resume = dq_runner.executer(c)
        for r in resume["resultats"]:
            self.assertEqual(r["statut"], "pass", f"{r['regle_id']} devrait réussir : {r}")
        self.assertEqual((resume["score_global"], resume["nb_echecs"], resume["nb_bloquants_echec"]), (100.0, 0, 0))
        self.assertEqual(c.execute("SELECT COUNT(*) FROM core_mouvement WHERE statut_dq = 'ok'").fetchone()[0], 4)
        self.assertEqual(c.execute("SELECT COUNT(*) FROM stg_rejet").fetchone()[0], 0)

    def test_detection_des_anomalies(self):
        c = self.conn
        cp = mdm_utils.resoudre_contrepartie(c, "Fournisseur X")[0]
        for i in (1, 2):
            c.execute("INSERT INTO meta_fichier_source (nom_fichier, hash_sha256) VALUES (?, ?)", (f"f{i}.csv", f"h{i}"))
        f1, f2 = [r[0] for r in c.execute("SELECT fichier_id FROM meta_fichier_source ORDER BY fichier_id")]
        self._ins(self.c1, jour(2), 0, "AJUSTEMENT")                                    # VAL-002 (bloquante)
        self._ins(self.c1, "1999-12-31", -100, "ANCIEN")                                # VAL-001 (bloquante)
        self._ins(self.c1, jour(2), -200, "USD ACHAT", devise="USD")                    # VAL-004 (bloquante)
        self._ins(self.c1, jour(2), -300, "ACHAT DIVERS", categorie="NON_CLASSE")       # COM-001
        self._ins(self.c1, jour(2), -400, "")                                           # COM-002
        self._ins(self.c1, jour(2), 1000, "REMB FOURNISSEUR X", "DEC_FOURNISSEURS", contrepartie=cp)  # COH-001
        self._ins(self.c1, jour(2), -5000, "VIREMENT", "TRF_INTERNE")                   # COH-002
        self._ins(self.c1, jour(2), -600, "FACTURE",
                  date_valeur=(date.today() + timedelta(days=58)).isoformat())          # VAL-003
        self._ins(self.c1, jour(2), -700, "ABC", fichier=f1)                            # UNI-001 (x2)
        self._ins(self.c1, jour(2), -700, "ABC AUTRE LIBELLE", fichier=f2)
        self._ins(self.c1, jour(2), 800, "CLIENT", "ENC_CLIENTS")                       # COM-003
        c.execute("INSERT INTO core_solde_releve (compte_id, date_solde, solde_cents) VALUES (?, ?, 1000)",
                  (self.c1, jour(20)))
        c.execute("INSERT INTO core_solde_releve (compte_id, date_solde, solde_cents) VALUES (?, ?, 5000)",
                  (self.c1, jour(12)))                                                  # EXA-001 (bloquante)
        c.commit()

        resume = dq_runner.executer(c)
        r = self._resultats(resume)
        attendu = {"DQ-COM-001": 1, "DQ-COM-002": 1, "DQ-COM-003": 1, "DQ-VAL-001": 1, "DQ-VAL-002": 1,
                   "DQ-VAL-003": 1, "DQ-VAL-004": 1, "DQ-UNI-001": 2, "DQ-INT-001": 0, "DQ-INT-002": 0,
                   "DQ-COH-001": 1, "DQ-COH-002": 1, "DQ-EXA-001": 1, "DQ-PON-001": 1}
        for regle, nb in attendu.items():
            self.assertEqual(r[regle]["nb_violation"], nb, f"{regle}: {r[regle]}")
            # DQ-COM-001 : 1 violation sur 11 = 90,91 % >= seuil de 90 % -> la règle réussit malgré la violation
            reussie = nb == 0 or regle == "DQ-COM-001"
            self.assertEqual(r[regle]["statut"], "pass" if reussie else "fail", regle)
        self.assertEqual(r["DQ-COM-001"]["score_pct"], 90.91)
        self.assertEqual(resume["nb_bloquants_echec"], 4)
        self.assertLess(resume["score_global"], 100)

        statuts = dict(c.execute("SELECT statut_dq, COUNT(*) FROM core_mouvement GROUP BY statut_dq").fetchall())
        self.assertEqual(statuts, {"quarantaine": 3, "avertissement": 8})
        self.assertEqual(c.execute("SELECT COUNT(*) FROM stg_rejet WHERE statut_traitement = 'a_revoir'").fetchone()[0], 4)
        self.assertEqual(c.execute("SELECT payload_json IS NOT NULL FROM stg_rejet WHERE regle_id = 'DQ-EXA-001'")
                         .fetchone()[0], 1)

        # Les vues de restitution excluent la quarantaine et les transferts internes (flux mensuels)
        self.assertEqual(c.execute("SELECT SUM(nb_mouvements) FROM mart_mouvement_quotidien").fetchone()[0], 8)
        self.assertEqual(c.execute(
            "SELECT COUNT(*) FROM mart_flux_mensuel WHERE categorie_code = 'TRF_INTERNE'").fetchone()[0], 0)
        self.assertEqual(c.execute("SELECT COUNT(*) FROM mart_dq_derniere_execution").fetchone()[0], len(dq_runner.REGLES))

        # Rejouable : mêmes statuts, pas de doublon dans la file de revue
        resume2 = dq_runner.executer(c)
        self.assertEqual(resume2["score_global"], resume["score_global"])
        self.assertEqual(c.execute("SELECT COUNT(*) FROM stg_rejet WHERE statut_traitement = 'a_revoir'").fetchone()[0], 4)
        self.assertEqual(dict(c.execute("SELECT statut_dq, COUNT(*) FROM core_mouvement GROUP BY statut_dq")
                              .fetchall()), {"quarantaine": 3, "avertissement": 8})

    def test_portee_par_run_et_sans_quarantaine(self):
        c = self.conn
        autre_run = lineage.demarrer_run(c, "AUTRE")
        a = self._ins(self.c1, jour(2), 0, "ZERO DANS RUN TEST")
        c.execute("INSERT INTO core_mouvement (compte_id, date_operation, libelle_brut, libelle_normalise, "
                  "montant_cents, devise_code, hash_transaction, run_id) "
                  "VALUES (?, ?, 'ZERO AUTRE RUN', 'ZERO AUTRE RUN', 0, 'CAD', 'hash-autre', ?)",
                  (self.c1, jour(2), autre_run))
        c.commit()
        r = self._resultats(dq_runner.executer(c, run_id=self.run, quarantaine=False))
        self.assertEqual(r["DQ-VAL-002"]["nb_violation"], 1)        # seul le run demandé est évalué
        self.assertEqual(r["DQ-VAL-002"]["nb_evalue"], 1)
        self.assertEqual(c.execute("SELECT COUNT(*) FROM core_mouvement WHERE statut_dq <> 'ok'").fetchone()[0], 0)
        self.assertEqual(c.execute("SELECT COUNT(*) FROM stg_rejet").fetchone()[0], 0)
        dq_runner.executer(c, run_id=self.run)
        self.assertEqual(c.execute("SELECT statut_dq FROM core_mouvement WHERE mouvement_id = ?", (a,)).fetchone()[0],
                         "quarantaine")

    def test_regle_desactivee_ignoree_et_preservee(self):
        c = self.conn
        c.execute("UPDATE dq_regle SET actif = 0 WHERE regle_id = 'DQ-PON-001'")
        c.commit()
        dq_runner.charger_regles(c)   # une resynchronisation ne doit pas réactiver la règle
        resume = dq_runner.executer(c)
        self.assertNotIn("DQ-PON-001", self._resultats(resume))
        self.assertEqual(resume["nb_regles"], len(dq_runner.REGLES) - 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
