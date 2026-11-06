"""Données du scénario 2 — ajouts en octobre 2026 (mois différent du scénario 1,
pour voir clairement que chaque scénario affecte son propre mois)."""

import os
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter

DOSSIER = "releves_scenario2"
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
        ("2026-10-20", "MATIERES PREMIERES - METAUX SOLUTIONS QUEBEC FACT 77101", -220000.00),
        ("2026-10-21", "SOUS-TRAITANCE - TRAITEMENT THERMIQUE MAURICIE FACT 77102", -95000.00),
        ("2026-10-22", "ASSURANCE - INTACT ASSURANCE ENTREPRISES FACT 77103", -15000.00),
    ]
    lignes = lignes_en_cascade(1_000_000.00, mouvements)
    creer_releve(os.path.join(DOSSIER, f"{COMPTE}_2026-10.pdf"), COMPTE, lignes)

    print(f"Scénario 2 : relevé créé dans ./{DOSSIER}/ — effet net attendu : {sum(m[2] for m in mouvements):+,.2f} $")
