"""Tests du moteur du réseau de neurones (raisonnement_graphe.py) et de son dessin (demo_live/reseau_ui.py), sur des événements synthétiques.
Lancer : python test_reseau_raisonnement.py"""
from __future__ import annotations

import json
import sys

import raisonnement_graphe as G

_n, _ko = 0, 0


def ok(cond, msg):
    global _n, _ko
    _n += 1
    if not cond:
        _ko += 1
        print("ÉCHEC :", msg)


def ag(code, sorties, statut="complet", duree=1.0, message="ok", **resume):
    return {"type": "agent", "agent": code, "statut": statut, "duree": duree, "message": message, "detail": {"resume": {"sorties": sorties, **resume}}}


def passage_normal():
    kpi_a = json.dumps({"solde_actuel": 600000, "creux": 400000, "semaines_sous_seuil": 3, "coussin_requis": 20000, "flux_net_2026": 1400000, "ecart_budget_annee": 80000})
    kpi_b = json.dumps({"solde_actuel": 800000, "creux": 470000, "semaines_sous_seuil": 1, "coussin_requis": 24000, "flux_net_2026": 1500000, "ecart_budget_annee": 90000})
    return [
        {"type": "instantane", "kpi": kpi_a},
        ag("A1", {"fichiers_trouves": 12}), ag("A2", {"transactions": 900}), ag("A3", {"classees_a3": 880, "residu_a3": 20}),
        ag("A4", {"previsions": 52, "flux_net_prevu": 100}), ag("A5", {"ecarts_a5": 4}), ag("A6", {"controles_a6": 11}, controles=[{"ok": True}] * 10 + [{"ok": False}]),
        ag("A8", {"constats_a8": 2}), ag("A7", {"fichiers_a7": 3}),
        {"type": "instantane", "kpi": kpi_b}, {"type": "fin", "statut": "complet", "message": "fin", "detail": {"statut_pipeline": "complet", "fichiers": ["a.pdf"]}},
    ]


def traces_normales():
    return [{"id": 1, "agent": "A3", "decision": None, "fournisseur": "simule", "modele": "sim"}, {"id": 2, "agent": "A3", "decision": "escalade_confiance", "decision_detail": "confiance 0.4 < seuil", "fournisseur": "simule", "modele": "sim"},
            {"id": 3, "agent": "A5", "decision": "rejet_nombre", "decision_detail": "nombre 99 absent", "fournisseur": "claude", "modele": "x"}]


def main() -> int:
    # structure seule
    s = G.construire()
    ok(not s.avec_passage and G.nb_etapes(s) == 0, "sans événement : structure seule")
    ok(len(s.neurones) == len(G.ENTREES) + 8 + 8 + len(G.INDICATEURS) + 2, "nombre de neurones de la structure")
    ok(all(x.source in s.neurones and x.cible in s.neurones for x in s.synapses), "toutes les synapses relient des neurones existants")
    ok(any(x.source == "A2" and x.cible == "A3" and x.type == "flux" for x in s.synapses), "synapse A2→A3")
    ok({"A2", "llm_A3", "gf_A3"} <= G.voisins(s, "A3", 1), "voisins directs d'A3")
    ok(G.voisins(s, "A3", 2) >= G.voisins(s, "A3", 1), "le voisinage grandit avec la profondeur")
    ok(set(G.allume(s, 0)) >= set(G.ENTREES), "entrées allumées à l'étape 0")

    # passage normal
    r = G.construire(passage_normal(), traces_normales(), [], "t1")
    m = G.resume(r)
    ok(r.avec_passage and m["agents_actifs"] == 8, f"8 agents actifs ({m})")
    ok(next(x.poids for x in r.synapses if (x.source, x.cible) == ("A2", "A3") and x.type == "flux") == 900, "poids A2→A3 = transactions")
    ok(r.neurones["solde_actuel"].valeur and r.neurones["solde_actuel"].delta == 200000 and r.neurones["solde_actuel"].delta_bon is True, "solde : +200 000 dans le bon sens")
    ok(r.neurones["semaines_sous_seuil"].delta == -2 and r.neurones["semaines_sous_seuil"].delta_bon is True, "moins de semaines sous le seuil = favorable")
    ok(r.neurones["k_controles"].valeur == "10 / 11" and r.neurones["k_controles"].statut == "crit", "contrôle en échec signalé")
    ok(r.neurones["k_a_classer"].statut == "att", "résidu à classer = à surveiller")
    ok(r.neurones["gf_A3"].details["rejets"] == 1 and r.neurones["gf_A3"].statut == "att", "garde-fou A3 : une escalade")
    ok(r.neurones["gf_A5"].statut == "crit", "rejet dur A5 = critique")
    ok(r.neurones["llm_A3"].valeur.endswith("simulé"), "échanges simulés signalés")
    ok(r.neurones["llm_A8"].valeur == "non sollicité", "LLM non sollicité")
    ok(r.neurones["sortie"].statut == "ok" and r.neurones["humain"].statut == "ok", "sortie et humain allumés")
    ok(len(G.allume(r, 3)) < len(G.allume(r, G.nb_etapes(r))), "le rejeu allume progressivement")
    amont, aval = G.amont_aval(r, "A3")
    ok(any(x.source == "A2" for x in amont) and any(x.cible == "A4" for x in aval), "amont/aval d'A3")

    # arrêt précoce + arbitrage
    court = [ag("A1", {"fichiers_trouves": 4}), ag("A2", {"transactions": 50}), ag("A3", {"classees_a3": 40, "residu_a3": 10}, statut="a_arbitrer"), {"type": "fin", "statut": "a_arbitrer", "detail": {"statut_pipeline": "arbitrage"}}]
    r2 = G.construire(court, [], None, "t2")
    ok(r2.neurones["A4"].statut == "inactif" and r2.neurones["A7"].statut == "inactif", "agents non exécutés inactifs")
    ok(r2.neurones["humain"].statut == "att" and r2.neurones["sortie"].statut == "att", "arbitrage : humain en attente")
    ok(r2.neurones["solde_actuel"].statut == "inactif", "sans KPI, indicateur inactif")

    # utilitaires
    ok(G._kpi({"kpi": "pas du json"}) is None and G._kpi({"kpi": '{"a": 1}'}) == {"a": 1}, "décodage des KPI")
    ok([G._categorie_decision(x) for x in (None, "accepte", "rejet_x", "escalade")] == ["accepte", "accepte", "rejet", "escalade"], "catégories de décision")

    # dessin
    try:
        from demo_live import reseau_ui as U
        for rr in (s, r, r2):
            f = U.figure(rr, G.nb_etapes(rr), "A3", 1, True, True)
            ok(len(f.data) >= 5 and len(f.layout.annotations) > 20, "figure construite")
            U.figure(rr, 0, None, 0, False, False)
    except ImportError as e:
        print("dessin non testé :", e)
    print(f"{_n - _ko}/{_n} tests réussis")
    return 1 if _ko else 0


if __name__ == "__main__":
    sys.exit(main())
