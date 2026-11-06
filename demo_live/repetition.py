"""Répétition générale : joue les 12 scénarios de démonstration à la suite (mode simulé, sans pause) et vérifie l'issue attendue.

    python -m demo_live.repetition            # repart d'une base neuve, ~1,5 minute
    python -m demo_live.repetition --garder   # ne remet pas la base de démo à zéro à la fin

À lancer la veille et juste avant la présentation : si une ligne est en échec, ne la présentez pas sans l'avoir comprise.
La base de démo est remise à zéro à la fin (sauf --garder) pour que la présentation parte d'un état propre.
"""
import json
import os
import sqlite3
import subprocess
import sys
import time

from demo_live import moteur as M

OK_CHARGE = {"complet", "complet_avec_reserves", "a_arbitrer"}
ATTENDU = {
    "normal": (OK_CHARGE, False), "commercants": (OK_CHARGE, False), "ambigu": ({"a_arbitrer", "complet_avec_reserves", "complet"}, False),
    "jumeaux": (OK_CHARGE, True), "remboursement": (OK_CHARGE, True), "collision": (OK_CHARGE, False), "volume": (OK_CHARGE, False),
    "mois_manquant": ({"arrete_a1"}, False), "solde_casse": ({"arrete_a2"}, False),
    "base_corrompue": ({"bloque_a6", "arrete_a4", "arrete_a5"}, False), "injection": (OK_CHARGE, False), "panne_llm": (OK_CHARGE, False),
}


def main():
    garder = "--garder" in sys.argv
    sans_reset = "--sans-reset" in sys.argv
    if not sans_reset:
        M.reinitialiser()
    prefixe = ("raf" + time.strftime("%H%M%S") + "_") if sans_reset else "rep_"
    echecs = 0
    print(f"{'scénario':<16}{'issue':<24}{'A8':<6}{'durée':>7}   verdict")
    for c in M.CATALOGUE:
        rid = prefixe + c["cle"]
        t0 = time.time()
        subprocess.run([sys.executable, "-m", "demo_live.moteur", "--run-id", rid, "--scenario", c["cle"], "--delai", "0"],
                       cwd=M.RACINE, capture_output=True)
        con = sqlite3.connect(M.DB_EVENEMENTS)
        r = con.execute("SELECT resume FROM runs WHERE run_id=?", (rid,)).fetchone()
        con.close()
        res = json.loads(r[0]) if r and r[0] else {}
        issue = res.get("statut_pipeline")
        reserves = [k for k in res.get("a8_constats", []) if k.get("gravite") == "reserve"]
        statuts, veut_a8 = ATTENDU[c["cle"]]
        ok = issue in statuts and (bool(reserves) or not veut_a8)
        echecs += not ok
        print(f"{c['cle']:<16}{str(issue):<24}{len(reserves):<6}{time.time() - t0:>6.1f}s   {'OK' if ok else 'ÉCHEC'}")
    print("\nRépétition", "réussie." if not echecs else f"terminée avec {echecs} échec(s).")
    if not garder and not sans_reset:
        M.reinitialiser()
        print("Base de démo remise à zéro.")
    sys.exit(1 if echecs else 0)


if __name__ == "__main__":
    main()
