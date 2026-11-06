"""Test des calculs de la section « Coûts de revient » (couts_revient.py) : cohérence des méthodes et identités comptables."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import couts_revient as C  # noqa: E402

TOTAL_INDIRECT = sum(C.CENTRES_AUXILIAIRES.values()) + sum(C.CENTRES_PRINCIPAUX.values())


def test_repartition_secondaire_conserve_les_charges():
    for aux, cles in C.CLES_SECONDAIRES.items():
        assert abs(sum(cles.values()) - 1) < 1e-9, aux
    assert abs(C.repartition_secondaire()["Total"].sum() - TOTAL_INDIRECT) < 1e-9


def test_les_deux_methodes_absorbent_les_memes_charges():
    d = C.cout_complet()
    for m in ("Centres d'analyse", "ABC"):
        assert abs((d[f"{m} : indirect ($/unité)"] * d["Volume (milliers)"]).sum() - TOTAL_INDIRECT) < 1e-6, m
    assert not any("UVA" in c for c in d.columns)


def test_frais_fixes_budget_et_volume():
    e = C.ecarts_frais_fixes(2000, 31900)
    assert abs(e["ecart_budget"] + e["ecart_volume"] - e["sous_imputation"]) < 1e-9
    assert abs(e["taux"] - 14.0) < 1e-9 and abs(e["ecart_volume"] - 2800) < 1e-9 and abs(e["ecart_budget"] - 1100) < 1e-9
    plein = C.ecarts_frais_fixes(C.FIXES_STANDARD["volume_normal"], C.FIXES_STANDARD["budget_mensuel"])
    assert abs(plein["sous_imputation"]) < 1e-9 and abs(plein["ecart_volume"]) < 1e-9          # production normale et budget respecté : aucun écart
    assert C.ecarts_frais_fixes(2400, 30800)["ecart_volume"] < 0                                   # suractivité : écart de volume favorable


def test_commandes_devis_contre_reel():
    c, d = C.commandes(), C.commandes_detail()
    assert len(c) == len(C.COMMANDES) and set(d["Élément"]) == set(C.ELEMENTS_COMMANDE)
    for _, r in c.iterrows():
        assert abs(r["Marge prévue (%)"] - C.COMMANDES.set_index("Commande").loc[r["Commande"], "Marge soumise"]) < 1e-9
        assert abs(r["Écart ($)"] - d[d["Commande"] == r["Commande"]]["Écart ($)"].sum()) < 1e-6      # les écarts par élément somment l'écart de la commande
        assert abs(r["Marge perdue (pts)"] - (r["Marge prévue (%)"] - r["Marge réelle (%)"])) < 1e-12
    p = C.precision_soumissions().set_index("Ligne")
    assert p.loc["Prototypage", "Écart moyen pondéré"] > p.loc["Contrats aéro et rail", "Écart moyen pondéré"]      # le prototypage est la ligne la plus mal estimée
    assert p["Commandes"].sum() == len(c)


def test_commande_speciale():
    libre = C.commande_speciale("Pièces de rechange", 5000, 70, True)
    pleine = C.commande_speciale("Pièces de rechange", 5000, 70, False)
    assert libre["accepter"] and not pleine["accepter"]                                            # même prix : acceptable si la capacité dort, perdant si elle est pleine
    assert abs(libre["plancher"] - C.direct_unitaire("Pièces de rechange")) < 1e-9 and pleine["plancher"] > libre["plancher"]


def test_registre_des_methodes():
    m = C.METHODES
    assert set(m["Statut"]) == {"Pilier", "Complément", "Écartée"} and m["Méthode"].is_unique
    assert "Unités de valeur ajoutée (UVA)" in set(m.loc[m["Statut"] == "Écartée", "Méthode"])
    assert (m.loc[m["Statut"] != "Écartée", "Question à laquelle elle répond"] != "—").all()


def test_abc_revele_ce_que_la_main_d_oeuvre_cache():
    d = C.cout_complet()
    marge_c, marge_a = d["Centres d'analyse : marge ($/unité)"], d["ABC : marge ($/unité)"]
    assert marge_c["Contrats aéro et rail"] > 0 > marge_a["Contrats aéro et rail"]       # le contrôle à 100 % rend déficitaires des contrats qui paraissaient rentables
    assert marge_a["Prototypage"] < marge_c["Prototypage"] < 0                          # l'ingénierie du prototypage est très sous-évaluée
    assert marge_a["Usinage sur mesure"] > marge_c["Usinage sur mesure"]               # et l'usinage sur mesure, surévalué


def test_point_mort_annule_le_resultat():
    r = C.resultat_et_point_mort(C.contribution())
    assert abs(r["point_mort"] * r["taux_mcv"] - r["fixes"]) < 1e-6
    assert abs(r["resultat"] - (r["mcv"] - r["fixes"])) < 1e-6


def test_abandon_d_une_ligne():
    df = C.contribution()
    ligne = df.set_index("Produit")
    for p in df["Produit"]:
        assert abs(C.abandon(p, df) - (-ligne.loc[p, "MCV (k$)"] + C.FIXES_SPECIFIQUES[p])) < 1e-9
    assert C.abandon("Prototypage", df) > 0 > C.abandon("Usinage sur mesure", df)


def test_postes_indirects_egalent_les_centres():
    p = C.postes_comptables()
    ind = p[p["Nature"] == "Indirect"].groupby("Imputé à")["Montant (k$)"].sum()
    for centre, montant in {**C.CENTRES_AUXILIAIRES, **C.CENTRES_PRINCIPAUX}.items():
        assert abs(ind[centre] - montant) < 1e-9, centre


def test_flux_d_imputation_conserve_les_montants():
    f = C.imputation_flux()
    produits = set(C.PRODUITS)
    directs = C.postes_comptables().query("Nature == 'Direct'")["Montant (k$)"].sum()
    arrivee = f[f["Cible"].isin(produits)]["Montant (k$)"].sum()
    assert abs(arrivee - (directs + TOTAL_INDIRECT)) < 1e-6
    assert abs(C.imputation_flux("Charges indirectes").query("Cible in @produits")["Montant (k$)"].sum() - TOTAL_INDIRECT) < 1e-6
    assert abs(C.imputation_flux("Charges directes").query("Cible in @produits")["Montant (k$)"].sum() - directs) < 1e-6


def test_composantes_coincident_avec_l_abc():
    comp = C.cout_complet_par_composante().sum(axis=1)
    d = C.cout_complet()
    assert ((comp - d["ABC : revient ($/unité)"]).abs() < 1e-9).all()


def test_ecarts_somme_egale_cout_reel_moins_standard():
    e = C.ecarts(2000, 5010, 8.05, 1830, 60.5, 6900)
    somme = sum(v for k, v in e.items() if not k.startswith("_"))
    assert abs(somme - e["_total"]) < 1e-6
    assert e["Prix de la matière"] > 0 and e["Rendement (heures)"] > 0
    S = C.STANDARD
    e0 = C.ecarts(2000, 2000 * S["kg_par_piece"], S["prix"], 2000 * S["heures_par_piece"], S["taux"], 2000 * S["variable_par_piece"])
    assert abs(e0["_total"]) < 1e-6 and all(abs(v) < 1e-6 for k, v in e0.items() if not k.startswith("_"))


def test_ircf():
    r = C.ircf(3435, 40000, 31000)
    assert abs(r["coefficient"] - .775) < 1e-12
    assert abs(r["imputees"] + r["sous_activite"] - 3435) < 1e-9
    assert r["unitaire_complet"] > r["unitaire_ircf"]
    assert abs(r["unitaire_ircf"] - 85.875) < 1e-9                            # $ par heure-machine
    assert C.ircf(3435, 40000, 48000)["sous_activite"] < 0                    # boni de suractivité


def test_cout_cible_repartit_l_enveloppe():
    cadre, t = C.cout_cible(185, .20, 48, C.CARACTERISTIQUES)
    assert abs(cadre["admissible"] - 148) < 1e-9 and abs(cadre["enveloppe"] - 100) < 1e-9
    assert abs(t["Coût cible ($/pièce)"].sum() - cadre["enveloppe"]) < 1e-9
    assert abs(cadre["ecart"] - (104 - 100)) < 1e-9
    assert t.set_index("Caractéristique")["Ratio coût / valeur"].idxmax().startswith("Contrôle dimensionnel")


def test_abm():
    assert set(C.ACTIVITES["Classe"]) <= set(C.CLASSES)
    t = C.scenario_abm({"Corrections de factures": .5})
    assert abs(t["Coût (k$)"].sum() - t["Coût après (k$)"].sum() - 60) < 1e-9


def test_rentabilite_par_ligne_et_distorsion():
    r = C.rentabilite_produits()
    fixes = sum(C.FIXES_SPECIFIQUES.values()) + C.FIXES_COMMUNES                       # 6,75 M$ de fixes du modèle de marge, contre 7,1 M$ de charges indirectes absorbées en ABC
    assert abs(r["Marge complète ABC (k$)"].sum() - (C.resultat_et_point_mort(C.contribution())["resultat"] - (TOTAL_INDIRECT - fixes))) < 1e-6
    assert abs(r["Distorsion (k$)"].sum()) < 1e-6                                    # une subvention croisée se compense toujours entre les lignes
    assert r.loc["Contrats aéro et rail", "Distorsion (k$)"] > 0 > r.loc["Usinage sur mesure", "Distorsion (k$)"]
    assert abs(r["Indirect ABC (k$)"].sum() - TOTAL_INDIRECT) < 1e-6
    assert r["Rang ABC"].tolist() and set(r["Rang ABC"]) == {1, 2, 3, 4}


def test_planchers_de_prix_sont_ordonnes():
    t = C.planchers_prix(0.15).set_index("Produit")
    for p, r in t.iterrows():
        assert r["Plancher variable ($)"] < r["Plancher spécifique ($)"]
        assert abs(r["Prix cible ($)"] * 0.85 - r["Plancher complet ABC ($)"]) < 1e-6
    assert t.loc["Contrats aéro et rail", "Position"] == "Sous le coût complet"
    assert t.loc["Prototypage", "Position"] == "Sous le coût spécifique"
    assert t.loc["Usinage sur mesure", "Position"] == "Au-dessus du prix cible"


def test_sensibilite_et_levier():
    base = C.resultat_scenario()
    assert abs(base - C.resultat_et_point_mort(C.contribution())["resultat"]) < 1e-9
    s = C.sensibilite_resultat(0.10)
    assert s.iloc[0]["Facteur"] == "Prix de vente"                                    # le prix est le facteur qui pèse le plus
    assert (s["Favorable (k$)"] > 0).all() and (s["Défavorable (k$)"] < 0).all()
    lev = C.levier_exploitation()
    assert abs(lev["degre_levier"] * lev["resultat"] - lev["mcv"]) < 1e-9
    assert abs((C.resultat_scenario(var_volume=0.01) - base) / base - lev["degre_levier"] * 0.01) < 1e-9     # +1 % de volume = levier × 1 % de résultat


def test_point_mort_par_ligne():
    t = C.point_mort_produits().set_index("Produit")
    assert t.loc["Prototypage", "Marge de sécurité"] < 0 < t.loc["Usinage sur mesure", "Marge de sécurité"]
    for p, r in t.iterrows():
        assert abs(r["Point mort (milliers)"] * r["Marge unitaire ($)"] - r["Fixes spécifiques (k$)"]) < 1e-9


def test_mix_sous_contrainte_de_capacite():
    m = C.mix_capacite(40000, 0.20)
    assert abs(m["Heures allouées"].sum() - 40000) < 1e-6 and m.attrs["contrainte_active"]
    assert m["MCV par heure-machine ($)"].is_monotonic_decreasing                     # on sert d'abord ce qui rapporte le plus par heure
    assert m.attrs["mcv_optimale"] > m.attrs["mcv_actuelle"] and m.attrs["prix_ombre"] > 0
    large = C.mix_capacite(80000, 0.20)
    assert not large.attrs["contrainte_active"] and large.attrs["prix_ombre"] == 0 and large.attrs["heures_inutilisees"] > 0
    serre = C.mix_capacite(30000, 0.20)
    assert serre.attrs["mcv_optimale"] < serre.attrs["mcv_actuelle"]                  # moins de capacité que l'actuel : la marge baisse


def test_capacite_par_centre():
    t = C.capacite_centres()
    assert (t["Utilisation"] < 1).all() and (t["Coût de sous-activité (k$)"] > 0).all()
    for _, r in t.iterrows():
        assert abs(r["Charges fixes (k$)"] - r["Charges du centre (k$)"] * C.PART_FIXE_CENTRES) < 1e-9
        assert r["Taux fixe réel ($/unité)"] > r["Taux fixe normal ($/unité)"]
    surcharge = C.capacite_centres({**C.CAPACITE_NORMALE, "Usinage CNC": 30000.0})
    assert surcharge.set_index("Centre").loc["Usinage CNC", "Coût de sous-activité (k$)"] < 0       # activité au-dessus de la normale : boni


def test_cout_de_la_qualite():
    q = C.cout_qualite()
    assert abs(q["total"] - q["detail"]["Montant (k$)"].sum()) < 1e-9 and abs(q["conformite"] + q["non_conformite"] - q["total"]) < 1e-9
    assert 0 < q["pct_ventes"] < 0.10 and 0 < q["ratio_non_conformite"] < 1
    assert set(q["par_categorie"].index) == {"Prévention", "Évaluation", "Défaillance interne", "Défaillance externe"}


def test_regle_d_investigation_et_limites_de_controle():
    assert C.investigation(7540, 100000) and not C.investigation(1000, 100000)       # sous le seuil en dollars
    assert not C.investigation(3000, 100000, 0.05, 2500)                             # sous le seuil en pourcentage (5 % de 100 000 = 5 000)
    h = C.historique_ecarts(courant={"Rendement (heures)": 7540})
    assert len(h) == 12 and h.index[-1] == "2026-09" and h.equals(C.historique_ecarts(courant={"Rendement (heures)": 7540}))
    lim = C.limites_controle(h)
    assert lim.loc["Rendement (heures)", "Hors limites"] and not lim.loc["Frais variables", "Hors limites"]
    assert (lim["Limite haute"] > lim["Moyenne"]).all()


def test_decomposition_de_l_ecart_de_prix():
    d = C.decomposer_ecart_prix(1253, 0.03, 0.55, 7.80, 5010)
    assert abs(d["effet_marche"] - 7.80 * 0.55 * 0.03 * 5010) < 1e-9 and abs(d["effet_marche"] + d["effet_achat"] - 1253) < 1e-9


if __name__ == "__main__":
    for nom, f in sorted(globals().items()):
        if nom.startswith("test_"):
            f()
            print("OK", nom)
    print("Tous les tests passent.")
