"""
Poste de pilotage du banc d'essai — contrôler, observer, évaluer le système multi-agents.

    streamlit run banc_essai/tableau_de_bord.py

Quatre onglets :
  Contrôle              lancer un lot (taille, mode, filtres, relecteur A8 oui/non), pause / reprise / arrêt, rejouer
  Vue d'ensemble        où le système réussit et où il casse (par type, banque, format), parcours des scénarios
  Scénarios & agents    un scénario à la fois : A1 → A8 → A7, ce que chaque agent a reçu / produit / décidé, ligne par ligne
  Performance           latence par agent, débit, jetons, évaluation du relecteur A8, comparaison de deux lots

Il lit banc_essai/resultats/resultats.db (écrite par l'exécuteur au fil de l'eau). Il n'écrit que des commandes
(pause, arrêt…) dans la table `lots` ; l'exécuteur est un processus séparé qui continue même si on ferme cette page.
"""

import json
import os
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime

import altair as alt
import pandas as pd
import streamlit as st

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RACINE not in sys.path:
    sys.path.insert(0, RACINE)
from banc_essai import pilotage as P          # noqa: E402

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(RACINE, ".env"))
except Exception:
    pass

DB = P.DB

# Statuts (réservés, jamais utilisés pour une série) + icône et libellé : la couleur ne porte jamais seule le sens
GRAVITES = ["ok", "info", "avertissement", "critique"]
LIBELLE = {"ok": "✓ Conforme", "info": "ℹ Écart sans dommage", "avertissement": "▲ Avertissement", "critique": "✖ Critique"}
ICONE = {"ok": "✓", "info": "ℹ", "avertissement": "▲", "critique": "✖"}
COULEUR = {"ok": "#0ca30c", "info": "#8f9aa8", "avertissement": "#fab219", "critique": "#d03b3b"}
BLEU = "#2a78d6"
VERDICTS_AIDE = {
    "PLANTAGE": "exception non gérée", "DONNEES_FAUSSES": "ligne perdue ou fantôme en base", "MAL_CLASSE": "mauvaise catégorie",
    "ECRITURE_PARTIELLE": "écritures malgré un arrêt", "DEFAUT_NON_DETECTE": "entrée défectueuse acceptée",
    "SURCONFIANCE": "ligne ambiguë classée sans humain", "ESCALADE_INATTENDUE": "ligne claire envoyée à l'arbitrage",
    "ARRET_PRUDENT": "entrée valide refusée", "STATUT_INATTENDU": "statut hors attendu", "ARRET_AUTRE_AGENT": "arrêt par un autre agent",
    "OK": "conforme"}
AGENTS = [("A1", "Acquisition"), ("A2", "Extraction"), ("A3", "Réconciliation"), ("A4", "Prévision"), ("A5", "Écarts"),
          ("A6", "Contrôle"), ("A8", "Relecture"), ("H", "Approbation"), ("A7", "Reporting")]
NOM_AGENT = dict(AGENTS)
EVAL_A8 = {"vrai_positif": "✓ défaut signalé", "manque": "✖ défaut non signalé", "faux_positif": "▲ fausse alerte",
           "vrai_negatif": "✓ rien à signaler", "indisponible": "ℹ relecteur indisponible", "non_applicable": "— non atteint"}
ETAT_LOT = {"en cours": "⏳ En cours", "en pause": "⏸ En pause", "arrêt en cours": "⏹ Arrêt en cours", "terminé": "✔ Terminé",
            "arrêté": "⏹ Arrêté", "interrompu": "⚠ Interrompu"}

try:
    st.set_page_config(page_title="Poste de pilotage — SMA trésorerie", layout="wide")
except Exception:          # déjà fixée : la page est intégrée à l'application de démonstration
    pass
st.markdown("""<style>
.block-container{padding-top:1.4rem;max-width:1300px}
.tuile{border:1px solid rgba(128,128,128,.28);border-radius:10px;padding:.7rem .9rem;height:100%}
.tuile .v{font-size:1.8rem;font-weight:650;line-height:1.1}
.tuile .v.t{font-size:1.02rem;line-height:1.3;word-break:break-word}
.tuile .l{font-size:.8rem;opacity:.72;margin-top:.15rem}
.tuile .s{font-size:.75rem;opacity:.6}
.chaine{display:flex;gap:3px;align-items:stretch;margin:.4rem 0 .2rem}
.etape{flex:1 1 0;min-width:0;border:1.5px solid rgba(128,128,128,.35);border-radius:9px;padding:.4rem .45rem;word-break:break-word}
.etape .a{font-weight:650;font-size:.95rem}.etape .n{font-size:.72rem;opacity:.7}
.etape .st{font-size:.82rem;margin-top:.25rem;font-weight:600}.etape .d{font-size:.72rem;opacity:.75}
.etape .v{font-size:.72rem;opacity:.85;margin-top:.1rem}
.e-ok{border-color:#0ca30c;background:rgba(12,163,12,.08)}.e-avert{border-color:#fab219;background:rgba(250,178,25,.12)}
.e-ko{border-color:#d03b3b;background:rgba(208,59,59,.10)}.e-nul{border-style:dashed;opacity:.55}
.fleche{align-self:center;opacity:.5;font-size:.9rem;flex:0 0 auto}
</style>""", unsafe_allow_html=True)


# --------------------------------------------------------------------------- #
# Accès aux données
# --------------------------------------------------------------------------- #
LOURDES = ("spec", "trace", "a8_rejetes")


def _ro():
    return sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=10)


def charger_lots():
    if not os.path.exists(DB):
        return pd.DataFrame()
    c = _ro()
    try:
        d = pd.read_sql("SELECT * FROM lots ORDER BY debut DESC", c)
        return d.astype(object).where(d.notna(), None)          # NULL → None (pandas mettrait NaN, qui est « vrai »)
    finally:
        c.close()


def lots_frais():
    """Table des lots relue à chaque appel (les sections « en direct » ne réexécutent pas le haut du script)."""
    d = charger_lots()
    return d if "run_id" in d.columns else pd.DataFrame(columns=["run_id", "n", "mode", "statut"])


def charger(run_id):
    """Colonnes légères seulement (pas de spec ni de trace) : appelé toutes les 2 s."""
    if not os.path.exists(DB) or not run_id:
        return pd.DataFrame()
    c = _ro()
    try:
        cols = [r[1] for r in c.execute("PRAGMA table_info(test_runs)") if r[1] not in LOURDES]
        return pd.read_sql(f"SELECT {','.join(cols)} FROM test_runs WHERE run_id=?", c, params=(run_id,))
    finally:
        c.close()


def charger_un(run_id, ident):
    c = _ro()
    try:
        c.row_factory = sqlite3.Row
        r = c.execute("SELECT * FROM test_runs WHERE run_id=? AND id=?", (run_id, ident)).fetchone()
        return dict(r) if r else None
    finally:
        c.close()


def nb_rejetes_a8(run_id):
    c = _ro()
    try:
        return c.execute("SELECT COUNT(*) FROM test_runs WHERE run_id=? AND a8_rejetes IS NOT NULL AND a8_rejetes NOT IN ('[]','')",
                         (run_id,)).fetchone()[0]
    except sqlite3.OperationalError:
        return 0
    finally:
        c.close()


def a8_utilisable(df):
    return "a8_eval" in df.columns and df["a8_eval"].notna().any()


def tuile(col, valeur, libelle, sous=""):
    court = "" if len(str(valeur)) <= 14 else " t"
    col.markdown(f'<div class="tuile"><div class="v{court}">{valeur}</div><div class="l">{libelle}</div><div class="s">{sous}</div></div>',
                 unsafe_allow_html=True)


def barres_gravite(df, champ, titre, hauteur_ligne=20, tri="critique"):
    t = df.groupby([champ, "gravite"]).size().reset_index(name="n")
    t["gravite_l"] = t["gravite"].map(LIBELLE)
    ordre = (df.assign(c=(df["gravite"] == tri)).groupby(champ)["c"].mean().sort_values(ascending=False).index.tolist())
    ch = alt.Chart(t).mark_bar(stroke="white", strokeWidth=0.5).encode(
        y=alt.Y(f"{champ}:N", sort=ordre, title=None, axis=alt.Axis(labelLimit=260, labelOverlap=False)),
        x=alt.X("n:Q", stack="zero", title="scénarios"),
        color=alt.Color("gravite_l:N", title=None, scale=alt.Scale(domain=[LIBELLE[g] for g in GRAVITES], range=[COULEUR[g] for g in GRAVITES]),
                        legend=alt.Legend(orient="top")),
        order=alt.Order("gravite:N", sort="ascending"),
        tooltip=[alt.Tooltip(f"{champ}:N", title=titre), alt.Tooltip("gravite_l:N", title="résultat"), alt.Tooltip("n:Q", title="scénarios")])
    return ch.properties(height=alt.Step(hauteur_ligne))


def rafraichi():
    """Décorateur de section « en direct » : se réexécute seule toutes les 2 s si l'option est cochée."""
    return st.fragment(run_every=2 if st.session_state.get("auto", True) else None)


# --------------------------------------------------------------------------- #
# Barre latérale : choix du lot
# --------------------------------------------------------------------------- #
st.title("Poste de pilotage — système multi-agents de trésorerie")
lots = lots_frais()
if "lot_demande" in st.session_state:                      # lot qu'on vient de lancer : le sélectionner avant de créer le widget
    st.session_state["lot_choisi"] = st.session_state.pop("lot_demande")
st.sidebar.toggle("Mise à jour automatique (2 s)", value=True, key="auto")
ids = lots["run_id"].tolist() if not lots.empty else []
attente = st.session_state.get("demarrage")                # lot lancé mais pas encore écrit en base (génération des PDF)
if attente and attente not in ids:
    ids = [attente] + ids
if ids:
    if st.session_state.get("lot_choisi") not in ids:
        st.session_state["lot_choisi"] = ids[0]
    choix = st.sidebar.selectbox("Lot", ids, key="lot_choisi", format_func=lambda r: (
        f"{r} — {lots[lots['run_id'] == r].iloc[0]['n']} scén., {lots[lots['run_id'] == r].iloc[0]['mode']}"
        if (not lots.empty and r in lots["run_id"].tolist()) else r))
else:
    choix = None
    st.sidebar.info("Aucun lot pour l'instant. Lancez-en un depuis l'onglet Contrôle.")


# --------------------------------------------------------------------------- #
# Onglet 1 — Contrôle
# --------------------------------------------------------------------------- #
def types_disponibles():
    try:
        from banc_essai import generateur
        return {k: v[0] for k, v in generateur.TYPES.items()}
    except Exception:
        return {}


def formulaire_lancement():
    cle_api = bool(os.getenv("ANTHROPIC_API_KEY"))
    with st.expander("➕ Lancer un nouveau lot", expanded=lots.empty):
        with st.form("lancement"):
            c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
            nom = c1.text_input("Nom du lot", value=datetime.now().strftime("lot-%Y%m%d-%H%M"))
            n = c2.number_input("Scénarios", 1, 1000, 100, step=10, help="Le générateur répartit les types de scénarios selon leurs poids ; 1000 = le lot complet.")
            graine = c3.number_input("Graine", 0, 99999, 7, help="Même graine + même taille = exactement les mêmes scénarios (comparables d'un lot à l'autre).")
            workers = c4.number_input("Workers", 1, 8, 2, help="Processus en parallèle.")
            d1, d2 = st.columns(2)
            mode = d1.radio("Modèle de langage", ["Simulé (gratuit, déterministe)", "Réel (Claude, coûte des jetons)"],
                            help="Simulé : A3/A5/A7/A8 utilisent leurs règles internes. Réel : appels à Claude via ANTHROPIC_API_KEY.")
            a8 = d2.checkbox("Relecteur A8 actif", value=True, help="Décocher pour mesurer le pipeline sans le relecteur et comparer les deux lots.")
            d2.caption("Réel : " + ("clé API détectée." if cle_api else "⚠ ANTHROPIC_API_KEY introuvable : le lancement en mode réel sera refusé."))
            f1, f2 = st.columns(2)
            cats = f1.multiselect("Catégories de scénarios", ["nominal", "limite", "defectueux", "chaos"], default=[],
                                  help="Vide = toutes.")
            tdispo = types_disponibles()
            types = f2.multiselect("Types précis", sorted(tdispo), default=[], help="Vide = tous. Un type = un défi particulier (jumeaux, collisions de mots-clés, base corrompue…).")
            ok = st.form_submit_button("▶ Lancer", type="primary")
        if ok:
            reel = mode.startswith("Réel")
            if reel and not cle_api:
                st.error("Mode réel impossible : ANTHROPIC_API_KEY n'est pas définie (fichier .env ou variable d'environnement).")
            elif not P.nom_valide(nom):
                st.error("Nom de lot invalide : lettres, chiffres, _ et - (40 caractères max).")
            elif not lots.empty and nom in lots["run_id"].tolist():
                st.error("Ce nom de lot existe déjà. Choisissez-en un autre, ou sélectionnez-le à gauche pour le reprendre.")
            else:
                if reel and n > 50:
                    st.warning("Mode réel avec plus de 50 scénarios : vérifiez le coût avant de poursuivre (commencez par 20).")
                P.lancer(nom, graine, n, workers, reel, not a8, cats or None, types or None)
                st.session_state["lot_demande"] = nom
                st.session_state["demarrage"] = nom
                st.rerun()


def panneau_lot(run_id):
    lots_ = charger_lots()
    ligne = lots_[lots_["run_id"] == run_id] if not lots_.empty else pd.DataFrame()
    if ligne.empty:
        if st.session_state.get("demarrage") == run_id:
            st.info(f"Démarrage du lot « {run_id} » (génération des scénarios et des PDF)…")
            st.code(P.fin_du_journal(run_id) or "(journal vide)")
        return
    lot = ligne.iloc[0]
    if st.session_state.get("demarrage") == run_id:
        st.session_state.pop("demarrage")
    df = charger(run_id)
    n, total = len(df), int(lot["n"])
    vivant = P.etat_vivant(lot["statut"], lot.get("heartbeat"))
    statut = lot["statut"]
    etiquette = ETAT_LOT.get(statut, statut)
    if vivant == "mort":
        etiquette = "⚠ Exécuteur arrêté sans prévenir"
    debut = datetime.fromisoformat(lot["debut"])
    fin = datetime.fromisoformat(lot["fin"]) if lot["fin"] else datetime.now()
    ecoule = max((fin - debut).total_seconds(), 1.0)
    debit = n / ecoule
    reste = (total - n) / debit if debit > 0 and vivant == "actif" and statut == "en cours" else None
    st.progress(min(n / max(total, 1), 1.0),
                text=f"{etiquette} — {n} / {total} scénarios · mode {lot['mode']} · {lot['workers']} worker(s)"
                     + (f" · ≈ {int(reste // 60)} min {int(reste % 60):02d} s restantes" if reste else ""))

    cols = st.columns(5)
    ok = int((df["gravite"] == "ok").sum()) if n else 0
    crit = int((df["gravite"] == "critique").sum()) if n else 0
    avert = int((df["gravite"] == "avertissement").sum()) if n else 0
    tuile(cols[0], f"{ok / n:.0%}" if n else "—", "conformes", f"{ok} sur {n}")
    tuile(cols[1], str(crit), "défauts critiques", "ligne perdue, mauvaise catégorie…")
    tuile(cols[2], str(avert), "avertissements", "refus à tort, surconfiance…")
    tuile(cols[3], f"{debit * 60:.0f}/min" if n else "—", "débit", f"{ecoule:.0f} s écoulées")
    age = P.age_battement(lot.get("heartbeat"))
    tuile(cols[4], f"{age:.0f} s" if (age is not None and vivant != "inactif") else "—", "dernier signe de vie",
          "de l'exécuteur" if vivant == "actif" else ("plus de signal" if vivant == "mort" else "lot non actif"))

    b = st.columns([1.2, 1.7, 1.4, 1.2, 2])
    cmd_attente = lot.get("commande")
    if vivant == "actif":
        if statut == "en cours":
            if b[0].button("⏸ Pause", key=f"pause_{run_id}", help="Termine les scénarios déjà démarrés puis attend."):
                P.envoyer_commande(run_id, "pause")
        if statut == "en pause":
            if b[0].button("▶ Reprendre", key=f"repr_{run_id}", type="primary"):
                P.envoyer_commande(run_id, "reprendre")
        if b[1].button("⏹ Arrêter", key=f"stop_{run_id}", help="Termine les scénarios déjà démarrés puis s'arrête proprement."):
            P.envoyer_commande(run_id, "arreter")
        if b[2].button("⛔ Arrêt immédiat", key=f"kill_{run_id}", help="Abandonne les scénarios en cours (leurs résultats ne sont pas enregistrés)."):
            P.envoyer_commande(run_id, "tuer")
        if cmd_attente:
            b[4].caption(f"Commande envoyée : « {cmd_attente} » (prise en compte à la prochaine seconde)")
    elif vivant == "mort":
        st.warning("Le processus de l'exécuteur ne répond plus (fenêtre fermée, machine en veille ou plantage). Les résultats déjà enregistrés sont conservés.")
        if b[0].button("Marquer interrompu", key=f"mi_{run_id}"):
            P.marquer_interrompu(run_id)
    if vivant != "actif" and n < total:
        if b[1].button("↻ Reprendre les restants", key=f"rest_{run_id}", help="Relance le lot : les scénarios déjà faits sont sautés."):
            filtre = json.loads(lot["filtre"]) if lot.get("filtre") else {}
            opts = json.loads(lot["options"]) if lot.get("options") else {}
            types = filtre.get("types")
            cats = filtre.get("categories")
            P.lancer(run_id, int(lot["seed"]), 1000 if types or cats else total, int(lot["workers"]), lot["mode"] == "reel",
                     bool(opts.get("sans_a8")), cats.split(",") if cats else None, types.split(",") if types else None)
            st.session_state["demarrage"] = run_id
    if vivant != "actif":
        with b[3].popover("🗑 Supprimer"):
            st.caption("Efface ce lot et ses résultats de la base du banc d'essai (pas les relevés, pas tresorerie.db).")
            if st.button("Confirmer la suppression", key=f"del_{run_id}"):
                P.supprimer_lot(run_id)
                st.session_state.pop("lot_choisi", None)
                st.rerun()

    st.markdown("##### En direct : derniers scénarios passés")
    if n:
        d = df.sort_values("horodatage", ascending=False).head(8)
        vue = pd.DataFrame({"": d["gravite"].map(ICONE), "scénario": d["id"], "banque": d["banque"], "verdict": d["verdict"],
                            "statut obtenu": d["statut_obtenu"], "durée (s)": d["duree_s"],
                            "relecture A8": d["a8_eval"].map(EVAL_A8) if "a8_eval" in d else None})
        st.dataframe(vue, hide_index=True, use_container_width=True)
    else:
        st.caption("Aucun résultat pour l'instant.")
    with st.expander("Journal de l'exécuteur"):
        st.code(P.fin_du_journal(run_id) or "(vide)")


def onglet_controle():
    formulaire_lancement()
    if choix is None and not st.session_state.get("demarrage"):
        return
    rafraichi()(lambda: panneau_lot(choix or st.session_state.get("demarrage")))()


# --------------------------------------------------------------------------- #
# Onglet 2 — Vue d'ensemble
# --------------------------------------------------------------------------- #
def vue_ensemble(run_id):
    df = charger(run_id)
    if df.empty or lots_frais().pipe(lambda d: d[d["run_id"] == run_id]).empty:
        st.info("En attente des premiers résultats…")
        return
    lot = lots_frais().pipe(lambda d: d[d["run_id"] == run_id]).iloc[0]
    n, total = len(df), int(lot["n"])
    ok = int((df["gravite"] == "ok").sum())
    crit = int((df["gravite"] == "critique").sum())
    avert = int((df["gravite"] == "avertissement").sum())
    connues = df["limite_connue"].notna()
    c = st.columns(5)
    tuile(c[0], f"{ok / n:.0%}", "conformes", f"{ok} sur {n} ({total} prévus)")
    tuile(c[1], f"{crit}", "défauts critiques", f"{int(((df['gravite'] == 'critique') & connues).sum())} sur limites connues")
    tuile(c[2], f"{avert}", "avertissements", "refus à tort, surconfiance…")
    tuile(c[3], f"{df['duree_s'].median():.1f} s", "durée médiane / scénario", f"p95 : {df['duree_s'].quantile(.95):.1f} s")
    jet = int(df["jetons_entree"].fillna(0).sum() + df["jetons_sortie"].fillna(0).sum())
    tuile(c[4], f"{jet:,}".replace(",", " ") if lot["mode"] == "reel" else "0", "jetons LLM",
          "mode simulé : aucun appel" if lot["mode"] != "reel" else "entrée + sortie")

    if a8_utilisable(df):
        dd = df[df["verdict"].isin(["DONNEES_FAUSSES", "MAL_CLASSE", "SURCONFIANCE"]) & df["a8_eval"].isin(["vrai_positif", "manque"])]
        if not dd.empty:
            st.markdown("#### Défauts de données : signalés à l'humain, ou silencieux ?")
            t = dd.assign(sig=dd["a8_eval"].map({"vrai_positif": "signalé par A8", "manque": "silencieux"})).pivot_table(
                index="verdict", columns="sig", values="id", aggfunc="count", fill_value=0)
            for col in ("signalé par A8", "silencieux"):
                if col not in t.columns:
                    t[col] = 0
            t["total"] = t.sum(axis=1)
            vus, tot_d = int(t["signalé par A8"].sum()), int(t["total"].sum())
            cc = st.columns([1, 3])
            tuile(cc[0], f"{vus} / {tot_d}", "défauts signalés", "ligne citée dans une réserve du rapport")
            cc[1].dataframe(t[["signalé par A8", "silencieux", "total"]], use_container_width=True)
            st.caption("La donnée reste fausse dans les deux cas (A8 ne corrige rien) : la différence est qu'un humain est prévenu, avec la ligne exacte. "
                       "« Silencieux » = rien n'a alerté le lecteur du rapport.")

    st.markdown("#### Où le système réussit… et où il casse")
    tabs = st.tabs(["Par type de scénario", "Par banque", "Par format", "Par catégorie"])
    with tabs[0]:
        st.altair_chart(barres_gravite(df, "type", "type"), use_container_width=True)
    with tabs[1]:
        st.altair_chart(barres_gravite(df, "banque", "banque", 26), use_container_width=True)
    with tabs[2]:
        st.altair_chart(barres_gravite(df, "format", "format", 34), use_container_width=True)
        st.caption("F1 = ligne signée (Desjardins) · F2 = Débit/Crédit (BNC, BMO) · F3 = date courte + DR/CR (RBC, TD, CIBC) · F4 = parenthèses (Scotia, Laurentienne, Caisse pop.)")
    with tabs[3]:
        st.altair_chart(barres_gravite(df, "categorie_test", "catégorie", 40), use_container_width=True)

    g1, g2 = st.columns(2)
    with g1:
        st.markdown("#### Parcours : jusqu'où les scénarios vont")
        atteints = defaultdict(int)
        for s in df["durees_agents"].dropna():
            for a in json.loads(s):
                atteints[a] += 1
        fun = pd.DataFrame([(a, f"{a} {NOM_AGENT[a]}", atteints.get(a, 0)) for a, _ in AGENTS if a != "H"], columns=["code", "agent", "scénarios"])
        ch = alt.Chart(fun).mark_bar(color=BLEU, size=14, cornerRadiusEnd=4).encode(
            y=alt.Y("agent:N", sort=list(fun["agent"]), title=None), x=alt.X("scénarios:Q", title="scénarios ayant atteint cet agent"),
            tooltip=["agent", "scénarios"])
        st.altair_chart(ch.properties(height=alt.Step(24)), use_container_width=True)
        st.caption("A8 relit aussi les dossiers qui s'arrêtent à l'arbitrage humain (après A3) : il peut donc dépasser A6.")
    with g2:
        st.markdown("#### Comment ils se terminent")
        fin = df.groupby(["statut_obtenu"]).size().reset_index(name="scénarios").sort_values("scénarios", ascending=False)
        ch2 = alt.Chart(fin).mark_bar(color=BLEU, size=14, cornerRadiusEnd=4).encode(
            y=alt.Y("statut_obtenu:N", sort=list(fin["statut_obtenu"]), title=None), x=alt.X("scénarios:Q"), tooltip=["statut_obtenu", "scénarios"])
        st.altair_chart(ch2.properties(height=alt.Step(24)), use_container_width=True)

    st.markdown("#### Verdicts")
    v = df.groupby(["verdict", "gravite"]).size().reset_index(name="scénarios")
    v["sens"] = v["verdict"].map(VERDICTS_AIDE)
    v["gravite"] = v["gravite"].map(LIBELLE)
    st.dataframe(v.sort_values("scénarios", ascending=False), hide_index=True, use_container_width=True)

    st.markdown("#### Classement des lignes (scénarios où le chargement a eu lieu)")
    s = df[["lignes_ok", "lignes_escaladees", "lignes_surconfiance", "lignes_mal_classees", "lignes_perdues", "lignes_fantomes"]].sum()
    tot = int(s.sum()) or 1
    cl = st.columns(6)
    for col, (lib, k) in zip(cl, [("classées correctement", "lignes_ok"), ("envoyées à l'arbitrage", "lignes_escaladees"), ("ambiguës classées seules", "lignes_surconfiance"),
                                  ("mauvaise catégorie", "lignes_mal_classees"), ("perdues", "lignes_perdues"), ("fantômes", "lignes_fantomes")]):
        tuile(col, f"{int(s[k])}", lib, f"{s[k] / tot:.1%} des lignes")

    with st.expander("Table complète (export)"):
        cols = [c for c in ["id", "type", "banque", "format", "statut_attendu", "statut_obtenu", "agent_arret", "verdict", "gravite", "duree_s",
                            "limite_connue", "a8_eval"] if c in df.columns]
        st.dataframe(df[cols], hide_index=True, use_container_width=True)
        st.download_button("Télécharger en CSV", df[cols].to_csv(index=False).encode("utf-8-sig"), f"banc_essai_{run_id}.csv", "text/csv")


# --------------------------------------------------------------------------- #
# Onglet 3 — Scénarios & agents
# --------------------------------------------------------------------------- #
def classe_statut(statut):
    if statut in ("complet", "approuve", "ok", "auto"):
        return "ok", "✓"
    if statut in ("degrade", "reserves", "a_arbitrer", "indisponible", "complet_avec_reserves"):
        return "avert", "▲"
    return "ko", "✖"


RESUME_SORTIES = {
    "A1": [("fichiers_trouves", "fichier(s) transmis")], "A2": [("transactions", "transaction(s) lues")],
    "A3": [("classees_a3", "classée(s)"), ("residu_a3", "à classer"), ("doublons_a3", "doublon(s) écartés")],
    "A4": [("previsions", "série(s) prévues")], "A5": [("ecarts_a5", "ligne(s) d'écarts")],
    "A6": [("controles_a6", "contrôle(s)")], "A8": [("constats_a8", "constat(s)")], "A7": [("fichiers_a7", "fichier(s) produits")]}


def resume_sorties(code, noeud):
    s = noeud.get("sorties", {})
    parts = []
    for cle, lib in RESUME_SORTIES.get(code, []):
        if cle in s and (s[cle] or cle in ("transactions", "classees_a3", "controles_a6")):
            if code == "A6" and noeud.get("controles"):
                ok = sum(c["ok"] for c in noeud["controles"])
                parts.append(f"{ok}/{len(noeud['controles'])} contrôles OK")
            else:
                parts.append(f"{s[cle]} {lib}")
    return " · ".join(parts)


def chaine_agents(trace):
    par_agent = {}
    for nd in trace["noeuds"]:
        if nd.get("agent"):
            par_agent[nd["agent"]] = nd
    noms = [nd["noeud"] for nd in trace["noeuds"]]
    morceaux = []
    for code, nom in AGENTS:
        if code == "H":
            if "finaliser_rejet_humain" in noms:
                nd, cls, ic, stat = next(x for x in trace["noeuds"] if x["noeud"] == "approbation_humaine"), "ko", "✖", "rejetée"
            elif "approbation_humaine" in noms:
                nd = next(x for x in trace["noeuds"] if x["noeud"] == "approbation_humaine")
                cls, ic, stat = "ok", "✓", "automatique"
            else:
                nd = None
        else:
            nd = par_agent.get(code)
        if nd is None:
            morceaux.append(f'<div class="etape e-nul"><div class="a">{code}</div><div class="n">{nom}</div>'
                            f'<div class="st">○ non atteint</div></div>')
        else:
            if code != "H":
                cls, ic = classe_statut(nd.get("statut"))
                stat = nd.get("statut") or "?"
            morceaux.append(f'<div class="etape e-{cls}"><div class="a">{code}</div><div class="n">{nom}</div>'
                            f'<div class="st">{ic} {stat}</div><div class="d">{nd["duree"]:.2f} s</div>'
                            f'<div class="v">{resume_sorties(code, nd) if code != "H" else ""}</div></div>')
    st.markdown('<div class="chaine">' + '<div class="fleche">→</div>'.join(morceaux) + "</div>", unsafe_allow_html=True)


def interactions(trace):
    ordre = [nd for nd in trace["noeuds"] if nd.get("agent")]
    lignes = []
    for a, b in zip(ordre, ordre[1:]):
        r = resume_sorties(a["agent"], a)
        lignes.append(f"**{a['agent']} → {b['agent']}** : {r or 'statut transmis'}")
    fin = next((nd for nd in trace["noeuds"] if nd["noeud"].startswith("finaliser")), None)
    if ordre and fin:
        lignes.append(f"**{ordre[-1]['agent']} → fin** ({fin['noeud'].replace('finaliser_', '')}) : statut final « {fin.get('statut_pipeline')} »")
    if lignes:
        st.markdown("\n\n".join("- " + l for l in lignes))


def gantt(trace):
    rows = [{"agent": nd["agent"], "début": nd["debut"], "fin": nd["debut"] + max(nd["duree"], 0.004), "durée (s)": nd["duree"]}
            for nd in trace["noeuds"] if nd.get("agent")]
    if not rows:
        return
    d = pd.DataFrame(rows)
    ch = alt.Chart(d).mark_bar(color=BLEU, size=12, cornerRadius=3).encode(
        y=alt.Y("agent:N", sort=[a for a, _ in AGENTS], title=None), x=alt.X("début:Q", title="secondes depuis le début du scénario"),
        x2="fin:Q", tooltip=["agent", alt.Tooltip("début:Q", format=".2f"), alt.Tooltip("durée (s):Q", format=".3f")])
    st.altair_chart(ch.properties(height=alt.Step(22)), use_container_width=True)


def comparer_lignes(spec, trace, constats):
    obt = defaultdict(list)
    for l in trace.get("classement", []):
        obt[(l["date"], l["description"], round(l["montant"], 2))].append(l)
    refs_a8 = {c["ref"]: c for c in constats if c.get("gravite") == "reserve"}
    rows = []
    for t in spec["verite"]:
        k = (t["date"], t["description"], round(t["montant"], 2))
        l = obt[k].pop() if obt[k] else None
        attendu = ("→ arbitrage humain" if t["cible"] == "escalade" else
                   f"{t['categorie']} ou arbitrage" if t["cible"] == "promue_ou_escalade" else t["categorie"])
        if l is None:
            res, obtenu = "✖ perdue", "— absente de la base"
        else:
            promue = l["categorie"] != "À classer"
            obtenu = f"{l['categorie']} · {l['methode']}" + (f" ({l['confiance']:.2f})" if l.get("confiance") is not None else "")
            if t["cible"] == "escalade":
                res = "▲ classée sans humain" if promue else "✓ escaladée"
            elif promue:
                res = "✓ correcte" if l["categorie"] == t["categorie"] else "✖ mauvaise catégorie"
            else:
                res = "✓ escaladée" if t["cible"] == "promue_ou_escalade" else "▲ escaladée à tort"
        ref = l.get("ref") if l else None
        rows.append({"résultat": res, "libellé": t["description"], "montant": t["montant"], "attendu": attendu, "obtenu": obtenu,
                     "A8": ("⚑ " + refs_a8[ref]["texte"][:90]) if ref in refs_a8 else "", "date": t["date"]})
    return pd.DataFrame(rows)


def detail_scenario(run_id, ident):
    r = charger_un(run_id, ident)
    if not r:
        st.warning("Scénario introuvable.")
        return
    spec = json.loads(r["spec"])
    trace = json.loads(r["trace"]) if r.get("trace") else None
    st.markdown(f"### {ICONE.get(r['gravite'], '')} {r['verdict']} — `{r['id']}`")
    st.write(r["description"])
    c = st.columns(4)
    tuile(c[0], f"{r['banque']}", "banque", f"format {r['format']} · {r['nb_fichiers']} relevé(s)")
    tuile(c[1], ", ".join(json.loads(r["statut_attendu"])), "statut(s) attendu(s)", f"{r['nb_lignes']} ligne(s) de vérité")
    tuile(c[2], r["statut_obtenu"], "statut obtenu", f"arrêt : {r['agent_arret'] or '—'}")
    tuile(c[3], f"{r['duree_s']:.2f} s", "durée", "pannes : " + (", ".join(spec["pannes"]) or "aucune"))
    if r["limite_connue"]:
        st.warning("Limite connue : " + r["limite_connue"])
    if r["message"]:
        st.caption("Message final du pipeline : " + r["message"])

    if not trace:
        st.info("Ce scénario vient d'un lot exécuté avant l'ajout de la trace détaillée : seuls les verdicts et durées sont disponibles. "
                "Rejouez-le (bouton ci-dessous) pour obtenir la trace complète.")
    else:
        st.markdown("##### Parcours dans le pipeline")
        chaine_agents(trace)
        g1, g2 = st.columns([3, 2])
        with g1:
            gantt(trace)
        with g2:
            st.markdown("**Qui a passé quoi à qui**")
            interactions(trace)

    onglets = st.tabs(["Lignes classées (A3)", "Contrôles A6", "Relecture A8", "Défauts constatés", "Entrée du scénario"])
    constats = json.loads(r["a8_constats"]) if r.get("a8_constats") else []
    with onglets[0]:
        if trace and spec["verite"]:
            t = comparer_lignes(spec, trace, constats)
            st.dataframe(t, hide_index=True, use_container_width=True, height=min(60 + 35 * len(t), 460))
            st.caption("« attendu » vient de la vérité écrite avant l'exécution ; « obtenu » est ce qu'A3 a décidé (règle, LLM ou escalade).")
            if trace.get("doublons"):
                st.markdown("**Lignes écartées comme doublons par A3**")
                st.dataframe(pd.DataFrame(trace["doublons"]).rename(columns={"origine": "origine (base | même relevé)"}), hide_index=True, use_container_width=True)
        else:
            st.caption("Aucune ligne de vérité, ou trace indisponible.")
    with onglets[1]:
        a6 = next((nd for nd in (trace or {}).get("noeuds", []) if nd["noeud"] == "executer_a6"), None)
        if a6 and a6.get("controles"):
            d = pd.DataFrame(a6["controles"])
            d[""] = d["ok"].map({True: "✓", False: "✖"})
            st.dataframe(d[["", "id", "gravite", "libelle", "detail"]], hide_index=True, use_container_width=True)
            st.caption("Onze contrôles déterministes, recalculés indépendamment des agents amont. « bloquant » en échec = rien ne sort.")
        else:
            st.caption("A6 n'a pas été atteint dans ce scénario.")
    with onglets[2]:
        a8 = next((nd for nd in (trace or {}).get("noeuds", []) if nd["noeud"] == "executer_a8"), None)
        if a8 and a8.get("relecture") is not None:
            rl = a8["relecture"]
            st.markdown(f"Origine : **{rl.get('origine')}** · évaluation par rapport à la vérité : **{EVAL_A8.get(r.get('a8_eval'), '—')}**")
            notes = {k: v for k, v in (rl.get("notes") or {}).items() if v is not None}
            if notes:
                nc = st.columns(len(notes))
                for col, (k, v) in zip(nc, notes.items()):
                    tuile(col, f"{v} / 5", f"note {k}")
            if rl.get("constats"):
                st.dataframe(pd.DataFrame(rl["constats"]), hide_index=True, use_container_width=True)
            else:
                st.caption("Aucun constat : le relecteur n'a rien à signaler.")
            if rl.get("rejetes"):
                st.markdown("**Avis écartés par les garde-fous** (référence inconnue ou nombre absent du dossier)")
                st.dataframe(pd.DataFrame(rl["rejetes"]), hide_index=True, use_container_width=True)
            st.caption("A8 ne peut qu'ajouter des réserves ; il ne débloque ni ne modifie rien.")
        else:
            st.caption("A8 n'a pas été atteint (ou le lot précède son ajout).")
    with onglets[3]:
        issues = json.loads(r["details"]) if r.get("details") else []
        if issues:
            for i in issues[:30]:
                st.markdown(f"- `{i['type']}` — {i['detail'][:400]}")
        else:
            st.caption("Aucun défaut constaté par la vérification déterministe.")
    with onglets[4]:
        st.json({k: spec[k] for k in ("banque", "format", "compte", "periode_debut", "periode_fin", "pannes", "corruption_sql", "limite_connue")
                 if k in spec}, expanded=False)
        st.caption("Fichiers : " + ", ".join(f["nom"] if isinstance(f, dict) and "nom" in f else str(f)[:60] for f in spec["fichiers"][:6]))
        st.code(f"python -m banc_essai.executeur --ids {r['id']} --run-id {run_id} --forcer", language="bash")


@st.fragment(run_every=2)
def attendre_resultats(run_id):
    """Monté seulement tant que le lot n'a aucun résultat : relance la page entière quand le premier arrive
    (le reste de cet onglet n'est calculé qu'à chaque rechargement complet, pas par les sections « en direct »)."""
    if len(charger(run_id)) > 0 and not lots_frais().pipe(lambda d: d[d["run_id"] == run_id]).empty:
        st.rerun()


def onglet_scenarios():
    if choix is None:
        st.info("Aucun lot à examiner.")
        return
    df = charger(choix)
    if df.empty or lots_frais().pipe(lambda d: d[d["run_id"] == choix]).empty:
        st.info("Ce lot n'a pas encore de résultat. Cette liste apparaîtra toute seule dès le premier scénario terminé.")
        attendre_resultats(choix)
        return
    if st.button("↻ Actualiser la liste", help="Cet onglet ne se rafraîchit pas seul, pour rester stable pendant la lecture."):
        st.rerun()
    cols = st.columns([1.2, 1.2, 1.2, 1.2, 2])
    gr = cols[0].multiselect("Gravité", ["critique", "avertissement", "info", "ok"], default=["critique", "avertissement"])
    vd = cols[1].multiselect("Verdict", sorted(df["verdict"].unique()))
    ty = cols[2].multiselect("Type", sorted(df["type"].unique()))
    bq = cols[3].multiselect("Banque", sorted(df["banque"].unique()))
    q = cols[4].text_input("Recherche (identifiant, description)")
    sel = df[df["gravite"].isin(gr)]
    if vd:
        sel = sel[sel["verdict"].isin(vd)]
    if ty:
        sel = sel[sel["type"].isin(ty)]
    if bq:
        sel = sel[sel["banque"].isin(bq)]
    if q:
        sel = sel[sel["id"].str.contains(q, case=False) | sel["description"].str.contains(q, case=False)]
    ordre = {g: i for i, g in enumerate(["critique", "avertissement", "info", "ok"])}
    sel = sel.sort_values(["gravite", "idx"], key=lambda c: c.map(ordre) if c.name == "gravite" else c)
    st.caption(f"{len(sel)} scénario(s) — cliquez une ligne pour voir le détail. (La liste ne se rafraîchit pas seule : le panneau reste stable pendant la lecture.)")
    vue = pd.DataFrame({"": sel["gravite"].map(ICONE), "scénario": sel["id"], "verdict": sel["verdict"], "banque": sel["banque"],
                        "format": sel["format"], "attendu → obtenu": sel["statut_attendu"].map(lambda s: "/".join(json.loads(s))) + " → " + sel["statut_obtenu"].astype(str),
                        "A8": sel["a8_eval"].map(EVAL_A8) if "a8_eval" in sel else ""})
    ev = st.dataframe(vue, hide_index=True, use_container_width=True, height=300, on_select="rerun", selection_mode="single-row", key="liste_scn",
                      column_config={"": st.column_config.TextColumn(width="small"), "scénario": st.column_config.TextColumn(width="large"),
                                     "verdict": st.column_config.TextColumn(width="medium"),
                                     "attendu → obtenu": st.column_config.TextColumn(width="large"),
                                     "A8": st.column_config.TextColumn(width="medium")})
    lignes = ev.selection.rows if ev and ev.selection else []
    if not lignes:
        st.info("Sélectionnez un scénario dans la liste pour voir le parcours de chaque agent.")
        return
    ident = sel.iloc[lignes[0]]["id"]
    st.divider()
    detail_scenario(choix, ident)
    lot = lots_frais().pipe(lambda d: d[d["run_id"] == choix]).iloc[0]
    vivant = P.etat_vivant(lot["statut"], lot.get("heartbeat"))
    if st.button("↻ Rejouer ce scénario", help="Relance uniquement ce scénario dans ce lot et remplace son résultat (utile après un correctif).",
                 disabled=vivant == "actif"):
        opts = json.loads(lot["options"]) if lot.get("options") else {}
        P.lancer(choix, int(lot["seed"]), 1000, 1, lot["mode"] == "reel", bool(opts.get("sans_a8")), ids=[ident], forcer=True)
        st.session_state["demarrage"] = choix
        st.toast("Scénario relancé : actualisez la liste dans quelques secondes.")
    if vivant == "actif":
        st.caption("Un lot est en cours d'exécution : attendez sa fin ou mettez-le en pause avant de rejouer.")


# --------------------------------------------------------------------------- #
# Onglet 4 — Performance
# --------------------------------------------------------------------------- #
def perf_a8(run_id, df):
    st.markdown("#### Évaluation du relecteur A8")
    if not a8_utilisable(df):
        st.caption("Ce lot précède l'ajout d'A8 : aucune donnée de relecture.")
        return
    e = df["a8_eval"].value_counts()
    vp, mq, fp, vn = (int(e.get(k, 0)) for k in ("vrai_positif", "manque", "faux_positif", "vrai_negatif"))
    ind, na = int(e.get("indisponible", 0)), int(e.get("non_applicable", 0))
    c = st.columns(5)
    tuile(c[0], f"{vp / (vp + mq):.0%}" if vp + mq else "—", "défauts signalés (rappel)", f"{vp} sur {vp + mq} scénarios avec un défaut réel")
    tuile(c[1], f"{vp / (vp + fp):.0%}" if vp + fp else "—", "alertes justifiées (précision)", f"{fp} fausse(s) alerte(s)")
    tuile(c[2], str(fp), "fausses alertes", f"sur {fp + vn} scénarios sains relus")
    j, t = int(df["a8_lignes_justes"].fillna(0).sum()), int(df["a8_lignes_total"].fillna(0).sum())
    tuile(c[3], f"{j / t:.0%}" if t else "—", "lignes citées à bon escient", f"{j} sur {t} ligne(s) citée(s)")
    tuile(c[4], str(nb_rejetes_a8(run_id)), "scénarios avec avis écartés", "par les garde-fous (LLM réel surtout)")
    origine = ", ".join(f"{k} ({v})" for k, v in df["a8_origine"].value_counts().items()) if df["a8_origine"].notna().any() else "—"
    st.caption(f"Origine des relectures : {origine}. Non atteint : {na} · indisponible : {ind}. « Défaut réel » = ligne perdue, fantôme, "
               "mauvaise catégorie ou ambiguë classée seule, d'après la vérité du banc d'essai. "
               "En mode simulé, A8 applique des règles (signe/nature, précédent discordant, mot-clé dans un mot, doublon interne) : "
               "la mesure du vrai LLM exige un lot `--reel`.")
    p = df[df["a8_eval"].isin(["vrai_positif", "manque", "faux_positif", "vrai_negatif"])]
    if not p.empty:
        pv = p.pivot_table(index="type", columns="a8_eval", values="id", aggfunc="count", fill_value=0)
        pv = pv.rename(columns=EVAL_A8)
        st.dataframe(pv, use_container_width=True)
    notes = defaultdict(list)
    for s in df["a8_notes"].dropna():
        for k, v in json.loads(s).items():
            if isinstance(v, (int, float)):
                notes[k].append(v)
    if notes:
        st.markdown("**Notes moyennes du relecteur (1 à 5)** : " + " · ".join(f"{k} {sum(v) / len(v):.1f}" for k, v in notes.items()))


def comparaison(run_id, df):
    st.markdown("#### Comparer deux lots")
    autres = [r for r in lots_frais()["run_id"] if r != run_id]
    if not autres:
        st.caption("Il faut au moins deux lots. Astuce : relancez le même lot (même graine, même taille) avec « Relecteur A8 » décoché, ou après un correctif.")
        return
    ref = st.selectbox("Comparer à", autres, key="lot_ref")
    d2 = charger(ref)
    if d2.empty:
        return

    def kpi(d):
        return {"scénarios": len(d), "conformes": f"{(d['gravite'] == 'ok').mean():.1%}", "critiques": int((d["gravite"] == "critique").sum()),
                "avertissements": int((d["gravite"] == "avertissement").sum()), "durée médiane (s)": round(d["duree_s"].median(), 2),
                "durée p95 (s)": round(d["duree_s"].quantile(.95), 2)}
    st.dataframe(pd.DataFrame({run_id: {k: str(v) for k, v in kpi(df).items()}, ref: {k: str(v) for k, v in kpi(d2).items()}}),
                 use_container_width=True)
    m = df[["id", "verdict", "gravite"]].merge(d2[["id", "verdict", "gravite"]], on="id", suffixes=("", "_ref"))
    if m.empty:
        st.caption("Aucun scénario en commun (graine ou taille différentes).")
        return
    ordre = {g: i for i, g in enumerate(GRAVITES)}
    m["delta"] = m["gravite"].map(ordre) - m["gravite_ref"].map(ordre)
    mieux, pire = int((m["delta"] < 0).sum()), int((m["delta"] > 0).sum())
    c = st.columns(3)
    tuile(c[0], str(len(m)), "scénarios en commun", "")
    tuile(c[1], str(mieux), f"meilleurs dans {run_id}", "gravité du verdict plus basse")
    tuile(c[2], str(pire), f"plus mauvais dans {run_id}", "gravité du verdict plus haute")
    chg = m[m["verdict"] != m["verdict_ref"]]
    if not chg.empty:
        t = chg.groupby(["verdict_ref", "verdict"]).size().reset_index(name="scénarios")
        t.columns = [f"verdict dans {ref}", f"verdict dans {run_id}", "scénarios"]
        st.dataframe(t.sort_values("scénarios", ascending=False), hide_index=True, use_container_width=True)
    else:
        st.caption("Les verdicts sont identiques scénario par scénario.")


def performance(run_id):
    df = charger(run_id)
    if df.empty or lots_frais().pipe(lambda d: d[d["run_id"] == run_id]).empty:
        st.info("En attente des premiers résultats…")
        return
    st.markdown("#### Latence par agent")
    lignes = []
    for s in df["durees_agents"].dropna():
        for k, d in json.loads(s).items():
            lignes.append((k, d))
    if lignes:
        la = pd.DataFrame(lignes, columns=["agent", "s"])
        res = la.groupby("agent")["s"].agg(médiane="median", p95=lambda x: x.quantile(.95), n="count").reset_index()
        base = alt.Chart(res).encode(y=alt.Y("agent:N", sort="ascending", title=None))
        barre = base.mark_bar(color=BLEU, size=14, cornerRadiusEnd=4).encode(
            x=alt.X("médiane:Q", title="secondes"), tooltip=["agent", alt.Tooltip("médiane:Q", format=".2f"), alt.Tooltip("p95:Q", format=".2f"), "n"])
        repere = base.mark_tick(color="#52514e", thickness=2, size=18).encode(x="p95:Q")
        st.altair_chart((barre + repere).properties(height=alt.Step(26)), use_container_width=True)
        st.caption("Barre = médiane · trait = p95. Seuls les agents atteints sont mesurés.")

    g1, g2 = st.columns(2)
    with g1:
        st.markdown("#### Débit du lot")
        d = df.dropna(subset=["horodatage"]).copy()
        d["t"] = pd.to_datetime(d["horodatage"])
        d = d.sort_values("t")
        d["terminés"] = range(1, len(d) + 1)
        ch = alt.Chart(d).mark_line(color=BLEU, strokeWidth=2).encode(x=alt.X("t:T", title=None), y=alt.Y("terminés:Q", title="scénarios terminés"),
                                                                       tooltip=["t:T", "terminés:Q"])
        st.altair_chart(ch.properties(height=220), use_container_width=True)
    with g2:
        st.markdown("#### Distribution des durées")
        h = alt.Chart(df).mark_bar(color=BLEU).encode(x=alt.X("duree_s:Q", bin=alt.Bin(maxbins=30), title="durée d'un scénario (s)"),
                                                      y=alt.Y("count():Q", title="scénarios"))
        st.altair_chart(h.properties(height=220), use_container_width=True)

    st.markdown("#### Taux de conformité par catégorie")
    t = df.groupby("categorie_test").agg(scénarios=("id", "count"), conformes=("gravite", lambda s: (s == "ok").sum()),
                                        critiques=("gravite", lambda s: (s == "critique").sum()),
                                        avertissements=("gravite", lambda s: (s == "avertissement").sum())).reset_index()
    t["taux de conformité"] = (t["conformes"] / t["scénarios"]).map("{:.0%}".format)
    st.dataframe(t, hide_index=True, use_container_width=True)

    lot = lots_frais().pipe(lambda d: d[d["run_id"] == run_id]).iloc[0]
    if lot["mode"] == "reel":
        ti, to = int(df["jetons_entree"].fillna(0).sum()), int(df["jetons_sortie"].fillna(0).sum())
        c = st.columns(3)
        tuile(c[0], f"{ti:,}".replace(",", " "), "jetons en entrée", "")
        tuile(c[1], f"{to:,}".replace(",", " "), "jetons en sortie", "")
        tuile(c[2], f"{(ti + to) / max(len(df), 1):,.0f}".replace(",", " "), "jetons / scénario", "")
    perf_a8(run_id, df)
    comparaison(run_id, df)


# --------------------------------------------------------------------------- #
# Assemblage
# --------------------------------------------------------------------------- #
onglets = st.tabs(["🎛 Contrôle", "📊 Vue d'ensemble", "🔎 Scénarios & agents", "⚡ Performance"])
with onglets[0]:
    onglet_controle()
with onglets[1]:
    if choix:
        rafraichi()(lambda: vue_ensemble(choix))()
    else:
        st.info("Lancez un lot depuis l'onglet Contrôle.")
with onglets[2]:
    onglet_scenarios()
with onglets[3]:
    if choix:
        rafraichi()(lambda: performance(choix))()
    else:
        st.info("Lancez un lot depuis l'onglet Contrôle.")
