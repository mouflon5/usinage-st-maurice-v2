"""Démarrage EN LIGNE (conteneur Docker : Hugging Face Spaces, Render, etc.).

Trois processus, un seul port public (PORT, 7860 par défaut) :
  1. le serveur du tableau de trésorerie (port interne 8765) ;
  2. l'application Streamlit (port interne 8501) ;
  3. Caddy, le proxy qui expose les deux sur le même lien (voir Caddyfile).

Comme lancer_demo.py, mais sans navigateur, et avec des adresses d'iframe relatives à l'hôte public.
"""
import os
import subprocess
import sys
import time

RACINE = os.path.dirname(os.path.abspath(__file__))
os.chdir(RACINE)
sys.path.insert(0, RACINE)

P_TAB, P_APP = 8765, 8501
PORT = int(os.environ.get("PORT", "7860"))


def main():
    from demo_live import moteur as M
    if not os.path.isfile(M.BASE_DEMO):
        M.reinitialiser()
    M.ouvrir().close()
    os.makedirs(M.TRACES, exist_ok=True)

    env = dict(os.environ, TRESORERIE_DB=M.BASE_DEMO, TRESORERIE_REF=M.BASE_ORIGINE, TRESORERIE_LIVE="1",
               DEMO_DB=M.DB_EVENEMENTS, TRACES_DIR=M.TRACES, PYTHONIOENCODING="utf-8",
               DEMO_TABLEAU_URL=f"http://127.0.0.1:{P_TAB}/",      # vu du serveur (test de santé)
               DEMO_URL_PUBLIQUE_TABLEAU="/tableau/",              # vu du navigateur (iframes), via Caddy
               DEMO_URL_PUBLIQUE_RACINE="")
    procs = [
        subprocess.Popen([sys.executable, "tresorerie_dashboard.py", "--serve", "--no-browser", "--port", str(P_TAB)], env=env),
        subprocess.Popen([sys.executable, "-m", "streamlit", "run", os.path.join("demo_live", "application.py"),
                          "--server.port", str(P_APP), "--server.address", "127.0.0.1", "--server.headless", "true",
                          "--server.enableCORS", "false", "--server.enableXsrfProtection", "false",
                          "--browser.gatherUsageStats", "false"], env=env),
    ]
    time.sleep(3)
    procs.append(subprocess.Popen(["caddy", "run", "--config", "Caddyfile", "--adapter", "caddyfile"],
                                  env=dict(env, PORT=str(PORT))))
    try:
        while all(p.poll() is None for p in procs):
            time.sleep(2)
    finally:
        for p in procs:
            if p.poll() is None:
                p.terminate()
    sys.exit(1)     # un processus est tombé : le conteneur redémarre


if __name__ == "__main__":
    main()
