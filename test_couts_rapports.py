"""Test des rapports de coûts de revient (couts_rapports.py) : charpente commune, seuils, cohérence avec le moteur, exports."""
import html
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import couts_rapports as R  # noqa: E402
import couts_revient as C  # noqa: E402


def test_les_trois_niveaux_ont_la_meme_charpente():
    assert list(R.RAPPORTS) == ["Stratégique", "Tactique", "Opérationnel"]
    for niv in R.RAPPORTS:
        r = R.construire(niv)
        assert r.niveau == niv and r.destinataires and r.frequence and r.objectif
        assert len(r.kpis) >= 6 and len(r.messages) >= 4 and len(r.sections) >= 4 and len(r.actions) >= 5
        assert all(k.statut in R.STATUTS for k in r.kpis) and all(a.responsable and a.echeance and a.impact for a in r.actions)
        assert any(a.priorite == "Haute" for a in r.actions)


def test_le_rapport_strategique_s_appuie_sur_le_moteur():
    r = R.rapport_strategique()
    k = {x.libelle: x for x in r.kpis}
    rent = C.rentabilite_produits()
    assert R.fk(rent["Ventes (k$)"].sum()) == k["Ventes"].valeur
    assert k["Lignes déficitaires au coût complet ABC"].valeur == "2 sur 4" and k["Lignes déficitaires au coût complet ABC"].statut == "crit"
    assert "Contrats aéro et rail" in " ".join(r.messages) and "prototypage" in " ".join(a.action for a in r.actions).lower()
    assert any("Usinage sur mesure" in m for m in r.messages)                       # la ligne qui porte le résultat est désignée


def test_les_seuils_changent_les_constats():
    r = R.rapport_tactique(R.Parametres(seuil_pct=0.50))                           # seuil très haut : plus rien à investiguer
    k = {x.libelle: x for x in r.kpis}
    assert k["Écarts à investiguer"].valeur.startswith("0 ") and k["Écarts à investiguer"].statut == "ok"
    r2 = R.rapport_tactique(R.Parametres(seuil_pct=0.01, seuil_dollars=100))
    assert {x.libelle: x for x in r2.kpis}["Écarts à investiguer"].statut == "crit"
    serre = R.rapport_strategique(R.Parametres(capacite_cnc=30000.0))
    large = R.rapport_strategique(R.Parametres(capacite_cnc=60000.0))
    u = lambda rap: {x.libelle: x for x in rap.kpis}["Utilisation du centre d'usinage CNC"].valeur
    assert u(serre) != u(large)


def test_les_ecarts_du_mois_decrits_dans_le_rapport_tactique():
    r = R.rapport_tactique()
    assert any("Rendement (heures)" in m for m in r.messages)                       # la cause principale est nommée
    dec = C.decomposer_ecart_prix(1253.0, 0.03, 0.55, C.STANDARD["prix"], 5010.0)
    assert R.fd(dec["effet_marche"]) in " ".join(r.messages)                         # marché contre achat


def test_le_rapport_operationnel_donne_des_standards_et_un_bareme():
    r = R.rapport_operationnel()
    titres = [s.titre for s in r.sections]
    assert any("Alertes" in t for t in titres) and any("barème" in t for t in titres) and any("standards" in t for t in titres)
    k = {x.libelle: x for x in r.kpis}
    assert k["Matière achetée contre standard"].statut == "att" and k["Coût par pièce : réel contre standard"].statut == "crit"


def test_exports():
    for niv in R.RAPPORTS:
        r = R.construire(niv)
        md, h, pdf = R.en_markdown(r), R.en_html(r), R.en_pdf(r)
        assert md.startswith("# ") and "## Plan d'action" in md and "## Indicateurs" in md
        assert h.startswith("<!doctype html>") and "Plan d'action" in html.unescape(h) and r.titre in html.unescape(h)
        assert pdf[:4] == b"%PDF" and len(pdf) > 3000
    assert R.fk(1234567) == "1 234 567 k$" and R.fk(-5, True) == "−5 k$" and R.fp(0.123) == "12,3 %" and R.fd(1234.5, 1) == "1 234,5 $"


if __name__ == "__main__":
    for nom, f in sorted(globals().items()):
        if nom.startswith("test_"):
            f()
            print("OK", nom)
    print("Tous les tests passent.")
