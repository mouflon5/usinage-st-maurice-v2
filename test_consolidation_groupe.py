"""Test de la consolidation juridique du Groupe Saint-Maurice (consolidation_groupe.py) : résultats du chiffrier de cours, identités comptables,
traitements de l'aval et de l'amont, effet des hypothèses, détection des décalages intersociétés."""
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import consolidation_groupe as G  # noqa: E402

PRES = 0.5


def proche(a, b, tol=PRES):
    return abs(a - b) < tol


def test_les_cinq_balances_totalisent_zero():
    bv = G.balances(G.Hypotheses())
    for e in G.ENTITES:
        assert proche(bv[e].sum(), 0), e
    assert proche(bv["Total agrégé"].sum(), 0)


def test_resultats_du_chiffrier_de_cours():
    r = G.consolider()
    k = r["chiffres_cles"]
    assert proche(k["Produits consolidés"], 33_690_000) and proche(k["Résultat net consolidé"], 2_579_522.5)
    assert proche(k["dont attribuable aux minoritaires"], 61_304.5) and proche(k["dont attribuable à la société mère"], 2_518_218)
    assert proche(k["Total de l'actif consolidé"], 31_211_750) and proche(k["Écart d'acquisition"], 1_163_000)
    assert proche(k["Participation ne donnant pas le contrôle"], 1_111_304.5) and proche(k["Écart de conversion cumulé"], 268_150)
    assert proche(sum(l["debit"] for e in r["journal"] for l in e["lignes"]), 14_994_202)
    assert len(r["journal"]) == 19 and all(c["ok"] for c in r["controles"]) and len(r["controles"]) == 8


def test_conversion_ecart_residuel_et_interco_a_420_000():
    c = G.conversion(G.Hypotheses()).set_index("Compte")["Solde (CAD)"]
    assert proche(c.sum(), 0) and proche(c["Écart de conversion cumulé"], -268_150)
    assert proche(c["Créditeurs intersociétés"], -420_000)                       # libellé en CAD dans l'entente : se concilie sans résidu
    assert proche(c["Capital-actions"], -660_000)                               # cours historique 1,32


def test_acquisition_et_amortissement_des_ecarts():
    a = G.consolider()["acquisition"]
    assert proche(a["jv_actif_net"], 4_717_000) and proche(a["impots_differes"], 583_000) and proche(a["goodwill"], 1_163_000)
    assert proche(a["amort_total"], 342_500) and proche(a["reprise_impots"], 90_762.5) and proche(a["reduction_nette"], 251_737.5)
    assert proche(a["goodwill_quote_part"], 1_026_400) and proche(a["diff_goodwill"], 136_600)       # IFRS 3 : quote-part contre juste valeur


def test_chaque_ecriture_s_equilibre_et_les_comptes_internes_s_annulent():
    r = G.consolider()
    for e in r["journal"]:
        assert proche(sum(l["debit"] for l in e["lignes"]), sum(l["credit"] for l in e["lignes"])), e["no"]
    J = r["chiffrier"]["Consolidé"]
    for c in ("Débiteurs intersociétés", "Créditeurs intersociétés", "Billet à recevoir — Soudure Bécancour", "Billet à payer — Gestion SM", "Dividendes déclarés",
              "Dividendes reçus", "Honoraires de gestion — produits", "Frais de gestion — intragroupe", "Produits de location", "Charges de loyer", "Produits d'intérêts", *G.PLACEMENTS):
        assert proche(J[c], 0), c


def test_les_ventes_internes_sont_eliminees_a_100_pour_cent_meme_en_amont():
    r = G.consolider(G.Hypotheses(detention_sbe=0.6))
    e4 = next(e for e in r["journal"] if e["no"] == "E4")
    assert proche(e4["lignes"][0]["debit"], 950_000)                             # jamais la quote-part de détention
    assert all(c["ok"] for c in r["controles"])


def test_la_detention_deplace_le_partage_des_dividendes_et_du_resultat():
    r80, r60 = G.consolider(), G.consolider(G.Hypotheses(detention_sbe=0.6))
    e11, e12 = (next(e for e in r60["journal"] if e["no"] == n) for n in ("E11", "E12"))
    assert proche(e11["lignes"][0]["debit"], 90_000) and proche(e12["lignes"][0]["debit"], 60_000)
    assert r60["pndc"]["quote_part_pndc"] > r80["pndc"]["quote_part_pndc"]
    assert proche(r60["pndc"]["quote_part_pndc"], r60["pndc"]["resultat_ajuste"] * 0.4)
    assert all(c["ok"] for c in r60["controles"])


def test_vente_aval_imputee_a_100_pour_cent_a_la_mere():
    base = G.consolider()
    aval = G.consolider(G.Hypotheses(stocks_usinage_chez_usp=100_000, marge_usinage=0.3))
    e5 = next(e for e in aval["journal"] if e["no"] == "E5")
    assert proche(e5["lignes"][0]["debit"], 84_000 + 30_000)                    # amont + aval
    assert proche(aval["pndc"]["quote_part_pndc"], base["pndc"]["quote_part_pndc"])      # la part des minoritaires ne bouge pas
    assert aval["etats"]["resultats"]["net"] < base["etats"]["resultats"]["net"]
    assert all(c["ok"] for c in aval["controles"])


def test_le_profit_non_realise_reduit_le_resultat_et_cree_un_impot_differe():
    sans = G.consolider(G.Hypotheses(stocks_sbe=0))
    avec = G.consolider()
    net_sans, net_avec = sans["etats"]["resultats"]["net"], avec["etats"]["resultats"]["net"]
    assert proche(net_sans - net_avec, 84_000 * (1 - 0.265))                     # profit retiré, net de l'impôt différé
    e6 = next(e for e in avec["journal"] if e["no"] == "E6")
    assert proche(e6["lignes"][0]["debit"], 22_260)


def test_cours_de_change_ajuste_l_ecart_de_conversion_sans_casser_l_equilibre():
    r = G.consolider(G.Hypotheses(cours_cloture=1.30, cours_moyen=1.38))
    assert all(c["ok"] for c in r["controles"])
    assert not proche(r["chiffres_cles"]["Écart de conversion cumulé"], 268_150, 1000)
    assert proche(r["etats"]["resultats"]["net"] - G.consolider()["etats"]["resultats"]["net"], r["etats"]["resultats"]["net"] - G.consolider()["etats"]["resultats"]["net"])


def test_un_decalage_intersocietes_est_detecte():
    r = G.consolider(G.Hypotheses(soldes_interco=1_300_000))                    # coupure : l'un des côtés n'a pas la même valeur
    c = {x["controle"]: x for x in r["controles"]}
    assert not c["Solde net des comptes intersociétés"]["ok"] and proche(c["Solde net des comptes intersociétés"]["ecart"], 120_000)   # 60 000 $ de chaque côté
    assert c["Total des débits égal au total des crédits au journal"]["ok"]       # le journal reste équilibré : c'est la réciprocité qui échoue


def test_billet_et_dividendes_mal_eliminés_sont_detectes():
    assert not next(c for c in G.consolider(G.Hypotheses(billet=1_400_000))["controles"] if c["controle"].startswith("Billet"))["ok"]
    assert not next(c for c in G.consolider(G.Hypotheses(dividende_usinage=500_000))["controles"] if c["controle"].startswith("Dividendes"))["ok"]


def test_continuite_de_la_pndc():
    p = G.consolider()["pndc"]
    assert proche(p["solde_cloture"], p["solde_acquisition"] + p["quote_part_pndc"] + p["dividendes_min"])
    assert proche(p["resultat_ajuste"], 620_000 - 251_737.5 - 61_740)


def test_combinaisons_aleatoires():
    rnd = random.Random(11)
    for _ in range(150):
        h = G.Hypotheses(detention_sbe=rnd.uniform(0.51, 0.95), taux_impot=rnd.uniform(0, 0.4), cours_cloture=rnd.uniform(1.1, 1.6), cours_moyen=rnd.uniform(1.1, 1.6),
                         jv_immobilisations=rnd.uniform(0, 2e6), jv_relations=rnd.uniform(0, 2e6), jv_carnet=rnd.uniform(0, 5e5),
                         duree_immobilisations=rnd.uniform(3, 30), duree_relations=rnd.uniform(3, 15), duree_carnet=rnd.uniform(0.5, 3), mois_exercice=rnd.uniform(1, 12),
                         stocks_sbe=rnd.uniform(0, 1e6), marge_sbe=rnd.uniform(0, 0.6), stocks_usinage_chez_usp=rnd.uniform(0, 1e6), marge_usinage=rnd.uniform(0, 0.6),
                         jv_pndc=rnd.uniform(5e5, 2e6))
        r = G.consolider(h)
        echecs = [c for c in r["controles"] if not c["ok"]]
        assert not echecs, (h, echecs)


def test_un_cours_historique_different_de_celui_du_placement_est_detecte():
    c = {x["controle"]: x for x in G.consolider(G.Hypotheses(cours_historique=1.40))["controles"]}
    j = c["Total des débits égal au total des crédits au journal"]
    assert not j["ok"] and proche(j["ecart"], 40_000)                  # le placement a été inscrit à 1,32 : E15 ne balance plus (500 000 US × 0,08)


def test_presentation_et_excel():
    r = G.consolider()
    assert len(G.journal_plat(r)) == sum(len(e["lignes"]) for e in r["journal"])
    assert G.classeur_excel(r)[:2] == b"PK"
    et = r["etats"]
    assert proche(et["total_actif"], et["total_passif"] + et["total_cp"]) and not et["residuels_actif"] and not et["residuels_passif"]


if __name__ == "__main__":
    for nom, f in sorted(globals().items()):
        if nom.startswith("test_"):
            f()
            print("OK", nom)
    print("Tous les tests passent.")
