"""Lance TOUTE la démonstration en une commande :

    python lancer_demo.py                 # tableau de trésorerie (port 8765) + poste de démonstration (port 8501)
    python lancer_demo.py --reset         # repart d'une base de démo neuve
    python lancer_demo.py --port-tableau 8770 --port-app 8600 --pas-de-navigateur

Deux processus sont démarrés puis arrêtés ensemble (Ctrl+C) :
  1. le serveur de TON tableau de bord HTML en mode « direct » (R0–R7 recalculés depuis la base de démo,
     R8 SARIMAX en direct, rechargement automatique quand la base change) ;
  2. l'application Streamlit (démo en direct, trésorerie, pilotage, rapports, assistant).
"""
import argparse
import os
import socket
import subprocess
import sys
import time
import webbrowser

RACINE = os.path.dirname(os.path.abspath(__file__))
os.chdir(RACINE)
sys.path.insert(0, RACINE)


def port_libre(depart: int) -> int:
    for p in range(depart, depart + 30):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", p)) != 0:
                return p
    raise RuntimeError("Aucun port libre")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true", help="repartir d'une base de démo neuve")
    ap.add_argument("--port-tableau", type=int, default=8765)
    ap.add_argument("--port-app", type=int, default=8501)
    ap.add_argument("--pas-de-navigateur", action="store_true")
    a = ap.parse_args()

    from demo_live import moteur as M
    if a.reset or not os.path.isfile(M.BASE_DEMO):
        M.reinitialiser()
        print("Base de démo remise à zéro.")
    M.ouvrir().close()

    p_tab, p_app = port_libre(a.port_tableau), port_libre(a.port_app)
    env = dict(os.environ, TRESORERIE_DB=M.BASE_DEMO, TRESORERIE_REF=M.BASE_ORIGINE, TRESORERIE_LIVE="1",
               DEMO_DB=M.DB_EVENEMENTS, TRACES_DIR=M.TRACES, PYTHONIOENCODING="utf-8")
    os.makedirs(M.TRACES, exist_ok=True)
    serveur = subprocess.Popen([sys.executable, "tresorerie_dashboard.py", "--serve", "--no-browser", "--port", str(p_tab)], env=env)
    url_tab = f"http://127.0.0.1:{p_tab}/"
    env_app = dict(env, DEMO_TABLEAU_URL=url_tab)
    app = subprocess.Popen([sys.executable, "-m", "streamlit", "run", os.path.join("demo_live", "application.py"),
                            "--server.port", str(p_app), "--server.headless", "true", "--browser.gatherUsageStats", "false"], env=env_app)
    url_app = f"http://localhost:{p_app}/"
    print(f"\n  Poste de démonstration : {url_app}\n  Tableau de trésorerie  : {url_tab}\n  Ctrl+C pour tout arrêter.\n")
    if not a.pas_de_navigateur:
        time.sleep(3)
        webbrowser.open(url_app)
    try:
        while serveur.poll() is None and app.poll() is None:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        for p in (app, serveur):
            if p.poll() is None:
                p.terminate()


if __name__ == "__main__":
    main()
