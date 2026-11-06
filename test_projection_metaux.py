"""Test de la projection du prix des métaux (projection_metaux.py et paquet prevision_metaux) : données, indices, trajectoires, effet sur la trésorerie."""
import os
import sqlite3
import sys
import tempfile

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import projection_metaux as pm  # noqa: E402
from prevision_metaux import base, donnees  # noqa: E402

SERIES = pm.charger_series(None)


def _base_journal() -> str:
    """Base minimale : un an de journal, 100 000 $ de ventes (rang 20) et 40 000 $ d'achats de matières (rang 2) par mois."""
    chemin = os.path.join(tempfile.mkdtemp(), "t.db")
    c = sqlite3.connect(chemin)
    c.executescript("CREATE TABLE categories (categorie TEXT, ordre INTEGER);"
                    "CREATE TABLE journal_general (mois INTEGER, annee INTEGER, categorie TEXT, montant REAL);"
                    "CREATE TABLE parametres (domaine TEXT, cle TEXT, valeur TEXT);")
    c.executemany("INSERT INTO categories VALUES (?, ?)", [("Ventes", 20), ("Matières", 2)])
    for m in range(1, 13):
        c.execute("INSERT INTO journal_general VALUES (?, 2026, 'Ventes', 100000)", (m,))
        c.execute("INSERT INTO journal_general VALUES (?, 2026, 'Matières', -40000)", (m,))
    c.execute("INSERT INTO parametres VALUES ('forecast', 'seuil_securite', '200000')")
    c.commit()
    c.close()
    return chemin


DB = _base_journal()


def _ctx(**kw):
    h = pm.Hypotheses(taux_change=float(SERIES["fx"].iloc[-250:].mean()), **kw)      # change = change de référence : aucun effet de change
    return pm.contexte(h, SERIES, modeles=None), h


def test_series_et_panier():
    for cle in ("alu", "acier", "nickel", "cuivre", "fx", "panier"):
        assert len(SERIES[cle]) > 100, cle
    p = SERIES["panier"]
    assert abs(p.iloc[-12:].mean() - 1) < 1e-9                    # le panier vaut 1 en moyenne sur la dernière année
    assert abs(sum(donnees.PANIER.values()) - 1) < 1e-9


def test_catalogue_et_import_en_base():
    chemin = os.path.join(tempfile.mkdtemp(), "m.db")
    sqlite3.connect(chemin).close()
    assert not base.disponible(chemin)
    n = base.importer(chemin)
    assert base.disponible(chemin) and n["PALUMUSDM"] > 300
    assert all(v == 0 for v in base.importer(chemin).values())    # idempotent
    cat = base.catalogue(chemin)
    assert {"PALUMUSDM", "WPU1017", "PNICKUSDM", "PCOPPUSDM", "DEXCAUS"} <= set(cat["code"])
    assert abs(base.lire(chemin, "PALUMUSDM").iloc[-1] - SERIES["alu"].iloc[-1]) < 1e-6


def test_indice_d_achat():
    c, h = _ctx(part_matiere=0.5)
    assert abs(pm.indice_achat(c, c.ref)[()] - 1) < 1e-9 if np.ndim(pm.indice_achat(c, c.ref)) == 0 else abs(pm.indice_achat(c, [c.ref])[0] - 1) < 1e-9
    assert abs(pm.indice_achat(c, [1.2 * c.ref])[0] - 1.10) < 1e-9          # +20 % de marché × 50 % de part = +10 %
    assert pm.indice_achat(c, [0.5 * c.ref])[0] < 1
    c0, _ = _ctx(part_matiere=0.0)
    assert abs(pm.indice_achat(c0, [3 * c0.ref])[0] - 1) < 1e-9             # aucune part : le prix d'achat ne bouge pas
    # un dollar canadien plus faible renchérit les achats
    assert pm.indice_achat(c, [c.ref], fx=c.fx_ref * 1.1)[0] > 1


def test_trajectoire_des_trois_scenarios():
    c, _ = _ctx(horizon_mois=12, choc=0.10)
    t = pm.trajectoire(c)
    assert len(t) == 13 and abs(t["central"].iloc[0] - c.spot) < 1e-9
    assert (t["bas"].iloc[1:] < t["central"].iloc[1:]).all() and (t["central"].iloc[1:] < t["haut"].iloc[1:]).all()
    assert t["haut"].iloc[-1] - t["central"].iloc[-1] > t["haut"].iloc[3] - t["central"].iloc[3]    # l'incertitude croît avec l'horizon


def test_prix_inchange_aucun_effet():
    c, h = _ctx(reference="Dernier prix")
    base_j = pm.base_mensuelle(DB)
    d = pm.impact(c, np.full(13, c.spot), pm.trajectoire(c)["mois_civil"].to_numpy(), base_j)
    assert d["d_marge"].abs().max() < 1e-6 and d["d_cash"].abs().max() < 1e-6


def test_repercussion_complete_preserve_la_marge():
    c, h = _ctx(reference="Dernier prix", part_matiere=1.0, passage=1.0, delai_mois=0, elasticite=0.0)
    base_j = pm.base_mensuelle(DB)
    d = pm.impact(c, np.full(13, c.spot * 1.10), pm.trajectoire(c)["mois_civil"].to_numpy(), base_j)
    assert abs(d["achats"].iloc[0] - 1.10 * 40000) < 1e-6                    # achats +10 %
    assert abs(d["ventes"].iloc[0] - (100000 + 0.10 * 40000)) < 1e-6         # ventes + 100 % de la hausse du coût
    assert d["d_marge"].abs().max() < 1e-6                                   # la marge est préservée en dollars


def test_aucune_repercussion_la_marge_absorbe_tout():
    c, h = _ctx(reference="Dernier prix", part_matiere=1.0, passage=0.0, delai_mois=0, elasticite=0.0)
    d = pm.impact(c, np.full(13, c.spot * 1.10), pm.trajectoire(c)["mois_civil"].to_numpy(), pm.base_mensuelle(DB))
    assert abs(d["d_marge"].iloc[0] + 4000) < 1e-6                           # −10 % × 40 000 $
    assert d["d_cash"].iloc[-1] < 0 and d["d_cash_cumul"].iloc[-1] < d["d_cash_cumul"].iloc[0]


def test_decalage_et_encaisse():
    assert abs(pm._decale(np.array([0.0, 10.0, 10.0, 10.0]), 1.0)[2] - 10.0) < 1e-9
    assert pm._decale(np.array([0.0, 10.0, 10.0]), 1.0)[1] == 0.0


def test_projection_et_sensibilite():
    r = pm.projeter(pm.Hypotheses(), DB, SERIES, None)
    assert r.seuil == 200000 and set(r.impacts) == set(pm.SCENARIOS) and len(r.impacts["central"]) == 12
    assert r.impacts["haut"]["achat_kg"].iloc[-1] > r.impacts["bas"]["achat_kg"].iloc[-1]
    s = pm.sensibilite(r, [-0.2, -0.1, 0.1, 0.2])
    assert s["Effet sur l'encaisse ($)"].is_monotonic_decreasing                   # plus le métal est cher, plus l'encaisse recule
    assert s["Prix d'achat ($/kg)"].is_monotonic_increasing


def test_modeles_precalcules():
    for cible in pm.CIBLES:
        m = pm.charger_modeles(cible)
        assert m is not None, cible
        assert {"Marche aléatoire", "ARIMA", "GARCH", "Ensemble"} <= set(pm.noms_modeles(m))
        c, _ = _ctx(cible=cible, modele="Ensemble")
        c = pm.contexte(c.h, SERIES, m)
        t = pm.trajectoire(c)
        assert len(t) == c.horizon + 1 and (t["bas"] <= t["haut"]).all()
    c = pm.contexte(pm.Hypotheses(modele="Modèle inconnu"), SERIES, pm.charger_modeles("panier"))
    assert c.alertes                                                               # repli sur la marche aléatoire, signalé


def test_variations_pour_les_etats_financiers():
    import etats_financiers as ef
    r = pm.projeter(pm.Hypotheses(), DB, SERIES, None)
    montants = {2026: {20: 1_200_000.0, 2: -480_000.0}}
    j = ef.Journal([2026], montants, {})
    v = pm.variations_etats_financiers(r, "central", j)
    assert abs(v["achats_base"] - 480_000) < 1e-6 and abs(v["var_produits"] * 480_000 - v["d_achats"]) < 1e-6


if __name__ == "__main__":
    for nom, f in sorted(globals().items()):
        if nom.startswith("test_"):
            f()
            print("OK", nom)
    print("Tous les tests passent.")
