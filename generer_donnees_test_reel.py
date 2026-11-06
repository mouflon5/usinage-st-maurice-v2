"""
Génère un relevé PDF de test « réaliste » — vrai compte (Desjardins EOP), vraies
descriptions correspondant aux mots-clés existants dans tresorerie.db, plus une
ligne volontairement non classifiable pour tester le cas « à classer ».

Période choisie : 2026-09, un mois déjà présent dans l'historique (48 mois de
2023-01 à 2026-12) — important, car R8/SARIMAX exige exactement 48 mois distincts.
Ajouter un mois hors de cette plage casserait le calcul.
"""

import os
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter

DOSSIER = "releves_test_reel"
COMPTE = "Desjardins EOP"


def creer_releve(chemin: str, compte: str, lignes: list[str]) -> None:
    c = canvas.Canvas(chemin, pagesize=letter)
    c.setFont("Courier", 10)
    y = 750
    c.drawString(50, y, f"Relevé de compte {compte}")
    y -= 30
    for ligne in lignes:
        c.drawString(50, y, ligne)
        y -= 15
    c.save()


def lignes_en_cascade(solde_depart: float, mouvements: list[tuple[str, str, float]]) -> list[str]:
    lignes = []
    solde = solde_depart
    for date, description, montant in mouvements:
        solde = round(solde + montant, 2)
        lignes.append(f"{date}  {description:<48}{montant:>12.2f}{solde:>12.2f}")
    return lignes


if __name__ == "__main__":
    os.makedirs(DOSSIER, exist_ok=True)

    mouvements = [
        ("2026-09-14", "MATIERES PREMIERES - ACIER RUSSEL TROIS-RIVIERES FACT 99001", -60000.00),
        ("2026-09-15", "PAIE PRODUCTION - DEPOT DIRECT EMPLOYES FACT 99002", -95000.00),
        ("2026-09-16", "FACTURE USINAGE - KRUGER TROIS-RIVIERES FACT 99003", 180000.00),
        ("2026-09-17", "HYDRO - HYDRO-QUEBEC TARIF M FACT 99004", -28000.00),
        ("2026-09-18", "DIVERS - FOURNISSEUR INCONNU FACT 99005", -5000.00),  # volontairement non reconnu
    ]
    lignes = lignes_en_cascade(1_000_000.00, mouvements)
    creer_releve(os.path.join(DOSSIER, f"{COMPTE}_2026-09.pdf"), COMPTE, lignes)

    print(f"Relevé réaliste créé dans ./{DOSSIER}/ pour {COMPTE}, période 2026-09")
    print("4 transactions classifiables (mots-clés réels) + 1 volontairement 'à classer'")
