"""
Nœuds de l'agent A7 — Reporting.

Produit, pour la période : un classeur Excel « miroir » (feuilles R0 à R5 + Contrôles) et un brouillon
R0 en Markdown. Chaque chiffre provient du dossier déjà contrôlé par A6 ; la synthèse rédigée par le
LLM est soumise au même contrôle de chiffres qu'en A5.
"""

import suivi_llm as suivi
import os
import re

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

import balance_verification
import llm_fournisseur as llm_f
import llm_outils as llm
from a5_nodes import fmt_montant, fmt_pct, _nombres, _p
from a7_state import ReportingState

VERT, ROUGE, GRIS, BLEU = "C6EFCE", "FFC7CE", "F2F2F2", "1F4E78"
JUGEMENTS = {"significatif_favorable": "Écart favorable", "significatif_defavorable": "Écart défavorable",
             "dans_la_tolerance": "Dans la tolérance", None: "n/d"}
VERDICTS = {"approuve": "APPROUVÉ", "reserves": "APPROUVÉ AVEC RÉSERVES", "bloque": "BLOQUÉ"}


def preparer_node(state: ReportingState) -> dict:
    d = state["dossier"]
    if d.get("verdict") not in ("approuve", "reserves"):
        return {"statut": "erreur", "message": f"A7 refuse de produire : verdict A6 = {d.get('verdict')!r}"}
    if d.get("decision_humaine", {}).get("decision") == "rejeter":
        return {"statut": "erreur", "message": "A7 refuse de produire : rejet humain"}
    sortie = state.get("dossier_sortie") or os.path.join(os.getenv("SORTIES_DIR", "sorties"), state["periode"])
    os.makedirs(sortie, exist_ok=True)
    return {"dossier_sortie": sortie}


def router_apres_preparation(state: ReportingState) -> str:
    return "erreur" if state.get("statut") == "erreur" else "rediger"


def _faits(state: ReportingState) -> str:
    """Seule source de chiffres de la synthèse (déjà formatés)."""
    d, per = state["dossier"], state["periode"]
    out = [f"Période : {per}", f"Verdict de contrôle : {VERDICTS[d['verdict']]} (empreinte {d['empreinte']})"]
    for l in d["ecarts"]:
        out.append(f"- {l['libelle']} : réel {fmt_montant(l['reel'])}"
                   + (f"; budget {fmt_montant(l['budget'])}" if l["budget"] is not None else "")
                   + (f"; prévu {fmt_montant(l['prevu'])}" if l["prevu"] is not None else "")
                   + (f"; écart vs budget {fmt_montant(l['ecart_budget'])}{_p(l['ecart_budget_pct'])}" if l["ecart_budget"] is not None else "")
                   + (f"; écart vs prévision {fmt_montant(l['ecart_prevision'])}{_p(l['ecart_prevision_pct'])}" if l["ecart_prevision"] is not None else ""))
    fn = d.get("flux_net_prevu", {})
    if fn:
        out.append("Flux net prévu : " + "; ".join(f"{p} {fmt_montant(v)}" for p, v in zip(fn["periodes"], fn["valeurs"])))
    r3 = d.get("resume_a3", {})
    out.append(f"Chargement : {r3.get('promus_journal_general', 0)} écriture(s), {r3.get('doublons_ignores', 0)} doublon(s)")
    return "\n".join(out)


def _synthese_modele(state: ReportingState) -> str:
    d = state["dossier"]
    flux = next(l for l in d["ecarts"] if l["code"] == "Flux")
    c = d.get("commentaire", {})
    t = f"Flux net réel de {state['periode']} : {fmt_montant(flux['reel'])}"
    if flux["budget"] is not None:
        t += f" contre {fmt_montant(flux['budget'])} au budget"
    t += ". " + c.get("resume", "")
    return t


def rediger_node(state: ReportingState) -> dict:
    modele = _synthese_modele(state)
    if llm.mode_llm() == "simule":
        suivi.noter("A7", "simulé", "simule", 0.3, entree="Rédige en français… " + _faits(state), sortie=modele, origine="gabarit")
        llm_f.tracer_regle("A7", "Gabarit déterministe appliqué aux faits :\n" + _faits(state), modele)
        return {"synthese": {"texte": modele, "origine": "simule"}}
    prompt = ("Rédige en français, pour un contrôleur financier, une synthèse exécutive de 4 phrases maximum "
              "à partir UNIQUEMENT des faits ci-dessous. Recopie les chiffres exactement; n'en invente, n'en "
              "calcule et n'en arrondis aucun.\n\n" + _faits(state))
    try:
        with suivi.chrono() as _t:
            _rep = llm_f.invoquer("A7", prompt, max_tokens=500, defaut=os.getenv("A7_MODELE", "claude-sonnet-5-5"))
        texte = _rep.texte
        suivi.noter("A7", _rep.modele, "reel", _t[0], entree=prompt, sortie=texte, tokens=_rep.jetons, fournisseur=_rep.fournisseur)
        hors = sorted(_nombres(texte) - _nombres(_faits(state)))
        suivi.noter_garde("A7", "nombres de la synthèse", not hors, hors_source=hors)
        suivi.decider(_rep.trace_id, "rejetée par garde-fou" if hors else "acceptée",
                      f"nombre(s) absent(s) des faits : {hors} → gabarit utilisé" if hors else "tous les nombres figurent dans les faits fournis")
        if hors:
            return {"synthese": {"texte": modele, "origine": "modele", "rejet": f"nombres non sourcés {hors}"}}
        return {"synthese": {"texte": texte.strip(), "origine": "llm"}}
    except Exception as e:
        suivi.decider(llm_f.dernier_trace_id(), "repli sur le gabarit", f"appel en échec ({type(e).__name__})")
        return {"synthese": {"texte": modele, "origine": "modele", "rejet": f"{type(e).__name__}"}}


# ---------- Excel ---------- #
def _entete(ws, ligne, titres):
    for j, t in enumerate(titres, 1):
        c = ws.cell(ligne, j, t)
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor=BLEU)
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)


def _largeurs(ws, largeurs):
    for j, w in enumerate(largeurs, 1):
        ws.column_dimensions[get_column_letter(j)].width = w


def _balance(db_path, per):
    """Balance de vérification du journal pour la période ; None si la base est indisponible."""
    if not db_path:
        return None
    try:
        return balance_verification.balance_journal(db_path, per)
    except Exception:                                    # un rapport ne doit pas échouer pour une feuille annexe
        return None


def _feuille_balance(wb, db_path, per):
    ws = wb.create_sheet("Balance de vérification")
    b = _balance(db_path, per)
    if b is None:
        ws["A1"] = "Balance indisponible : base du journal introuvable."
        return
    ws["A1"] = f"Balance de vérification du journal général — {per} et cumul de l'exercice {b['annee']}"
    ws["A1"].font = Font(bold=True, size=12)
    ws["A2"] = "Sorties de fonds = débits ; entrées de fonds = crédits. Solde net = crédits − débits."
    _entete(ws, 4, ["Catégorie", "Nature", "Écritures", "Débits", "Crédits", "Solde net", "Débits cumulés", "Crédits cumulés", "Solde net cumulé"])
    argent = '#,##0.00;[Red]-#,##0.00'
    r = 4
    for l in b["lignes"]:
        r += 1
        for j, v in enumerate([l["categorie"], l["nature"], l["nb"], l["debit"], l["credit"], l["net"], l["debit_cumul"], l["credit_cumul"], l["net_cumul"]], 1):
            c = ws.cell(r, j, v)
            if j >= 4:
                c.number_format = argent
    t = b["totaux"]
    r += 1
    for j, v in enumerate(["TOTAL", "", t["nb"], t["debit"], t["credit"], t["net"], t["debit_cumul"], t["credit_cumul"], t["net_cumul"]], 1):
        c = ws.cell(r, j, v)
        c.font = Font(bold=True)
        c.fill = PatternFill("solid", fgColor=GRIS)
        if j >= 4:
            c.number_format = argent
    r += 2
    for ctl in b["controles"]:
        ws.cell(r, 1, ctl["controle"])
        ws.cell(r, 2, "OK" if ctl["ok"] else "ÉCHEC").fill = PatternFill("solid", fgColor=VERT if ctl["ok"] else ROUGE)
        r += 1
    ws.cell(r, 1, "Écritures au signe inattendu (période) à relire")
    ws.cell(r, 2, b["signes_inattendus"])
    _largeurs(ws, [58, 12, 10, 16, 16, 16, 16, 16, 16])
    ws.freeze_panes = "A5"


def construire_excel_node(state: ReportingState) -> dict:
    d, per = state["dossier"], state["periode"]
    wb = Workbook()

    ws = wb.active
    ws.title = "R0 Sommaire"
    ws["A1"] = f"Rapport de trésorerie — {per}"
    ws["A1"].font = Font(bold=True, size=14)
    ws["A2"] = f"Verdict A6 : {VERDICTS[d['verdict']]}  |  empreinte {d['empreinte']}  |  statut du pipeline : voir R3"
    ws["A4"] = "Synthèse (" + state["synthese"]["origine"] + ")"
    ws["A4"].font = Font(bold=True)
    ws["A5"] = state["synthese"]["texte"]
    ws["A5"].alignment = Alignment(wrap_text=True, vertical="top")
    ws.merge_cells("A5:F9")
    r = 11
    ws.cell(r, 1, "Points d'attention").font = Font(bold=True)
    for p in d.get("commentaire", {}).get("points", []) or ["Aucun écart significatif."]:
        r += 1
        ws.cell(r, 1, "• " + p)
    for a in d.get("alertes", []):
        r += 1
        ws.cell(r, 1, "⚠ " + a).font = Font(color="9C5700")
    _largeurs(ws, [30, 18, 18, 18, 18, 18])

    ws = wb.create_sheet("R5 Écarts")
    _entete(ws, 1, ["Ligne", "Réel", "Budget", "Écart vs budget", "% budget", "Jugement budget",
                    "Prévu (SARIMAX)", "Écart vs prévision", "% prévision", "Jugement prévision"])
    for i, l in enumerate(d["ecarts"], 2):
        vals = [l["libelle"], l["reel"], l["budget"], l["ecart_budget"], l["ecart_budget_pct"], JUGEMENTS.get(l["jugement_budget"]),
                l["prevu"], l["ecart_prevision"], l["ecart_prevision_pct"], JUGEMENTS.get(l["jugement_prevision"])]
        for j, v in enumerate(vals, 1):
            c = ws.cell(i, j, v)
            if j in (2, 3, 4, 7, 8):
                c.number_format = '#,##0 "$";[Red]-#,##0 "$"'
            if j in (5, 9):
                c.number_format = "+0.0%;-0.0%"
            if j in (6, 10) and v:
                c.fill = PatternFill("solid", fgColor=VERT if "favorable" in v and "dé" not in v else ROUGE if "défavorable" in v else GRIS)
    _largeurs(ws, [18, 14, 14, 16, 10, 20, 16, 18, 12, 20])
    ws.freeze_panes = "B2"

    ws = wb.create_sheet("R4 Prévision")
    _entete(ws, 1, ["Série", "Période", "Prévision", "IC 80 % bas", "IC 80 % haut", "IC 95 % bas", "IC 95 % haut", "Méthode", "MAPE backtest"])
    i = 2
    for s, p in d.get("previsions", {}).items():
        for k, per_f in enumerate(p["periodes"]):
            vals = [s, per_f, p["valeurs"][k], p["ci80"][k][0], p["ci80"][k][1], p["ci95"][k][0], p["ci95"][k][1],
                    p["methode"], p["backtest"].get("mape")]
            for j, v in enumerate(vals, 1):
                c = ws.cell(i, j, v)
                if 3 <= j <= 7:
                    c.number_format = '#,##0 "$"'
                if j == 9:
                    c.number_format = "0.0%"
            i += 1
    fn = d.get("flux_net_prevu", {})
    for per_f, v in zip(fn.get("periodes", []), fn.get("valeurs", [])):
        ws.cell(i, 1, "Flux net (Revenu − Décaissements)")
        ws.cell(i, 2, per_f)
        ws.cell(i, 3, v).number_format = '#,##0 "$";[Red]-#,##0 "$"'
        i += 1
    _largeurs(ws, [32, 10, 14, 14, 14, 14, 14, 24, 12])

    ws = wb.create_sheet("R3 Chargement")
    r3 = d.get("resume_a3", {})
    _entete(ws, 1, ["Indicateur", "Valeur"])
    for i, (k, v) in enumerate([("Écritures promues au grand livre", r3.get("promus_journal_general")),
                                ("Insérées au staging", r3.get("inseres_staging")),
                                ("Doublons ignorés", r3.get("doublons_ignores")),
                                ("À classer (arbitrage)", r3.get("a_classer")),
                                ("Méthodes de classement", str(r3.get("par_methode"))),
                                ("Mode LLM", d.get("mode_llm")),
                                ("Statut du pipeline", d.get("statut_pipeline"))], 2):
        ws.cell(i, 1, k)
        ws.cell(i, 2, v)
    _largeurs(ws, [36, 40])

    ws = wb.create_sheet("Journal du mois")
    _entete(ws, 1, ["Date", "Description", "Montant", "Fichier source"])
    for i, t in enumerate(sorted(d.get("transactions", []), key=lambda t: t["date"]), 2):
        ws.cell(i, 1, t["date"])
        ws.cell(i, 2, t["description"])
        ws.cell(i, 3, t["montant"]).number_format = '#,##0.00;[Red]-#,##0.00'
        ws.cell(i, 4, t["fichier"])
    _largeurs(ws, [12, 64, 16, 32])

    _feuille_balance(wb, d.get("db_path"), per)

    ws = wb.create_sheet("Contrôles A6")
    _entete(ws, 1, ["ID", "Contrôle", "Gravité", "Résultat", "Détail"])
    for i, c in enumerate(d.get("controles", []), 2):
        for j, v in enumerate([c["id"], c["libelle"], c["gravite"], "OK" if c["ok"] else "ÉCHEC", c["detail"]], 1):
            cell = ws.cell(i, j, v)
            if j == 4:
                cell.fill = PatternFill("solid", fgColor=VERT if c["ok"] else ROUGE)
    _largeurs(ws, [6, 62, 12, 10, 70])

    chemin = os.path.join(state["dossier_sortie"], f"Rapport_Tresorerie_{per}.xlsx")
    wb.save(chemin)
    return {"fichiers": [chemin]}


def construire_r0_node(state: ReportingState) -> dict:
    d, per = state["dossier"], state["periode"]
    L = [f"# R0 — Brouillon du rapport de trésorerie, {per}", "",
         f"**Statut : BROUILLON — verdict de contrôle {VERDICTS[d['verdict']]}** (empreinte `{d['empreinte']}`)", "",
         "## Synthèse", state["synthese"]["texte"], "", "## Écarts", "",
         "| Ligne | Réel | Budget | Écart | Prévu | Écart |", "|---|---:|---:|---:|---:|---:|"]
    for l in d["ecarts"]:
        def m(x): return fmt_montant(x) if x is not None else "n/d"
        L.append(f"| {l['libelle']} | {m(l['reel'])} | {m(l['budget'])} | {m(l['ecart_budget'])}{_p(l['ecart_budget_pct'])} "
                 f"| {m(l['prevu'])} | {m(l['ecart_prevision'])}{_p(l['ecart_prevision_pct'])} |")
    if d.get("commentaire", {}).get("points"):
        L += ["", "### Commentaire", *[f"- {p}" for p in d["commentaire"]["points"]]]
    fn = d.get("flux_net_prevu", {})
    if fn:
        L += ["", "## Prévision du flux net", *[f"- {p} : {fmt_montant(v)}" for p, v in zip(fn["periodes"], fn["valeurs"])]]
    bal = _balance(d.get("db_path"), per)
    if bal:
        t = bal["totaux"]
        L += ["", "## Balance de vérification du journal",
              f"- {per} : débits {fmt_montant(t['debit'])}, crédits {fmt_montant(t['credit'])}, solde net {fmt_montant(t['net'])} "
              f"({t['nb']} écriture(s)) ; cumul {bal['annee']} : solde net {fmt_montant(t['net_cumul'])}.",
              "- Contrôles : " + ("tous OK" if all(c["ok"] for c in bal["controles"]) else "ÉCHEC — voir l'onglet « Balance de vérification » du classeur")
              + (f" ; {bal['signes_inattendus']} écriture(s) au signe inattendu à relire." if bal["signes_inattendus"] else ".")]
    L += ["", "## Contrôles", *[f"- [{'x' if c['ok'] else ' '}] {c['id']} {c['libelle']} — {c['detail']}" for c in d.get("controles", [])]]
    if d.get("alertes"):
        L += ["", "## Réserves", *[f"- {a}" for a in d["alertes"]]]
    if d.get("decision_humaine"):
        h = d["decision_humaine"]
        L += ["", "## Décision humaine", f"- {h.get('decision')} — {h.get('commentaire', '')}"]
    chemin = os.path.join(state["dossier_sortie"], f"R0_{per}.md")
    with open(chemin, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    return {"fichiers": state["fichiers"] + [chemin]}


def finaliser_node(state: ReportingState) -> dict:
    from openpyxl import load_workbook
    try:
        feuilles = load_workbook(state["fichiers"][0]).sheetnames
    except Exception as e:
        return {"statut": "erreur", "message": f"Classeur illisible après écriture : {e}"}
    return {"statut": "complet", "message": (f"{len(state['fichiers'])} fichier(s) produit(s) dans {state['dossier_sortie']} "
                                             f"({len(feuilles)} feuilles ; synthèse : {state['synthese']['origine']}).")}
