"""Test de la consolidation des trois divisions (consolidation.py) : le consolidé retrouve les états existants, les écritures s'équilibrent,
les éliminations annulent exactement les opérations internes, sur 200 combinaisons aléatoires de paramètres."""
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import consolidation as K  # noqa: E402
import etats_financiers as ef  # noqa: E402

M2025 = {1: -1077461, 2: -4331392, 3: -3026347, 4: -1160291, 5: -876237, 6: -482215, 7: -342198, 8: -453056, 9: -374207, 10: -201796, 11: -201555,
         12: -161357, 13: -106517, 14: -104037, 15: -88025, 16: -99363, 17: -53676, 18: -69500, 19: -57514, 20: 7923498, 21: 3502344, 22: 1780292,
         23: 746116, 24: 179031, 25: 256780}
M2026 = {1: -1138516, 2: -5150910, 3: -4329344, 4: -1622201, 5: -1091874, 6: -618130, 7: -464927, 8: -617011, 9: -416545, 10: -230686, 11: -281842,
         12: -226945, 13: -147497, 14: -114317, 15: -108000, 16: -117879, 17: -64851, 18: -92131, 19: -67752, 20: 10338230, 21: 4839631, 22: 1978537,
         23: 994759, 24: 282474, 25: 309607}
J = ef.Journal([2025, 2026], {2025: M2025, 2026: M2026}, {o: f"Catégorie {o}" for o in range(1, 26)}, marge_solde=890000.0, marge_limite=1_000_000.0)


def _res(**kw):
    return ef.calculer(J, ef.parametres_par_defaut(J).modifie(**kw))


def test_les_parts_de_repartition_totalisent_un():
    for nom in ("PART_SUBVENTIONS", "PART_STOCKS", "PART_IMMO", "PART_DETTES", "PART_ENCAISSE", "PART_CAPITAL"):
        assert abs(sum(getattr(K, nom)) - 1) < 1e-9, nom
    for o, p in K.PART_CHARGES.items():
        assert abs(sum(p) - 1) < 1e-9, o
    assert set(K.PART_CHARGES) == set(ef.CHARGES_OPERATIONS + ef.CHARGES_ADMIN)


def test_le_consolide_retrouve_les_etats_existants():
    res = _res()
    for an in J.annees:
        c = K.consolider(res, an)
        assert all(x["ok"] for x in K.controles(c)), [x for x in K.controles(c) if not x["ok"]]


def test_les_ecritures_sont_equilibrees_une_a_une():
    c = K.consolider(_res(), 2026)
    for no in sorted({l["no"] for l in c["journal"]}):
        lignes = [l for l in c["journal"] if l["no"] == no]
        assert abs(sum(l["debit"] for l in lignes) - sum(l["credit"] for l in lignes)) < 1e-6, no


def test_l_elimination_annule_les_comptes_internes():
    c = K.consolider(_res(), 2026)
    r, b = c["consolide_r"], c["consolide_b"]
    for cle in ("ventes_ic", "services_ic", "gestion_ic", "achats_ic", "svc_ch", "gest_ch", "interets_ic_ch", "prod_fin_ic"):
        assert abs(r[cle]) < 1e-6, cle
    for cle in ("creances_ic", "dettes_ic", "pret_ic", "emprunt_ic"):
        assert abs(b[cle]) < 1e-6, cle


def test_la_marge_interne_des_stocks_est_eliminee():
    c = K.consolider(_res(), 2026, K.ParametresConso(majoration=0.20))
    ic = c["interco"]
    assert ic["nr_fin"] > 0 and abs(ic["nr_fin"] - 0.20 * sum(ic["stock_ic_fin"])) < 1e-6
    assert abs(c["agrege_b"]["stocks"] - c["consolide_b"]["stocks"] - ic["nr_fin"]) < 1e-6
    sans = K.consolider(_res(), 2026, K.ParametresConso(majoration=0.0))
    assert abs(sans["interco"]["nr_fin"]) < 1e-9 and abs(sans["elim_r"]["cpv_ext"]) < 1e-9


def test_la_premiere_annee_utilise_le_bilan_d_ouverture():
    c = K.consolider(_res(), 2025)
    assert all(x["ok"] for x in K.controles(c))


def test_combinaisons_aleatoires():
    rnd = random.Random(7)
    for _ in range(200):
        res = _res(var_ventes=rnd.uniform(-.3, .3), var_cout_produits=rnd.uniform(-.3, .3), var_charges=rnd.uniform(-.3, .3), dso=rnd.uniform(10, 90),
                   dio=rnd.uniform(0, 60), dpo=rnd.uniform(10, 90), taux_impot=rnd.uniform(0, .45), annee_scenario=2025)
        pc = K.ParametresConso(achats_pie_chez_usi=rnd.uniform(0, 1), achats_pro_chez_usi=rnd.uniform(0, 1), majoration=rnd.uniform(0, .5),
                               temps_machine_pct=rnd.uniform(0, .15), gestion_pct=rnd.uniform(0, .05), pret=rnd.uniform(0, 1_500_000), taux_pret=rnd.uniform(0, .1),
                               jours_ic=rnd.uniform(0, 90))
        for an in J.annees:
            echecs = [x for x in K.controles(K.consolider(res, an, pc)) if not x["ok"]]
            assert not echecs, (an, pc, echecs)


def test_ecritures_des_divisions_equilibrees_par_operation_et_par_division():
    c = K.consolider(_res(), 2026)
    lignes = K.ecritures_divisions(c)
    cles = {(l["operation"], l["division"]) for l in lignes}
    for op, div in cles:
        sel = [l for l in lignes if l["operation"] == op and l["division"] == div]
        assert abs(sum(l["debit"] for l in sel) - sum(l["credit"] for l in sel)) < 1e-6, (op, div)
    # les créances et les dettes de clôture, nettes des règlements, égalent les soldes du bilan des divisions
    def solde(compte, div, sens):
        return sum(l[sens] - l["debit" if sens == "credit" else "credit"] for l in lignes if l["compte"] == compte and l["division"] == K.DIVISIONS[div])
    assert abs(solde("1150", "USI", "debit") - c["agrege_b"]["creances_ic"]) < 1e-6
    assert abs(solde("2050", "PIE", "credit") + solde("2050", "PRO", "credit") - c["agrege_b"]["dettes_ic"]) < 1e-6


def test_presentation_et_excel():
    c = K.consolider(_res(), 2026)
    p = K.presenter(c)
    for lignes in p.values():
        for style, lib, vals in lignes:
            assert len(vals) == 6
    net = next(v for s, l, v in p["resultats"] if l == "Résultat net")
    assert abs(net[3] + net[4] - net[5]) < 1e-6
    assert K.classeur_excel(c)[:2] == b"PK"


if __name__ == "__main__":
    for nom, f in sorted(globals().items()):
        if nom.startswith("test_"):
            f()
            print("OK", nom)
    print("Tous les tests passent.")
