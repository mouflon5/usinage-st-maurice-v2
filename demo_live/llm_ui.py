"""Sélecteur du LLM des agents (barre latérale, présent dans toutes les vues).

Trois choix : Simulé (règles, aucun appel), Claude (API Anthropic) ou Ollama (modèles locaux et gratuits).
Le choix est conservé dans demo_live/donnees/config_llm.json et appliqué à l'environnement du processus ; les passages
lancés ensuite (moteur détaché) le reçoivent en paramètre. La clé API n'est jamais écrite sur disque par l'interface.
"""
from __future__ import annotations

import os

import streamlit as st

import llm_fournisseur as llm_f

NOMS = {"simule": "Simulé (règles, sans LLM)", "claude": "Claude (API Anthropic)", "ollama": "Ollama (local, gratuit)"}
DEFAUT_AGENT = "(défaut de chaque agent)"


def configuration() -> dict:
    """Choix courant : {fournisseur, modele, url}."""
    return {"fournisseur": llm_f.fournisseur(), "modele": os.environ.get("LLM_MODELE", ""), "url": llm_f.url_ollama()}


def _initialiser():
    if st.session_state.get("_llm_init"):
        return
    cfg = llm_f.lire_config()
    if cfg.get("fournisseur") in llm_f.FOURNISSEURS and not os.environ.get("LLM_FOURNISSEUR"):
        llm_f.appliquer(cfg["fournisseur"], cfg.get("modele", ""), cfg.get("url", ""))
    st.session_state["_llm_init"] = True


def _choisir_modele_ollama(url: str, courant: str) -> str:
    modeles = llm_f.lister_ollama(url)
    if not modeles:
        st.warning(f"Ollama ne répond pas sur {url}. Lancez l'application Ollama (ou `ollama serve`).")
        return st.text_input("Nom du modèle", courant or llm_f.OLLAMA_MODELE_DEFAUT, key="llm_modele_ollama_txt")
    noms = [m["nom"] for m in modeles]
    etiquettes = {m["nom"]: f"{m['nom']}  ({m['taille_go']} Go)" for m in modeles}
    index = noms.index(courant) if courant in noms else 0
    choix = st.selectbox("Modèle installé", noms, index=index, format_func=etiquettes.get, key="llm_modele_ollama")
    st.caption("Les modèles « raisonnement » (deepseek-r1, qwen3) montrent leur réflexion dans l'onglet 🧠 Raisonnement, mais "
               "respectent moins bien les sorties structurées : une réponse inexploitable est tracée puis escaladée.")
    return choix


def selecteur() -> dict:
    """Dessine le sélecteur dans la barre latérale et retourne le choix courant."""
    _initialiser()
    cfg = configuration()
    with st.sidebar:
        with st.expander(f"🤖 LLM des agents — {NOMS[cfg['fournisseur']].split(' (')[0]}", expanded=False):
            prov = st.radio("Fournisseur", llm_f.FOURNISSEURS, index=llm_f.FOURNISSEURS.index(cfg["fournisseur"]),
                            format_func=NOMS.get, key="llm_prov")
            modele, url = "", cfg["url"]
            if prov == "claude":
                present = bool(os.environ.get("ANTHROPIC_API_KEY"))
                st.caption("Clé API : " + ("✅ détectée" if present else "❌ absente — saisissez-la ci-dessous ou mettez-la dans le fichier .env"))
                saisie = st.text_input("Clé API (cette session seulement)", type="password", key="llm_cle",
                                       help="Gardée en mémoire par ce processus, jamais écrite sur disque. Pour la conserver : ANTHROPIC_API_KEY dans .env.")
                if saisie:
                    os.environ["ANTHROPIC_API_KEY"] = saisie.strip()
                options = [DEFAUT_AGENT] + llm_f.CLAUDE_MODELES
                courant = cfg["modele"] if cfg["modele"] in llm_f.CLAUDE_MODELES else DEFAUT_AGENT
                choix = st.selectbox("Modèle", options, index=options.index(courant), key="llm_modele_claude")
                modele = "" if choix == DEFAUT_AGENT else choix
                autre = st.text_input("…ou un identifiant de modèle précis", "", key="llm_modele_libre")
                modele = autre.strip() or modele
            elif prov == "ollama":
                url = st.text_input("Adresse du serveur Ollama", cfg["url"], key="llm_url").strip() or llm_f.OLLAMA_URL_DEFAUT
                modele = _choisir_modele_ollama(url, cfg["modele"])
            if prov != "simule":
                a, b = st.columns(2)
                if a.button("Tester", key="llm_tester", width="stretch"):
                    cible = modele or ("claude-haiku-5-5" if prov == "claude" else llm_f.OLLAMA_MODELE_DEFAUT)
                    with st.spinner(f"Appel de {cible}…"):
                        st.session_state["llm_test"] = {"cible": cible, **llm_f.tester(prov, cible, url)}
                t = st.session_state.get("llm_test")
                if t:
                    (st.success if t["ok"] else st.error)(
                        f"{t['cible']} : " + (f"répond en {t['ms']} ms ({t['reponse']!r})" if t["ok"] else t["erreur"]))
            if (prov, modele, url) != (cfg["fournisseur"], cfg["modele"], cfg["url"]):
                llm_f.appliquer(prov, modele, url)
                llm_f.ecrire_config({"fournisseur": prov, "modele": modele, "url": url})
                st.rerun()
            st.caption("S'applique aux passages lancés ensuite : classement des lignes (A3), commentaire d'écarts (A5), "
                       "synthèse (A7), relecture (A8) et assistant.")
    return configuration()
