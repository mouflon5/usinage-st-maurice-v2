"""
Rendu PDF des relevés de test — 4 mises en page (F1 à F4) + un format inconnu (F5) servant de piège.

Le rendu est écrit SANS référence au lecteur (formats_releves.py) : il reproduit des mises en page de type
« banque » avec des colonnes positionnées en x, des pages multiples (en-tête répété, « Page x de y »),
des soldes d'ouverture / de clôture et des séparateurs propres à chaque format.

Une ligne imprimée est un dict : date (ISO), description, montant, solde, et éventuellement des surcharges
de texte (`date_txt`, `solde_txt`, `montant_txt`) ou `brut` (texte libre inséré tel quel dans le tableau).
"""

import os
from datetime import date

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

POLICE, TAILLE, CAR = "Courier", 9, 5.4
HAUT, BAS, PAS = 740, 60, 12
MOIS_EN = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

LIM_DESC = {"F1": 48, "F2": 40, "F3": 44, "F4": 44}

GEOM = {
    "F2": dict(date=40, desc=105, debit=410, credit=485, solde=568, max_desc=40),
    "F3": dict(date=40, desc=105, montant=450, solde=568, max_desc=44),
    "F4": dict(date=40, desc=110, montant=450, solde=568, max_desc=44),
}


def fr(v: float) -> str:
    return f"{abs(v):,.2f}".replace(",", " ").replace(".", ",")


def en(v: float) -> str:
    return f"{abs(v):,.2f}"


def _fmt_solde_f2(v):
    return ("-" if v < 0 else "") + fr(v)


def _fmt_solde_f4(v):
    return f"({fr(v)})" if v < 0 else fr(v)


def _suffixe(v):
    return f"{en(v)} {'DR' if v < 0 else 'CR'}"


def dernier_jour(periode: str) -> date:
    a, m = int(periode[:4]), int(periode[5:])
    nxt = date(a + (m == 12), 1 if m == 12 else m + 1, 1)
    return date.fromordinal(nxt.toordinal() - 1)


def _desc(texte: str, fmt: str) -> str:
    return texte[:LIM_DESC[fmt]].rstrip()


def rendre(chemin: str, fmt: str, banque: str, compte: str, periode: str, lignes: list,
           solde_ouverture: float | None, ouverture_cloture: bool = True, par_page: int = 38,
           sans_colonne_solde: bool = False, cloture: float | None = None) -> None:
    """Écrit un relevé PDF. `periode` = AAAA-MM. Les lignes sont imprimées dans l'ordre donné."""
    os.makedirs(os.path.dirname(chemin) or ".", exist_ok=True)
    c = canvas.Canvas(chemin, pagesize=letter)
    d0, d1 = date(int(periode[:4]), int(periode[5:]), 1), dernier_jour(periode)
    if fmt == "F5":
        return _rendre_f5(c, banque, compte, d0, d1, lignes)

    pages = [lignes[i:i + par_page] for i in range(0, max(len(lignes), 1), par_page)] or [[]]
    total = len(pages)
    if cloture is None:
        cloture = lignes[-1]["solde"] if lignes else solde_ouverture
    for n, bloc in enumerate(pages, 1):
        c.setFont(POLICE, TAILLE)
        y = HAUT
        # --- en-tête de page ---
        if fmt == "F1":
            c.drawString(50, y, f"Relevé de compte {compte}")
            y -= 30
        else:
            c.setFont("Courier-Bold", 11)
            c.drawString(40, y, banque.upper())
            c.setFont(POLICE, TAILLE)
            y -= 18
            if fmt == "F2":
                c.drawString(40, y, f"Compte : {compte}")
                y -= PAS
                c.drawString(40, y, f"Période : {d0:%d/%m/%Y} au {d1:%d/%m/%Y}")
            elif fmt == "F3":
                c.drawString(40, y, f"Account: {compte}")
                y -= PAS
                c.drawString(40, y, f"Statement period: {MOIS_EN[d0.month - 1]} {d0.day}, {d0.year} - {MOIS_EN[d1.month - 1]} {d1.day}, {d1.year}")
            else:
                c.drawString(40, y, f"Compte n° {compte}")
                y -= PAS
                c.drawString(40, y, f"Période du {d0:%d-%m-%Y} au {d1:%d-%m-%Y}")
            y -= 24
            g = GEOM[fmt]
            c.setFont("Courier-Bold", TAILLE)
            c.drawString(g["date"], y, "Date")
            c.drawString(g["desc"], y, "Description")
            if fmt == "F2":
                c.drawRightString(g["debit"], y, "Débit")
                c.drawRightString(g["credit"], y, "Crédit")
            elif fmt == "F3":
                c.drawRightString(g["montant"], y, "Amount")
            else:
                c.drawRightString(g["montant"], y, "Montant")
            if not sans_colonne_solde:
                c.drawRightString(g["solde"], y, {"F2": "Solde", "F3": "Balance", "F4": "Solde"}[fmt])
            c.setFont(POLICE, TAILLE)
            y -= PAS + 4
            if ouverture_cloture and n == 1 and solde_ouverture is not None:
                lib = {"F2": "Solde précédent", "F3": "Opening balance", "F4": "SOLDE D'OUVERTURE"}[fmt]
                c.drawString(g["desc"], y, lib)
                sol = {"F2": _fmt_solde_f2, "F3": _suffixe, "F4": _fmt_solde_f4}[fmt](solde_ouverture)
                if not sans_colonne_solde:
                    c.drawRightString(g["solde"], y, sol)
                y -= PAS

        # --- lignes ---
        for r in bloc:
            if "brut" in r:
                c.drawString(50 if fmt == "F1" else GEOM[fmt]["desc"], y, r["brut"])
                y -= PAS
                continue
            desc = _desc(r["description"], fmt)
            if fmt == "F1":
                d = r.get("date_txt", r["date"])
                m = r.get("montant_txt", f"{r['montant']:.2f}")
                s = r.get("solde_txt", f"{r['solde']:.2f}")
                if sans_colonne_solde:
                    c.drawString(50, y, f"{d}  {desc:<48}{m:>12}")
                else:
                    c.drawString(50, y, f"{d}  {desc:<48}{m:>12}{s:>12}")
            else:
                g = GEOM[fmt]
                dt = date.fromisoformat(r["date"]) if "date_txt" not in r else date(2000, 1, 1)
                if fmt == "F2":
                    d = r.get("date_txt", f"{dt:%d/%m/%Y}")
                    c.drawString(g["date"], y, d)
                    c.drawString(g["desc"], y, desc)
                    col = "debit" if r["montant"] < 0 else "credit"
                    c.drawRightString(g[col], y, r.get("montant_txt", fr(r["montant"])))
                    if not sans_colonne_solde:
                        c.drawRightString(g["solde"], y, r.get("solde_txt", _fmt_solde_f2(r["solde"])))
                elif fmt == "F3":
                    d = r.get("date_txt", f"{MOIS_EN[dt.month - 1]} {dt.day:02d}")
                    c.drawString(g["date"], y, d)
                    c.drawString(g["desc"], y, desc)
                    c.drawRightString(g["montant"], y, r.get("montant_txt", _suffixe(r["montant"])))
                    if not sans_colonne_solde:
                        c.drawRightString(g["solde"], y, r.get("solde_txt", _suffixe(r["solde"])))
                else:
                    d = r.get("date_txt", f"{dt:%d-%m-%Y}")
                    c.drawString(g["date"], y, d)
                    c.drawString(g["desc"], y, desc)
                    mt = fr(r["montant"])
                    c.drawRightString(g["montant"], y, r.get("montant_txt", f"({mt})" if r["montant"] < 0 else mt))
                    if not sans_colonne_solde:
                        c.drawRightString(g["solde"], y, r.get("solde_txt", _fmt_solde_f4(r["solde"])))
            y -= PAS

        # --- clôture (dernière page) + pied de page ---
        if fmt != "F1" and ouverture_cloture and n == total and cloture is not None:
            g = GEOM[fmt]
            lib = {"F2": "Solde final", "F3": "Closing balance", "F4": "SOLDE DE FERMETURE"}[fmt]
            c.drawString(g["desc"], y - 4, lib)
            val = {"F2": _fmt_solde_f2, "F3": _suffixe, "F4": _fmt_solde_f4}[fmt](cloture)
            if not sans_colonne_solde:
                c.drawRightString(g["solde"], y - 4, val)
        c.setFont(POLICE, 8)
        c.drawString(270, BAS - 20, f"Page {n} de {total}")
        c.showPage()
    c.save()


def _rendre_f5(c, banque, compte, d0, d1, lignes):
    """Format INCONNU : deux colonnes de dates (opération / valeur), montant avant la description.
    Aucun des 4 formats supportés ne doit l'accepter ; il sert à vérifier qu'on refuse au lieu de mal lire."""
    c.setFont(POLICE, TAILLE)
    y = HAUT
    c.drawString(40, y, f"{banque} — Relevé d'opérations — compte {compte}")
    y -= 30
    c.drawString(40, y, "Date op.   Date val.        Montant        Solde   Libellé")
    y -= 16
    for r in lignes:
        dt = date.fromisoformat(r["date"])
        c.drawString(40, y, f"{dt:%d.%m}      {dt:%d.%m}   {r['montant']:>12.2f}  {r['solde']:>12.2f}   {r['description'][:30]}")
        y -= PAS
    c.showPage()
    c.save()
