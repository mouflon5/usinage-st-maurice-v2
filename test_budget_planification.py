"""Test de la planification budgétaire (budget_planification.py) et du process mining (process_mining.py) : identités, cohérence et reproductibilité."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import budget_planification as B  # noqa: E402
import couts_revient as C  # noqa: E402
import process_mining as P  # noqa: E402

TOTAL_INDIRECT = sum(C.CENTRES_AUXILIAIRES.values()) + sum(C.CENTRES_PRINCIPAUX.values())


# --- Budget -----------------------------------------------------------------------------------------------------------------------------------------
def test_base_concorde_avec_le_cout_de_revient():
    r = B.resultat_base()
    rent = C.rentabilite_produits()
    assert abs(r["ventes"] - rent["Ventes (k$)"].sum()) < 1e-6
    assert abs(r["indirects"] - TOTAL_INDIRECT) < 1e-9
    assert abs(r["resultat"] - rent["Marge complète ABC (k$)"].sum()) < 1e-6


def test_top_down_enveloppe_residuelle_et_repartition():
    td = B.top_down()
    assert abs(td["ventes"] - td["directs"] - td["enveloppe"] - td["resultat"]) < 1e-6
    assert abs(td["par_ligne"]["Ventes cibles"].sum() - td["ventes"]) < 1e-6
    assert abs(td["par_centre"]["Enveloppe cible"].sum() - td["enveloppe"]) < 1e-6
    assert abs(td["resultat"] - td["ventes"] * td["marge"] / 100) < 1e-6
    assert B.top_down(marge_cible=15)["enveloppe"] < td["enveloppe"]                   # une cible plus exigeante resserre l'enveloppe


def test_bottom_up_sans_hypotheses_retrouve_la_base():
    neutre = B.HYP_LIGNES * 0
    bu = B.bottom_up(neutre, {"inflation_matiere": 0, "inflation_salaires": 0, "inflation_generale": 0, "prudence": 0})
    assert abs(bu["resultat"] - B.resultat_base()["resultat"]) < 1e-6
    assert abs(bu["indirects"] - TOTAL_INDIRECT) < 1e-6


def test_pont_ascendant_est_exact():
    bu = B.bottom_up()
    pont = B.pont_ascendant(bu)
    assert abs(B.resultat_base()["resultat"] + sum(v for _, v in pont) - bu["resultat"]) < 1e-6
    assert abs(bu["indirects"] - bu["indirects_sans_prudence"] - bu["prudence"]) < 1e-9


def test_capacite_machine_suit_le_volume():
    h0 = B.heures_machine(B.HYP_LIGNES * 0)
    assert abs(h0["requises"] - h0["base"]) < 1e-9
    assert B.heures_machine()["requises"] > h0["requises"]


def test_base_zero_respecte_enveloppe_et_obligatoires():
    p = B.paquets()
    assert abs(p[p["Niveau"] != "Amélioré"]["Coût (k$)"].sum() - TOTAL_INDIRECT) < 1e-9            # minimum + actuel = frais indirects de base
    td = B.top_down()
    bz = B.zbb(td["enveloppe"])
    assert bz["total"] <= td["enveloppe"] + 1e-9 and not bz["obligatoire_depasse"]
    d = bz["paquets"]
    assert d.loc[d["Obligatoire"], "Financé"].all()
    cumul_non_finance = d[~d["Financé"]]["Efficience"]
    assert (cumul_non_finance <= d[d["Financé"] & ~d["Obligatoire"]]["Efficience"].max() + 1e-9).all()  # rien de mieux classé que le dernier financé n'est resté dehors, sauf par manque de place
    assert abs(bz["par_centre"]["Budget base zéro"].sum() - bz["total"]) < 1e-6


def test_base_zero_enveloppe_trop_basse_signale_le_plancher():
    bz = B.zbb(1000.0)
    assert bz["obligatoire_depasse"] and abs(bz["total"] - bz["obligatoire"]) < 1e-9


def test_base_zero_paquet_process_mining():
    sans = B.zbb(7200.0)
    avec = B.zbb(7200.0, economie_process_mining=40.0)
    assert B.PAQUET_PM in set(avec["paquets"]["Paquet"]) and B.PAQUET_PM not in set(sans["paquets"]["Paquet"])
    net = avec["paquets"].set_index("Paquet").loc[B.PAQUET_PM, "Coût net (k$)"]
    assert abs(net - 5.0) < 1e-9                                                                   # 45 k$ moins 40 k$ d'économie


def test_reconciliation_somme_des_leviers():
    td, bu = B.top_down(), B.bottom_up()
    bz = B.zbb(td["enveloppe"], indexation=bu["indexation_indirect"])
    rec = B.reconciliation(td, bu, bz)
    assert abs(rec["resultat_bu"] + sum(v for _, v in rec["leviers"]) - rec["resultat_retenu"]) < 1e-6
    assert abs(rec["ventes"] - rec["directs"] - rec["indirects"] - rec["resultat_retenu"]) < 1e-6    # le budget retenu est équilibré
    assert abs(rec["ecart_residuel"] - (rec["cible"] - rec["resultat_retenu"])) < 1e-9


def test_iterations_convergent():
    it = B.iterations(600.0)
    assert it["Écart restant"].is_monotonic_decreasing and it["Écart restant"].iloc[-1] < 600 * 0.1
    assert abs(600.0 - it["Écart restant"].iloc[-1] - it["Concession direction"].sum() - it["Effort gestionnaires"].sum()) < 1e-9


def test_phasage_somme_au_budget():
    td, bu = B.top_down(), B.bottom_up()
    rec = B.reconciliation(td, bu, B.zbb(td["enveloppe"]))
    ph = B.phasage(rec)
    assert abs(ph["Ventes"].sum() - rec["ventes"]) < 1e-6 and abs(ph["Résultat"].sum() - rec["resultat_retenu"]) < 1e-6
    assert len(ph) == 12 and abs(sum(B.SAISONNALITE) - 1) < 0.01


def test_calendrier_coherent():
    e = B.ETAPES
    assert (e["Fin"] >= e["Début"]).all() and e["Approche"].isin({"Top-down", "Bottom-up", "Base zéro", "Réconciliation", "Approbation", "Suivi"}).all()


# --- Process mining ---------------------------------------------------------------------------------------------------------------------------------
def test_journal_reproductible_et_ordonne():
    for nom in P.PROCESSUS:
        a, b = P.journal(nom), P.journal(nom)
        assert a.equals(b)
        assert set(P.PROCESSUS[nom].chemin) <= set(a["Activité"])
        for _, g in a.groupby("Cas"):
            assert g["Horodatage"].is_monotonic_increasing


def test_conformite_alignement():
    p = P.ACHATS
    import pandas as pd
    parfait = pd.DataFrame({"Cas": ["X"] * 9, "Activité": p.chemin, "Horodatage": pd.date_range("2026-04-01", periods=9, freq="D"), "Ressource": "r", "Montant ($)": 1.0})
    c = P.conformite(parfait)
    assert c.loc["X", "Conforme"] and abs(c.loc["X", "Aptitude"] - 1) < 1e-9
    saute = parfait[parfait["Activité"] != "Approbation de la commande"]
    c = P.conformite(saute)
    assert "Étape sautée" in c.loc["X", "Écarts"] and c.loc["X", "Aptitude"] < 1
    boucle = pd.concat([parfait, parfait.iloc[[5]].assign(Horodatage=pd.Timestamp("2026-04-20"))])
    assert "Reprise" in P.conformite(boucle).loc["X", "Écarts"]


def test_activite_optionnelle_n_est_pas_un_ecart():
    import pandas as pd
    p = P.FABRICATION
    chemin = [a for a in p.chemin if a not in p.optionnelles]
    d = pd.DataFrame({"Cas": ["Y"] * len(chemin), "Activité": chemin, "Horodatage": pd.date_range("2026-04-01", periods=len(chemin), freq="D"), "Ressource": "r", "Montant ($)": 1.0})
    c = P.conformite(d, p.nom)
    assert c.loc["Y", "Conforme"] and abs(c.loc["Y", "Aptitude"] - 1) < 1e-9


def test_suivis_directs_et_variantes():
    for nom in P.PROCESSUS:
        log = P.journal(nom)
        arcs = P.suivis_directs(log)
        assert arcs["Fréquence"].sum() == len(log) - log["Cas"].nunique()                         # un arc par paire d'événements consécutifs
        assert (arcs["Attente moyenne (h)"] >= 0).all()
        v = P.variantes(log, nom)
        assert v["Cas"].sum() == log["Cas"].nunique() and abs(v["Part (%)"].sum() - 100) < 1e-9 and v["Cumul (%)"].is_monotonic_increasing
        assert set(arcs["De"]) | set(arcs["Vers"]) <= set(P.PROCESSUS[nom].positions)            # tout arc a une position sur la carte


def test_goulots_tries_et_separation_des_taches():
    log = P.journal()
    g = P.goulots(P.suivis_directs(log))
    assert g["Attente totale (h)"].is_monotonic_decreasing and abs(P.goulots(P.suivis_directs(log), 100)["Part de l'attente (%)"].sum() - 100) < 1e-6
    sod = P.separation_taches(log)
    assert len(sod) > 0 and (sod["Cas"].isin(log["Cas"])).all()
    assert len(P.separation_taches(P.journal(P.FABRICATION.nom), P.FABRICATION.nom)) == 0


def test_cout_des_reprises():
    for nom in P.PROCESSUS:
        cr = P.cout_reprises(P.journal(nom), nom)
        assert cr["annuel"] > 0 and abs(cr["evitable_k"] - cr["annuel_k"] / 2) < 1e-9


if __name__ == "__main__":
    for nom, f in sorted(globals().items()):
        if nom.startswith("test_") and callable(f):
            f()
            print("OK", nom)
    print("Tous les tests passent.")
