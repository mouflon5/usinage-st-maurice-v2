"""Données du scénario 1 — ajouts en septembre 2026."""

import os
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter

DOSSIER = "releves_scenario1"
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
        ("2026-09-25", "FACTURE USINAGE - MARMEN INC FACT 77001", 500000.00),
        ("2026-09-26", "MATIERES PREMIERES - ALCAN DISTRIBUTION FACT 77002", -150000.00),
        ("2026-09-27", "PAIE PRODUCTION - DEPOT DIRECT EMPLOYES FACT 77003", -95000.00),
    ]
    lignes = lignes_en_cascade(1_000_000.00, mouvements)
    creer_releve(os.path.join(DOSSIER, f"{COMPTE}_2026-09.pdf"), COMPTE, lignes)

    print(f"Scénario 1 : relevé créé dans ./{DOSSIER}/ — effet net attendu : {sum(m[2] for m in mouvements):+,.2f} $")
