"""Lance ton tableau de bord (R0–R8) sur la base de DÉMO, avec l'onglet « Agents ».

    python lancer_dashboard.py                  # utilise tresorerie_demo.db et le dossier sorties/
    python lancer_dashboard.py --port 8770
R8 lit la base en direct : après un passage du pipeline, rafraîchis la page pour voir l'effet.
R0–R7 sont des chiffres précalculés dans le HTML et ne bougent pas.
"""
import os
import sys

os.environ.setdefault("TRESORERIE_DB", os.path.abspath("tresorerie_demo.db"))
os.environ.setdefault("TRACES_DIR", os.path.abspath("sorties"))
if not os.path.isfile(os.environ["TRESORERIE_DB"]):
    sys.exit(f"Base introuvable : {os.environ['TRESORERIE_DB']} (voir README_DEMO.md, étape « copier la base »).")

import tresorerie_dashboard as td  # noqa: E402

if __name__ == "__main__":
    td.main()
