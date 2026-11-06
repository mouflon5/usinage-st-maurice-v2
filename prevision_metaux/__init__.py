"""Prévision des prix des métaux (acier, aluminium, nickel, cuivre) : données FRED mensuelles, trois modèles statistiques, backtest walk-forward.

    python -m prevision_metaux.calcul --update     # données à jour + modèles de chaque cible (quelques minutes)
    python -m prevision_metaux.calcul --fenetres 12   # essai rapide

Les résultats sont écrits dans donnees_externes/metaux/<cible>/ et lus par la vue « Prix des métaux ».
"""
