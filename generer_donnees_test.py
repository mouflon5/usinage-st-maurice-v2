"""
Génère 3 scénarios de test pour l'orchestrateur A1 → A2.

- releves_test_succes/     : tout est propre, le pipeline va jusqu'au bout.
- releves_test_arret_a1/   : trou de période volontaire, A1 arrête tout avant A2.
- releves_test_arret_a2/   : périodes complètes, mais anomalie de solde en 2026-02,
                              A2 arrête le pipeline après A1.
"""

import os
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter

COMPTE = "BNC-1234"


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
    """Calcule les soldes en cascade à partir d'une liste (date, description, montant)."""
    lignes = []
    solde = solde_depart
    for date, description, montant in mouvements:
        solde = round(solde + montant, 2)
        lignes.append(f"{date}  {description:<28}{montant:>10.2f}{solde:>10.2f}")
    return lignes


if __name__ == "__main__":
    # --- Scénario 1 : succès complet ---
    dossier = "releves_test_succes"
    os.makedirs(dossier, exist_ok=True)
    creer_releve(
        os.path.join(dossier, f"{COMPTE}_2026-01.pdf"), COMPTE,
        lignes_en_cascade(10000.00, [
            ("2026-01-05", "Achat fournisseur ABC", -1250.00),
            ("2026-01-12", "Paiement client XYZ", 3200.00),
            ("2026-01-20", "Frais bancaires", -25.00),
        ]),
    )
    creer_releve(
        os.path.join(dossier, f"{COMPTE}_2026-02.pdf"), COMPTE,
        lignes_en_cascade(11925.00, [
            ("2026-02-03", "Vente produit", 1500.00),
            ("2026-02-10", "Achat matières premières", -800.00),
            ("2026-02-15", "Virement reçu", 500.00),
        ]),
    )
    print(f"Scénario succès       : 2 relevés propres dans ./{dossier}/")

    # --- Scénario 2 : arrêt à A1 (trou de période en 2026-02) ---
    dossier = "releves_test_arret_a1"
    os.makedirs(dossier, exist_ok=True)
    creer_releve(
        os.path.join(dossier, f"{COMPTE}_2026-01.pdf"), COMPTE,
        lignes_en_cascade(10000.00, [("2026-01-05", "Achat", -100.00)]),
    )
    # 2026-02 volontairement absent
    creer_releve(
        os.path.join(dossier, f"{COMPTE}_2026-03.pdf"), COMPTE,
        lignes_en_cascade(9900.00, [("2026-03-05", "Achat", -50.00)]),
    )
    print(f"Scénario arrêt à A1    : trou volontaire en 2026-02 dans ./{dossier}/")

    # --- Scénario 3 : arrêt à A2 (anomalie de solde en 2026-02) ---
    dossier = "releves_test_arret_a2"
    os.makedirs(dossier, exist_ok=True)
    creer_releve(
        os.path.join(dossier, f"{COMPTE}_2026-01.pdf"), COMPTE,
        lignes_en_cascade(10000.00, [("2026-01-05", "Achat", -100.00)]),
    )
    lignes_anomalie = [
        "2026-02-03  Vente produit                     1500.00   11400.00",
        "2026-02-15  Virement suspect                    500.00   12500.00",  # devrait être 11900.00
    ]
    creer_releve(os.path.join(dossier, f"{COMPTE}_2026-02.pdf"), COMPTE, lignes_anomalie)
    print(f"Scénario arrêt à A2    : anomalie de solde volontaire dans ./{dossier}/")
