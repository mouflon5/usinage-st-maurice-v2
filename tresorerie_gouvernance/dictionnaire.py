"""Dictionnaire de données (DMBOK : Metadata Management).

Lit le schéma réel de la base (tables et vues préfixées meta_, ref_, mdm_, dq_, stg_, core_, dim_, mart_),
le croise avec descriptions_champs.py et remplit la table meta_champ. Génère aussi un export
Markdown et un classeur Excel (onglets Dictionnaire, Glossaire, Regles_DQ).

Usage :
    python dictionnaire.py --db tresorerie.db --md docs/dictionnaire_donnees.md --xlsx dictionnaire_donnees.xlsx
"""
import argparse
import sqlite3
from pathlib import Path

from descriptions_champs import trouver

PREFIXES = ("meta_", "ref_", "mdm_", "dq_", "stg_", "core_", "dim_", "mart_")

PROPRIETAIRES = {
    "meta_": "Intendant des données",
    "ref_": "Intendant des données",
    "mdm_": "Intendant des données",
    "dq_": "Intendant des données",
    "stg_": "Trésorier (propriétaire des données)",
    "core_": "Trésorier (propriétaire des données)",
    "dim_": "Intendant des données",
    "mart_": "Trésorier (propriétaire des données)",
}
SOURCES = {
    "meta_": "Gouvernance (documentation et lineage)",
    "ref_": "Saisie manuelle du référentiel",
    "mdm_": "Données maîtres (création automatique + validation humaine)",
    "dq_": "Moteur de qualité des données",
    "stg_": "Zone d'arrivée (agents d'acquisition et d'extraction)",
    "core_": "Pipeline de normalisation",
    "dim_": "Générée par init_db.py",
    "mart_": "Vue calculée à partir de la couche core",
}
ENTETES = ["Table", "Champ", "Type", "Obligatoire", "Définition métier", "Unité / format",
           "Règle de validation", "Sensibilité", "Propriétaire", "Source", "Exemple"]


def _prefixe(nom):
    return next((p for p in PREFIXES if nom.startswith(p)), "")


def _objets(conn):
    lignes = conn.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table', 'view') AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    return [n for (n,) in lignes if n.startswith(PREFIXES)]


def construire_dictionnaire(conn, version_schema=None):
    """Synchronise meta_champ avec le schéma. Retourne un dict de statistiques."""
    courants = set()
    a_documenter = []
    total = 0
    for table in _objets(conn):
        pref = _prefixe(table)
        for _, nom, type_, notnull, _, pk in conn.execute(f"PRAGMA table_info('{table}')").fetchall():
            total += 1
            courants.add((table, nom))
            desc = trouver(table, nom)
            if desc is None:
                a_documenter.append(f"{table}.{nom}")
                desc = {"definition": "À DOCUMENTER", "unite": None, "regle": None, "sensibilite": "interne",
                        "exemple": None}
            obligatoire = 1 if (notnull or pk) and not table.startswith("mart_") else 0
            conn.execute(
                "INSERT INTO meta_champ (table_nom, champ_nom, type_donnee, nullable, definition_metier, unite, "
                " regle_validation, source, sensibilite, proprietaire, exemple, version_schema) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT (table_nom, champ_nom) DO UPDATE SET "
                " type_donnee = excluded.type_donnee, nullable = excluded.nullable, "
                " definition_metier = excluded.definition_metier, unite = excluded.unite, "
                " regle_validation = excluded.regle_validation, source = excluded.source, "
                " sensibilite = excluded.sensibilite, proprietaire = excluded.proprietaire, "
                " exemple = excluded.exemple, version_schema = excluded.version_schema, "
                " maj_le = datetime('now')",
                (table, nom, type_ or None, 0 if obligatoire else 1, desc["definition"], desc["unite"],
                 desc["regle"], SOURCES.get(pref), desc["sensibilite"], PROPRIETAIRES.get(pref),
                 desc["exemple"], version_schema),
            )
    obsoletes = 0
    for table, nom in conn.execute("SELECT table_nom, champ_nom FROM meta_champ").fetchall():
        if (table, nom) not in courants:
            conn.execute("DELETE FROM meta_champ WHERE table_nom = ? AND champ_nom = ?", (table, nom))
            obsoletes += 1
    conn.commit()
    return {"total": total, "documentes": total - len(a_documenter),
            "a_documenter": a_documenter, "obsoletes_supprimes": obsoletes}


def _lignes_dictionnaire(conn):
    return conn.execute(
        "SELECT table_nom, champ_nom, COALESCE(type_donnee, ''), CASE nullable WHEN 0 THEN 'Oui' ELSE 'Non' END, "
        "definition_metier, COALESCE(unite, ''), COALESCE(regle_validation, ''), sensibilite, "
        "COALESCE(proprietaire, ''), COALESCE(source, ''), COALESCE(exemple, '') "
        "FROM meta_champ ORDER BY table_nom, champ_id"
    ).fetchall()


def exporter_markdown(conn, chemin):
    """Exporte le dictionnaire en Markdown, une section par table."""
    lignes = _lignes_dictionnaire(conn)
    glossaire = conn.execute("SELECT terme, definition, COALESCE(synonymes, '') FROM meta_glossaire ORDER BY terme").fetchall()
    sortie = ["# Dictionnaire de données — Trésorerie", "",
              "Généré automatiquement par `dictionnaire.py`. Ne pas modifier à la main : "
              "modifier `descriptions_champs.py` puis régénérer.", ""]
    table_courante = None
    esc = lambda s: str(s).replace("|", "\\|").replace("\n", " ")
    for l in lignes:
        if l[0] != table_courante:
            table_courante = l[0]
            sortie += ["", f"## {table_courante}", "",
                       "| Champ | Type | Oblig. | Définition | Unité / format | Règle | Sensibilité |",
                       "|---|---|---|---|---|---|---|"]
        sortie.append(f"| `{l[1]}` | {l[2]} | {l[3]} | {esc(l[4])} | {esc(l[5])} | {esc(l[6])} | {l[7]} |")
    sortie += ["", "## Glossaire métier", "", "| Terme | Définition | Synonymes |", "|---|---|---|"]
    sortie += [f"| {esc(t)} | {esc(d)} | {esc(s)} |" for t, d, s in glossaire]
    Path(chemin).parent.mkdir(parents=True, exist_ok=True)
    Path(chemin).write_text("\n".join(sortie) + "\n", encoding="utf-8")


def exporter_xlsx(conn, chemin):
    """Exporte le dictionnaire, le glossaire et les règles qualité en classeur Excel (openpyxl requis)."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    wb = Workbook()
    feuilles = [
        ("Dictionnaire", ENTETES, _lignes_dictionnaire(conn)),
        ("Glossaire", ["Terme", "Définition", "Synonymes", "Référence"],
         conn.execute("SELECT terme, definition, COALESCE(synonymes,''), COALESCE(reference,'') "
                      "FROM meta_glossaire ORDER BY terme").fetchall()),
        ("Regles_DQ", ["Règle", "Nom", "Dimension", "Sévérité", "Cible", "Seuil (%)", "Actif", "Description"],
         conn.execute("SELECT regle_id, nom, dimension, severite, cible_table, seuil_pct, actif, "
                      "COALESCE(description,'') FROM dq_regle ORDER BY regle_id").fetchall()),
    ]
    wb.remove(wb.active)
    for titre, entetes, lignes in feuilles:
        ws = wb.create_sheet(titre)
        ws.append(entetes)
        for c in ws[1]:
            c.font = Font(bold=True, color="FFFFFF")
            c.fill = PatternFill("solid", fgColor="1F3864")
            c.alignment = Alignment(vertical="center", wrap_text=True)
        for l in lignes:
            ws.append(list(l))
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions
        for col in ws.columns:
            largeur = max(len(str(c.value)) if c.value is not None else 0 for c in col)
            ws.column_dimensions[col[0].column_letter].width = min(max(12, largeur + 2), 60)
        for row in ws.iter_rows(min_row=2):
            for c in row:
                c.alignment = Alignment(vertical="top", wrap_text=True)
    Path(chemin).parent.mkdir(parents=True, exist_ok=True)
    wb.save(chemin)


def main():
    p = argparse.ArgumentParser(description="Génère le dictionnaire de données.")
    p.add_argument("--db", required=True, help="Chemin de tresorerie.db")
    p.add_argument("--md", help="Export Markdown (ex. docs/dictionnaire_donnees.md)")
    p.add_argument("--xlsx", help="Export Excel (ex. dictionnaire_donnees.xlsx)")
    a = p.parse_args()
    conn = sqlite3.connect(a.db)
    stats = construire_dictionnaire(conn)
    print(f"{stats['documentes']}/{stats['total']} champs documentés; "
          f"{stats['obsoletes_supprimes']} entrées obsolètes retirées.")
    if stats["a_documenter"]:
        print("À DOCUMENTER dans descriptions_champs.py :")
        for x in stats["a_documenter"]:
            print("  -", x)
    if a.md:
        exporter_markdown(conn, a.md)
        print("Markdown :", a.md)
    if a.xlsx:
        exporter_xlsx(conn, a.xlsx)
        print("Excel    :", a.xlsx)
    conn.close()


if __name__ == "__main__":
    main()
