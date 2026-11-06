"""
Test local de l'orchestrateur, à lancer dans PyCharm.

Étapes :
    1. python generer_donnees_test.py   (crée les 3 dossiers de scénario)
    2. python test_local.py             (exécute le pipeline sur chacun)
"""

from graph import graph

COMPTE = "BNC-1234"


def executer_scenario(nom: str, dossier: str, periode_debut: str, periode_fin: str) -> None:
    print("=" * 70)
    print(f"SCÉNARIO : {nom}")
    entree = {
        "compte": COMPTE,
        "dossier_releves": dossier,
        "periode_debut": periode_debut,
        "periode_fin": periode_fin,
    }
    resultat = graph.invoke(entree)
    print(f"Statut pipeline : {resultat['statut_pipeline']}")
    print(f"Message         : {resultat['message_pipeline']}")
    print("=" * 70)
    print()


if __name__ == "__main__":
    executer_scenario("1. Succès complet (A1 -> A2 -> fin)", "releves_test_succes", "2026-01", "2026-02")
    executer_scenario("2. Arrêt à A1 (trou de période)", "releves_test_arret_a1", "2026-01", "2026-03")
    executer_scenario("3. Arrêt à A2 (anomalie de solde)", "releves_test_arret_a2", "2026-01", "2026-02")
